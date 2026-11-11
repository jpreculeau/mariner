import threading
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import serial
from pyexpect import expect
from pyfakefs.fake_filesystem import FakeFilesystem
from pyfakefs.fake_filesystem_unittest import TestCase

from mariner.config import _get_config
from mariner.exceptions import UnexpectedPrinterResponse
from mariner.printer import ChiTuPrinter, PrinterState, PrintStatus
from mariner.server import printer_access


class PrinterAccessTest(TestCase):
    fs: FakeFilesystem
    printer_mock: Any
    printer_patcher: Any

    def setUp(self) -> None:
        _get_config.cache_clear()
        self.setUpPyfakefs(additional_skip_names=["importlib.metadata"])
        self.fs.create_file("/mnt/usb_share/model.ctb", contents=b"x")
        self.fs.create_file("/mnt/usb_share/sub/part.ctb", contents=b"x")

        self.printer_mock = Mock(spec=ChiTuPrinter)
        self.printer_patcher = patch("mariner.server.printer_access.ChiTuPrinter")
        self.printer_patcher.start().return_value = self.printer_mock
        self.printer_mock.__enter__ = Mock(return_value=self.printer_mock)
        self.printer_mock.__exit__ = Mock(return_value=None)

        self.sleep_patcher = patch("mariner.server.utils.time.sleep")
        self.sleep_patcher.start()

    def tearDown(self) -> None:
        self.printer_patcher.stop()
        self.sleep_patcher.stop()

    def _printer_reports(self, state: PrinterState, selected: str) -> None:
        self.printer_mock.get_print_status.return_value = PrintStatus(
            state=state, current_byte=10, total_bytes=100
        )
        self.printer_mock.get_selected_file.return_value = selected

    # ---- one conversation with the printer at a time ----

    def test_only_one_session_talks_to_the_printer_at_a_time(self) -> None:
        first_is_inside = threading.Event()
        release_first = threading.Event()
        second_got_in = threading.Event()

        def first() -> None:
            with printer_access.printer_session():
                first_is_inside.set()
                release_first.wait(timeout=5)

        def second() -> None:
            with printer_access.printer_session():
                second_got_in.set()

        first_thread = threading.Thread(target=first)
        first_thread.start()
        first_is_inside.wait(timeout=5)
        second_thread = threading.Thread(target=second)
        second_thread.start()

        expect(second_got_in.wait(timeout=0.2)).to_equal(False)
        release_first.set()
        expect(second_got_in.wait(timeout=5)).to_equal(True)
        first_thread.join()
        second_thread.join()

    def test_a_session_can_be_reentered_by_the_same_thread(self) -> None:
        with printer_access.printer_session():
            with printer_access.printer_session() as printer:
                expect(printer).to_equal(self.printer_mock)

    def test_the_lock_is_released_when_the_session_fails(self) -> None:
        with self.assertRaises(RuntimeError):
            with printer_access.printer_session():
                raise RuntimeError("boom")
        with printer_access.printer_session() as printer:
            expect(printer).to_equal(self.printer_mock)

    # ---- reading the status ----

    def test_read_status(self) -> None:
        self._printer_reports(PrinterState.PRINTING, "model.ctb")
        status, selected = printer_access.read_status()
        expect(status.state).to_equal(PrinterState.PRINTING)
        expect(selected).to_equal("model.ctb")

    def test_read_status_reports_closed_when_the_printer_does_not_answer(self) -> None:
        for error in (
            UnexpectedPrinterResponse(""),
            serial.SerialException("unplugged"),
            OSError("no such device"),
        ):
            self.printer_mock.get_print_status.side_effect = error
            status, selected = printer_access.read_status()
            expect(status.state).to_equal(PrinterState.CLOSED)
            expect(selected).to_equal("")

    # ---- which file is in use ----

    def test_file_being_printed(self) -> None:
        for state in (
            PrinterState.STARTING_PRINT,
            PrinterState.PRINTING,
            PrinterState.PAUSED,
        ):
            self._printer_reports(state, "sub/part.ctb")
            expect(printer_access.file_being_printed()).to_equal(
                Path("/mnt/usb_share/sub/part.ctb")
            )

    def test_no_file_is_being_printed_when_idle_or_unreachable(self) -> None:
        for state in (PrinterState.IDLE, PrinterState.CLOSED):
            self._printer_reports(state, "model.ctb")
            expect(printer_access.file_being_printed()).to_equal(None)

    def test_is_being_printed(self) -> None:
        self._printer_reports(PrinterState.PRINTING, "model.ctb")
        expect(
            printer_access.is_being_printed(Path("/mnt/usb_share/model.ctb"))
        ).to_equal(True)
        expect(
            printer_access.is_being_printed(Path("/mnt/usb_share/sub/part.ctb"))
        ).to_equal(False)

    def test_is_being_printed_ignores_case_like_the_fat_filesystem_does(self) -> None:
        self._printer_reports(PrinterState.PRINTING, "MODEL.CTB")
        expect(
            printer_access.is_being_printed(Path("/mnt/usb_share/model.ctb"))
        ).to_equal(True)

    def test_contains_file_being_printed(self) -> None:
        self._printer_reports(PrinterState.PAUSED, "sub/part.ctb")
        expect(
            printer_access.contains_file_being_printed(Path("/mnt/usb_share/sub"))
        ).to_equal(True)
        expect(
            printer_access.contains_file_being_printed(Path("/mnt/usb_share/other"))
        ).to_equal(False)
