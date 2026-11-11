import unittest.mock
from unittest import TestCase
from unittest.mock import MagicMock, Mock, call, patch

import serial
from pyexpect import expect

from mariner.exceptions import FileNotSelected, UnexpectedPrinterResponse
from mariner.printer import (
    ChiTuPrinter,
    PrinterState,
    has_control_character,
    is_safe_for_printer,
)


class ChiTuPrinterTest(TestCase):
    printer: ChiTuPrinter
    # pyre-ignore[24]: Generic type `unittest.mock._patch` expects
    # 1 type parameter
    serial_port_patcher: unittest.mock._patch
    serial_port_mock: MagicMock

    def setUp(self) -> None:
        self.serial_port_mock = Mock(spec=serial.Serial)
        self.serial_port_patcher = patch("mariner.printer.serial.Serial")
        serial_port_constructor = self.serial_port_patcher.start()
        serial_port_constructor.return_value = self.serial_port_mock
        self.printer = ChiTuPrinter()

    def tearDown(self) -> None:
        self.serial_port_patcher.stop()

    def test_open_and_close(self) -> None:
        self.serial_port_mock.open.assert_not_called()
        self.serial_port_mock.close.assert_not_called()

        self.printer.open()
        self.serial_port_mock.open.assert_called_once_with()
        self.serial_port_mock.close.assert_not_called()
        self.serial_port_mock.reset_mock()

        self.printer.close()
        self.serial_port_mock.open.assert_not_called()
        self.serial_port_mock.close.assert_called_once_with()

    def test_usage_with_context_manager(self) -> None:
        self.serial_port_mock.open.assert_not_called()
        self.serial_port_mock.close.assert_not_called()

        with self.printer:
            self.serial_port_mock.open.assert_called_once_with()
            self.serial_port_mock.close.assert_not_called()
            self.serial_port_mock.reset_mock()

        self.serial_port_mock.open.assert_not_called()
        self.serial_port_mock.close.assert_called_once_with()

    def test_get_firmware_version(self) -> None:
        self.serial_port_mock.readline.return_value = b"ok V4.3.4_LCDC\n"

        self.printer.open()
        firmware_version = self.printer.get_firmware_version()
        self.printer.close()

        self.serial_port_mock.write.assert_called_once_with(b"M4002\r\n")
        expect(firmware_version).to_equal("V4.3.4_LCDC")

    def test_get_state(self) -> None:
        self.serial_port_mock.readline.return_value = (
            b"ok B:0/0 X:0.000 Y:0.000 Z:151.900 F:0/0 D:31540/0/1 "
        )

        self.printer.open()
        # TODO: make this return a dataclass with the parsed information
        self.printer.get_state()
        self.printer.close()

        self.serial_port_mock.write.assert_called_once_with(b"M4000\r\n")

    def test_get_print_status_when_not_printing(self) -> None:
        self.serial_port_mock.readline.return_value = (
            b"ok B:0/0 X:0.000 Y:0.000 Z:8.233 F:0/0 D:0/0/1 "
        )

        self.printer.open()
        print_status = self.printer.get_print_status()
        self.printer.close()

        self.serial_port_mock.write.assert_called_once_with(b"M4000\r\n")
        expect(print_status.state).to_equal(PrinterState.IDLE)

    def test_get_print_status_after_slow_first_readline(self) -> None:
        """First readline can time out empty before firmware replies (see #180)."""
        self.serial_port_mock.readline.side_effect = [
            b"",
            b"ok B:0/0 X:0.000 Y:0.000 Z:8.233 F:0/0 D:0/0/1 ",
        ]

        self.printer.open()
        print_status = self.printer.get_print_status()
        self.printer.close()

        self.serial_port_mock.write.assert_called_once_with(b"M4000\r\n")
        expect(print_status.state).to_equal(PrinterState.IDLE)
        expect(print_status.current_byte).to_be_none()
        expect(print_status.total_bytes).to_be_none()

    def test_get_print_status_after_ok_keepalive_line(self) -> None:
        self.serial_port_mock.readline.side_effect = [
            b"ok\r\n",
            b"ok B:0/0 X:0.000 Y:0.000 Z:8.233 F:0/0 D:0/0/1 ",
        ]

        self.printer.open()
        print_status = self.printer.get_print_status()
        self.printer.close()

        self.serial_port_mock.write.assert_called_once_with(b"M4000\r\n")
        expect(print_status.state).to_equal(PrinterState.IDLE)
        expect(print_status.current_byte).to_be_none()
        expect(print_status.total_bytes).to_be_none()

    def test_get_print_status_retries_m4000_after_keepalive_only_response(self) -> None:
        with patch.object(
            self.printer,
            "_send_and_read_until_contains",
            side_effect=[
                "ok\r\n",
                "ok B:0/0 X:0.000 Y:0.000 Z:8.233 F:0/0 D:0/0/1 ",
            ],
        ) as send_and_read_mock:
            self.printer.open()
            print_status = self.printer.get_print_status()
            self.printer.close()

        expect(send_and_read_mock.call_count).to_equal(2)
        expect(print_status.state).to_equal(PrinterState.IDLE)
        expect(print_status.current_byte).to_be_none()
        expect(print_status.total_bytes).to_be_none()

    def test_get_print_status_returns_closed_after_unparseable_responses(self) -> None:
        with patch.object(
            self.printer,
            "_send_and_read_until_contains",
            side_effect=["", "ok\r\n", ""],
        ) as send_and_read_mock:
            self.printer.open()
            print_status = self.printer.get_print_status()
            self.printer.close()

        expect(send_and_read_mock.call_count).to_equal(3)
        expect(print_status.state).to_equal(PrinterState.CLOSED)
        expect(print_status.current_byte).to_be_none()
        expect(print_status.total_bytes).to_be_none()

    def test_get_print_status_returns_closed_after_serial_exception(self) -> None:
        with patch.object(
            self.printer,
            "_send_and_read_until_contains",
            side_effect=serial.SerialException("device disconnected"),
        ) as send_and_read_mock:
            self.printer.open()
            print_status = self.printer.get_print_status()
            self.printer.close()

        expect(send_and_read_mock.call_count).to_equal(1)
        expect(print_status.state).to_equal(PrinterState.CLOSED)
        expect(print_status.current_byte).to_be_none()
        expect(print_status.total_bytes).to_be_none()

    def test_get_print_status_while_starting_print(self) -> None:
        self.serial_port_mock.readline.return_value = (
            b"ok B:0/0 X:0.000 Y:0.000 Z:-33.421 F:256/256 D:0/11494803/0 "
        )

        self.printer.open()
        print_status = self.printer.get_print_status()
        self.printer.close()

        self.serial_port_mock.write.assert_called_once_with(b"M4000\r\n")
        expect(print_status.state).to_equal(PrinterState.STARTING_PRINT)
        expect(print_status.current_byte).to_equal(0)
        expect(print_status.total_bytes).to_equal(11494803)

    def test_get_print_status_while_printing(self) -> None:
        self.serial_port_mock.readline.return_value = (
            b"ok B:0/0 X:0.000 Y:0.000 Z:0.100 F:256/256 D:76903/11494803/0 "
        )

        self.printer.open()
        print_status = self.printer.get_print_status()
        self.printer.close()

        self.serial_port_mock.write.assert_called_once_with(b"M4000\r\n")
        expect(print_status.state).to_equal(PrinterState.PRINTING)
        expect(print_status.current_byte).to_equal(76903)
        expect(print_status.total_bytes).to_equal(11494803)

    def test_get_print_status_when_paused(self) -> None:
        self.serial_port_mock.readline.return_value = (
            b"ok B:0/0 X:0.000 Y:0.000 Z:78.000 F:256/256 D:5957675/11494803/1 "
        )

        self.printer.open()
        print_status = self.printer.get_print_status()
        self.printer.close()

        self.serial_port_mock.write.assert_called_once_with(b"M4000\r\n")
        expect(print_status.state).to_equal(PrinterState.PAUSED)
        expect(print_status.current_byte).to_equal(5957675)
        expect(print_status.total_bytes).to_equal(11494803)

    def test_get_z_pos(self) -> None:
        self.serial_port_mock.readline.return_value = (
            b"ok C: X:0.000000 Y:0.000000 Z:155.000000 E:0.000000\r\n"
        )

        self.printer.open()
        z_pos = self.printer.get_z_pos()
        self.printer.close()

        self.serial_port_mock.write.assert_called_once_with(b"M114\r\n")
        expect(z_pos).is_almost_equal(155.0, max_delta=1e-9)

    def test_start_printing_refuses_a_filename_that_carries_a_command(self) -> None:
        self.printer.open()
        for filename in ("a.ctb\r\nG0 Z-50", "a.ctb\nG28", "it's.ctb", "a\x00.ctb"):
            with self.assertRaises(ValueError):
                self.printer.start_printing(filename)
        self.printer.close()

        self.serial_port_mock.write.assert_not_called()

    def test_select_file_refuses_a_filename_that_carries_a_command(self) -> None:
        self.printer.open()
        with self.assertRaises(ValueError):
            self.printer.select_file("a.ctb\r\nG0 Z-50")
        self.printer.close()

        self.serial_port_mock.write.assert_not_called()

    def test_get_firmware_version_with_either_line_ending(self) -> None:
        for line in (b"ok V4.4.3_LCDC\n", b"ok V4.4.3_LCDC\r\n"):
            self.serial_port_mock.readline.return_value = line
            self.printer.open()
            expect(self.printer.get_firmware_version()).to_equal("V4.4.3_LCDC")
            self.printer.close()

    def test_line_noise_is_not_a_crash(self) -> None:
        # Bytes that are not UTF-8 show up with a wrong baud rate or a loose
        # wire. They must read as an unusable answer, not raise.
        self.serial_port_mock.readline.return_value = b"\xff\xfe\x80 noise\r\n"
        self.printer.open()
        expect(self.printer.get_print_status().state).to_equal(PrinterState.CLOSED)
        with self.assertRaises(UnexpectedPrinterResponse):
            self.printer.get_selected_file()
        self.printer.close()

    def test_a_print_in_progress_is_backed_by_the_print_counters(self) -> None:
        for line in (
            b"ok B:0/0 X:0.000 Y:0.000 Z:1.000 F:0/0 D:0/100/0 ",
            b"ok B:0/0 X:0.000 Y:0.000 Z:1.000 F:0/0 D:10/100/0 ",
            b"ok B:0/0 X:0.000 Y:0.000 Z:1.000 F:0/0 D:10/100/1 ",
        ):
            self.serial_port_mock.readline.return_value = line
            self.printer.open()
            status = self.printer.get_print_status()
            self.printer.close()
            expect(status.counters_seen).to_equal(True)

    def test_a_printer_that_is_not_connected_has_no_counters(self) -> None:
        expect(self.printer.get_print_status().state).to_equal(PrinterState.CLOSED)
        expect(self.printer.get_print_status().counters_seen).to_equal(False)

    def test_any_answer_at_all_shows_that_the_printer_is_on(self) -> None:
        for line in (
            b"ok B:0/0 X:0.000 Y:0.000 Z:1.000 F:0/0 D:10/100/0 ",
            b"ok B:0/0 X:0.000 Y:0.000 Z:8.233 F:0/0 D:0/0/1 ",
            b"ok\r\n",
            b"\xff\xfe garbled\r\n",
        ):
            self.serial_port_mock.readline.return_value = line
            self.printer.open()
            status = self.printer.get_print_status()
            self.printer.close()
            expect(status.answered).to_equal(True)

    def test_a_printer_that_sends_nothing_has_not_answered(self) -> None:
        # Not connected at all.
        expect(self.printer.get_print_status().answered).to_equal(False)

        with patch.object(
            self.printer, "_send_and_read_until_contains", side_effect=["", "", ""]
        ):
            self.printer.open()
            silent = self.printer.get_print_status()
            self.printer.close()
        expect(silent.state).to_equal(PrinterState.CLOSED)
        expect(silent.answered).to_equal(False)

        with patch.object(
            self.printer,
            "_send_and_read_until_contains",
            side_effect=serial.SerialException("device disconnected"),
        ):
            self.printer.open()
            unplugged = self.printer.get_print_status()
            self.printer.close()
        expect(unplugged.answered).to_equal(False)

    def test_an_answer_to_an_earlier_attempt_still_counts(self) -> None:
        # Three attempts are made. The printer said something to the first
        # one only: it is switched on all the same.
        with patch.object(
            self.printer,
            "_send_and_read_until_contains",
            side_effect=["wait\r\n", "", ""],
        ):
            self.printer.open()
            status = self.printer.get_print_status()
            self.printer.close()
        expect(status.state).to_equal(PrinterState.CLOSED)
        expect(status.answered).to_equal(True)

    def test_line_separators_of_any_kind_count_as_control_characters(self) -> None:
        for character in ("\n", "\r", "\x7f", "\x85", "\x9b", "\u2028", "\u2029"):
            expect(has_control_character(f"a{character}b")).to_equal(True)
        for text in ("model.ctb", "pièce (v2).ctb", "模型.ctb", "a b"):
            expect(has_control_character(text)).to_equal(False)

    def test_text_that_is_not_valid_unicode_is_not_safe_for_the_printer(self) -> None:
        expect(is_safe_for_printer("model.ctb")).to_equal(True)
        expect(is_safe_for_printer("sub/model.ctb")).to_equal(True)
        expect(is_safe_for_printer("\ud800.ctb")).to_equal(False)
        expect(is_safe_for_printer("")).to_equal(False)

    def test_idle_is_backed_by_the_print_counters_or_not(self) -> None:
        # Both answers read as IDLE. Only the first one says so.
        self.serial_port_mock.readline.return_value = (
            b"ok B:0/0 X:0.000 Y:0.000 Z:8.233 F:0/0 D:0/0/1 "
        )
        self.printer.open()
        with_counters = self.printer.get_print_status()
        self.serial_port_mock.readline.return_value = b"ok\r\n"
        ok_only = self.printer.get_print_status()
        self.printer.close()

        expect(with_counters.state).to_equal(PrinterState.IDLE)
        expect(with_counters.counters_seen).to_equal(True)
        expect(ok_only.state).to_equal(PrinterState.IDLE)
        expect(ok_only.counters_seen).to_equal(False)

    def test_get_selected_file(self) -> None:
        self.serial_port_mock.readline.return_value = b"ok 'LittleBBC.ctb'\r\n"

        self.printer.open()
        selected_file = self.printer.get_selected_file()
        self.printer.close()

        self.serial_port_mock.write.assert_called_once_with(b"M4006\r\n")
        expect(selected_file).equals("LittleBBC.ctb")

    def test_get_selected_file_with_leading_slash(self) -> None:
        self.serial_port_mock.readline.return_value = b"ok '/subdir/LittleBBC.ctb'\r\n"

        self.printer.open()
        selected_file = self.printer.get_selected_file()
        self.printer.close()

        self.serial_port_mock.write.assert_called_once_with(b"M4006\r\n")
        expect(selected_file).equals("subdir/LittleBBC.ctb")

    def test_get_selected_file_raises_after_serial_exception(self) -> None:
        # _send_and_read converts SerialException to UnexpectedPrinterResponse
        # and marks the port disconnected; retry()/api.py turn that into a
        # CLOSED state. This test locks in the new contract.
        self.serial_port_mock.readline.side_effect = serial.SerialException(
            "device disconnected"
        )

        self.printer.open()
        try:
            self.printer.get_selected_file()
            raised = False
        except UnexpectedPrinterResponse:
            raised = True
        finally:
            self.printer.close()

        self.serial_port_mock.write.assert_called_once_with(b"M4006\r\n")
        expect(raised).to_equal(True)
        expect(self.printer._is_connected).to_equal(False)

    def test_select_file(self) -> None:
        self.serial_port_mock.readline.return_value = (
            # FIXME: this isn't right, readline would return only the first one
            b"File opened:lattice.ctb Size:26058253\r\nFile selected\r\nok N:0\r\n"
        )
        self.printer.open()
        self.printer.select_file("lattice.ctb")
        self.printer.close()
        self.serial_port_mock.write.assert_called_once_with(b"M23 /lattice.ctb\r\n")

    def test_select_nonexisting_file(self) -> None:
        self.serial_port_mock.readline.return_value = (
            # FIXME: this isn't right, readline would return only the first one
            b"//############Error!cann't open file foobar.ctb!\r\n"
            + b"open failed, File :foobar.ctb\r\n"
            + b"ok N:0\r\n"
        )
        self.printer.open()
        with self.assertRaises(UnexpectedPrinterResponse):
            self.printer.select_file("foobar.ctb")
        self.printer.close()
        self.serial_port_mock.write.assert_called_once_with(b"M23 /foobar.ctb\r\n")

    def test_an_answer_before_the_cable_came_out_still_counts(self) -> None:
        with patch.object(
            self.printer,
            "_send_and_read_until_contains",
            side_effect=["wait\r\n", serial.SerialException("unplugged")],
        ):
            self.printer.open()
            status = self.printer.get_print_status()
            self.printer.close()
        expect(status.state).to_equal(PrinterState.CLOSED)
        expect(status.answered).to_equal(True)

    def test_select_file_says_when_the_printer_did_not_select_it(self) -> None:
        self.serial_port_mock.readline.return_value = (
            b"//############Error!cann't open file foobar.ctb!\r\n"
        )
        self.printer.open()
        with self.assertRaises(FileNotSelected):
            self.printer.select_file("foobar.ctb")
        self.printer.close()

    def test_select_file_says_so_too_when_the_printer_sent_nothing(self) -> None:
        self.printer.open()
        with patch.object(
            self.printer, "_send_and_read", side_effect=UnexpectedPrinterResponse("")
        ):
            with self.assertRaises(FileNotSelected):
                self.printer.select_file("foobar.ctb")
        self.printer.close()

    def test_start_printing_sends_no_print_command_for_an_unselected_file(
        self,
    ) -> None:
        self.serial_port_mock.readline.return_value = b"open failed\r\n"
        self.printer.open()
        with self.assertRaises(FileNotSelected):
            self.printer.start_printing("foobar.ctb")
        self.printer.close()
        self.serial_port_mock.write.assert_called_once_with(b"M23 /foobar.ctb\r\n")

    def test_stop_printing(self) -> None:
        self.serial_port_mock.readline.return_value = b"ok N:0\r\n"
        self.printer.open()
        self.printer.stop_printing()
        self.serial_port_mock.write.assert_called_once_with(b"M33\r\n")
        self.printer.close()

    def test_stop_printing_when_not_printing(self) -> None:
        self.serial_port_mock.readline.return_value = (
            # FIXME: this isn't right, readline would return only the first one
            b"Error:It's not printing now!\r\nok N:0\r\n"
        )
        self.printer.open()
        with self.assertRaises(UnexpectedPrinterResponse):
            self.printer.stop_printing()
        self.printer.close()
        self.serial_port_mock.write.assert_called_once_with(b"M33\r\n")

    def test_start_printing(self) -> None:
        self.serial_port_mock.readline.side_effect = [
            b"File opened:/benchy.ctb Size:11494803\r\n",
            b"ok N:0\r\n",
        ]
        self.printer.open()
        self.printer.start_printing("benchy.ctb")
        self.serial_port_mock.write.assert_has_calls(
            [
                call(b"M23 /benchy.ctb\r\n"),
                call(b"M6030 'benchy.ctb'\r\n"),
            ]
        )
        self.printer.close()

    def test_start_printing_from_subdirectory(self) -> None:
        self.serial_port_mock.readline.side_effect = [
            b"File opened:/more/model.ctb Size:11494803\r\n",
            b"ok N:0\r\n",
        ]
        self.printer.open()
        self.printer.start_printing("more/model.ctb")
        self.serial_port_mock.write.assert_has_calls(
            [
                call(b"M23 /more/model.ctb\r\n"),
                call(b"M6030 'model.ctb'\r\n"),
            ]
        )
        self.printer.close()

    def test_start_printing_with_invalid_response(self) -> None:
        self.serial_port_mock.readline.side_effect = [
            b"File opened:/benchy.ctb Size:11494803\r\n",
            b"foobar\r\n",
        ]
        self.printer.open()
        with self.assertRaises(UnexpectedPrinterResponse):
            self.printer.start_printing("benchy.ctb")
        self.serial_port_mock.write.assert_has_calls(
            [
                call(b"M23 /benchy.ctb\r\n"),
                call(b"M6030 'benchy.ctb'\r\n"),
            ]
        )
        self.printer.close()

    def test_resume_printing(self) -> None:
        self.serial_port_mock.readline.return_value = b"ok N:0\r\n"
        self.printer.open()
        self.printer.resume_printing()
        self.serial_port_mock.write.assert_called_once_with(b"M24\r\n")
        self.printer.close()

    def test_pause_printing(self) -> None:
        self.serial_port_mock.readline.return_value = b"ok N:0\r\n"
        self.printer.open()
        self.printer.pause_printing()
        self.serial_port_mock.write.assert_called_once_with(b"M25\r\n")
        self.printer.close()

    def test_move_by(self) -> None:
        self.serial_port_mock.readline.return_value = b"ok N:0\r\n"
        self.printer.open()

        self.printer.move_by(10)
        self.serial_port_mock.write.assert_called_once_with(b"G0 Z10.0 F600 I0\r\n")
        self.serial_port_mock.reset_mock()

        self.printer.move_by(-10)
        self.serial_port_mock.write.assert_called_once_with(b"G0 Z-10.0 F600 I0\r\n")
        self.serial_port_mock.reset_mock()

        self.printer.move_by(15.3, mm_per_min=30)
        self.serial_port_mock.write.assert_called_once_with(b"G0 Z15.3 F30 I0\r\n")
        self.serial_port_mock.reset_mock()

        self.printer.close()

    def test_move_to_home(self) -> None:
        self.serial_port_mock.readline.return_value = b"ok N:0\r\n"
        self.printer.open()
        self.printer.move_to_home()
        self.serial_port_mock.write.assert_called_once_with(b"G28\r\n")
        self.printer.close()

    def test_stop_motors(self) -> None:
        self.serial_port_mock.readline.return_value = b"ok N:0\r\n"
        self.printer.open()
        self.printer.stop_motors()
        self.serial_port_mock.write.assert_called_once_with(b"M112\r\n")
        self.printer.close()

    def test_reboot(self) -> None:
        self.printer.open()

        self.printer.reboot()
        self.serial_port_mock.write.assert_called_once_with(b"M6040 I0")
        self.serial_port_mock.reset_mock()

        self.printer.reboot(delay_in_ms=123)
        self.serial_port_mock.write.assert_called_once_with(b"M6040 I123")

        self.printer.close()
