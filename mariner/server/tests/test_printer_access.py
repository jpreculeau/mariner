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
        printer_access.forget_status()

    def tearDown(self) -> None:
        self.printer_patcher.stop()
        self.sleep_patcher.stop()

    def _printer_reports(self, state: PrinterState, selected: str) -> None:
        # The printer changed state on its own; a real one would be noticed
        # once the remembered status expires.
        printer_access.forget_status()
        self.printer_mock.get_print_status.return_value = PrintStatus(
            state=state, current_byte=10, total_bytes=100, counters_seen=True
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

    def test_read_status_does_not_ask_a_silent_printer_for_its_file(self) -> None:
        self._printer_reports(PrinterState.CLOSED, "model.ctb")
        printer_access.read_status()
        self.printer_mock.get_selected_file.assert_not_called()

    def test_read_status_keeps_the_state_when_only_the_file_is_unknown(self) -> None:
        self._printer_reports(PrinterState.PRINTING, "model.ctb")
        self.printer_mock.get_selected_file.side_effect = UnexpectedPrinterResponse(
            "ok\r\n"
        )
        status, selected = printer_access.read_status()
        expect(status.state).to_equal(PrinterState.PRINTING)
        expect(selected).to_equal("")

    # ---- which file is in use ----

    def test_the_file_being_printed_is_in_use(self) -> None:
        for state in (
            PrinterState.STARTING_PRINT,
            PrinterState.PRINTING,
            PrinterState.PAUSED,
        ):
            self._printer_reports(state, "sub/part.ctb")
            expect(
                printer_access.is_in_use(Path("/mnt/usb_share/sub/part.ctb"))
            ).to_equal(True)

    def test_other_files_are_not_in_use(self) -> None:
        self._printer_reports(PrinterState.PRINTING, "model.ctb")
        expect(printer_access.is_in_use(Path("/mnt/usb_share/sub/part.ctb"))).to_equal(
            False
        )

    def test_a_folder_holding_the_file_being_printed_is_in_use(self) -> None:
        self._printer_reports(PrinterState.PAUSED, "sub/part.ctb")
        self.fs.create_dir("/mnt/usb_share/other")
        expect(printer_access.is_in_use(Path("/mnt/usb_share/sub"))).to_equal(True)
        expect(printer_access.is_in_use(Path("/mnt/usb_share/other"))).to_equal(False)

    def test_nothing_is_in_use_when_idle(self) -> None:
        self._printer_reports(PrinterState.IDLE, "model.ctb")
        expect(printer_access.usage_of(Path("/mnt/usb_share/model.ctb"))).to_equal(
            printer_access.Usage.FREE
        )

    def test_an_existing_file_is_protected_when_the_printer_is_silent(self) -> None:
        # It may be printing with the serial cable knocked loose; there is no
        # way to tell, so the file is left alone until the printer answers.
        self._printer_reports(PrinterState.CLOSED, "")
        expect(printer_access.usage_of(Path("/mnt/usb_share/model.ctb"))).to_equal(
            printer_access.Usage.UNKNOWN
        )
        expect(printer_access.is_in_use(Path("/mnt/usb_share/model.ctb"))).to_equal(
            True
        )

    def test_a_path_that_does_not_exist_is_always_free(self) -> None:
        # Nothing can be reading it, so a new file can always be stored.
        for state in (PrinterState.CLOSED, PrinterState.PRINTING):
            self._printer_reports(state, "model.ctb")
            expect(printer_access.usage_of(Path("/mnt/usb_share/new.ctb"))).to_equal(
                printer_access.Usage.FREE
            )
        self.printer_mock.get_print_status.assert_not_called()

    def test_case_is_ignored_like_the_fat_filesystem_does(self) -> None:
        self._printer_reports(PrinterState.PRINTING, "MODEL.CTB")
        expect(printer_access.is_in_use(Path("/mnt/usb_share/model.ctb"))).to_equal(
            True
        )

    def test_everything_is_in_use_when_the_printing_file_is_unknown(self) -> None:
        self._printer_reports(PrinterState.PRINTING, "model.ctb")
        self.printer_mock.get_selected_file.side_effect = UnexpectedPrinterResponse(
            "ok\r\n"
        )
        printer_access.forget_status()
        expect(printer_access.usage_of(Path("/mnt/usb_share/sub/part.ctb"))).to_equal(
            printer_access.Usage.UNKNOWN
        )

    # ---- one status read serves several checks ----

    def test_checks_in_quick_succession_share_one_status_read(self) -> None:
        self._printer_reports(PrinterState.PRINTING, "model.ctb")
        for _ in range(3):
            printer_access.is_in_use(Path("/mnt/usb_share/model.ctb"))
        expect(self.printer_mock.get_print_status.call_count).to_equal(1)

    def test_a_status_read_is_not_reused_once_it_is_old(self) -> None:
        self._printer_reports(PrinterState.PRINTING, "model.ctb")
        with patch("mariner.server.printer_access.time.monotonic") as clock:
            clock.return_value = 100.0
            printer_access.is_in_use(Path("/mnt/usb_share/model.ctb"))
            clock.return_value = 100.0 + printer_access._STATUS_MAX_AGE_SECS + 1
            printer_access.is_in_use(Path("/mnt/usb_share/model.ctb"))
        expect(self.printer_mock.get_print_status.call_count).to_equal(2)

    def test_a_silent_printer_is_remembered_for_longer(self) -> None:
        # It takes seconds to give up on a printer that is off; file
        # management must not pay that on every operation.
        self._printer_reports(PrinterState.CLOSED, "")
        with patch("mariner.server.printer_access.time.monotonic") as clock:
            clock.return_value = 100.0
            printer_access.is_in_use(Path("/mnt/usb_share/model.ctb"))
            clock.return_value = 100.0 + printer_access._STATUS_MAX_AGE_SECS + 1
            printer_access.is_in_use(Path("/mnt/usb_share/model.ctb"))
            expect(self.printer_mock.get_print_status.call_count).to_equal(1)
            clock.return_value = 100.0 + printer_access._CLOSED_STATUS_MAX_AGE_SECS + 1
            printer_access.is_in_use(Path("/mnt/usb_share/model.ctb"))
            expect(self.printer_mock.get_print_status.call_count).to_equal(2)

    def test_talking_to_the_printer_forgets_the_remembered_status(self) -> None:
        # Otherwise a command sent through Mariner would go unnoticed until
        # the remembered status expired. The fake printer is changed directly
        # here, not through a helper that forgets the status itself.
        self._printer_reports(PrinterState.IDLE, "")
        printer_access.is_in_use(Path("/mnt/usb_share/model.ctb"))
        expect(self.printer_mock.get_print_status.call_count).to_equal(1)

        with printer_access.printer_session() as printer:
            printer.pause_printing()

        printer_access.is_in_use(Path("/mnt/usb_share/model.ctb"))
        expect(self.printer_mock.get_print_status.call_count).to_equal(2)

    # ---- a print Mariner has just started ----

    def _printer_still_says_idle(self) -> None:
        # Changed directly: nothing here forgets what start_print remembered.
        self.printer_mock.get_print_status.return_value = PrintStatus(
            state=PrinterState.IDLE, counters_seen=True
        )
        self.printer_mock.get_selected_file.return_value = ""

    def test_a_file_is_in_use_as_soon_as_its_print_is_started(self) -> None:
        self._printer_still_says_idle()
        printer_access.start_print("sub/part.ctb")
        self.printer_mock.start_printing.assert_called_once_with("sub/part.ctb")

        expect(printer_access.usage_of(Path("/mnt/usb_share/sub/part.ctb"))).to_equal(
            printer_access.Usage.PRINTING
        )
        expect(printer_access.usage_of(Path("/mnt/usb_share/sub"))).to_equal(
            printer_access.Usage.PRINTING
        )
        expect(printer_access.usage_of(Path("/mnt/usb_share/model.ctb"))).to_equal(
            printer_access.Usage.FREE
        )

    def test_a_started_print_is_forgotten_once_the_printer_reports_it(self) -> None:
        self._printer_still_says_idle()
        printer_access.start_print("model.ctb")

        with patch("mariner.server.printer_access.time.monotonic") as clock:
            clock.return_value = 1000.0
            self.printer_mock.get_print_status.return_value = PrintStatus(
                state=PrinterState.PRINTING,
                current_byte=10,
                total_bytes=100,
                counters_seen=True,
            )
            self.printer_mock.get_selected_file.return_value = "model.ctb"
            expect(printer_access.usage_of(Path("/mnt/usb_share/model.ctb"))).to_equal(
                printer_access.Usage.PRINTING
            )

            # The print ends: from now on the printer's word is enough.
            clock.return_value = 1010.0
            self._printer_still_says_idle()
            expect(printer_access.usage_of(Path("/mnt/usb_share/model.ctb"))).to_equal(
                printer_access.Usage.FREE
            )

    def test_a_started_print_the_printer_never_reports_is_given_up_on(self) -> None:
        self._printer_still_says_idle()
        with patch("mariner.server.printer_access.time.monotonic") as clock:
            clock.return_value = 1000.0
            printer_access.start_print("model.ctb")
            clock.return_value = 1000.0 + printer_access._START_GRACE_SECS - 1
            expect(printer_access.usage_of(Path("/mnt/usb_share/model.ctb"))).to_equal(
                printer_access.Usage.PRINTING
            )
            clock.return_value = 1000.0 + printer_access._START_GRACE_SECS + 1
            expect(printer_access.usage_of(Path("/mnt/usb_share/model.ctb"))).to_equal(
                printer_access.Usage.FREE
            )

    def test_a_print_that_fails_to_start_is_not_remembered(self) -> None:
        self._printer_still_says_idle()
        self.printer_mock.start_printing.side_effect = UnexpectedPrinterResponse("")
        with self.assertRaises(UnexpectedPrinterResponse):
            printer_access.start_print("model.ctb")
        expect(printer_access.usage_of(Path("/mnt/usb_share/model.ctb"))).to_equal(
            printer_access.Usage.FREE
        )

    # ---- answers that settle nothing ----

    def test_an_answer_without_the_print_counters_settles_nothing(self) -> None:
        # The printer answered "ok" and nothing else. That reads as IDLE but
        # says nothing about a print.
        printer_access.forget_status()
        self.printer_mock.get_print_status.return_value = PrintStatus(
            state=PrinterState.IDLE
        )
        self.printer_mock.get_selected_file.return_value = "model.ctb"
        expect(printer_access.usage_of(Path("/mnt/usb_share/model.ctb"))).to_equal(
            printer_access.Usage.UNKNOWN
        )

    def test_a_print_from_a_file_that_cannot_be_found_settles_nothing(self) -> None:
        # A short FAT alias, or a name mangled on the serial line: the file
        # being printed is one of those here, but which one is not known.
        self._printer_reports(PrinterState.PRINTING, "MODEL~1.CTB")
        expect(printer_access.usage_of(Path("/mnt/usb_share/model.ctb"))).to_equal(
            printer_access.Usage.UNKNOWN
        )

    # ---- guarding a change ----

    def test_unless_in_use_runs_the_block_for_a_free_file(self) -> None:
        self._printer_reports(PrinterState.PRINTING, "model.ctb")
        ran = []
        with printer_access.unless_in_use(Path("/mnt/usb_share/sub/part.ctb")):
            ran.append(True)
        expect(ran).to_equal([True])

    def test_unless_in_use_refuses_the_file_being_printed(self) -> None:
        self._printer_reports(PrinterState.PRINTING, "model.ctb")
        ran = []
        with self.assertRaises(printer_access.FileInUse) as raised:
            with printer_access.unless_in_use(Path("/mnt/usb_share/model.ctb")):
                ran.append(True)
        expect(ran).to_equal([])
        expect(raised.exception.path).to_equal(Path("/mnt/usb_share/model.ctb"))
        expect(raised.exception.printer_is_silent).to_equal(False)

    def test_unless_in_use_says_when_the_printer_could_not_be_asked(self) -> None:
        self._printer_reports(PrinterState.CLOSED, "")
        with self.assertRaises(printer_access.FileInUse) as raised:
            with printer_access.unless_in_use(Path("/mnt/usb_share/model.ctb")):
                pass
        expect(raised.exception.printer_is_silent).to_equal(True)

    def test_no_print_can_start_while_a_guarded_change_is_under_way(self) -> None:
        self._printer_reports(PrinterState.IDLE, "")
        inside_guard = threading.Event()
        leave_guard = threading.Event()
        print_started = threading.Event()

        def change_the_file() -> None:
            with printer_access.unless_in_use(Path("/mnt/usb_share/model.ctb")):
                inside_guard.set()
                leave_guard.wait(timeout=5)

        def start_a_print() -> None:
            with printer_access.printer_session() as printer:
                printer.start_printing("model.ctb")
                print_started.set()

        changer = threading.Thread(target=change_the_file)
        changer.start()
        inside_guard.wait(timeout=5)
        starter = threading.Thread(target=start_a_print)
        starter.start()

        expect(print_started.wait(timeout=0.2)).to_equal(False)
        leave_guard.set()
        expect(print_started.wait(timeout=5)).to_equal(True)
        changer.join()
        starter.join()


class SameFileTest(TestCase):
    """On a real filesystem: one file reached under two names."""

    def test_two_names_for_one_file(self) -> None:
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory) / "folder" / "model.ctb"
            original.parent.mkdir()
            original.write_bytes(b"x")
            alias = Path(directory) / "folder" / "MODEL~1.CTB"
            os.link(original, alias)
            folder_alias = Path(directory) / "FOLDER~1"
            os.symlink(original.parent, folder_alias)
            other = Path(directory) / "other.ctb"
            other.write_bytes(b"x")

            expect(printer_access.same_file(original, alias)).to_equal(True)
            expect(printer_access.same_file(original, other)).to_equal(False)
            expect(printer_access.is_inside(original, folder_alias)).to_equal(True)
            expect(printer_access.is_inside(other, folder_alias)).to_equal(False)

    def test_names_that_do_not_exist_are_compared_without_case(self) -> None:
        expect(
            printer_access.same_file(
                Path("/nowhere/Model.CTB"), Path("/nowhere/model.ctb")
            )
        ).to_equal(True)
        expect(
            printer_access.same_file(Path("/nowhere/a.ctb"), Path("/nowhere/b.ctb"))
        ).to_equal(False)
