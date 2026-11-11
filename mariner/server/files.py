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
import shutil
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

# The longest name Linux filesystems accept. Deliberately conservative: FAT
# counts in UTF-16 units and could store somewhat longer non-ASCII names.
_MAX_NAME_BYTES = 255

# Files and folders on their way in or out are stored under this pattern,
# see ``scratch_path_beside``. They are hidden from listings and removed at
# startup if a previous run left any behind.
_SCRATCH_PREFIX = ".upload-"
_SCRATCH_SUFFIX = ".part"

# Where the SDCP provider assembles chunked transfers, inside the files
# directory.
SDCP_SCRATCH_DIRNAME = ".sdcp_uploads"


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
    ending with a dot (FAT drops it, so the stored name would differ), names
    longer than a filesystem entry can be, and names reserved for files on
    their way in or out (see ``is_scratch_file``), which listings hide.

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
    if is_scratch_file(name) or name == SDCP_SCRATCH_DIRNAME:
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
    """Whether *name* is something on its way in or out, not an entry to list."""
    return name.startswith(_SCRATCH_PREFIX) and name.endswith(_SCRATCH_SUFFIX)


def scratch_path_beside(path: Path) -> Path:
    """A fresh scratch path in the same directory as *path*.

    The name is short and random: it fits beside the longest file name, and
    no two callers ever get the same one. Being in the same directory, it
    can be moved onto *path*, or *path* onto it, in one step.
    """
    return path.with_name(f"{_SCRATCH_PREFIX}{secrets.token_hex(8)}{_SCRATCH_SUFFIX}")


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
    scratch = scratch_path_beside(destination)
    try:
        yield scratch
        with guard(destination):
            os.replace(scratch, destination)
    except BaseException:
        _remove_quietly(scratch)
        raise


def _remove_tree_or_file(path: Path) -> bool:
    try:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            os.remove(path)
    except OSError:
        return False
    return True


def remove_stale_scratch_files() -> int:
    """Remove what a crash or a power cut left unfinished in the files directory.

    Covers uploads through the web interface and UVtools, folders that were
    being deleted, and chunked SDCP transfers. Each of these cleans up after
    itself when it fails, but not when the process is killed halfway. Meant
    to run once at startup, before anything can be in progress. Returns how
    many entries were removed.
    """
    files_directory = config.get_files_directory()
    try:
        leftovers = list(files_directory.rglob(f"{_SCRATCH_PREFIX}*{_SCRATCH_SUFFIX}"))
        leftovers.append(files_directory / SDCP_SCRATCH_DIRNAME)
    except OSError:
        return 0
    removed = sum(
        1
        for leftover in leftovers
        if os.path.lexists(leftover) and _remove_tree_or_file(leftover)
    )
    if removed:
        logger.info("Removed %d unfinished transfer(s) left by a previous run", removed)
    return removed
