import errno
import html
import logging
import os
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Any, Optional, Sequence, Tuple, Union, cast

from flask import Flask, Response, jsonify, make_response, request
from werkzeug.exceptions import HTTPException
from flask_wtf.csrf import CSRFProtect
from whitenoise import WhiteNoise

from mariner import config
from mariner.server import origin

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
# interface sets some in place, and takes its fonts from Google's servers.
CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src 'self' data: https://fonts.gstatic.com",
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


frontend_dist_directory: str = get_frontend_assets_path()
app: Flask = Flask(
    __name__,
    template_folder=frontend_dist_directory,
    static_folder=frontend_dist_directory,
)
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
    logger.warning("Not using the cache directory %r; using %r", wanted, fallback)
    return fallback


# What a form adds around the file it carries.
UPLOAD_OVERHEAD_BYTES = 1024 * 1024

app.config.from_mapping(
    # Checked by Flask against the length a request announces, and as its
    # body is read.
    MAX_CONTENT_LENGTH=config.get_max_upload_bytes()
    + UPLOAD_OVERHEAD_BYTES,
)


# What acts on the printer or the files, or tells about them.
_GUARDED_PREFIXES = ("/api/", "/uvtools/")
# What is made for slicers, and acts on a GET.
_SLICER_PREFIXES = ("/uvtools/",)


@app.before_request
def refuse_other_sites() -> Optional[Tuple[Response, int]]:
    """Turn away what a page from elsewhere has a browser send.

    See ``mariner.server.origin``. A foreign name is refused everywhere; a
    request from another site only where it would act or tell, so that a
    link to Mariner on another page still opens it.
    """
    refusal = origin.host_refusal(request.headers)
    if refusal is None and request.path.startswith(_GUARDED_PREFIXES):
        refusal = origin.site_refusal(request.headers)
    if refusal is None and request.path.startswith(_SLICER_PREFIXES):
        refusal = origin.browser_refusal(request.headers)
    if refusal is None:
        return None
    if refusal.code == "host_not_allowed" and _wants_a_page():
        return _name_not_allowed_page(), 403
    return jsonify(refusal.body()), 403


# First of all: before the check of the token a form carries, which reads
# the whole form, file included.
app.before_request_funcs.setdefault(None, []).remove(refuse_other_sites)
app.before_request_funcs[None].insert(0, refuse_other_sites)


def _wants_a_page() -> bool:
    return (
        not request.path.startswith(_GUARDED_PREFIXES)
        and request.accept_mimetypes.best_match(["application/json", "text/html"])
        == "text/html"
    )


def _name_not_allowed_page() -> Response:
    """What to do about it, for someone who opened Mariner in a browser."""
    name = html.escape(request.host.rsplit(":", 1)[0])
    page = f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Mariner: name not allowed</title></head>
<body>
<h1>Mariner does not answer to this name</h1>
<p>You reached Mariner as <code>{name}</code>. It answers to its IP address
and to names of a local network, so that a web site cannot point a name of
its own at your printer and drive it through your browser.</p>
<p>To use this name, add it to <code>/etc/mariner/config.toml</code> and
restart Mariner:</p>
<pre>[http]
allowed_hosts = ["{name}"]</pre>
<p>Or open Mariner by its IP address.</p>
</body>
</html>
"""
    response = make_response(page)
    response.mimetype = "text/html"
    return response


def _no_room(what: str) -> Tuple[Response, int]:
    megabytes = shutil.disk_usage(tempfile.gettempdir()).free // (1024 * 1024)
    logger.warning("No room to keep an upload in while it arrives: %s", what)
    body = {
        "code": "upload_not_stored",
        "title": "File Not Stored",
        "description": "There is not enough room on Mariner's own drive to "
        f"take this file in: {megabytes} MB are free where uploads wait. A "
        "file sent from the web page needs twice its size there.",
    }
    return jsonify(body), 507


@app.before_request
def refuse_what_cannot_wait() -> Optional[Tuple[Response, int]]:
    """Turn away an upload larger than the room it would wait in.

    Before a byte of it is read. A form is kept twice while it arrives:
    once by the web server, once more as it is taken apart.
    """
    length = request.content_length or 0
    if length == 0:
        return None
    copies = 2 if request.mimetype == "multipart/form-data" else 1
    try:
        free = shutil.disk_usage(tempfile.gettempdir()).free
    except OSError:
        return None
    if length * copies > free:
        return _no_room(f"{length} bytes announced, {free} free")
    return None


@app.after_request
def add_protective_headers(response: Response) -> Response:
    for name, value in PROTECTIVE_HEADERS.items():
        response.headers.setdefault(name, value)
    if request.path.startswith(_GUARDED_PREFIXES):
        # The state of the printer and of the files changes by the second.
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
        "SECRET_KEY": os.urandom(16),
    }
)
