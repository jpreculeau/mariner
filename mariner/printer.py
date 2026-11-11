import logging
import os
import re
import time
from dataclasses import dataclass
from enum import Enum
from types import TracebackType
from typing import Match, Optional, Type

import serial

from mariner import config
from mariner.exceptions import UnexpectedPrinterResponse

logger: logging.Logger = logging.getLogger(__name__)


def has_control_character(value: str) -> bool:
    """Whether *value* holds a character that would break a command line."""
    return any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)


def is_safe_for_printer(path: str) -> bool:
    """Whether *path* can be placed in a command line sent to the printer.

    A line break would start a second command, and a single quote would end
    the quoted file name of the print command early. Text that is not valid
    Unicode cannot be sent at all. ``/`` is fine: a file in a subdirectory
    is selected by its relative path.
    """
    if not path or "'" in path or has_control_character(path):
        return False
    try:
        path.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


class PrinterState(Enum):
    IDLE = "IDLE"
    STARTING_PRINT = "STARTING_PRINT"
    PRINTING = "PRINTING"
    PAUSED = "PAUSED"
    CLOSED = "CLOSED"


@dataclass(frozen=True)
class PrintStatus:
    state: PrinterState
    current_byte: Optional[int] = None
    total_bytes: Optional[int] = None
    z_pos_mm: Optional[float] = None
    # Whether the printer's answer carried its print counters (the "D:"
    # field). An answer of nothing but "ok" also reads as IDLE, but says
    # nothing about a print; this tells the two apart.
    counters_seen: bool = False


class ChiTuPrinter:
    _serial_port: serial.Serial
    # Track serial / printer connection status to allow disconnects
    _is_connected = False

    def __init__(self) -> None:
        self._serial_port = serial.Serial(
            baudrate=config.get_printer_baudrate(),
            timeout=0.1,
        )

    def _extract_response_with_regex(self, regex: str, data: str) -> Match[str]:
        match = re.search(regex, data)
        if match is None:
            raise UnexpectedPrinterResponse(data)
        return match

    def open(self) -> None:
        try:
            self._serial_port.port = config.get_printer_serial_port()
            self._serial_port.open()
            self._is_connected = True
        except serial.SerialException:
            self._is_connected = False

    def close(self) -> None:
        if self._is_connected:
            self._serial_port.close()

    def __enter__(self) -> "ChiTuPrinter":
        self.open()
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_value: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> bool:
        self.close()
        return False

    def get_firmware_version(self) -> str:
        data = self._send_and_read(b"M4002")
        return self._extract_response_with_regex(
            "^ok ([a-zA-Z0-9_.]+)\r?\n$", data
        ).group(1)

    def get_state(self) -> str:
        return self._send_and_read(b"M4000")

    def get_print_status(self) -> PrintStatus:
        current_byte = 0
        total_bytes = 0
        z_pos_mm: Optional[float] = None
        if self._is_connected:
            match = None
            data = ""
            try:
                for _ in range(3):
                    data = self._send_and_read_until_contains(
                        b"M4000",
                        "D:",
                        max_readline_attempts=30,
                        read_timeout_secs=3.0,
                    )
                    logger.debug("M4000 raw response: %r", data)
                    match = re.search("D:([0-9]+)/([0-9]+)/([0-9]+)", data)
                    if match is not None:
                        break
            except serial.SerialException as exception:
                logger.warning(
                    "Serial exception while reading M4000; "
                    "treating printer as CLOSED. error=%s",
                    exception,
                )
                self._is_connected = False
                return PrintStatus(state=PrinterState.CLOSED)
            if match is None:
                if "ok" in data:
                    return PrintStatus(state=PrinterState.IDLE)
                logger.warning(
                    "M4000 returned no parseable status payload; "
                    "treating printer as CLOSED. last_response=%r",
                    data,
                )
                return PrintStatus(state=PrinterState.CLOSED)

            current_byte = int(match.group(1))
            total_bytes = int(match.group(2))
            is_paused = match.group(3) == "1"
            z_match = re.search(r"Z:(-?[0-9]+\.[0-9]+)", data)
            if z_match is not None:
                z_pos_mm = float(z_match.group(1))
            logger.debug(
                "M4000 parsed D: current=%s total=%s paused_flag=%s z=%s",
                current_byte,
                total_bytes,
                match.group(3),
                z_pos_mm,
            )

            if total_bytes == 0:
                return PrintStatus(state=PrinterState.IDLE, counters_seen=True)

            if current_byte == 0:
                state = PrinterState.STARTING_PRINT
            elif is_paused:
                state = PrinterState.PAUSED
            else:
                state = PrinterState.PRINTING
        else:
            return PrintStatus(
                state=PrinterState.CLOSED,
                current_byte=current_byte,
                total_bytes=total_bytes,
            )

        return PrintStatus(
            state=state,
            current_byte=current_byte,
            total_bytes=total_bytes,
            z_pos_mm=z_pos_mm,
            counters_seen=True,
        )

    def get_z_pos(self) -> float:
        data = self._send_and_read(b"M114")
        return float(self._extract_response_with_regex("Z:([0-9.]+)", data).group(1))

    def get_selected_file(self) -> str:
        if not self._is_connected:
            return ""

        # SerialException mid-read is now converted to UnexpectedPrinterResponse
        # by _send_and_read, so it propagates to retry()/api.py which degrades
        # to CLOSED state — no need to catch it here.
        data = self._send_and_read(b"M4006")
        selected_file = str(
            self._extract_response_with_regex("ok '([^']+)'\r\n", data).group(1)
        )
        # normalize the selected file by removing the leading slash, which is
        # sometimes returned by the printer
        return re.sub("^/", "", selected_file)

    @staticmethod
    def _check_filename(filename: str) -> None:
        """Refuse a filename that would not stay inside its command line.

        Callers validate names before they get here. This is the last check
        before the wire.
        """
        if not is_safe_for_printer(filename):
            raise ValueError(f"unsafe filename for the printer: {filename!r}")

    def select_file(self, filename: str) -> None:
        self._check_filename(filename)
        response = self._send_and_read((f"M23 /{filename}").encode())
        if "File opened" not in response and "File selected" not in response:
            raise UnexpectedPrinterResponse(response)

    def move_by(self, z_dist_mm: float, mm_per_min: int = 600) -> None:
        response = self._send_and_read(
            (f"G0 Z{z_dist_mm:.1f} F{mm_per_min} I0").encode()
        )
        if "ok" not in response:
            raise UnexpectedPrinterResponse(response)

    def move_to(self, z_pos: float) -> str:
        return self._send_and_read((f"G0 Z{z_pos:.1f}").encode())

    def move_to_home(self) -> None:
        response = self._send_and_read(b"G28")
        if "ok" not in response:
            raise UnexpectedPrinterResponse(response)

    def start_printing(self, filename: str) -> None:
        # the printer's firmware is weird when the file is in a subdirectory. we need to
        # send M23 to select the file with its full path and then M6030 with just the
        # basename.
        self._check_filename(filename)
        self.select_file(filename)
        response = self._send_and_read(
            (f"M6030 '{os.path.basename(filename)}'").encode(),
            # the mainboard takes longer to reply to this command, so we override the
            # timeout to 2 seconds
            timeout_secs=2.0,
        )
        if "ok" not in response:
            raise UnexpectedPrinterResponse(response)

    def pause_printing(self) -> None:
        response = self._send_and_read(b"M25")
        if "ok" not in response:
            raise UnexpectedPrinterResponse(response)

    def resume_printing(self) -> None:
        response = self._send_and_read(b"M24")
        if "ok" not in response:
            raise UnexpectedPrinterResponse(response)

    def stop_printing(self) -> None:
        response = self._send_and_read(b"M33")
        if "Error" in response or "Er" in response:
            raise UnexpectedPrinterResponse(response)

    def stop_motors(self) -> None:
        response = self._send_and_read(b"M112")
        if "ok" not in response:
            raise UnexpectedPrinterResponse(response)

    def reboot(self, delay_in_ms: int = 0) -> None:
        self._send((f"M6040 I{delay_in_ms}").encode())

    def _send_and_read(self, data: bytes, timeout_secs: Optional[float] = None) -> str:
        try:
            self._serial_port.reset_input_buffer()
            self._serial_port.reset_output_buffer()

            self._send(data + b"\r\n")

            original_timeout = self._serial_port.timeout
            if timeout_secs is not None:
                self._serial_port.timeout = timeout_secs
            # A single readline often times out (default 0.1s) before the board
            # replies, yielding ''. Retrying readline without re-sending avoids
            # flaky UnexpectedPrinterResponse on /api/print_status and elsewhere.
            max_empty_line_reads = 15
            response = ""
            for _ in range(max_empty_line_reads):
                line = self._serial_port.readline().decode("utf-8", errors="replace")
                if line:
                    response = line
                    break
            if timeout_secs is not None:
                self._serial_port.timeout = original_timeout
            # TODO actually read the rest of the response instead of just
            # flushing it like this
            self._serial_port.read(size=1024)
            return response
        except serial.SerialException as exception:
            # Cable unplugged / kernel closed the tty mid-read. Mark the port
            # dead so subsequent calls short-circuit, and surface a typed
            # error so callers (and retry()) can react.
            logger.warning(
                "Serial exception during _send_and_read(%r); "
                "treating printer as disconnected. error=%s",
                data,
                exception,
            )
            self._is_connected = False
            raise UnexpectedPrinterResponse("") from exception

    def _send_and_read_until_contains(
        self,
        data: bytes,
        expected_substring: str,
        *,
        max_readline_attempts: int = 20,
        read_timeout_secs: float = 2.0,
    ) -> str:
        self._serial_port.reset_input_buffer()
        self._serial_port.reset_output_buffer()
        self._send(data + b"\r\n")

        original_timeout = self._serial_port.timeout
        self._serial_port.timeout = 0.1

        deadline = time.monotonic() + read_timeout_secs
        response = ""
        attempts = 0
        while attempts < max_readline_attempts and time.monotonic() < deadline:
            line = self._serial_port.readline().decode("utf-8", errors="replace")
            attempts += 1
            if expected_substring in line:
                response = line
                break
            if line:
                response = line

        self._serial_port.timeout = original_timeout
        self._serial_port.read(size=1024)
        return response

    def _send(self, data: bytes) -> None:
        self._serial_port.write(data)
