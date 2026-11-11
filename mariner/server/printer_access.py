"""The one way in to the printer's serial port.

The web UI polls the printer every few seconds, the SDCP service does the
same for its clients, and a slicer can send a command at any moment. They all
share a single serial line on which a command is followed by its answer, so
two conversations at once read each other's answers. Everything that talks to
the printer goes through ``printer_session`` and therefore waits its turn.

This module also answers the question every file operation has to ask before
replacing or removing a file: is the printer reading it right now? See
``usage_of`` and ``unless_in_use``.

The answer comes from the printer itself, so it is the same whether the print
was started from Mariner, from a slicer or from the printer's own screen. When
the printer does not answer, the question cannot be settled, and an existing
file is treated as in use until it can be: see ``Usage.UNKNOWN``.
"""

import os
import threading
import time
from contextlib import contextmanager
from enum import Enum
from pathlib import Path
from typing import Iterator, Optional, Tuple, Type

import serial

from mariner.exceptions import UnexpectedPrinterResponse
from mariner.printer import ChiTuPrinter, PrinterState, PrintStatus
from mariner.server.files import resolve_in_files_directory
from mariner.server.utils import retry

TRANSIENT_ERRORS: Tuple[Type[Exception], ...] = (
    UnexpectedPrinterResponse,
    serial.SerialException,
)

_ACTIVE_STATES = (
    PrinterState.STARTING_PRINT,
    PrinterState.PRINTING,
    PrinterState.PAUSED,
)

# How long a status read stays good enough to decide whether a file is in
# use. Long enough for a check before an upload and another as it completes,
# or for a batch of deletions, to share one conversation with the printer;
# short enough that a print started from the printer's own screen is noticed
# almost at once.
_STATUS_MAX_AGE_SECS = 1.0

# Giving up on a printer that does not answer takes several seconds, every
# time. That answer is kept longer so repeated attempts are told at once.
# Keeping it errs on the safe side: while it lasts, existing files stay
# protected. Reading the status again (see ``read_status``) replaces it.
_CLOSED_STATUS_MAX_AGE_SECS = 30.0

# Reentrant, so a caller that already holds the port can use the helpers
# below without deadlocking on itself.
_printer_lock = threading.RLock()

# The last status read and when, guarded by _printer_lock.
_last_status: Optional[Tuple[float, PrintStatus, str]] = None


class Usage(Enum):
    """What the print in progress means for a file or folder."""

    FREE = "free"
    # The printer is reading it, or something inside it.
    PRINTING = "printing"
    # The printer did not answer, so whether it is being read is not known.
    UNKNOWN = "unknown"


class FileInUse(Exception):
    """Raised when a file operation could disturb a print in progress."""

    def __init__(self, path: Path, usage: Usage) -> None:
        super().__init__(f"{path.name}: {usage.value}")
        self.path = path
        self.usage = usage

    @property
    def printer_is_silent(self) -> bool:
        """Whether the refusal comes from not knowing, not from a known print."""
        return self.usage is Usage.UNKNOWN


def forget_status() -> None:
    """Drop the remembered status, so the next check asks the printer again."""
    global _last_status
    with _printer_lock:
        _last_status = None


@contextmanager
def printer_session() -> Iterator[ChiTuPrinter]:
    """Open the printer for one conversation, exclusively."""
    with _printer_lock:
        # Whatever is said next may change what the printer is doing, so the
        # remembered status can no longer be trusted.
        forget_status()
        with ChiTuPrinter() as printer:
            yield printer


def _query_printer() -> Tuple[PrintStatus, str]:
    with printer_session() as printer:
        status = retry(printer.get_print_status, TRANSIENT_ERRORS, num_retries=3)
        if status.state == PrinterState.CLOSED:
            return (status, "")
        try:
            selected_file = retry(
                printer.get_selected_file, TRANSIENT_ERRORS, num_retries=3
            )
        except TRANSIENT_ERRORS:
            selected_file = ""
        return (status, selected_file or "")


def read_status() -> Tuple[PrintStatus, str]:
    """The print status and the selected file, as the printer reports them.

    The printer sends unsolicited "ok" lines, so a read can come back with
    the wrong answer; each query is retried a few times. A printer that still
    does not answer is reported as CLOSED with no selected file, so callers
    never have to handle a serial failure themselves.

    If the status is known but the selected file cannot be read, the status
    is kept and the file is reported as ``""``: knowing that a print is
    running matters even when its file is unknown.
    """
    global _last_status
    with _printer_lock:
        try:
            status, selected_file = _query_printer()
        except TRANSIENT_ERRORS + (OSError,):
            status, selected_file = PrintStatus(state=PrinterState.CLOSED), ""
        _last_status = (time.monotonic(), status, selected_file)
        return (status, selected_file)


def _recent_status() -> Tuple[PrintStatus, str]:
    """The status, read again only if the last read is too old to rely on."""
    with _printer_lock:
        if _last_status is not None:
            read_at, status, selected_file = _last_status
            max_age = (
                _CLOSED_STATUS_MAX_AGE_SECS
                if status.state == PrinterState.CLOSED
                else _STATUS_MAX_AGE_SECS
            )
            if time.monotonic() - read_at < max_age:
                return (status, selected_file)
        return read_status()


def same_file(a: Path, b: Path) -> bool:
    """Whether two paths name the same file as the printer sees it.

    The printer reads a FAT filesystem, where names that differ only by case
    are one file.
    """
    return str(a).casefold() == str(b).casefold()


def is_inside(file: Path, directory: Path) -> bool:
    """Whether *file* is somewhere under *directory*, ignoring case."""
    return Path(str(directory).casefold()) in Path(str(file).casefold()).parents


def usage_of(path: Path) -> Usage:
    """What replacing or removing *path* would mean for the print in progress.

    The printer reads its file layer by layer for the whole print, so that
    file, and any folder holding it, must stay as they are until the print is
    over. *path* may be a file or a folder.

    A path that does not exist yet is always free: nothing can be reading
    it, so a new file can be stored whatever the printer is doing.

    For an existing path the printer is asked. If a print is running but the
    printer did not say from which file, or if the printer does not answer
    at all, the result is UNKNOWN rather than FREE: refusing a harmless
    change costs a retry, allowing a harmful one costs the print.
    """
    if not os.path.lexists(path):
        return Usage.FREE
    status, selected_file = _recent_status()
    if status.state == PrinterState.CLOSED:
        return Usage.UNKNOWN
    if status.state not in _ACTIVE_STATES:
        return Usage.FREE
    current = resolve_in_files_directory(selected_file) if selected_file else None
    if current is None:
        return Usage.UNKNOWN
    if same_file(current, path) or is_inside(current, path):
        return Usage.PRINTING
    return Usage.FREE


def is_in_use(path: Path) -> bool:
    """Whether *path* must be left alone for now. See ``usage_of``."""
    return usage_of(path) is not Usage.FREE


@contextmanager
def unless_in_use(path: Path) -> Iterator[None]:
    """Run the block only if *path* is free, raising FileInUse otherwise.

    The printer lock is held for the whole block. Starting a print through
    Mariner needs the same lock, so a print cannot begin on *path* between
    the check and the change the block makes. Keep the block short: every
    other conversation with the printer waits for it.
    """
    with _printer_lock:
        usage = usage_of(path)
        if usage is not Usage.FREE:
            raise FileInUse(path, usage)
        yield
