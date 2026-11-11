"""Filename and path handling shared by every interface that touches files.

The web API and the network print providers all take a name or a path from a
client, then store, list, print or delete a file under it. The helpers here
decide whether such a value is acceptable and how a file is written, so no
interface can forget a check another one has.

The rule for what may appear in a command line sent to the printer lives in
``mariner.printer`` (``is_safe_for_printer``), next to the code that builds
those lines, and is reused here.
"""

import logging
import os
import secrets
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Callable, ContextManager, Iterator, Optional

from mariner import config
from mariner.printer import has_control_character

logger: logging.Logger = logging.getLogger(__name__)

# Path separators would let a name escape its directory. The single quote
# delimits the file name in the printer's print command. The rest cannot be
# stored on the FAT filesystem the printer reads the files from.
_FORBIDDEN_CHARACTERS = frozenset("/\\'" + ':*?"<>|')

# The longest name a FAT (and most other) filesystems can store.
_MAX_NAME_BYTES = 255

# Uploads in progress are stored under this pattern; see ``replacing``.
_SCRATCH_PREFIX = ".upload-"
_SCRATCH_SUFFIX = ".part"


def safe_filename(filename: Optional[str]) -> Optional[str]:
    """The client's filename, or None if it is not safe to use.

    The name is returned as given, apart from surrounding whitespace, which
    is removed. It is deliberately not passed through
    ``werkzeug.secure_filename``, which rewrites it: parentheses are
    stripped, spaces collapsed, and non-ASCII characters dropped, extension
    included. A client that uploads ``model_6(1).ctb`` and then asks to print
    it under that name would find nothing, because the stored file would be
    ``model_61.ctb``. Validating and rejecting instead of rewriting keeps
    exactly one name in play across upload, listing, printing and deletion.

    Refused: empty names, ``.`` and ``..``, names with a path separator, a
    single quote, a control character or a character FAT cannot store, names
    ending with a dot (FAT drops it, so the stored name would differ), and
    names longer than a filesystem entry can be.

    This is not on its own sufficient to contain a path: callers must still
    resolve it with ``resolve_in_files_directory``.
    """
    name = (filename or "").strip()
    if not name or name in (".", "..") or name.endswith("."):
        return None
    if not _FORBIDDEN_CHARACTERS.isdisjoint(name):
        return None
    if has_control_character(name):
        return None
    if len(name.encode("utf-8", errors="replace")) > _MAX_NAME_BYTES:
        return None
    return name


def resolve_in_files_directory(relative: str) -> Optional[Path]:
    """Resolve *relative* inside the files directory, or None if it escapes.

    Returns the files directory itself for ``""`` and ``"."``. Symbolic links
    are followed before the check, so a link pointing outside is refused too.
    """
    if "\x00" in relative:
        # No path can carry a NUL byte; refuse it here instead of letting the
        # filesystem call raise.
        return None
    files_directory = config.get_files_directory().resolve()
    candidate = (files_directory / relative).resolve()
    if candidate != files_directory and files_directory not in candidate.parents:
        return None
    return candidate


def modification_time(dir_entry: "os.DirEntry[str]") -> float:
    """When *dir_entry* was last modified, for sorting a listing.

    A dangling symbolic link has nothing to stat; it sorts as the oldest
    entry instead of failing the whole listing.
    """
    try:
        return dir_entry.stat().st_mtime
    except OSError:
        return 0.0


def is_scratch_file(name: str) -> bool:
    """Whether *name* is an upload in progress rather than a file to list."""
    return name.startswith(_SCRATCH_PREFIX) and name.endswith(_SCRATCH_SUFFIX)


def _remove_quietly(path: Path) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _no_guard(_destination: Path) -> ContextManager[None]:
    return nullcontext()


@contextmanager
def replacing(
    destination: Path,
    guard: Callable[[Path], ContextManager[None]] = _no_guard,
) -> Iterator[Path]:
    """Yield a scratch path whose contents become *destination* on success.

    The caller writes the new contents to the scratch path, next to the
    destination. On leaving the block they are moved into place in one step.
    The printer therefore never reads a half-written file under its final
    name, and an upload that fails leaves the file it was meant to replace
    untouched.

    Each call gets its own scratch file, so two uploads of the same name do
    not write into each other; the last one to finish wins, whole.

    *guard* wraps the final move. It is how a caller refuses the replacement
    at the last moment, by raising, with whatever it needs held for the
    duration of the move (see ``printer_access.unless_in_use``).

    If the block or the guard raises, the scratch file is removed and the
    exception propagates.
    """
    scratch = destination.with_name(
        f"{_SCRATCH_PREFIX}{secrets.token_hex(8)}{_SCRATCH_SUFFIX}"
    )
    try:
        yield scratch
        with guard(destination):
            os.replace(scratch, destination)
    except BaseException:
        _remove_quietly(scratch)
        raise


def remove_stale_scratch_files() -> int:
    """Remove uploads that a crash or a power cut left unfinished.

    ``replacing`` cleans up after an upload that fails, but not after a
    process that is killed mid-upload. Meant to run once at startup, before
    any upload can be in progress. Returns how many files were removed.
    """
    removed = 0
    pattern = f"{_SCRATCH_PREFIX}*{_SCRATCH_SUFFIX}"
    try:
        leftovers = list(config.get_files_directory().rglob(pattern))
    except OSError:
        return 0
    for leftover in leftovers:
        try:
            os.remove(leftover)
        except OSError:
            continue
        removed += 1
    if removed:
        logger.info("Removed %d unfinished upload(s) left by a previous run", removed)
    return removed
