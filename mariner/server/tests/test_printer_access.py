import threading
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import serial
from pyexpect import expect
from pyfakefs.fake_filesystem import FakeFilesystem
from pyfakefs.fake_filesystem_unittest import TestCase

from mariner.config import _get_config
from mariner.exceptions import (
    FileNotSelected,
    PrintAlreadyRunning,
    UnexpectedPrinterResponse,
)
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

    @staticmethod
    def _in_use(path: Path) -> bool:
        return printer_access.usage_of(path) is not printer_access.Usage.FREE

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

    # ---- file operations do not queue behind the serial line ----

    @staticmethod
    def _pause(seconds: float) -> None:
        # Not time.sleep, which setUp replaces to keep retries instant.
        threading.Event().wait(seconds)

    def _while_a_conversation_is_under_way(self, check: Any) -> None:
        """Run *check* while another thread is talking to the printer."""
        talking = threading.Event()
        hang_up = threading.Event()

        def talk() -> None:
            with printer_access.printer_session():
                talking.set()
                hang_up.wait(timeout=5)

        talker = threading.Thread(target=talk)
        talker.start()
        talking.wait(timeout=5)
        try:
            checker = threading.Thread(target=check)
            checker.start()
            checker.join(timeout=2)
            expect(checker.is_alive()).to_equal(False)
        finally:
            hang_up.set()
            talker.join()

    def test_storing_a_new_file_does_not_wait_for_the_printer(self) -> None:
        ran = []

        def store_a_new_file() -> None:
            with printer_access.unless_in_use(Path("/mnt/usb_share/new.ctb")):
                ran.append(True)

        self._while_a_conversation_is_under_way(store_a_new_file)
        expect(ran).to_equal([True])

    def test_a_check_arriving_during_a_poll_reuses_the_answer_of_that_poll(
        self,
    ) -> None:
        # A poll is waiting for a printer that is off. A file check that
        # arrives meanwhile must not ask the printer a second time once the
        # poll is done: the poll's answer is right there.
        asked = threading.Event()
        give_up = threading.Event()

        def slow_silent_printer() -> PrintStatus:
            asked.set()
            give_up.wait(timeout=5)
            return PrintStatus(state=PrinterState.CLOSED)

        self.printer_mock.get_print_status.side_effect = slow_silent_printer
        answers = []

        poll = threading.Thread(target=printer_access.read_status)
        poll.start()
        asked.wait(timeout=5)
        check = threading.Thread(
            target=lambda: answers.append(
                printer_access.usage_of(Path("/mnt/usb_share/model.ctb"))
            )
        )
        check.start()
        # Let the check reach the point where it waits for the poll.
        self._pause(0.2)
        give_up.set()
        poll.join(timeout=5)
        check.join(timeout=5)

        expect(answers).to_equal([printer_access.Usage.PRINTER_UNREACHABLE])
        expect(self.printer_mock.get_print_status.call_count).to_equal(1)

    def test_storing_a_new_file_does_not_wait_behind_a_pending_check(self) -> None:
        # Someone is talking to the printer, and a deletion is waiting for
        # them. A new file, which needs nothing from the printer, must not
        # be made to wait behind that deletion.
        self._printer_reports(PrinterState.IDLE, "")
        stored = []

        def delete_an_existing_file() -> None:
            with printer_access.unless_in_use(Path("/mnt/usb_share/model.ctb")):
                pass

        def store_a_new_file() -> None:
            deleter = threading.Thread(target=delete_an_existing_file)
            deleter.start()
            # Let the deletion reach the point where it waits for the printer.
            self._pause(0.2)
            with printer_access.unless_in_use(Path("/mnt/usb_share/new.ctb")):
                stored.append(True)
            deleters.append(deleter)

        deleters: list = []
        self._while_a_conversation_is_under_way(store_a_new_file)
        expect(stored).to_equal([True])
        for deleter in deleters:
            deleter.join(timeout=5)

    # ---- reading the status ----

    def test_read_status(self) -> None:
        self._printer_reports(PrinterState.PRINTING, "model.ctb")
        status, selected = printer_access.read_status()
        expect(status.state).to_equal(PrinterState.PRINTING)
        expect(selected).to_equal("model.ctb")

    def test_read_status_remembers_the_answer_before_anyone_else_can_talk(
        self,
    ) -> None:
        # Otherwise an answer read just before a print was started could be
        # stored just after, and say "idle" for a second too long.
        free_when_stored = []

        def try_to_talk() -> None:
            got_it = printer_access._serial_lock.acquire(blocking=False)
            if got_it:
                printer_access._serial_lock.release()
            free_when_stored.append(got_it)

        def clock() -> float:
            other = threading.Thread(target=try_to_talk)
            other.start()
            other.join(timeout=5)
            return 1000.0

        with patch("mariner.server.printer_access.time.monotonic", side_effect=clock):
            printer_access.read_status()
        expect(free_when_stored).to_equal([False])

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
            expect(self._in_use(Path("/mnt/usb_share/sub/part.ctb"))).to_equal(True)

    def test_other_files_are_not_in_use(self) -> None:
        self._printer_reports(PrinterState.PRINTING, "model.ctb")
        expect(self._in_use(Path("/mnt/usb_share/sub/part.ctb"))).to_equal(False)

    def test_a_folder_holding_the_file_being_printed_is_in_use(self) -> None:
        self._printer_reports(PrinterState.PAUSED, "sub/part.ctb")
        self.fs.create_dir("/mnt/usb_share/other")
        expect(self._in_use(Path("/mnt/usb_share/sub"))).to_equal(True)
        expect(self._in_use(Path("/mnt/usb_share/other"))).to_equal(False)

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
            printer_access.Usage.PRINTER_UNREACHABLE
        )
        expect(self._in_use(Path("/mnt/usb_share/model.ctb"))).to_equal(True)

    def test_a_path_that_does_not_exist_is_always_free(self) -> None:
        # Nothing can be reading it, so a new file can always be stored.
        for state in (PrinterState.CLOSED, PrinterState.PRINTING):
            self._printer_reports(state, "model.ctb")
            expect(printer_access.usage_of(Path("/mnt/usb_share/new.ctb"))).to_equal(
                printer_access.Usage.FREE
            )
        self.printer_mock.get_print_status.assert_not_called()

    def test_the_file_is_recognised_whatever_the_case_of_its_name(self) -> None:
        # As on the FAT filesystem the printer reads, where the printer may
        # well report MODEL.CTB for a file stored as model.ctb.
        self.fs.is_case_sensitive = False
        self._printer_reports(PrinterState.PRINTING, "MODEL.CTB")
        expect(printer_access.usage_of(Path("/mnt/usb_share/model.ctb"))).to_equal(
            printer_access.Usage.PRINTING
        )
        expect(printer_access.usage_of(Path("/mnt/usb_share/sub/part.ctb"))).to_equal(
            printer_access.Usage.FREE
        )

    def test_everything_is_in_use_when_the_printing_file_is_unknown(self) -> None:
        self._printer_reports(PrinterState.PRINTING, "model.ctb")
        self.printer_mock.get_selected_file.side_effect = UnexpectedPrinterResponse(
            "ok\r\n"
        )
        printer_access.forget_status()
        expect(printer_access.usage_of(Path("/mnt/usb_share/sub/part.ctb"))).to_equal(
            printer_access.Usage.UNIDENTIFIED_PRINT
        )

    # ---- one status read serves several checks ----

    def test_checks_in_quick_succession_share_one_status_read(self) -> None:
        self._printer_reports(PrinterState.PRINTING, "model.ctb")
        for _ in range(3):
            self._in_use(Path("/mnt/usb_share/model.ctb"))
        expect(self.printer_mock.get_print_status.call_count).to_equal(1)

    def test_a_status_read_is_not_reused_once_it_is_old(self) -> None:
        self._printer_reports(PrinterState.PRINTING, "model.ctb")
        with patch("mariner.server.printer_access.time.monotonic") as clock:
            clock.return_value = 100.0
            self._in_use(Path("/mnt/usb_share/model.ctb"))
            clock.return_value = 100.0 + printer_access._STATUS_MAX_AGE_SECS + 1
            self._in_use(Path("/mnt/usb_share/model.ctb"))
        expect(self.printer_mock.get_print_status.call_count).to_equal(2)

    def test_a_silent_printer_is_remembered_for_longer(self) -> None:
        # It takes seconds to give up on a printer that is off; file
        # management must not pay that on every operation.
        self._printer_reports(PrinterState.CLOSED, "")
        with patch("mariner.server.printer_access.time.monotonic") as clock:
            clock.return_value = 100.0
            self._in_use(Path("/mnt/usb_share/model.ctb"))
            clock.return_value = 100.0 + printer_access._STATUS_MAX_AGE_SECS + 1
            self._in_use(Path("/mnt/usb_share/model.ctb"))
            expect(self.printer_mock.get_print_status.call_count).to_equal(1)
            clock.return_value = 100.0 + printer_access._CLOSED_STATUS_MAX_AGE_SECS + 1
            self._in_use(Path("/mnt/usb_share/model.ctb"))
            expect(self.printer_mock.get_print_status.call_count).to_equal(2)

    def test_talking_to_the_printer_forgets_the_remembered_status(self) -> None:
        # Otherwise a command sent through Mariner would go unnoticed until
        # the remembered status expired. The fake printer is changed directly
        # here, not through a helper that forgets the status itself.
        self._printer_reports(PrinterState.IDLE, "")
        self._in_use(Path("/mnt/usb_share/model.ctb"))
        expect(self.printer_mock.get_print_status.call_count).to_equal(1)

        with printer_access.printer_session() as printer:
            printer.pause_printing()

        self._in_use(Path("/mnt/usb_share/model.ctb"))
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
        with patch("mariner.server.printer_access.time.monotonic") as clock:
            clock.return_value = 1000.0
            printer_access.start_print("model.ctb")

            clock.return_value = 1002.0
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

            # The print is cancelled well within the grace period. Only the
            # printer having reported it can explain the file being free.
            clock.return_value = 1004.0
            self._printer_still_says_idle()
            expect(printer_access.usage_of(Path("/mnt/usb_share/model.ctb"))).to_equal(
                printer_access.Usage.FREE
            )

    def test_a_start_the_printer_turned_down_does_not_unprotect_another(
        self,
    ) -> None:
        self._printer_still_says_idle()
        printer_access.start_print("model.ctb")
        self.printer_mock.start_printing.side_effect = UnexpectedPrinterResponse("busy")
        with self.assertRaises(UnexpectedPrinterResponse):
            printer_access.start_print("sub/part.ctb")

        for name in ("model.ctb", "sub/part.ctb"):
            expect(printer_access.usage_of(Path("/mnt/usb_share") / name)).to_equal(
                printer_access.Usage.PRINTING
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

    def test_a_start_whose_answer_was_lost_still_protects_the_file(self) -> None:
        # The command went out; only the printer's answer was not read. The
        # print may well be starting.
        self._printer_still_says_idle()
        self.printer_mock.start_printing.side_effect = UnexpectedPrinterResponse("")
        with self.assertRaises(UnexpectedPrinterResponse):
            printer_access.start_print("model.ctb")
        expect(printer_access.usage_of(Path("/mnt/usb_share/model.ctb"))).to_equal(
            printer_access.Usage.PRINTING
        )

    def test_a_start_that_was_never_sent_is_not_remembered(self) -> None:
        # The printer class refused the name before anything went out.
        self._printer_still_says_idle()
        self.printer_mock.start_printing.side_effect = ValueError("unsafe name")
        with self.assertRaises(ValueError):
            printer_access.start_print("model.ctb")
        expect(printer_access.usage_of(Path("/mnt/usb_share/model.ctb"))).to_equal(
            printer_access.Usage.FREE
        )

    def test_a_file_the_printer_did_not_select_is_not_remembered(self) -> None:
        # Selecting comes before the print command, which therefore never
        # went out. That is also what a switched-off printer leads to.
        self._printer_still_says_idle()
        self.printer_mock.start_printing.side_effect = FileNotSelected("")
        with self.assertRaises(FileNotSelected):
            printer_access.start_print("model.ctb")
        expect(printer_access.usage_of(Path("/mnt/usb_share/model.ctb"))).to_equal(
            printer_access.Usage.FREE
        )

    def test_a_failed_start_on_a_switched_off_printer_can_still_be_overridden(
        self,
    ) -> None:
        self._printer_reports(PrinterState.CLOSED, "")
        self.printer_mock.get_print_status.return_value = PrintStatus(
            state=PrinterState.CLOSED
        )
        self.printer_mock.start_printing.side_effect = FileNotSelected("")
        with self.assertRaises(FileNotSelected):
            printer_access.start_print("model.ctb")

        ran = []
        with printer_access.unless_in_use(
            Path("/mnt/usb_share/model.ctb"), even_if_unreachable=True
        ):
            ran.append(True)
        expect(ran).to_equal([True])

    def test_a_started_print_is_forgotten_whoever_sees_the_printer_report_it(
        self,
    ) -> None:
        # The status page polls the printer; no file operation is involved.
        self._printer_still_says_idle()
        with patch("mariner.server.printer_access.time.monotonic") as clock:
            clock.return_value = 1000.0
            printer_access.start_print("model.ctb")

            clock.return_value = 1002.0
            self.printer_mock.get_print_status.return_value = PrintStatus(
                state=PrinterState.PRINTING,
                current_byte=10,
                total_bytes=100,
                counters_seen=True,
                answered=True,
            )
            self.printer_mock.get_selected_file.return_value = "model.ctb"
            printer_access.read_status()

            clock.return_value = 1004.0
            self._printer_still_says_idle()
            printer_access.forget_status()
            expect(printer_access.usage_of(Path("/mnt/usb_share/model.ctb"))).to_equal(
                printer_access.Usage.FREE
            )

    def test_a_print_is_not_started_over_another(self) -> None:
        # The printer might select the new file while still reading the
        # old one, and what it reports would then protect the wrong file.
        for state in (
            PrinterState.STARTING_PRINT,
            PrinterState.PRINTING,
            PrinterState.PAUSED,
        ):
            self._printer_reports(state, "model.ctb")
            with self.assertRaises(PrintAlreadyRunning):
                printer_access.start_print("sub/part.ctb")
        self.printer_mock.start_printing.assert_not_called()
        expect(printer_access.usage_of(Path("/mnt/usb_share/sub/part.ctb"))).to_equal(
            printer_access.Usage.FREE
        )

    def test_a_print_is_still_attempted_when_the_printer_says_nothing_clear(
        self,
    ) -> None:
        # Only a reported print stands in the way. The printer itself
        # turns the command down if it cannot print.
        for status in (
            PrintStatus(state=PrinterState.CLOSED),
            PrintStatus(state=PrinterState.IDLE, answered=True),
        ):
            printer_access.forget_status()
            self.printer_mock.start_printing.reset_mock()
            self.printer_mock.get_print_status.return_value = status
            printer_access.start_print("model.ctb")
            self.printer_mock.start_printing.assert_called_once_with("model.ctb")

    def test_a_cancelled_print_no_longer_protects_its_file(self) -> None:
        # Cancelled before the printer ever reported it.
        self._printer_still_says_idle()
        printer_access.start_print("model.ctb")
        printer_access.stop_print()
        self.printer_mock.stop_printing.assert_called_once_with()
        expect(printer_access.usage_of(Path("/mnt/usb_share/model.ctb"))).to_equal(
            printer_access.Usage.FREE
        )

    def test_a_cancellation_the_printer_turned_down_changes_nothing(self) -> None:
        self._printer_still_says_idle()
        printer_access.start_print("model.ctb")
        self.printer_mock.stop_printing.side_effect = UnexpectedPrinterResponse("")
        with self.assertRaises(UnexpectedPrinterResponse):
            printer_access.stop_print()
        expect(printer_access.usage_of(Path("/mnt/usb_share/model.ctb"))).to_equal(
            printer_access.Usage.PRINTING
        )

    # ---- answers that settle nothing ----

    def _printer_answers_unclearly(self, state: PrinterState) -> None:
        printer_access.forget_status()
        self.printer_mock.get_print_status.return_value = PrintStatus(
            state=state, answered=True
        )
        self.printer_mock.get_selected_file.return_value = "model.ctb"

    def test_an_answer_without_the_print_counters_settles_nothing(self) -> None:
        # The printer answered "ok" and nothing else. That reads as IDLE but
        # says nothing about a print.
        self._printer_answers_unclearly(PrinterState.IDLE)
        expect(printer_access.usage_of(Path("/mnt/usb_share/model.ctb"))).to_equal(
            printer_access.Usage.PRINTER_UNCLEAR
        )

    def test_an_answer_that_cannot_be_read_settles_nothing(self) -> None:
        # Garbled text reads as CLOSED, yet something did come back.
        self._printer_answers_unclearly(PrinterState.CLOSED)
        expect(printer_access.usage_of(Path("/mnt/usb_share/model.ctb"))).to_equal(
            printer_access.Usage.PRINTER_UNCLEAR
        )

    def test_a_printer_that_sends_nothing_is_unreachable(self) -> None:
        self._printer_reports(PrinterState.CLOSED, "")
        self.printer_mock.get_print_status.return_value = PrintStatus(
            state=PrinterState.CLOSED
        )
        expect(printer_access.usage_of(Path("/mnt/usb_share/model.ctb"))).to_equal(
            printer_access.Usage.PRINTER_UNREACHABLE
        )

    def test_a_print_from_a_file_that_cannot_be_found_settles_nothing(self) -> None:
        # A short FAT alias, or a name mangled on the serial line: the file
        # being printed is one of those here, but which one is not known.
        self._printer_reports(PrinterState.PRINTING, "MODEL~1.CTB")
        expect(printer_access.usage_of(Path("/mnt/usb_share/model.ctb"))).to_equal(
            printer_access.Usage.UNIDENTIFIED_PRINT
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
        expect(raised.exception.usage).to_equal(printer_access.Usage.PRINTING)

    def test_unless_in_use_says_when_the_printer_could_not_be_asked(self) -> None:
        self._printer_reports(PrinterState.CLOSED, "")
        with self.assertRaises(printer_access.FileInUse) as raised:
            with printer_access.unless_in_use(Path("/mnt/usb_share/model.ctb")):
                pass
        expect(raised.exception.usage).to_equal(
            printer_access.Usage.PRINTER_UNREACHABLE
        )

    def test_a_silent_printer_can_be_overridden_on_request(self) -> None:
        self._printer_reports(PrinterState.CLOSED, "")
        ran = []
        with printer_access.unless_in_use(
            Path("/mnt/usb_share/model.ctb"), even_if_unreachable=True
        ):
            ran.append(True)
        expect(ran).to_equal([True])

    def test_an_override_asks_the_printer_again_first(self) -> None:
        # Remembered as silent a moment ago. Since then the printer was
        # switched on and a print started from its screen.
        self._printer_reports(PrinterState.CLOSED, "")
        self._in_use(Path("/mnt/usb_share/model.ctb"))
        self.printer_mock.get_print_status.return_value = PrintStatus(
            state=PrinterState.PRINTING,
            current_byte=10,
            total_bytes=100,
            counters_seen=True,
        )
        self.printer_mock.get_selected_file.return_value = "model.ctb"

        with self.assertRaises(printer_access.FileInUse) as raised:
            with printer_access.unless_in_use(
                Path("/mnt/usb_share/model.ctb"), even_if_unreachable=True
            ):
                pass
        expect(raised.exception.usage).to_equal(printer_access.Usage.PRINTING)

    def test_an_unclear_answer_cannot_be_overridden(self) -> None:
        # The override is for a printer that is switched off. One that
        # answers, however badly, is switched on.
        for state in (PrinterState.IDLE, PrinterState.CLOSED):
            self._printer_answers_unclearly(state)
            with self.assertRaises(printer_access.FileInUse) as raised:
                with printer_access.unless_in_use(
                    Path("/mnt/usb_share/model.ctb"), even_if_unreachable=True
                ):
                    pass
            expect(raised.exception.usage).to_equal(
                printer_access.Usage.PRINTER_UNCLEAR
            )

    def test_an_override_asks_the_printer_once_when_nothing_holds_it_up(
        self,
    ) -> None:
        self._printer_reports(PrinterState.CLOSED, "")
        self.printer_mock.get_print_status.return_value = PrintStatus(
            state=PrinterState.CLOSED
        )
        with printer_access.unless_in_use(
            Path("/mnt/usb_share/model.ctb"), even_if_unreachable=True
        ):
            pass
        expect(self.printer_mock.get_print_status.call_count).to_equal(1)

    def test_an_override_does_not_hold_up_new_files_while_it_asks(self) -> None:
        # A silent printer takes seconds to give up on. Meanwhile, storing
        # a file under a new name must go through.
        stored = threading.Event()

        def store_a_new_file() -> None:
            with printer_access.unless_in_use(Path("/mnt/usb_share/new.ctb")):
                stored.set()

        def silent_printer() -> PrintStatus:
            other = threading.Thread(target=store_a_new_file)
            other.start()
            other.join(timeout=5)
            return PrintStatus(state=PrinterState.CLOSED)

        printer_access.forget_status()
        self.printer_mock.get_print_status.side_effect = silent_printer
        with printer_access.unless_in_use(
            Path("/mnt/usb_share/model.ctb"), even_if_unreachable=True
        ):
            pass
        expect(stored.is_set()).to_equal(True)

    def test_an_override_asks_again_after_a_long_wait_for_its_turn(self) -> None:
        # The printer was silent when asked. The request then waited behind
        # another change, long enough for a print to be started from the
        # printer's own screen.
        self._printer_reports(PrinterState.CLOSED, "")
        self.printer_mock.get_print_status.return_value = PrintStatus(
            state=PrinterState.CLOSED
        )
        now = [1000.0]
        change_lock = printer_access._change_lock
        test = self

        class SlowToGet:
            def __enter__(self) -> None:
                now[0] += printer_access._STATUS_MAX_AGE_SECS + 1
                test.printer_mock.get_print_status.return_value = PrintStatus(
                    state=PrinterState.PRINTING,
                    current_byte=10,
                    total_bytes=100,
                    counters_seen=True,
                    answered=True,
                )
                test.printer_mock.get_selected_file.return_value = "model.ctb"
                change_lock.acquire()

            def __exit__(self, *_: Any) -> None:
                change_lock.release()

        with patch(
            "mariner.server.printer_access.time.monotonic", side_effect=lambda: now[0]
        ), patch.object(printer_access, "_change_lock", SlowToGet()):
            with self.assertRaises(printer_access.FileInUse) as raised:
                with printer_access.unless_in_use(
                    Path("/mnt/usb_share/model.ctb"), even_if_unreachable=True
                ):
                    pass
        expect(raised.exception.usage).to_equal(printer_access.Usage.PRINTING)

    def test_a_reported_print_cannot_be_overridden(self) -> None:
        for selected in ("model.ctb", "MODEL~1.CTB"):
            self._printer_reports(PrinterState.PRINTING, selected)
            with self.assertRaises(printer_access.FileInUse):
                with printer_access.unless_in_use(
                    Path("/mnt/usb_share/model.ctb"), even_if_unreachable=True
                ):
                    pass

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
            printer_access.start_print("model.ctb")
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
