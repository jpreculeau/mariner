import errno
import html
import logging
import os
import re
import stat
import tempfile
from datetime import timedelta
from pathlib import Path
from typing import Any, Optional, Sequence, Tuple, Union, cast

from flask import Flask, Response, jsonify, make_response, request, session
from werkzeug.exceptions import HTTPException
from flask_wtf.csrf import CSRFError, CSRFProtect
from whitenoise import WhiteNoise

from mariner import config
from mariner.server import auth, origin, refusals, sessions

logger: logging.Logger = logging.getLogger(__name__)


def get_frontend_assets_path() -> str:
    potential_paths: Sequence[Path] = [
        Path("./frontend/dist/"),
        Path("/opt/venvs/mariner3d/dist/"),
    ]
    try:
        path = next(path for path in potential_paths if path.exists() and path.is_dir())
    except StopIteration:
        # fallback to potential_paths. we're likely running from tests
        path = potential_paths[0]
    return str(path.absolute())


# What the page may load and do, said to the browser with every answer. The
# page's scripts come from Mariner alone, so that text which found its way
# into the page, a file name say, cannot run as one. Styles are looser: the
# interface sets some in place. Its typefaces are its own files.
CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self'",
        # The page carries its styles and typefaces with it: nothing is
        # fetched from another site.
        "style-src 'self' 'unsafe-inline'",
        "font-src 'self'",
        "img-src 'self' data: blob:",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        # Not shown inside a page of another site, where a click meant for
        # that page could land on a button of this one.
        "frame-ancestors 'none'",
    )
)

PROTECTIVE_HEADERS = {
    # A file is what its type says, whatever its contents look like.
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    # The address of a page of Mariner's is not told to other sites.
    "Referrer-Policy": "same-origin",
    # Pictures and data are for Mariner's own pages to load.
    "Cross-Origin-Resource-Policy": "same-origin",
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
}


def add_static_headers(headers: Any, path: str, url: str) -> None:
    """The same headers on the files of the page, served aside from Flask."""
    for name, value in PROTECTIVE_HEADERS.items():
        headers[name] = value
    if _NAMED_AFTER_ITS_CONTENT.match(url):
        # Changed, it would have another name: no need to ask again.
        headers["Cache-Control"] = "max-age=31536000, public, immutable"


# What the build names its files: "/assets/index-Q-zpu2Rs.js".
_NAMED_AFTER_ITS_CONTENT = re.compile(r"^/assets/.+-[A-Za-z0-9_-]{8}\.[a-z0-9]+$")


frontend_dist_directory: str = get_frontend_assets_path()
app: Flask = Flask(
    __name__,
    template_folder=frontend_dist_directory,
    static_folder=frontend_dist_directory,
)
app.session_interface = sessions.Sessions()
csrf = CSRFProtect(app)
# pyre-ignore[8]: incompatible attribute type
app.wsgi_app = WhiteNoise(
    app.wsgi_app,
    add_headers_function=add_static_headers,
    # The page's own files are for the page.
    allow_all_origins=False,
)
# pyre-ignore[16]: undefined attribute
app.wsgi_app.add_files(frontend_dist_directory)


def _can_hold_the_cache(wanted: str) -> bool:
    """Whether *wanted* is a folder Mariner may fill and empty as it likes."""
    real = os.path.realpath(wanted)
    if real != os.path.abspath(wanted):
        # Reached through a link: what is there may not be Mariner's.
        return False
    models = config.get_files_directory().resolve()
    if Path(real) == models or models in Path(real).parents:
        return False
    try:
        os.makedirs(wanted, exist_ok=True)
        status = os.stat(wanted)
    except OSError:
        return False
    # Entries are loaded as they are found: a folder of another account's
    # could hold anything.
    return status.st_uid == os.geteuid() and os.access(wanted, os.W_OK | os.X_OK)


def _own_folder() -> str:
    """A folder for this account alone, the same from one start to the next."""
    folder = os.path.join(tempfile.gettempdir(), f"mariner-{os.geteuid()}")
    try:
        os.mkdir(folder, 0o700)
    except FileExistsError:
        pass
    try:
        status = os.lstat(folder)
        if stat.S_ISDIR(status.st_mode) and status.st_uid == os.geteuid():
            os.chmod(folder, 0o700)
            return folder
    except OSError:
        pass
    return tempfile.mkdtemp(prefix="mariner-")


def usable_cache_directory(wanted: str) -> str:
    """*wanted*, made if need be, or a folder of this account's own.

    What is kept there is removed at each start and as room is needed, and
    loaded as it is found. So *wanted* is not used if it is reached through
    a link, is where the models are, or belongs to another account. Nor if
    it cannot be made or written: a cache directory left by a run under
    another account must not keep Mariner from starting.
    """
    if _can_hold_the_cache(wanted):
        return wanted
    fallback = _own_folder()
    # Not worth a warning where nothing was asked for: run outside its
    # service, Mariner has no folder under /var/cache.
    asked_for = not wanted.startswith(config.DEFAULT_CACHE_DIRECTORY)
    logger.log(
        logging.WARNING if asked_for else logging.INFO,
        "Not using the cache directory %r; using %r",
        wanted,
        fallback,
    )
    return fallback


# What a form adds around the file it carries.
UPLOAD_OVERHEAD_BYTES = 1024 * 1024

app.config.from_mapping(
    # Checked by Flask against the length a request announces, and as its
    # body is read.
    MAX_CONTENT_LENGTH=config.get_max_upload_bytes()
    + UPLOAD_OVERHEAD_BYTES,
)


@app.before_request
def refuse_other_sites() -> Optional[Tuple[Response, int]]:
    """Turn away what a page from elsewhere has a browser send.

    See ``mariner.server.origin``. For a request that has a body, the
    web server Mariner runs under has already made this check before
    taking the body in (see ``mariner.server.early``); it is made again
    here so that it holds under any other. For a request without one this
    is the only check.
    """
    refusal = origin.request_refusal(request.path, request.headers)
    if refusal is None:
        return None
    refusals.log(
        "Web",
        request.remote_addr,
        refusal.code,
        request.headers,
        request.method,
        request.path,
    )
    if refusal.code == "host_not_allowed" and _wants_a_page():
        return _name_not_allowed_page(), 403
    return jsonify(refusal.body()), 403


@app.before_request
def ask_for_the_password() -> Optional[Tuple[Response, int]]:
    """Answer the page's own addresses only to who is signed in.

    See ``mariner.server.auth``. As above, the web server Mariner runs
    under has already made this check for a request that has a body.
    """
    refused = auth.refusal(request.path, session)
    if refused is None:
        return None
    return jsonify(refused), 401


# First of all: before the check of the token a form carries, which reads
# the whole form, file included.
for early in (ask_for_the_password, refuse_other_sites):
    app.before_request_funcs.setdefault(None, []).remove(early)
    app.before_request_funcs[None].insert(0, early)


def _wants_a_page() -> bool:
    return (
        not request.path.startswith(origin.GUARDED_PREFIXES)
        and request.accept_mimetypes.best_match(["application/json", "text/html"])
        == "text/html"
    )


def _name_asked_for() -> str:
    """The name of the request as the client wrote it, without the port.

    From the header itself: what the framework makes of it is empty for a
    name it does not take for one.
    """
    host = request.headers.get("Host", "")
    parts = origin.name_and_port(host)
    return parts[0] if parts is not None else host


def _name_not_allowed_page() -> Response:
    """What to do about it, for someone who opened Mariner in a browser."""
    name = html.escape(_name_asked_for())
    page = f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Mariner: name not allowed</title></head>
<body>
<h1>Mariner does not answer to this name</h1>
<p>You reached Mariner as <code>{name}</code>. It answers to its IP address
and to names of a local network, so that a web site cannot point a name of
its own at your printer and drive it through your browser.</p>
<p>If this is a name you gave the printer yourself, add it to
<code>/etc/mariner/config.toml</code> and restart Mariner:</p>
<pre>[http]
allowed_hosts = ["{name}"]</pre>
<p>If it is not, or you do not know it, do not: open Mariner by its IP
address.</p>
</body>
</html>
"""
    response = make_response(page)
    response.mimetype = "text/html"
    return response


def _no_room(what: str) -> Tuple[Response, int]:
    """Say that an upload ran out of room while it was taken in.

    The web server refuses beforehand an upload that announces a size
    larger than the room there is (``mariner.server.early``). This is for
    a form that ran out of room while it was taken apart, which that
    could not foresee: several uploads at once, say. When the web server
    itself runs out while it takes a body in, it closes the connection
    and nothing is answered.
    """
    logger.warning("No room to keep an upload in while it arrives: %s", what)
    return jsonify(refusals.no_room_body(None)), 507


@app.after_request
def add_protective_headers(response: Response) -> Response:
    for name, value in PROTECTIVE_HEADERS.items():
        response.headers.setdefault(name, value)
    if request.path.startswith(origin.GUARDED_PREFIXES):
        # The state of the printer and of the files changes by the second.
        response.headers.setdefault("Cache-Control", "no-store")
    elif response.mimetype == "text/html":
        # The page carries the token its requests are checked against.
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.errorhandler(Exception)
def unexpected_error(error: Exception) -> Union[Response, Tuple[Response, int]]:
    """Answer an error nobody planned for without telling of the inside.

    The cause goes to the logs. The request path is quoted there: it is
    the client's text, and could otherwise start a log line of its own.
    """
    if isinstance(error, HTTPException):
        # A refusal that was meant: 400, 404 and the like.
        return cast(Response, error)
    if isinstance(error, OSError) and error.errno == errno.ENOSPC:
        # While a form was being taken apart, most likely.
        return _no_room(str(error))
    logger.error("Unexpected error while serving %r", request.path, exc_info=error)
    body = {
        "code": "internal_error",
        "title": "Unexpected Error",
        "description": "Mariner ran into an error it did not expect. "
        "Its logs say what happened.",
    }
    return jsonify(body), 500


@app.errorhandler(CSRFError)
def token_refused(error: CSRFError) -> Tuple[Response, int]:
    """Say what to do when the page's token is not taken.

    Most often the page was open when Mariner restarted: the token it
    holds was made by the Mariner that is gone.
    """
    body = {
        "code": "token_refused",
        "title": "Page Out Of Date",
        "description": "This page was opened before Mariner last restarted, "
        "or its session ended. Reload the page and try again. (A script "
        "first asks /api/csrf_token for a token, and sends it as "
        "X-CSRFToken with the cookie that came with it.)",
    }
    return jsonify(body), 400


@app.errorhandler(413)
def file_too_large(error: Exception) -> Tuple[Response, int]:
    megabytes = config.get_max_upload_bytes() // (1024 * 1024)
    body = {
        "code": "file_too_large",
        "title": "File Too Large",
        "description": f"Files can be {megabytes} MB at most.",
    }
    return jsonify(body), 413


app.config.from_mapping(
    {
        # Never the debug mode: it hands the inside of an error to whoever
        # caused it.
        "DEBUG": False,
        # The cookie that goes with the token is kept from what another
        # site has the browser post or load. It must still come along
        # when a link to Mariner is followed from another site ("Lax", not
        # "Strict"): the page would otherwise be given a new token, and
        # the tabs already open would hold one that is refused.
        "SESSION_COOKIE_SAMESITE": "Lax",
        # A name of Mariner's own, kept from scripts. Kept a month from
        # the last visit: who is signed in stays so.
        "SESSION_COOKIE_NAME": sessions.COOKIE_NAME,
        "SESSION_COOKIE_HTTPONLY": True,
        "PERMANENT_SESSION_LIFETIME": timedelta(days=30),
        # Left to itself the token is refused after an hour: a page left
        # open on a long print could then not pause or stop it. It still
        # ends when Mariner restarts, or a month after the cookie that
        # goes with it was made; the page then asks for a new one.
        "WTF_CSRF_TIME_LIMIT": None,
        # Backend class name, not the legacy "filesystem" factory alias. The
        # lowercase aliases are deprecated in flask-caching 2.x and gone in
        # 3.x, where they fail at import with ImportStringError.
        "CACHE_TYPE": "FileSystemCache",
        # A folder of its own within the cache directory: it is emptied at
        # each start, and other things are kept beside it.
        "CACHE_DIR": usable_cache_directory(
            os.path.join(config.get_cache_directory(), "parsed")
        ),
        # Not relied on: what Mariner keeps there is stored without expiry.
        "CACHE_DEFAULT_TIMEOUT": 300,
        # No limit to the number of entries. Past one, the cache drops
        # entries in no useful order, and a file whose entry was dropped is
        # read again in full at every listing. What is kept is bounded
        # otherwise: by its size and by a number of entries of Mariner's
        # own, and emptied at each start (see mariner.server.utils).
        "CACHE_THRESHOLD": 0,
        # Replaced at start by the key that is kept (mariner.server.state):
        # this one is for what imports the application without starting it.
        "SECRET_KEY": os.urandom(32),
    }
)
