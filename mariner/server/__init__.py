import logging
import multiprocessing
import os
import tempfile
from typing import Any, Dict

from flask import abort, render_template

from mariner import config
from mariner.file_formats.reading import MalformedFile
from mariner.file_formats.utils import get_supported_extensions
from mariner.server.api import api as api_blueprint
from mariner.server.auth import auth_api as auth_blueprint
from mariner.server.app import UPLOAD_OVERHEAD_BYTES, app as flask_app, csrf
from mariner.server import (
    auth,
    certificate,
    early,
    https,
    origin,
    sessions,
    settings,
    state,
    tls,
)
from mariner.server.early import serve
from mariner.server.files import printable_files, remove_stale_scratch_files
from mariner.server.providers import register_providers, start_providers
from mariner.server.utils import (
    empty_cache,
    read_cached_preview,
    read_cached_sliced_model_file,
)

from mariner.printer import has_control_character

logger: logging.Logger = logging.getLogger(__name__)

flask_app.register_blueprint(api_blueprint)
flask_app.register_blueprint(auth_blueprint)
flask_app.register_blueprint(settings.settings_api)
# Before the slicers' interfaces are set up: two of the settings changed
# from the page are their switches.
settings.note_what_runs()
register_providers(flask_app, csrf)


def render_index() -> str:
    template_vars: Dict[str, str] = {
        "supported_extensions": ",".join(get_supported_extensions()),
    }
    printer_display_name = config.get_printer_display_name()
    if printer_display_name is not None:
        template_vars["printer_display_name"] = printer_display_name
    return render_template("index.html", **template_vars)


@flask_app.route("/", methods=["GET"])
def index() -> str:
    return render_index()


@flask_app.get("/<path:spa_path>")
def spa_fallback(spa_path: str) -> str:
    # Let /api/* and provider routes pass through to their blueprints.
    if spa_path == "api" or spa_path.startswith("api/"):
        abort(404)
    from mariner.server.providers import get_provider_prefixes

    for prefix in get_provider_prefixes():
        if spa_path == prefix or spa_path.startswith(prefix + "/"):
            abort(404)
    return render_index()


class CacheBootstrapper(multiprocessing.Process):
    """Reads every printable file once at startup, at low priority.

    Parsing a large file takes seconds on a small board. Done here, it is
    not paid for by the first listing or the first status request.
    """

    def run(self) -> None:
        os.nice(5)
        for file in printable_files():
            # One file that cannot be read must not leave the others cold.
            # A file that is not what its format says is reported, with the
            # reason, where it is read.
            try:
                read_cached_sliced_model_file(file)
            except MalformedFile:
                continue
            except Exception:
                logger.warning(
                    "Could not read %r ahead of time", file.name, exc_info=True
                )
                continue
            try:
                read_cached_preview(file)
            except MalformedFile:
                pass
            except Exception:
                logger.warning(
                    "Could not render the preview of %r", file.name, exc_info=True
                )


class _OneLine(logging.Filter):
    """Escape what would break a line in a record of the web server.

    The web server logs the path of a request it could not finish as the
    client sent it, and a path can hold a line break: the rest of it would
    then read as a log line of its own. Mariner's own records are left
    alone; they quote client text with ``%r`` where they carry any.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name.split(".")[0] == "waitress":
            message = record.getMessage()
            if has_control_character(message):
                record.msg = "".join(
                    (
                        character.encode("unicode_escape").decode("ascii")
                        if has_control_character(character)
                        else character
                    )
                    for character in message
                )
                record.args = None
        return True


def keep_requests_on_one_line() -> None:
    """Have every log handler in place escape the web server's records."""
    for handler in logging.getLogger().handlers:
        if not any(isinstance(known, _OneLine) for known in handler.filters):
            handler.addFilter(_OneLine())


# Connections taken at once. Those of the Internet are held to part of
# them (``mariner.server.load``): the local network always finds room.
CONNECTION_LIMIT = 64
CHANNEL_TIMEOUT_SECONDS = 60


def use_spool_directory() -> None:
    """Have uploads wait on a drive while they arrive, not in memory.

    The web server, and Flask after it, keep an upload in a temporary file
    until it is whole. Temporary files go to /tmp unless told otherwise,
    and where /tmp is held in memory a large upload would not fit.
    """
    directory = config.get_spool_directory()
    if os.path.isdir(directory) and os.access(directory, os.W_OK | os.X_OK):
        tempfile.tempdir = directory
    else:
        logger.warning(
            "Cannot keep uploads in %r while they arrive; using %r",
            directory,
            tempfile.gettempdir(),
        )


def _listening() -> Dict[str, Any]:
    """Where the web server listens, and whether over HTTPS too.

    Sets what the application needs to know of it.
    """
    host, port = config.get_http_host(), config.get_http_port()
    in_the_clear: Dict[str, Any] = {"host": host, "port": port}
    flask_app.config.update(
        HTTPS_PORT=None,
        SESSION_COOKIE_SECURE=False,
        SESSION_COOKIE_NAME=sessions.COOKIE_NAME,
    )
    early.plain_refusal = None
    pair = certificate.in_use()
    if pair is None:
        if config.get_https_enabled():
            logger.warning(
                "Mariner's page is served without HTTPS: what is typed in "
                "it, its password included, can be read on the network"
            )
        return in_the_clear
    secured_port = config.get_https_port()
    if secured_port == port:
        logger.error(
            "Configuration: [https] port and [http] port are both %d. "
            "Mariner's page is served without HTTPS until they differ",
            port,
        )
        return in_the_clear
    flask_app.config.update(
        HTTPS_PORT=secured_port,
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_NAME=sessions.SECURED_COOKIE_NAME,
    )
    early.plain_refusal = lambda path, headers: (
        https.refusal(headers.get("Host", ""), secured_port)
        if https.is_for_the_page(path)
        else None
    )
    at = f"[{host}]" if ":" in host else host
    return {
        # Said once the ports are had: one of them may be taken.
        "once_listening": lambda: logger.info(
            "Mariner's page is served over HTTPS on port %d", secured_port
        ),
        "listen": f"{at}:{port} {at}:{secured_port}",
        "tls": tls.context(*pair),
        "tls_port": secured_port,
        # Renewed by a program of its own: taken without a restart.
        "tls_files": pair,
    }


def main() -> None:
    # Global log level applies to mariner.* and waitress output.
    log_level = getattr(logging, config.get_log_level(), logging.INFO)
    if not logging.getLogger().handlers:
        logging.basicConfig(level=log_level)
    else:
        logging.getLogger().setLevel(log_level)
    logging.getLogger("mariner").setLevel(log_level)
    logging.getLogger("waitress").setLevel(log_level)
    keep_requests_on_one_line()

    # First of all the work on the files directory: nothing else is reading
    # or writing it yet. After logging is set up, so that what was removed
    # is reported.
    remove_stale_scratch_files()

    # What was remembered of files deleted since is of no use, and nothing
    # else removes it. The warm-up reads again the files that are there.
    empty_cache()
    CacheBootstrapper().start()
    start_providers()

    # A password that is lost is cleared by a file on the boot drive.
    auth.clear_if_asked_on_the_boot_drive()

    # The same key at every start: a page left open goes on working, and
    # whoever is signed in stays so.
    if auth.signed_out_list_is_usable():
        flask_app.config["SECRET_KEY"] = state.session_key()
    else:
        # The sessions signed out of would all work again: every session
        # ends instead, by a new key.
        logger.warning(
            "What was signed out of cannot be read: every browser has to "
            "sign in again"
        )
        flask_app.config["SECRET_KEY"] = state.new_session_key()
        auth.start_signed_out_list_again()

    # A slicer's interface that is switched off is sent no file either.
    early.UPLOAD_PREFIXES = ("/api/upload_file",) + (
        ("/uvtools/upload/",) if config.get_uvtools_enabled() else ()
    )

    # Asked for before a body is taken in, not once it has been stored.
    early.password_refusal = lambda method, path, headers, peer: auth.refusal(
        path,
        sessions.read(
            flask_app, headers.get("Cookie", ""), headers.get(auth.KEY_HEADER, "")
        ),
        headers.get(auth.KEY_HEADER, ""),
        method,
        peer,
    )

    for ignored in config.ignored_settings() + origin.unusable_entries():
        logger.warning("Configuration: %s", ignored)
    use_spool_directory()
    listening = _listening()
    try:
        serve(
            flask_app,
            **listening,
            # Left to itself the web server refuses anything over a gigabyte.
            max_request_body_size=config.get_max_upload_bytes() + UPLOAD_OVERHEAD_BYTES,
            # Each connection can hold an upload waiting on the drive.
            connection_limit=CONNECTION_LIMIT,
            # A connection that says nothing is closed after this long, or up
            # to half as long again. It holds one of the few there are.
            channel_timeout=CHANNEL_TIMEOUT_SECONDS,
        )
    except OSError as error:
        # A port another program holds, most often.
        at = listening.get("listen") or f"{listening['host']}:{listening['port']}"
        logger.error(
            "Mariner cannot listen on %s: %s. Another program may be using "
            "the port: change it under [http] or [https] in the configuration",
            at,
            error,
        )
        raise SystemExit(1)
