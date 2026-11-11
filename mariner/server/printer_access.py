"""The one way in to the printer's serial port.

The web UI polls the printer every few seconds, the SDCP service does the
same for its clients, and a slicer can send a command at any moment. They all
share a single serial line on which a command is followed by its answer, so
two conversations at once read each other's answers. Everything that talks to
the printer goes through this module and therefore waits its turn.

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

A status poll takes the second, then the third. A file operation that needs
nothing from the printer, such as storing a new file, does not ask the
printer itself. It can still wait behind a print that is being started, or
behind another file operation that has to ask the printer again, for as
long as the printer takes to answer: seconds when it is silent.
"""

import os
import threading
import time
from contextlib import contextmanager
from enum import Enum
from pathlib import Path
from typing import Iterator, Optional, Tuple, Type

import serial

from mariner.exceptions import (
    FileNotSelected,
    PrintAlreadyRunning,
    PrintJustStarted,
    UnexpectedPrinterResponse,
)
from mariner.printer import ChiTuPrinter, PrinterState, PrintStatus
from mariner.server.files import printable_relative_path, resolve_in_files_directory
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

# Giving up on a printer that stays silent takes several seconds. That
# silence is kept longer, so that the same refusal is not paid for again on
# every attempt. Keeping it errs on the safe side: while it lasts, existing
# files stay protected. It is replaced by the next status read, and it is
# never enough to grant an override (see ``unless_in_use``). Any other
# answer, however unclear, is kept no longer than a clear one, so that
# trying again a moment later does ask again.
_SILENCE_MAX_AGE_SECS = 30.0

# For a moment after being told to print, the printer still reports that it
# is idle. A file Mariner has just started printing is treated as in use for
# this long, or until the printer reports a print itself.
_START_GRACE_SECS = 30.0

# The first two are reentrant, so that code holding one of them can call the
# helpers below. The third is never held across a call.
_change_lock = threading.RLock()
_serial_lock = threading.RLock()
_memory_lock = threading.Lock()

# The last status read and when. Guarded by _memory_lock.
_last_status: Optional[Tuple[float, PrintStatus, str]] = None

# The file Mariner last started printing and when, until the printer reports
# a print itself or the grace period runs out. Only one: no other print is
# started meanwhile (see ``start_print``). Guarded by _memory_lock.
_just_started: Optional[Tuple[Path, float]] = None


class Usage(Enum):
    """What the print in progress means for a file or folder."""

    # Positively not being read by the printer.
    FREE = "free"
    # The printer is reading it, or something inside it.
    PRINTING = "printing"
    # Mariner sent the command to print it a moment ago, and the printer
    # has yet to report that print. Cancelling does not lift this: nothing
    # the printer says in that moment tells a print that was stopped from
    # one that is about to begin.
    JUST_STARTED = "print just started"
    # A print is running, but which file it reads could not be established.
    UNIDENTIFIED_PRINT = "unidentified print"
    # No clear word from the printer: it answered something that settles
    # nothing, or the serial port could not be used.
    PRINTER_UNCLEAR = "printer answer unclear"
    # The printer was asked and nothing at all came back, or its serial
    # device is not there: it is off, or unplugged.
    PRINTER_UNREACHABLE = "printer unreachable"


class FileInUse(Exception):
    """Raised when a file operation could disturb a print in progress.

    ``usage`` says why, and is never ``Usage.FREE``.
    """

    def __init__(self, path: Path, usage: Usage) -> None:
        # The name is quoted: it comes from a client and ends up in logs,
        # where a line break in it would start a line of its own.
        super().__init__(f"{path.name!r}: {usage.value}")
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
def _open_printer() -> Iterator[ChiTuPrinter]:
    with _serial_lock:
        with ChiTuPrinter() as printer:
            yield printer


@contextmanager
def printer_session() -> Iterator[ChiTuPrinter]:
    """Open the printer for one conversation, exclusively.

    For sending commands. What the printer was last known to be doing is
    forgotten afterwards, since a command may have changed it. To read the
    status, use ``read_status``, which remembers its answer.
    """
    with _open_printer() as printer:
        try:
            yield printer
        finally:
            _forget_last_status()


def start_print(name: str) -> str:
    """Tell the printer to print the file a client calls *name*.

    Every interface starts a print through here. Returns the path that was
    sent to the printer, relative to the files directory, which is how the
    printer knows the file; see ``files.printable_relative_path``, whose
    NotPrintable this raises if *name* does not lead to a file that can be
    printed. That is checked here, with file changes held off, so that the
    file cannot be removed between the check and the command.

    The file counts as in use from the moment the print command is sent,
    before the printer reports the print. That holds even if the printer's
    answer to that command is lost and this raises: the print may well be
    starting, and wrongly protecting a file for a moment is harmless.

    Nothing is remembered when the print cannot have started: the name was
    refused outright (``ValueError``), or the printer did not select the
    file (``FileNotSelected``), which comes before the print command and
    includes a printer that is switched off.

    Raises ``PrintAlreadyRunning``, sending no print command, if the
    printer reports a print under way, and ``PrintJustStarted`` if Mariner
    started one a moment ago that the printer has yet to report: the
    printer might select the new file while still reading the old one, and
    the file it then names would no longer be the one to protect.

    A printer whose answer settles nothing is still sent the command, and
    turns it down itself if it cannot print. Refusing on anything short of
    a clear "idle" would be safer still, but would leave a board that
    answers tersely unable to print at all.

    Otherwise raises whatever ``ChiTuPrinter.start_printing`` raises.
    """
    with _change_lock:
        relative_path = printable_relative_path(name)
        status, _ = read_status()
        if status.state in _ACTIVE_STATES:
            raise PrintAlreadyRunning()
        if _file_just_started() is not None:
            raise PrintJustStarted()
        with printer_session() as printer:
            print_command_sent = True
            try:
                printer.start_printing(relative_path)
            except (ValueError, FileNotSelected):
                print_command_sent = False
                raise
            finally:
                if print_command_sent:
                    _remember_started(relative_path)
    return relative_path


def _remember_started(relative_path: str) -> None:
    global _just_started
    started = resolve_in_files_directory(relative_path)
    if started is not None:
        with _memory_lock:
            _just_started = (started, time.monotonic())


def _query_printer() -> Tuple[PrintStatus, str]:
    with _open_printer() as printer:
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
    global _last_status, _just_started
    # Held until the answer is stored, not only while asking: otherwise an
    # answer read just before a print is started could be stored just
    # after, and be taken for the printer's word on that print.
    with _serial_lock:
        try:
            status, selected_file = _query_printer()
        except TRANSIENT_ERRORS + (OSError,):
            status, selected_file = PrintStatus(state=PrinterState.CLOSED), ""
        with _memory_lock:
            _last_status = (time.monotonic(), status, selected_file)
            if status.state in _ACTIVE_STATES:
                # The printer now reports a print itself, and names its
                # file. What Mariner assumed since it started one is no
                # longer needed, whoever asked.
                _just_started = None
        return (status, selected_file)


def _remembered_status() -> Optional[Tuple[PrintStatus, str]]:
    """The last status read, if it is recent enough to rely on."""
    with _memory_lock:
        if _last_status is None:
            return None
        read_at, status, selected_file = _last_status
    max_age = _SILENCE_MAX_AGE_SECS if status.silent else _STATUS_MAX_AGE_SECS
    if time.monotonic() - read_at >= max_age:
        return None
    return (status, selected_file)


def _recent_status() -> Tuple[PrintStatus, str]:
    """The status, asking the printer only if nothing recent is remembered.

    If someone else is talking to the printer, this waits for them, and then
    looks again before asking: a status poll that just finished has left its
    answer behind, and that answer will do.
    """
    remembered = _remembered_status()
    if remembered is not None:
        return remembered
    with _serial_lock:
        return _remembered_status() or read_status()


def _file_just_started() -> Optional[Path]:
    """The file Mariner started printing, while the printer has yet to say so.

    Forgotten by ``read_status`` as soon as the printer reports a print,
    and after the grace period if the printer never does.
    """
    global _just_started
    with _memory_lock:
        if _just_started is None:
            return None
        started, started_at = _just_started
        if time.monotonic() - started_at >= _START_GRACE_SECS:
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
    and is another one. Otherwise the path is in use, for one of the reasons
    the result tells apart. Refusing a harmless change costs a
    retry; allowing a harmful one costs the print.
    """
    if not os.path.lexists(path):
        return Usage.FREE

    status, selected_file = _recent_status()

    if status.state in _ACTIVE_STATES:
        printing = resolve_in_files_directory(selected_file) if selected_file else None
        if printing is None or not os.path.lexists(printing):
            return Usage.UNIDENTIFIED_PRINT
        return Usage.PRINTING if _concerns(printing, path) else Usage.FREE

    started = _file_just_started()
    if started is not None and _concerns(started, path):
        return Usage.JUST_STARTED
    if _is_confirmed_idle(status):
        return Usage.FREE
    return Usage.PRINTER_UNREACHABLE if status.silent else Usage.PRINTER_UNCLEAR


@contextmanager
def unless_in_use(path: Path, *, even_if_unreachable: bool = False) -> Iterator[None]:
    """Run the block only if *path* is free, raising FileInUse otherwise.

    Starting a print through Mariner is held off for the whole block, so a
    print cannot begin on *path* between the check and the change the block
    makes. Keep the block short, a rename or a single removal.

    *even_if_unreachable* lets the block run although the printer is
    positively silent (``Usage.PRINTER_UNREACHABLE``). It is for a user who
    knows the printer is switched off and says so explicitly. It is granted
    only on silence observed after this request arrived, never on silence
    remembered from before, and never when the printer answered anything
    at all or could not be asked.
    """
    asked_at: Optional[float] = None
    if os.path.lexists(path):
        # The printer is asked before the lock is taken, so that operations
        # that need nothing from it are not held up meanwhile.
        if even_if_unreachable:
            read_status()
            asked_at = time.monotonic()
        else:
            _recent_status()

    with _change_lock:
        usage = usage_of(path)
        if usage is Usage.PRINTER_UNREACHABLE and even_if_unreachable:
            if asked_at is None or time.monotonic() - asked_at >= _STATUS_MAX_AGE_SECS:
                # The wait for the lock outlasted the answer. Ask again.
                read_status()
                usage = usage_of(path)
            if usage is Usage.PRINTER_UNREACHABLE:
                usage = Usage.FREE
        if usage is not Usage.FREE:
            raise FileInUse(path, usage)
        yield
