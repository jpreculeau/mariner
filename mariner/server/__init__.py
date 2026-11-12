import logging
import multiprocessing
import os
from typing import Dict

from flask import abort, render_template
from waitress import serve

from mariner import config
from mariner.file_formats.reading import MalformedFile
from mariner.file_formats.utils import get_supported_extensions
from mariner.server.api import api as api_blueprint
from mariner.server.app import app as flask_app, csrf
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

    serve(flask_app, host=config.get_http_host(), port=config.get_http_port())
