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
the printer does not give a clear answer, the question cannot be settled, and
an existing file is treated as in use until it can be.

Three locks, always taken in this order, never the other way round:

1. ``_change_lock`` makes "check that a file is free, then change it" and
   "start a print" exclude each other.
2. ``_serial_lock`` is held for the length of one conversation with the
   printer, which can be seconds.
3. ``_memory_lock`` guards the two things remembered between conversations,
   and is never held while anything else happens.

A status poll takes only the second, so file operations that do not need to
ask the printer anything never wait behind one.
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

# Giving up on a printer that does not answer takes several seconds. That
# answer is kept longer, so that a refusal is repeated at once instead of
# after the same wait each time. Keeping it errs on the safe side: while it
# lasts, existing files stay protected. Any new conversation with the
# printer, a status poll included, replaces it.
_CLOSED_STATUS_MAX_AGE_SECS = 30.0

# For a moment after being told to print, the printer still reports that it
# is idle. A file Mariner has just started printing is treated as in use for
# this long, or until the printer reports the print itself.
_START_GRACE_SECS = 30.0

# Reentrant, so that code holding one of them can call the helpers below.
_change_lock = threading.RLock()
_serial_lock = threading.RLock()
_memory_lock = threading.Lock()

# The last status read and when. Guarded by _memory_lock.
_last_status: Optional[Tuple[float, PrintStatus, str]] = None

# The file Mariner last started printing and when, until the printer reports
# the print itself. Guarded by _memory_lock.
_just_started: Optional[Tuple[Path, float]] = None


class Usage(Enum):
    """What the print in progress means for a file or folder."""

    # Positively not being read by the printer.
    FREE = "free"
    # The printer is reading it, or something inside it.
    PRINTING = "printing"
    # A print is running, but which file it reads could not be established.
    UNIDENTIFIED_PRINT = "unidentified print"
    # The printer did not answer, or not clearly enough to tell.
    PRINTER_UNREACHABLE = "printer unreachable"


class FileInUse(Exception):
    """Raised when a file operation could disturb a print in progress.

    ``usage`` says why, and is never ``Usage.FREE``.
    """

    def __init__(self, path: Path, usage: Usage) -> None:
        super().__init__(f"{path.name}: {usage.value}")
        self.path = path
        self.usage = usage


def forget_status() -> None:
    """Drop everything remembered about the printer.

    The next check then asks the printer, and a print started a moment ago
    is no longer assumed. Used by tests to start from a clean slate.
    """
    global _last_status, _just_started
    with _memory_lock:
        _last_status = None
        _just_started = None


def _forget_last_status() -> None:
    global _last_status
    with _memory_lock:
        _last_status = None


@contextmanager
def printer_session() -> Iterator[ChiTuPrinter]:
    """Open the printer for one conversation, exclusively."""
    with _serial_lock:
        # Whatever is said next may change what the printer is doing, so the
        # remembered status can no longer be trusted.
        _forget_last_status()
        with ChiTuPrinter() as printer:
            yield printer


def start_print(relative_path: str) -> None:
    """Tell the printer to print the file at *relative_path*.

    Every interface starts a print through here. *relative_path* is relative
    to the files directory, as the printer knows it; see
    ``files.printable_relative_path``.

    The file counts as in use from the moment the command is sent, before
    the printer reports the print. That holds even if the printer's answer
    is lost and this raises: the command may have gone through, and wrongly
    protecting a file for a moment is harmless. Only a name the printer
    class refuses outright (``ValueError``), which is never sent, is not
    remembered.

    Raises whatever ``ChiTuPrinter.start_printing`` raises.
    """
    with _change_lock:
        with printer_session() as printer:
            sent = True
            try:
                printer.start_printing(relative_path)
            except ValueError:
                sent = False
                raise
            finally:
                if sent:
                    _remember_started(relative_path)


def _remember_started(relative_path: str) -> None:
    global _just_started
    started = resolve_in_files_directory(relative_path)
    if started is not None:
        with _memory_lock:
            _just_started = (started, time.monotonic())


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
    """Ask the printer for its print status and its selected file.

    A printer that cannot be reached, or whose answers cannot be read after
    a few attempts, is reported as CLOSED with no selected file, so callers
    never have to handle a serial failure themselves.

    If the status is known but the selected file cannot be read, the status
    is kept and the file is reported as ``""``: knowing that a print is
    running matters even when its file is unknown.
    """
    global _last_status
    with _serial_lock:
        try:
            status, selected_file = _query_printer()
        except TRANSIENT_ERRORS + (OSError,):
            status, selected_file = PrintStatus(state=PrinterState.CLOSED), ""
        with _memory_lock:
            _last_status = (time.monotonic(), status, selected_file)
        return (status, selected_file)


def _remembered_status() -> Optional[Tuple[PrintStatus, str]]:
    """The last status read, if it is recent enough to rely on."""
    with _memory_lock:
        if _last_status is None:
            return None
        read_at, status, selected_file = _last_status
    max_age = (
        _CLOSED_STATUS_MAX_AGE_SECS
        if status.state == PrinterState.CLOSED
        else _STATUS_MAX_AGE_SECS
    )
    if time.monotonic() - read_at >= max_age:
        return None
    return (status, selected_file)


def _recent_status() -> Tuple[PrintStatus, str]:
    """The status, asking the printer only if nothing recent is remembered."""
    return _remembered_status() or read_status()


def _file_just_started(status: PrintStatus) -> Optional[Path]:
    """The file Mariner started printing, while the printer has yet to say so."""
    global _just_started
    with _memory_lock:
        if _just_started is None:
            return None
        started, started_at = _just_started
        reported_by_printer = status.state in _ACTIVE_STATES
        expired = time.monotonic() - started_at >= _START_GRACE_SECS
        if reported_by_printer or expired:
            _just_started = None
            return None
        return started


def same_file(a: Path, b: Path) -> bool:
    """Whether two paths name the same file as the printer sees it.

    The printer reads a FAT filesystem, where one file answers to several
    names: any mix of upper and lower case, and a short ``MODEL~1.CTB``
    alias. So the filesystem is asked whether the two paths lead to the same
    file. Only when it cannot say, because one of them does not exist, are
    the names compared instead, without regard to case.
    """
    try:
        return os.path.samefile(a, b)
    except OSError:
        return str(a).casefold() == str(b).casefold()


def is_inside(file: Path, directory: Path) -> bool:
    """Whether *file* is somewhere under *directory*, however it is named."""
    return any(same_file(parent, directory) for parent in file.parents)


def _concerns(printing: Path, path: Path) -> bool:
    """Whether changing *path* would change the file being printed."""
    return same_file(printing, path) or is_inside(printing, path)


def _is_confirmed_idle(status: PrintStatus) -> bool:
    """Whether the printer positively reported that nothing is printing.

    A printer also reads as IDLE when it answered with nothing but "ok",
    which says nothing about a print. Only an answer that carried the print
    counters counts.
    """
    return status.state == PrinterState.IDLE and status.counters_seen


def usage_of(path: Path) -> Usage:
    """What replacing or removing *path* would mean for the print in progress.

    The printer reads its file layer by layer for the whole print, so that
    file, and any folder holding it, must stay as they are until the print is
    over. *path* may be a file or a folder.

    A path that does not exist yet is always FREE, without asking the
    printer: nothing can be reading it, so a new file can be stored whatever
    the printer is doing.

    For an existing path the result is FREE only on positive evidence: the
    printer reports that it is idle, or reports a print whose file is found
    and is another one. Otherwise the path is in use, for one of three
    reasons the result tells apart. Refusing a harmless change costs a
    retry; allowing a harmful one costs the print.
    """
    if not os.path.lexists(path):
        return Usage.FREE

    status, selected_file = _recent_status()
    just_started = _file_just_started(status)

    if status.state in _ACTIVE_STATES:
        printing = resolve_in_files_directory(selected_file) if selected_file else None
        if printing is None or not os.path.lexists(printing):
            return Usage.UNIDENTIFIED_PRINT
        return Usage.PRINTING if _concerns(printing, path) else Usage.FREE

    if just_started is not None and _concerns(just_started, path):
        return Usage.PRINTING
    if _is_confirmed_idle(status):
        return Usage.FREE
    return Usage.PRINTER_UNREACHABLE


def is_in_use(path: Path) -> bool:
    """Whether *path* must be left alone for now. See ``usage_of``."""
    return usage_of(path) is not Usage.FREE


@contextmanager
def unless_in_use(path: Path, *, even_if_unreachable: bool = False) -> Iterator[None]:
    """Run the block only if *path* is free, raising FileInUse otherwise.

    Starting a print through Mariner is held off for the whole block, so a
    print cannot begin on *path* between the check and the change the block
    makes. Keep the block short, a rename or a single removal.

    *even_if_unreachable* lets the block run although the printer could not
    be asked (``Usage.PRINTER_UNREACHABLE``). It is for a user who knows the
    printer is switched off and says so explicitly; it never overrides a
    print the printer did report.
    """
    with _change_lock:
        usage = usage_of(path)
        overridden = even_if_unreachable and usage is Usage.PRINTER_UNREACHABLE
        if usage is not Usage.FREE and not overridden:
            raise FileInUse(path, usage)
        yield
