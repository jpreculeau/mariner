import errno
import hashlib
import io
import logging
import os
import stat
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple, Type, TypeVar, Union, cast

import png
from flask_caching import Cache

from mariner import config
from mariner.file_formats import SlicedModelFile
from mariner.file_formats.reading import MalformedFile
from mariner.file_formats.utils import get_file_format
from mariner.server.app import app


logger: logging.Logger = logging.getLogger(__name__)

cache = Cache(app)


def _version_of(path: Path) -> Tuple[int, int]:
    """What tells one version of the file at *path* from another.

    Its date of modification and its size. A file replaced under the same
    name, a new slice of the same model say, differs in one or the other
    unless it has the very same size and was written within the same two
    seconds, which is as fine as the FAT filesystem dates a file. It must
    not be answered for from what was read of the previous one.

    Raises FileNotFoundError if *path* is not an existing file.
    """
    status = os.stat(path)
    if not stat.S_ISREG(status.st_mode):
        raise FileNotFoundError(path)
    return (status.st_mtime_ns, status.st_size)


def read_sliced_model_file(path: Path) -> SlicedModelFile:
    """Parse the sliced model file at *path*. Slow: prefer the cached form."""
    return get_file_format(str(path)).read(path)


def _render_preview(path: Path) -> bytes:
    image: png.Image = get_file_format(str(path)).read_preview(path)
    rendered = io.BytesIO()
    image.write(rendered)
    return rendered.getvalue()


# Rendering a preview takes about ten megabytes for the largest picture
# allowed. One at a time keeps the memory a burst of requests can take to
# that of a single one. The warm-up at start is a process of its own, and
# may render one more beside.
_rendering = threading.Lock()
# Parsing takes seconds for a large file on a small board. One at a time
# lets requests that arrive together for the same file share one read
# instead of each doing its own; a request for another file waits its turn.
_parsing = threading.Lock()


@dataclass(frozen=True)
class _Unreadable:
    """Remembered in place of what a file holds: why it could not be read."""

    reason: str


class _ChangedWhileRead(Exception):
    """The file is no longer the version that the read was started on."""


TRead = TypeVar("TRead")
Version = Tuple[int, int]


def _read_version(
    read: Callable[[Path], TRead], filename: str, version: Version
) -> Union[TRead, _Unreadable]:
    """What *read* makes of that version of the file, to be remembered.

    A file that is not what its format says is remembered as such, with
    the reason, which is logged here once: finding out can take as long as
    reading a good file, and the status of a print asks every few seconds.
    Any other
    failure, an error of the drive say, is raised and not remembered.

    Raises _ChangedWhileRead, so that nothing is remembered, if the file was
    replaced during the read: what was read may be the new file, or part of
    each.
    """
    path = Path(filename)
    outcome: Union[TRead, _Unreadable]
    try:
        outcome = read(path)
    except MalformedFile as error:
        outcome = _Unreadable(str(error))
    if _version_of(path) != version:
        raise _ChangedWhileRead(filename)
    if isinstance(outcome, _Unreadable):
        logger.warning("Could not read %r: %s", path.name, outcome.reason)
    return outcome


# What is remembered is kept in files, by default under /tmp, which on
# current systems is in memory. Entries of files deleted since stay until
# the next start, and files can be sent only to leave some: the folder is
# kept under this size by dropping the entries written longest ago.
MAX_CACHE_BYTES = 64 * 1024 * 1024

# What could not be written to the cache: the parsed files only, which are
# asked for at every listing and every status. In this process, and no more
# of them than this.
_MAX_KEPT_HERE = 256
_kept_here: Dict[str, Tuple[Version, object]] = {}
_said_cache_failed = False


def _cache_directory() -> str:
    return str(app.config["CACHE_DIR"])


def _key(kind: str, path: Path) -> str:
    """What the *kind* of thing remembered of the file at *path* is kept under.

    The same whatever the case of the name, as the FAT filesystem answers
    to any; and made of plain characters, whatever those of the name.
    """
    name = os.fsencode(str(path).casefold())
    return f"{kind}:{hashlib.sha256(name).hexdigest()}"


def empty_cache() -> None:
    """Remove everything remembered of files, and what failed writes left.

    Done at each start: nothing else removes what was remembered of files
    deleted since. A folder reached through a link is left alone, since
    what it holds may not be Mariner's.
    """
    global _said_cache_failed
    _kept_here.clear()
    _said_cache_failed = False
    directory = _cache_directory()
    if os.path.islink(directory):
        logger.warning("Not emptying %r: it is a link", directory)
        return
    models = config.get_files_directory().resolve()
    kept = Path(directory).resolve()
    if kept == models or models in kept.parents:
        logger.warning("Not emptying %r: it is where the models are", directory)
        return
    try:
        with os.scandir(directory) as entries:
            files = [entry.path for entry in entries if entry.is_file()]
    except OSError:
        return
    for file in files:
        try:
            os.remove(file)
        except OSError:
            pass


def _make_room() -> None:
    """Drop the entries written longest ago until the folder is small enough."""
    try:
        with os.scandir(_cache_directory()) as entries:
            files = [
                (status.st_mtime_ns, status.st_size, entry.path)
                for entry in entries
                if entry.is_file(follow_symlinks=False)
                for status in (entry.stat(follow_symlinks=False),)
            ]
    except OSError:
        return
    total = sum(size for _, size, _ in files)
    for _, size, file in sorted(files):
        if total <= MAX_CACHE_BYTES:
            break
        try:
            os.remove(file)
        except OSError:
            continue
        total -= size


def _remember(kind: str, key: str, stored: Tuple[Version, object]) -> None:
    global _said_cache_failed
    if not cache.set(key, stored, timeout=0):
        # The folder may have been removed: make it again and try once more.
        try:
            os.makedirs(_cache_directory(), exist_ok=True)
        except OSError:
            pass
        if not cache.set(key, stored, timeout=0):
            if not _said_cache_failed:
                _said_cache_failed = True
                logger.warning(
                    "Could not write to the cache in %r; files will be read "
                    "again more often than needed",
                    _cache_directory(),
                )
            if kind == "details":
                if len(_kept_here) >= _MAX_KEPT_HERE:
                    _kept_here.pop(next(iter(_kept_here)))
                _kept_here[key] = stored
            return
    _kept_here.pop(key, None)
    _make_room()


def _remembered(key: str) -> Optional[Tuple[Version, object]]:
    stored = cache.get(key)
    if stored is None:
        return _kept_here.get(key)
    return stored  # type: ignore[no-any-return]


_ATTEMPTS = 3


def _current(
    kind: str, read: Callable[[Path], TRead], lock: threading.Lock, path: Path
) -> TRead:
    """What *read* makes of the file at *path*, done once per version.

    What is remembered is kept under the path, with the version it is for:
    a new version takes the place of the one before, so that a file holds
    one entry of each kind however many times it is replaced.
    """
    key = _key(kind, path)
    for _ in range(_ATTEMPTS):
        version = _version_of(path)
        stored = _remembered(key)
        if stored is None or stored[0] != version:
            with lock:
                # A request that waited here finds what the one before it
                # has just read.
                stored = _remembered(key)
                if stored is None or stored[0] != version:
                    try:
                        stored = (version, _read_version(read, str(path), version))
                    except _ChangedWhileRead:
                        continue
                    _remember(kind, key, stored)
        outcome = cast(Union[TRead, _Unreadable], stored[1])
        if isinstance(outcome, _Unreadable):
            raise MalformedFile(outcome.reason)
        return outcome
    # Not a file to send again: one to wait for.
    raise OSError(errno.EBUSY, "the file keeps changing: it is being written")


def read_cached_sliced_model_file(path: Path) -> SlicedModelFile:
    """What the sliced model file at *path* holds, parsed once per version.

    *path* is absolute. Raises FileNotFoundError if it is not an existing
    file, MalformedFile if it is not what its format says, which is found
    out once per version too, and whatever else the read raises.
    """
    return _current("details", read_sliced_model_file, _parsing, path)


def read_cached_preview(path: Path) -> bytes:
    """The preview of the file at *path* as a PNG, rendered once per version.

    Raises as ``read_cached_sliced_model_file`` does.
    """
    return _current("preview", _render_preview, _rendering, path)


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
