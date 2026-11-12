import logging
import os
import tempfile
from pathlib import Path
from typing import Sequence

from flask import Flask
from flask_wtf.csrf import CSRFProtect
from whitenoise import WhiteNoise

from mariner import config

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


def usable_cache_directory(wanted: str) -> str:
    """*wanted*, made if need be; a folder of this run's own if it cannot be.

    A cache directory left by a run under another account must not keep
    Mariner from starting: what it keeps there is only a convenience.
    """
    try:
        os.makedirs(wanted, exist_ok=True)
        if os.access(wanted, os.W_OK | os.X_OK):
            return wanted
    except OSError:
        pass
    fallback = tempfile.mkdtemp(prefix="mariner-")
    logger.warning("Cannot use the cache directory %r; using %r", wanted, fallback)
    return fallback


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
        "CACHE_DEFAULT_TIMEOUT": 300,
        # No limit to the number of entries. Past one, the cache drops
        # entries in no useful order, and a file whose entry was dropped is
        # read again in full at every listing. What is kept is bounded
        # otherwise: by its size, and emptied at each start (see
        # mariner.server.utils).
        "CACHE_THRESHOLD": 0,
        "SECRET_KEY": os.urandom(16),
    }
)
