"""The one way in to the printer's serial port.

The web UI polls the printer every few seconds, the SDCP service does the
same for its clients, and a slicer can send a command at any moment. They all
share a single serial line on which a command is followed by its answer, so
two conversations at once read each other's answers. Everything that talks to
the printer goes through ``printer_session`` and therefore waits its turn.

This module also answers the question every file operation has to ask before
replacing or removing a file: is the printer reading it right now?
"""

import threading
from contextlib import contextmanager
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

# Reentrant, so a caller that already holds the port can use the helpers
# below without deadlocking on itself.
_printer_lock = threading.RLock()


@contextmanager
def printer_session() -> Iterator[ChiTuPrinter]:
    """Open the printer for one conversation, exclusively."""
    with _printer_lock:
        with ChiTuPrinter() as printer:
            yield printer


def read_status() -> Tuple[PrintStatus, str]:
    """The print status and the selected file, as the printer reports them.

    The printer sends unsolicited "ok" lines, so a read can come back with
    the wrong answer; each query is retried a few times. A printer that still
    does not answer is reported as CLOSED with no selected file, so callers
    never have to handle a serial failure themselves.
    """
    try:
        with printer_session() as printer:
            status = retry(printer.get_print_status, TRANSIENT_ERRORS, num_retries=3)
            selected_file = retry(
                printer.get_selected_file, TRANSIENT_ERRORS, num_retries=3
            )
    except TRANSIENT_ERRORS:
        return (PrintStatus(state=PrinterState.CLOSED), "")
    except OSError:
        return (PrintStatus(state=PrinterState.CLOSED), "")
    return (status, selected_file or "")


def file_being_printed() -> Optional[Path]:
    """The file the printer is reading for the print in progress, if any."""
    status, selected_file = read_status()
    if status.state not in _ACTIVE_STATES or not selected_file:
        return None
    return resolve_in_files_directory(selected_file)


def same_file(a: Path, b: Path) -> bool:
    """Whether two paths name the same file as the printer sees it.

    The printer reads a FAT filesystem, where names that differ only by case
    are one file.
    """
    return str(a).casefold() == str(b).casefold()


def is_inside(file: Path, directory: Path) -> bool:
    """Whether *file* is somewhere under *directory*, ignoring case."""
    return Path(str(directory).casefold()) in Path(str(file).casefold()).parents


def is_being_printed(path: Path) -> bool:
    """Whether *path* is the file of the print in progress.

    The printer reads the file layer by layer for the whole print, so it must
    not be replaced or removed until the print is over.
    """
    current = file_being_printed()
    return current is not None and same_file(current, path)


def contains_file_being_printed(directory: Path) -> bool:
    """Whether the file of the print in progress is somewhere under *directory*."""
    current = file_being_printed()
    return current is not None and is_inside(current, directory)
