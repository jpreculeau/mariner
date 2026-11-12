import logging
import os
import stat
import tempfile
from pathlib import Path
from typing import Optional, Sequence, Tuple

from flask import Flask, Response, jsonify, request
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


frontend_dist_directory: str = get_frontend_assets_path()
app: Flask = Flask(
    __name__,
    template_folder=frontend_dist_directory,
    static_folder=frontend_dist_directory,
)
csrf = CSRFProtect(app)
# pyre-ignore[8]: incompatible attribute type
app.wsgi_app = WhiteNoise(app.wsgi_app)
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


@app.before_request
def refuse_other_sites() -> Optional[Tuple[Response, int]]:
    """Turn away what a page from elsewhere has a browser send.

    See ``mariner.server.origin``. A foreign name is refused everywhere; a
    request from another site only where it would act or tell, so that a
    link to Mariner on another page still opens it.
    """
    guarded = request.path.startswith(_GUARDED_PREFIXES)
    refusal = origin.host_refusal(request.headers) or (
        origin.site_refusal(request.headers) if guarded else None
    )
    if refusal is None:
        return None
    return jsonify(refusal.body()), 403


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
        "DEBUG": True,
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
