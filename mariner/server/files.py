"""Filename and path checks shared by every interface that touches files.

The web API and the network print providers all take a name or a path from a
client, then store, list, print or delete a file under it. These two helpers
are the single place that decides whether such a value is acceptable, so no
interface can forget a check another one has.
"""

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from mariner import config

# Characters that would let a name escape the files directory, plus the
# single quote: the printer is told which file to print as M6030 '<name>',
# so a quote inside the name ends it early.
_FORBIDDEN = ("/", "\\", "'")


def _has_control_character(value: str) -> bool:
    return any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)


def safe_filename(filename: Optional[str]) -> Optional[str]:
    """The client's filename, preserved, or None if it is not safe to use.

    Deliberately not ``werkzeug.secure_filename``. That rewrites the name:
    it strips parentheses, collapses spaces, and drops non-ASCII entirely,
    extension included. A client that uploads ``model_6(1).ctb`` and then
    asks to print it under that name finds nothing, because the stored file
    is ``model_61.ctb``. Validating and rejecting instead of rewriting keeps
    exactly one name in play across upload, listing, printing and deletion.

    Control characters are refused because the name ends up in a line sent
    to the printer, where a line break starts a new command.

    This is not on its own sufficient to contain a path: callers must still
    resolve it with ``resolve_in_files_directory``.
    """
    name = (filename or "").strip()
    if not name or name in (".", ".."):
        return None
    if any(character in name for character in _FORBIDDEN):
        return None
    if _has_control_character(name):
        return None
    return name


def is_safe_for_printer(path: str) -> bool:
    """Whether *path* can be placed in a command line sent to the printer.

    Unlike ``safe_filename`` this accepts ``/``, since files in a
    subdirectory are selected by their relative path.
    """
    return bool(path) and "'" not in path and not _has_control_character(path)


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


@contextmanager
def replacing(destination: Path) -> Iterator[Path]:
    """Yield a scratch path whose contents become *destination* on success.

    The file is written under a temporary name next to its destination and
    moved into place in one step. The printer therefore never reads a
    half-written file under its final name, and an upload that fails leaves
    the file it was meant to replace untouched.
    """
    scratch = destination.with_name(f".upload-{destination.name}.part")
    try:
        yield scratch
        os.replace(scratch, destination)
    except BaseException:
        try:
            os.remove(scratch)
        except OSError:
            pass
        raise
