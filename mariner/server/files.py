"""Filename and path handling shared by every interface that touches files.

The web API and the network print providers all take a name or a path from a
client, then store, list, print or delete a file under it. The helpers here
decide whether such a value is acceptable and how a file is written, so no
interface can forget a check another one has.

The rule for what may appear in a command line sent to the printer lives in
``mariner.printer`` (``is_safe_for_printer``), next to the code that builds
those lines. ``safe_filename`` and ``printable_relative_path`` both apply it.
"""

import logging
import os
import secrets
import shutil
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Callable, ContextManager, Iterator, Optional

from mariner import config
from mariner.file_formats.utils import get_file_extension, get_supported_extensions
from mariner.printer import has_control_character, is_safe_for_printer

logger: logging.Logger = logging.getLogger(__name__)

# Path separators would let a name escape its directory. The rest cannot be
# stored on the FAT filesystem the printer reads the files from.
_FORBIDDEN_CHARACTERS = frozenset("/\\" + ':*?"<>|')

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

    Refused: empty names, ``.`` and ``..``; names the printer could not be
    told to print (``is_safe_for_printer``: a single quote, a control
    character, text that is not valid Unicode); names with a path separator
    or a character FAT cannot store; names ending with a dot (FAT drops it,
    so the stored name would differ); names longer than a filesystem entry
    can be; and names that listings hide (``is_hidden_entry``).

    This is not on its own sufficient to contain a path: callers must still
    resolve it with ``resolve_in_files_directory``.
    """
    if has_control_character(filename or ""):
        # Before the whitespace is trimmed: trimming would quietly drop a
        # line break at either end, which the caller's copy still carries.
        return None
    name = (filename or "").strip()
    if not name or name in (".", "..") or name.endswith("."):
        return None
    if not is_safe_for_printer(name):
        return None
    if not _FORBIDDEN_CHARACTERS.isdisjoint(name):
        return None
    if len(name.encode("utf-8")) > _MAX_NAME_BYTES:
        return None
    if is_hidden_entry(name):
        return None
    return name


def _is_hidden(path: Path) -> bool:
    """Whether *path* is a hidden entry, under whatever name it is reached.

    The files directory is a FAT filesystem, where an entry also answers to
    its name in another case and to a short alias such as ``SDCP_U~1``. So
    besides the name, an existing entry is compared with the hidden entries
    beside it: if it is one of them, it is hidden too.
    """
    if is_hidden_entry(path.name):
        return True
    try:
        with os.scandir(path.parent) as entries:
            siblings = [entry for entry in entries if is_hidden_entry(entry.name)]
    except OSError:
        # The folder does not exist: nothing to be the same as.
        return False
    for sibling in siblings:
        try:
            # Both looked at in one go, so that a transfer beginning or
            # ending meanwhile cannot make two different files look alike.
            if os.path.samefile(sibling.path, path):
                return True
        except OSError:
            # One of the two is gone, or leads nowhere. The other hidden
            # entries still count.
            continue
    return False


def _is_inside_files_directory(candidate: Path, files_directory: Path) -> bool:
    """Whether *candidate* is the files directory or something clients may reach in it.

    Hidden entries (see ``is_hidden_entry``) are out of reach at any depth:
    they hold transfers in progress, which no client request may list,
    change or remove.
    """
    if candidate == files_directory:
        return True
    if files_directory not in candidate.parents:
        return False
    below = candidate.relative_to(files_directory).parts
    return not any(
        _is_hidden(files_directory.joinpath(*below[: depth + 1]))
        for depth in range(len(below))
    )


def resolve_in_files_directory(relative: str) -> Optional[Path]:
    """Resolve *relative* inside the files directory, or None if it escapes.

    Returns the files directory itself for ``""`` and ``"."``. Symbolic links
    are followed before the check, so a link pointing outside is refused too.
    A path that goes through a hidden entry is refused as well.
    """
    if "\x00" in relative:
        # No path can carry a NUL byte.
        return None
    files_directory = config.get_files_directory().resolve()
    try:
        candidate = (files_directory / relative).resolve()
    except (ValueError, OSError, RuntimeError):
        # Text the filesystem cannot take as a path at all, such as the lone
        # surrogates a JSON client can send, or a symbolic link that leads
        # back to itself (a RuntimeError before Python 3.13).
        return None
    if not _is_inside_files_directory(candidate, files_directory):
        return None
    return candidate


def resolve_entry_in_files_directory(relative: str) -> Optional[Path]:
    """Like ``resolve_in_files_directory``, but for the entry itself.

    The folder holding the entry is resolved; the entry's own name is kept
    as it is. For a symbolic link this gives the link, not what it points
    to, which is what removing an entry must act on: the link goes, its
    target stays, and a link whose target is gone can still be removed.
    (One exception: a link to a hidden entry beside it is itself refused,
    being another name for that entry.)

    Returns None if the path escapes, or does not name an entry (``""``,
    ``.``, a path ending in ``..``).
    """
    if "\x00" in relative:
        # No path can carry a NUL byte.
        return None
    name = os.path.basename(relative.rstrip("/"))
    if name in ("", ".", ".."):
        return None
    try:
        os.fsencode(name)
    except ValueError:
        # Text no entry can be named after, such as the lone surrogates a
        # JSON client can send.
        return None
    parent = resolve_in_files_directory(os.path.dirname(relative.rstrip("/")))
    if parent is None:
        return None
    entry = parent / name
    if not _is_inside_files_directory(entry, config.get_files_directory().resolve()):
        return None
    return entry


class NotPrintable(Exception):
    """Why a name cannot be handed to the printer. See the class constants."""

    # The name itself is unusable, or points outside the files directory.
    UNSAFE = "unsafe"
    # No such file.
    MISSING = "missing"
    # The file exists but is not in a format the printer can print.
    UNSUPPORTED = "unsupported"

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def printable_relative_path(name: str) -> str:
    """The path to give the printer for the file a client calls *name*.

    Every interface that starts a print goes through here. The result is the
    file's path relative to the files directory, which is how the printer
    knows it, whatever form the client used (``./a.ctb``, ``sub/../a.ctb``
    or an absolute path). It is safe to place in a command line sent to the
    printer.

    Raises NotPrintable, with the reason, if *name* does not lead to an
    existing file of a supported format inside the files directory.
    """
    if not is_safe_for_printer(name):
        raise NotPrintable(NotPrintable.UNSAFE)
    path = resolve_in_files_directory(name)
    if path is None:
        raise NotPrintable(NotPrintable.UNSAFE)
    if not os.path.isfile(path):
        raise NotPrintable(NotPrintable.MISSING)
    if get_file_extension(path.name) not in get_supported_extensions():
        raise NotPrintable(NotPrintable.UNSUPPORTED)
    relative = path.relative_to(config.get_files_directory().resolve()).as_posix()
    if not is_safe_for_printer(relative):
        # Possible only through a symbolic link whose target has such a name.
        raise NotPrintable(NotPrintable.UNSAFE)
    return relative


def is_directory(dir_entry: "os.DirEntry[str]") -> bool:
    """Whether *dir_entry* is a folder; False if that cannot be told.

    A symbolic link that leads back to itself cannot be asked, and must not
    take a whole listing down with it.
    """
    try:
        return dir_entry.is_dir()
    except OSError:
        return False


def is_regular_file(dir_entry: "os.DirEntry[str]") -> bool:
    """Whether *dir_entry* is a file; False if that cannot be told."""
    try:
        return dir_entry.is_file()
    except OSError:
        return False


def remove_entry(path: Path) -> None:
    """Remove the file or link at *path*, unless it is a hidden entry.

    *path* was checked when it was resolved, but a transfer may have begun
    since, and its scratch file answers to other names on a FAT filesystem.
    Checking again right before the removal leaves next to no time for
    that. Raises FileNotFoundError for a hidden entry, as for a missing one.
    """
    if _is_hidden(path):
        raise FileNotFoundError(path)
    os.remove(path)


def printable_files() -> Iterator[Path]:
    """Every file of a supported format in the files directory, at any depth.

    Hidden entries are left out, with all they hold, and so is whatever a
    symbolic link leads to outside the files directory: a folder reached
    through a link is not entered, and a file is given only if it stays
    inside.
    """
    files_directory = config.get_files_directory().resolve()
    supported = get_supported_extensions()
    for folder, subfolders, names in os.walk(files_directory):
        subfolders[:] = [name for name in subfolders if not is_hidden_entry(name)]
        for name in names:
            if is_hidden_entry(name) or get_file_extension(name) not in supported:
                continue
            path = Path(folder) / name
            if path.is_symlink() and not stays_in_files_directory(path):
                continue
            yield path


def move_aside(path: Path) -> Path:
    """Move the folder at *path* to a scratch name beside it, and give that name.

    For removing a folder in two steps: this one is instant, and the slow
    removal of its contents can follow without holding anything up. Like
    ``remove_entry``, it checks once more that *path* is not a hidden entry,
    and raises FileNotFoundError if it is.
    """
    if _is_hidden(path):
        raise FileNotFoundError(path)
    aside = scratch_path_beside(path)
    os.rename(path, aside)
    return aside


def modification_time(dir_entry: "os.DirEntry[str]") -> float:
    """When *dir_entry* was last modified, for sorting a listing.

    A dangling symbolic link has nothing to stat; it sorts as the oldest
    entry instead of failing the whole listing.
    """
    try:
        return dir_entry.stat().st_mtime
    except OSError:
        return 0.0


def stays_in_files_directory(entry: Path) -> bool:
    """Whether *entry* leads, links followed, to something clients may reach.

    For a listing, which finds entries by scanning a folder: a symbolic
    link is an entry of that folder wherever it points, and one that leads
    out of the files directory, or to a hidden entry, must be neither
    opened nor shown under the name of its target.
    """
    files_directory = config.get_files_directory().resolve()
    try:
        target = entry.resolve()
    except (ValueError, OSError, RuntimeError):
        return False
    return _is_inside_files_directory(target, files_directory)


def is_scratch_file(name: str) -> bool:
    """Whether *name* is something on its way in or out, not an entry to list.

    Case is ignored, as it is by the FAT filesystem the files are on.
    """
    folded = name.casefold()
    return folded.startswith(_SCRATCH_PREFIX) and folded.endswith(_SCRATCH_SUFFIX)


def is_hidden_entry(name: str) -> bool:
    """Whether a directory entry called *name* is kept out of listings.

    True for anything on its way in or out, and for the folder in which the
    SDCP provider assembles its transfers, whatever the case of the name.
    Such names cannot be given to a file or folder either, since the entry
    would then vanish from view.
    """
    return is_scratch_file(name) or name.casefold() == SDCP_SCRATCH_DIRNAME


def holds_a_transfer_in_progress(directory: Path) -> bool:
    """Whether something is being uploaded somewhere under *directory*.

    True as well when part of *directory* cannot be read: not knowing is no
    ground for treating it as free of transfers.
    """

    def stop(error: OSError) -> None:
        raise error

    try:
        # Folders are left out of the names: only a file is a transfer.
        return any(
            is_scratch_file(name)
            for _, _, names in os.walk(directory, onerror=stop)
            for name in names
        )
    except OSError:
        return True


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
