import io
import os
import stat
import time
from pathlib import Path
from typing import Callable, Tuple, Type, TypeVar, Union

import png
from flask_caching import Cache

from mariner.file_formats import SlicedModelFile
from mariner.file_formats.utils import get_file_format
from mariner.server.app import app


cache = Cache(app)


def _version_of(path: Path) -> Tuple[int, int]:
    """What tells one version of the file at *path* from another.

    Its date of modification and its size. A file replaced under the same
    name, a new slice of the same model say, differs in one or the other,
    and must not be answered for from what was read of the previous one.

    Raises FileNotFoundError if *path* is not an existing file.
    """
    status = os.stat(path)
    if not stat.S_ISREG(status.st_mode):
        raise FileNotFoundError(path)
    return (status.st_mtime_ns, status.st_size)


def read_sliced_model_file(path: Path) -> SlicedModelFile:
    """Parse the sliced model file at *path*. Slow: prefer the cached form."""
    return get_file_format(str(path)).read(path)


def read_preview(path: Path) -> bytes:
    """Render the preview of the sliced model file at *path* as a PNG."""
    image: png.Image = get_file_format(str(path)).read_preview(path)
    rendered = io.BytesIO()
    image.write(rendered)
    return rendered.getvalue()


# The cached forms take the version of the file as arguments only so that it
# is part of what the answer is remembered under. The answers never expire:
# a given version of a file always parses to the same thing.


@cache.memoize(timeout=0)
def _cached_sliced_model_file(
    filename: str, modified_ns: int, size: int
) -> SlicedModelFile:
    return read_sliced_model_file(Path(filename))


@cache.memoize(timeout=0)
def _cached_preview(filename: str, modified_ns: int, size: int) -> bytes:
    return read_preview(Path(filename))


def read_cached_sliced_model_file(path: Path) -> SlicedModelFile:
    """What the sliced model file at *path* holds, parsed once per version.

    *path* is absolute. Raises FileNotFoundError if it is not an existing
    file, and whatever the parser raises if the file cannot be read.
    """
    return _cached_sliced_model_file(str(path), *_version_of(path))


def read_cached_preview(path: Path) -> bytes:
    """The preview of the file at *path* as a PNG, rendered once per version.

    Raises as ``read_cached_sliced_model_file`` does.
    """
    return _cached_preview(str(path), *_version_of(path))


TReturn = TypeVar("TReturn")


def retry(
    func: Callable[[], TReturn],
    exception_type: Union[Type[Exception], Tuple[Type[Exception], ...]],
    *,
    num_retries: int,
    delay_ms: int = 100,
) -> TReturn:
    attempts_left = num_retries
    while attempts_left > 0:
        try:
            return func()
        except exception_type:
            attempts_left -= 1
            time.sleep(delay_ms / 1000.0)
    return func()
