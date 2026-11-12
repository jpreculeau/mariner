import hashlib
import errno
import io
import os
import subprocess
import pathlib
from typing import Any
from unittest.mock import patch, ANY, Mock

from flask.testing import FlaskClient
from freezegun import freeze_time
from pyfakefs.fake_filesystem import FakeFilesystem
from pyexpect import expect
from pyfakefs.fake_filesystem_unittest import TestCase
from werkzeug.datastructures import FileStorage

from mariner import config
from mariner.config import _get_config
from mariner.exceptions import UnexpectedPrinterResponse
from mariner.printer import (
    ChiTuPrinter,
    PrinterState,
    PrintStatus,
)
from mariner.server.api import reset_progress_tracking
from mariner.server import printer_access
from mariner.server.app import app
from mariner.server.utils import (
    read_cached_sliced_model_file,
    read_sliced_model_file,
)


class MarinerServerTest(TestCase):
    ctb_file_contents: bytes
    fork_file_contents: bytes
    client: FlaskClient
    fs: FakeFilesystem
    printer_mock: Any
    printer_patcher: Any

    def setUp(self) -> None:
        path = (
            pathlib.Path(__file__).parent.parent.absolute()
            / "file_formats"
            / "tests"
            / "stairs.ctb"
        )
        with open(path, "rb") as file:
            self.ctb_file_contents = file.read()

        forkpath = (
            pathlib.Path(__file__)
            .parent.parent.absolute()
            .joinpath("file_formats", "tests", "._stairs.ctb")
        )
        with open(forkpath, "rb") as forkfile:
            self.fork_file_contents = forkfile.read()

        _get_config.cache_clear()
        self.setUpPyfakefs(
            additional_skip_names=["importlib.metadata"],
        )
        self.fs.create_file(
            "/mnt/usb_share/foobar.ctb", contents=self.ctb_file_contents
        )
        self.fs.create_file(
            "/mnt/usb_share/._foobar.ctb", contents=self.fork_file_contents
        )

        self.client = app.test_client()
        printer_access.forget_everything()
        app.config["WTF_CSRF_ENABLED"] = False

        self.printer_mock = Mock(spec=ChiTuPrinter)
        self.printer_patcher = patch("mariner.server.printer_access.ChiTuPrinter")
        printer_constructor_mock = self.printer_patcher.start()
        printer_constructor_mock.return_value = self.printer_mock
        self.printer_mock.__enter__ = Mock(return_value=self.printer_mock)
        self.printer_mock.__exit__ = Mock(return_value=None)
        # An idle printer with nothing selected, unless a test says otherwise.
        self.printer_mock.get_print_status.return_value = PrintStatus(
            state=PrinterState.IDLE, counters_seen=True
        )
        self.printer_mock.get_selected_file.return_value = ""

        # this is so we don't try caching the values returned by this function during
        # tests. this is important because during tests this function returns a Mock,
        # which pickle cannot serialize.
        self._read_ctb_file_patcher = patch(
            "mariner.server.api.read_cached_sliced_model_file",
            side_effect=read_sliced_model_file,
        )
        self._read_ctb_file_patcher.start()
        reset_progress_tracking()

    def tearDown(self) -> None:
        self.printer_patcher.stop()
        reset_progress_tracking()

    def test_print_status_while_printing(self) -> None:
        self.printer_mock.get_selected_file.return_value = "foobar.ctb"
        self.printer_mock.get_print_status.return_value = PrintStatus(
            state=PrinterState.PRINTING,
            current_byte=256537,
            total_bytes=832745,
        )
        response = self.client.get("/api/print_status")
        expect(response.get_json()).to_equal(
            {
                "state": "PRINTING",
                "selected_file": "foobar.ctb",
                "progress": 32.25,
                "layer_count": 400,
                "current_layer": 130,
                "print_time_secs": 5621,
                "time_left_secs": 3808,
            }
        )

    def test_print_status_when_paused(self) -> None:
        self.printer_mock.get_selected_file.return_value = "foobar.ctb"
        self.printer_mock.get_print_status.return_value = PrintStatus(
            state=PrinterState.PAUSED,
            current_byte=256537,
            total_bytes=832745,
        )
        response = self.client.get("/api/print_status")
        expect(response.get_json()).to_equal(
            {
                "state": "PAUSED",
                "selected_file": "foobar.ctb",
                "progress": 32.25,
                "layer_count": 400,
                "current_layer": 130,
                "print_time_secs": 5621,
                "time_left_secs": 3808,
            }
        )

    def test_print_status_while_starting_print(self) -> None:
        self.printer_mock.get_selected_file.return_value = "foobar.ctb"
        self.printer_mock.get_print_status.return_value = PrintStatus(
            state=PrinterState.STARTING_PRINT,
            current_byte=0,
            total_bytes=832745,
        )
        response = self.client.get("/api/print_status")
        expect(response.get_json()).to_equal(
            {
                "state": "STARTING_PRINT",
                "selected_file": "foobar.ctb",
                "progress": 0.0,
                "layer_count": 400,
                "current_layer": 1,
                "print_time_secs": 5621,
                "time_left_secs": 5621,
            }
        )

    def test_print_status_while_idle(self) -> None:
        self.printer_mock.get_selected_file.return_value = "foobar.ctb"
        self.printer_mock.get_print_status.return_value = PrintStatus(
            state=PrinterState.IDLE,
            current_byte=0,
            total_bytes=0,
        )
        response = self.client.get("/api/print_status")
        expect(response.get_json()).to_equal(
            {
                "state": "IDLE",
                "selected_file": "foobar.ctb",
                "progress": 0.0,
            }
        )

    def test_print_status_returns_closed_when_printer_status_unreadable(self) -> None:
        self.printer_mock.get_print_status.side_effect = UnexpectedPrinterResponse("")
        response = self.client.get("/api/print_status")
        expect(response.status_code).to_equal(200)
        expect(response.get_json()).to_equal(
            {
                "state": "CLOSED",
                "selected_file": "",
                "progress": 0.0,
            }
        )

    def test_list_files(self) -> None:
        self.fs.create_dir("/mnt/usb_share/subdir/")
        with freeze_time("2020-03-15"):
            self.fs.create_file("/mnt/usb_share/a.ctb", contents=self.ctb_file_contents)
        with freeze_time("2020-03-17"):
            self.fs.create_file("/mnt/usb_share/b.ctb", contents=self.ctb_file_contents)
        with freeze_time("2020-03-16"):
            self.fs.create_file(
                "/mnt/usb_share/random_file.txt", contents="dummy content"
            )
        with freeze_time("2021-05-14"):
            self.fs.create_file(
                "/mnt/usb_share/README",
                contents=self.ctb_file_contents,
            )
        with freeze_time("2021-05-15"):
            self.fs.create_file(
                "/mnt/usb_share/case.CtB",
                contents=self.ctb_file_contents,
            )

        response = self.client.get("/api/list_files")
        expect(response.get_json()).to_equal(
            {
                "directories": [{"dirname": "subdir"}],
                "files": [
                    {
                        "filename": "._foobar.ctb",
                        "path": "._foobar.ctb",
                        "can_be_printed": False,
                    },
                    {
                        "filename": "foobar.ctb",
                        "path": "foobar.ctb",
                        "print_time_secs": 5621,
                        "can_be_printed": True,
                    },
                    {
                        "filename": "case.CtB",
                        "path": "case.CtB",
                        "print_time_secs": 5621,
                        "can_be_printed": True,
                    },
                    {
                        "filename": "README",
                        "path": "README",
                        "can_be_printed": False,
                    },
                    {
                        "filename": "b.ctb",
                        "path": "b.ctb",
                        "print_time_secs": 5621,
                        "can_be_printed": True,
                    },
                    {
                        "filename": "random_file.txt",
                        "path": "random_file.txt",
                        "can_be_printed": False,
                    },
                    {
                        "filename": "a.ctb",
                        "path": "a.ctb",
                        "print_time_secs": 5621,
                        "can_be_printed": True,
                    },
                ],
            }
        )

    def test_list_files_under_subdirectory(self) -> None:
        self.fs.create_dir("/mnt/usb_share/foo/bar/subdir/")
        self.fs.create_file(
            "/mnt/usb_share/foo/bar/a.ctb", contents=self.ctb_file_contents
        )
        self.fs.create_file(
            "/mnt/usb_share/foo/bar/b.ctb", contents=self.ctb_file_contents
        )

        response = self.client.get("/api/list_files?path=foo/bar/")
        expect(response.get_json()).to_equal(
            {
                "directories": [{"dirname": "subdir"}],
                "files": [
                    {
                        "filename": "b.ctb",
                        "path": "foo/bar/b.ctb",
                        "print_time_secs": 5621,
                        "can_be_printed": True,
                    },
                    {
                        "filename": "a.ctb",
                        "path": "foo/bar/a.ctb",
                        "print_time_secs": 5621,
                        "can_be_printed": True,
                    },
                ],
            }
        )

    def test_list_files_survives_an_unparseable_file(self) -> None:
        # A file with a supported extension that cannot be parsed (truncated,
        # corrupted in transfer, or an unsupported format variant) must not
        # take down the whole listing.
        self.fs.create_file(
            "/mnt/usb_share/corrupt.ctb", contents="not really a ctb file"
        )
        response = self.client.get("/api/list_files")
        expect(response.status_code).to_equal(200)

        files = {f["filename"]: f for f in response.get_json()["files"]}
        expect("corrupt.ctb" in files).to_equal(True)
        expect(files["corrupt.ctb"]["can_be_printed"]).to_equal(False)
        # The healthy file alongside it is still reported normally.
        expect(files["foobar.ctb"]["can_be_printed"]).to_equal(True)

    def test_listing_a_file_the_drive_fails_on_keeps_its_name_on_one_log_line(
        self,
    ) -> None:
        # Not a name Mariner would store, but one that can be on the drive.
        name = "x\u2028FORGED entry.ctb"
        self.fs.create_file(f"/mnt/usb_share/{name}", contents="whatever")
        self.fs.remove("/mnt/usb_share/foobar.ctb")
        self.fs.remove("/mnt/usb_share/._foobar.ctb")
        with patch(
            "mariner.server.api.read_cached_sliced_model_file",
            side_effect=OSError(5, "Input/output error"),
        ), self.assertLogs("mariner.server.api", level="WARNING") as logs:
            response = self.client.get("/api/list_files")
        expect(response.get_json()["files"][0]["can_be_printed"]).to_equal(False)
        messages = [record.getMessage() for record in logs.records]
        expect(len(messages)).to_equal(1)
        expect("\u2028" in messages[0]).to_equal(False)
        expect("FORGED entry.ctb" in messages[0]).to_equal(True)

    def test_listing_an_unparseable_file_does_not_log_it_again(self) -> None:
        self.fs.create_file("/mnt/usb_share/corrupt.ctb", contents="not a ctb file")
        with self.assertNoLogs("mariner.server.api", level="WARNING"):
            self.client.get("/api/list_files")

    def test_list_files_from_missing_directory(self) -> None:
        response = self.client.get("/api/list_files?path=no_such_dir")
        expect(response.status_code).to_equal(404)

    def test_list_files_from_a_file(self) -> None:
        response = self.client.get("/api/list_files?path=foobar.ctb")
        expect(response.status_code).to_equal(404)

    def test_list_files_survives_a_broken_symlink(self) -> None:
        self.fs.create_symlink("/mnt/usb_share/dangling.ctb", "/mnt/usb_share/gone")
        response = self.client.get("/api/list_files")
        expect(response.status_code).to_equal(200)
        listing = response.get_json()
        # Not offered as a folder, which could not be opened.
        expect(listing["directories"]).to_equal([])
        files = {f["filename"]: f for f in listing["files"]}
        expect(files["dangling.ctb"]["can_be_printed"]).to_equal(False)

    def test_list_files_lists_anything_that_is_not_a_directory_as_a_file(self) -> None:
        # pyfakefs reports a dangling link as a file; a real filesystem
        # reports it as neither file nor directory. Both must land in "files".
        entry = Mock()
        entry.name = "dangling.ctb"
        entry.path = "/mnt/usb_share/dangling.ctb"
        entry.is_dir.return_value = False
        entry.is_file.return_value = False
        entry.stat.side_effect = OSError("dangling")
        scan = Mock()
        scan.__enter__ = Mock(return_value=[entry])
        scan.__exit__ = Mock(return_value=None)
        with patch("mariner.server.api.os.scandir", return_value=scan):
            listing = self.client.get("/api/list_files").get_json()
        expect(listing["directories"]).to_equal([])
        expect([f["filename"] for f in listing["files"]]).to_equal(["dangling.ctb"])

    def test_list_files_does_not_open_what_a_link_leads_to_elsewhere(self) -> None:
        self.fs.create_file("/mnt/outside.ctb", contents=self.ctb_file_contents)
        self.fs.create_symlink("/mnt/usb_share/way-out.ctb", "/mnt/outside.ctb")
        with patch(
            "mariner.server.api.read_cached_sliced_model_file",
            wraps=read_cached_sliced_model_file,
        ) as reader:
            response = self.client.get("/api/list_files")
        listed = {entry["filename"]: entry for entry in response.get_json()["files"]}
        expect(listed["way-out.ctb"]["can_be_printed"]).to_equal(False)
        expect(listed["foobar.ctb"]["can_be_printed"]).to_equal(True)
        opened = [str(call.args[0]) for call in reader.call_args_list]
        expect([path for path in opened if "out" in path]).to_equal([])

    def test_list_files_survives_a_link_that_leads_back_to_itself(self) -> None:
        # Asked whether it is a folder, such a link answers with an error.
        # The fake filesystem does not; this entry does.
        class LoopingLink:
            name = "loop.txt"
            path = "/mnt/usb_share/loop.txt"

            def is_dir(self) -> bool:
                raise OSError(40, "Too many levels of symbolic links")

            def is_symlink(self) -> bool:
                return True

            def stat(self) -> None:
                raise OSError(40, "Too many levels of symbolic links")

        class Scan:
            def __enter__(self) -> Any:
                return [LoopingLink()]

            def __exit__(self, *_: Any) -> None:
                return None

        with patch("mariner.server.api.os.scandir", return_value=Scan()):
            response = self.client.get("/api/list_files")
        expect(response.status_code).to_equal(200)
        expect(response.get_json()).to_equal(
            {
                "directories": [],
                "files": [
                    {
                        "filename": "loop.txt",
                        "path": "loop.txt",
                        "can_be_printed": False,
                    }
                ],
            }
        )

    def test_list_files_only_follows_links(self) -> None:
        # Following an entry means looking through its whole folder. Only
        # a link can lead elsewhere, so only links are followed.
        self.fs.create_file("/mnt/usb_share/second.ctb", contents=b"x")
        self.fs.create_symlink("/mnt/usb_share/alias.ctb", "/mnt/usb_share/foobar.ctb")
        with patch(
            "mariner.server.api.stays_in_files_directory", return_value=True
        ) as followed:
            self.client.get("/api/list_files")
        followed.assert_called_once_with(pathlib.Path("/mnt/usb_share/alias.ctb"))

    def test_list_files_hides_uploads_in_progress(self) -> None:
        self.fs.create_file(
            "/mnt/usb_share/.upload-0123456789abcdef.part", contents=b"partial"
        )
        listing = self.client.get("/api/list_files").get_json()
        names = [f["filename"] for f in listing["files"]]
        expect(".upload-0123456789abcdef.part" in names).to_equal(False)
        expect("foobar.ctb" in names).to_equal(True)

    def test_list_files_hides_the_folder_of_slicer_transfers(self) -> None:
        self.fs.create_file("/mnt/usb_share/.sdcp_uploads/abcd.part", contents=b"x")
        self.fs.create_dir("/mnt/usb_share/models")
        listing = self.client.get("/api/list_files").get_json()
        expect(listing["directories"]).to_equal([{"dirname": "models"}])

    def test_list_files_from_invalid_directory(self) -> None:
        response = self.client.get("/api/list_files?path=../foo/")
        expect(response.status_code).to_equal(400)

    def test_command_start_printing(self) -> None:
        response = self.client.post(
            "/api/printer/command/start_print?filename=foobar.ctb"
        )
        expect(response.get_json()).to_equal({"success": True})
        self.printer_mock.start_printing.assert_called_once_with("foobar.ctb")

    def test_command_start_printing_in_subdirectory(self) -> None:
        self.fs.create_file(
            "/mnt/usb_share/sub/part.ctb", contents=self.ctb_file_contents
        )
        response = self.client.post(
            "/api/printer/command/start_print?filename=sub/part.ctb"
        )
        expect(response.status_code).to_equal(200)
        self.printer_mock.start_printing.assert_called_once_with("sub/part.ctb")

    def test_command_start_printing_sends_the_path_the_printer_knows(self) -> None:
        self.fs.create_file(
            "/mnt/usb_share/sub/part.ctb", contents=self.ctb_file_contents
        )
        for given, sent in (
            ("/mnt/usb_share/foobar.ctb", "foobar.ctb"),
            ("./foobar.ctb", "foobar.ctb"),
            ("sub/../foobar.ctb", "foobar.ctb"),
            ("sub//part.ctb", "sub/part.ctb"),
        ):
            self.printer_mock.start_printing.reset_mock()
            # Each one as the first print of the day.
            printer_access.forget_everything()
            response = self.client.post(
                f"/api/printer/command/start_print?filename={given}"
            )
            expect(response.status_code).to_equal(200)
            self.printer_mock.start_printing.assert_called_once_with(sent)

    def test_command_start_printing_refuses_control_characters(self) -> None:
        # Anything after a line break would reach the mainboard as a command
        # of its own.
        for filename in (
            "foobar.ctb%0D%0AG0%20Z-50",
            "foobar.ctb%0AG28",
            "foobar.ctb%00",
        ):
            response = self.client.post(
                f"/api/printer/command/start_print?filename={filename}"
            )
            expect(response.status_code).to_equal(400)
        self.printer_mock.start_printing.assert_not_called()

    def test_command_start_printing_refuses_a_quote(self) -> None:
        self.fs.create_file("/mnt/usb_share/it's.ctb", contents=b"x")
        response = self.client.post(
            "/api/printer/command/start_print?filename=it%27s.ctb"
        )
        expect(response.status_code).to_equal(400)
        self.printer_mock.start_printing.assert_not_called()

    def test_command_start_printing_without_a_filename(self) -> None:
        response = self.client.post("/api/printer/command/start_print")
        expect(response.status_code).to_equal(400)
        self.printer_mock.start_printing.assert_not_called()

    def test_command_start_printing_outside_files_directory(self) -> None:
        self.fs.create_file("/mnt/other.ctb", contents=self.ctb_file_contents)
        response = self.client.post(
            "/api/printer/command/start_print?filename=../other.ctb"
        )
        expect(response.status_code).to_equal(400)
        self.printer_mock.start_printing.assert_not_called()

    def test_command_start_printing_a_missing_file(self) -> None:
        response = self.client.post(
            "/api/printer/command/start_print?filename=missing.ctb"
        )
        expect(response.status_code).to_equal(404)
        self.printer_mock.start_printing.assert_not_called()

    def test_command_start_printing_an_unsupported_file(self) -> None:
        self.fs.create_file("/mnt/usb_share/notes.txt", contents=b"x")
        response = self.client.post(
            "/api/printer/command/start_print?filename=notes.txt"
        )
        expect(response.status_code).to_equal(400)
        self.printer_mock.start_printing.assert_not_called()

    def test_unknown_command(self) -> None:
        response = self.client.post("/api/printer/command/self_destruct")
        expect(response.status_code).to_equal(404)

    def test_command_pause_print(self) -> None:
        response = self.client.post("/api/printer/command/pause_print")
        expect(response.get_json()).to_equal({"success": True})
        self.printer_mock.pause_printing.assert_called_once_with()

    def test_command_resume_print(self) -> None:
        response = self.client.post("/api/printer/command/resume_print")
        expect(response.get_json()).to_equal({"success": True})
        self.printer_mock.resume_printing.assert_called_once_with()

    def test_command_start_printing_while_a_print_is_running(self) -> None:
        self._printer_is_printing("other.ctb")
        response = self.client.post(
            "/api/printer/command/start_print?filename=foobar.ctb"
        )
        expect(response.status_code).to_equal(409)
        expect(response.get_json()).to_equal(
            {
                "code": "print_in_progress",
                "title": "Print In Progress",
                "description": "The printer is already printing. Wait for the "
                "print to finish or cancel it first.",
            }
        )
        self.printer_mock.start_printing.assert_not_called()

    def test_a_cancelled_print_still_protects_its_file_for_a_moment(self) -> None:
        # Started and cancelled at once, before the printer reported it.
        # Nothing the printer says then tells a print that was stopped from
        # one that is about to begin.
        self.client.post("/api/printer/command/start_print?filename=foobar.ctb")
        cancelled = self.client.post("/api/printer/command/cancel_print")
        expect(cancelled.status_code).to_equal(200)

        response = self.client.post("/api/delete_file?filename=foobar.ctb")
        expect(response.status_code).to_equal(409)
        expect(response.get_json()["code"]).to_equal("print_just_started")

    def test_a_just_started_print_cannot_be_overridden(self) -> None:
        self.client.post("/api/printer/command/start_print?filename=foobar.ctb")
        # The printer goes quiet right after. Set directly: the helper
        # would also forget the print that was just started.
        printer_access._forget_last_status()
        self.printer_mock.get_print_status.return_value = PrintStatus(
            state=PrinterState.CLOSED, silent=True
        )
        response = self.client.post(
            "/api/delete_file?filename=foobar.ctb&ignore_unreachable_printer=1"
        )
        expect(response.status_code).to_equal(409)
        expect(response.get_json()["code"]).to_equal("print_just_started")

    def test_a_second_print_is_refused_until_the_first_is_reported(self) -> None:
        self.fs.create_file("/mnt/usb_share/other.ctb", contents=self.ctb_file_contents)
        self.client.post("/api/printer/command/start_print?filename=foobar.ctb")
        response = self.client.post(
            "/api/printer/command/start_print?filename=other.ctb"
        )
        expect(response.status_code).to_equal(409)
        expect(response.get_json()).to_equal(
            {
                "code": "print_just_started",
                "title": "Print Just Started",
                "description": "A print was started a moment ago and the "
                "printer has yet to report it. Try again in half a minute.",
            }
        )
        self.printer_mock.start_printing.assert_called_once_with("foobar.ctb")

    def test_command_cancel_print(self) -> None:
        response = self.client.post("/api/printer/command/cancel_print")
        expect(response.get_json()).to_equal({"success": True})
        self.printer_mock.stop_printing.assert_called_once_with()

    def test_error_handling_while_stopping_print(self) -> None:
        self.printer_mock.stop_printing.side_effect = UnexpectedPrinterResponse(
            "foobar\r\n"
        )
        # What went wrong inside goes to the logs, not to whoever asks.
        with self.assertLogs("mariner.server.api", level="WARNING") as logs:
            response = self.client.post("/api/printer/command/cancel_print")
        expect(response.status_code).to_equal(500)
        expect(response.get_json()).to_equal(
            {
                "code": "printer_error",
                "title": "Unexpected Printer Response",
                "description": "The printer returned an unexpected response: "
                + "'foobar\\r\\n'",
            }
        )
        expect(len(logs.records)).to_equal(1)
        expect(logs.records[0].exc_info is not None).to_equal(True)
        self.printer_mock.stop_printing.assert_called_once_with()

    def test_command_reboot(self) -> None:
        response = self.client.post("/api/printer/command/reboot")
        expect(response.get_json()).to_equal({"success": True})
        self.printer_mock.reboot.assert_called_once_with()

    def test_file_details(self) -> None:
        response = self.client.get("/api/file_details?filename=foobar.ctb")
        expect(response.get_json()).to_equal(
            {
                "filename": "foobar.ctb",
                "path": "foobar.ctb",
                "bed_size_mm": [68.04, 120.96, 150.0],
                "height_mm": 20.0,
                "layer_count": 400,
                "layer_height_mm": 0.05,
                "resolution": [1440, 2560],
                "print_time_secs": 5621,
            }
        )

    def test_file_details_in_subdirectory(self) -> None:
        self.fs.create_file(
            "/mnt/usb_share/functional/stairs.ctb", contents=self.ctb_file_contents
        )

        response = self.client.get("/api/file_details?filename=functional/stairs.ctb")
        expect(response.get_json()).to_equal(
            {
                "filename": "stairs.ctb",
                "path": "functional/stairs.ctb",
                "bed_size_mm": [68.04, 120.96, 150.0],
                "height_mm": 20.0,
                "layer_count": 400,
                "layer_height_mm": 0.05,
                "resolution": [1440, 2560],
                "print_time_secs": 5621,
            }
        )

    def test_file_details_with_invalid_path(self) -> None:
        response = self.client.get("/api/file_details?filename=../../etc/passwd")
        expect(response.status_code).to_equal(400)

    def test_file_preview(self) -> None:
        response = self.client.get("/api/file_preview?filename=foobar.ctb")
        expect(response.content_type).to_equal("image/png")
        expect(hashlib.md5(response.get_data()).hexdigest()).to_equal(
            "ca98c806d42898ba70626e556f714928"
        )

    def test_file_preview_with_invalid_path(self) -> None:
        response = self.client.get("/api/file_preview?filename=../../etc/passwd")
        expect(response.status_code).to_equal(400)

    def test_details_and_preview_of_an_incomplete_file_say_so(self) -> None:
        # What a transfer that stopped part of the way leaves behind. The
        # picture is stored near the start, so it takes a shorter file for
        # the preview to be missing too.
        half = len(self.ctb_file_contents) // 2
        self.fs.create_file(
            "/mnt/usb_share/half.ctb", contents=self.ctb_file_contents[:half]
        )
        self.fs.create_file(
            "/mnt/usb_share/start.ctb", contents=self.ctb_file_contents[:200]
        )
        for endpoint, name in (
            ("file_details", "half.ctb"),
            ("file_details", "start.ctb"),
            ("file_preview", "start.ctb"),
        ):
            # Not logged here: where the file is read, once, with the reason.
            with self.assertNoLogs("mariner.server.api", level="WARNING"):
                response = self.client.get(f"/api/{endpoint}?filename={name}")
            expect(response.status_code).to_equal(422)
            body = response.get_json()
            expect(body["code"]).to_equal("file_unreadable")
            expect(name in body["description"]).to_equal(True)
            expect("traceback" in body).to_equal(False)

    def test_details_and_preview_of_a_file_that_is_not_a_model_say_so(self) -> None:
        for endpoint in ("file_details", "file_preview"):
            with self.assertNoLogs("mariner.server.api", level="WARNING"):
                response = self.client.get(f"/api/{endpoint}?filename=._foobar.ctb")
            expect(response.status_code).to_equal(422)
            expect(response.get_json()["code"]).to_equal("file_unreadable")

    def test_a_malformed_file_being_printed_is_not_reported_again(self) -> None:
        from mariner.file_formats.reading import MalformedFile
        from mariner.server.api import _read_selected_file

        with patch(
            "mariner.server.api.read_cached_sliced_model_file",
            side_effect=MalformedFile("cut short"),
        ), self.assertNoLogs("mariner.server.api", level="WARNING"):
            expect(_read_selected_file("foobar.ctb")).to_equal(None)

    def test_details_and_preview_when_the_read_itself_fails(self) -> None:
        # The drive, or the memory: not something sending the file again
        # would cure, so the file is not blamed.
        for endpoint, reader in (
            ("file_details", "read_cached_sliced_model_file"),
            ("file_preview", "read_cached_preview"),
        ):
            with patch(
                f"mariner.server.api.{reader}",
                side_effect=OSError(5, "Input/output error"),
            ), self.assertLogs("mariner.server.api", level="WARNING"):
                response = self.client.get(f"/api/{endpoint}?filename=foobar.ctb")
            expect(response.status_code).to_equal(500)
            body = response.get_json()
            expect(body["code"]).to_equal("file_read_failed")
            expect("foobar.ctb" in body["description"]).to_equal(True)
            expect("traceback" in body).to_equal(False)

    def test_details_and_preview_of_an_unsupported_kind_of_file(self) -> None:
        self.fs.create_file("/mnt/usb_share/notes.txt", contents="hello")
        for endpoint in ("file_details", "file_preview"):
            response = self.client.get(f"/api/{endpoint}?filename=notes.txt")
            expect(response.status_code).to_equal(400)

    def test_details_and_preview_of_a_file_removed_meanwhile(self) -> None:
        # Deleted between the check and the read, by another client.
        for endpoint, reader in (
            ("file_details", "read_cached_sliced_model_file"),
            ("file_preview", "read_cached_preview"),
        ):
            with patch(f"mariner.server.api.{reader}", side_effect=FileNotFoundError()):
                response = self.client.get(f"/api/{endpoint}?filename=foobar.ctb")
            expect(response.status_code).to_equal(404)

    def test_upload_file_without_a_file(self) -> None:
        response = self.client.post("/api/upload_file")
        expect(response.status_code).to_equal(400)

    def test_upload_file_with_an_empty_filename(self) -> None:
        data = {"file": (io.BytesIO(b"abcdef"), "")}
        response = self.client.post("/api/upload_file", data=data)
        expect(response.status_code).to_equal(400)

    def test_upload_file_with_an_unsupported_file_extension(self) -> None:
        data = {"file": (io.BytesIO(b"abcdef"), "image.jpg")}
        response = self.client.post("/api/upload_file", data=data)
        expect(response.status_code).to_equal(400)

    def test_an_error_nobody_planned_for_tells_nothing_of_the_inside(self) -> None:
        with patch(
            "mariner.server.api.os.scandir",
            side_effect=RuntimeError("secret /home/mariner/thing"),
        ), self.assertLogs("mariner.server.app", level="ERROR") as logs:
            response = self.client.get("/api/list_files")
        expect(response.status_code).to_equal(500)
        body = response.get_json()
        expect(body["code"]).to_equal("internal_error")
        expect("secret" in response.get_data(as_text=True)).to_equal(False)
        expect("Traceback" in response.get_data(as_text=True)).to_equal(False)
        # Logged once, with the cause.
        expect(len(logs.records)).to_equal(1)
        expect(logs.records[0].exc_info is not None).to_equal(True)

    def test_refusals_keep_their_own_status(self) -> None:
        # The handler for the unplanned must not swallow the planned.
        expect(self.client.get("/api/nothing-here").status_code).to_equal(404)
        expect(self.client.get("/api/file_details").status_code).to_equal(400)
        expect(self.client.put("/api/list_files").status_code).to_equal(405)

    def test_the_app_does_not_run_in_debug_mode(self) -> None:
        application = self.client.application
        expect(application.debug).to_equal(False)
        expect(bool(application.config.get("PROPAGATE_EXCEPTIONS"))).to_equal(False)

    def test_every_answer_carries_the_protective_headers(self) -> None:
        with patch("mariner.server.render_template", return_value="the page"):
            answers = [
                self.client.get("/"),
                self.client.get("/api/list_files"),
                self.client.get("/api/nothing-here"),
                self.client.get("/api/list_files", headers={"Host": "evil.example"}),
                self.client.get("/api/file_preview?filename=foobar.ctb"),
            ]
        for response in answers:
            headers = response.headers
            expect(headers["X-Content-Type-Options"]).to_equal("nosniff")
            # Not shown inside a page of another site, where a click meant
            # for that page could land on a button of this one.
            expect(headers["X-Frame-Options"]).to_equal("DENY")
            expect(headers["Referrer-Policy"]).to_equal("same-origin")
            expect(headers["Cross-Origin-Resource-Policy"]).to_equal("same-origin")
            policy = headers["Content-Security-Policy"]
            # Nothing is fetched from another site: the page carries its
            # typefaces with it.
            expect("http" in policy).to_equal(False)
            expect("font-src 'self';" in policy).to_equal(True)
            for part in (
                "default-src 'self'",
                "script-src 'self'",
                "object-src 'none'",
                "frame-ancestors 'none'",
                "base-uri 'self'",
                "form-action 'self'",
            ):
                expect(part in policy.split("; ")).to_equal(True)
            expect("'unsafe-eval'" in policy).to_equal(False)
            expect("script-src 'self' 'unsafe-inline'" in policy).to_equal(False)

    def test_what_the_api_tells_is_not_kept_by_browsers_or_proxies(self) -> None:
        response = self.client.get("/api/list_files")
        expect(response.headers["Cache-Control"]).to_equal("no-store")

    def test_static_files_carry_the_headers_too(self) -> None:
        from mariner.server.app import add_static_headers

        headers: dict = {}
        add_static_headers(headers, "/opt/dist/assets/index.js", "/assets/index.js")
        expect(headers["X-Content-Type-Options"]).to_equal("nosniff")
        expect(headers["Cross-Origin-Resource-Policy"]).to_equal("same-origin")
        # A file whose name changes with its content is kept by the
        # browser for good: it is not asked for again at every visit.
        for kept in (
            "/assets/index-Q-zpu2Rs.js",
            "/assets/index-CvogB2Bx.css",
            "/assets/opendyslexic-latin-400-normal-wYUJcbXi.woff2",
        ):
            headers = {"Cache-Control": "max-age=60, public"}
            add_static_headers(headers, "/opt/dist" + kept, kept)
            expect(headers["Cache-Control"]).to_equal(
                "max-age=31536000, public, immutable"
            )
        for not_kept in ("/favicon.svg", "/licenses/x-OFL.txt", "/assets/plain.js"):
            headers = {"Cache-Control": "max-age=60, public"}
            add_static_headers(headers, "/opt/dist" + not_kept, not_kept)
            expect(headers["Cache-Control"]).to_equal("max-age=60, public")
        # And that is what serves them, for the page alone.
        served_by = self.client.application.wsgi_app
        expect(served_by.add_headers_function).to_equal(add_static_headers)
        expect(served_by.allow_all_origins).to_equal(False)

    def test_host_commands_say_whether_they_were_accepted(self) -> None:
        for url, command in (
            ("/api/host/shutdown", ["shutdown", "-h", "now"]),
            ("/api/host/reboot", ["reboot"]),
        ):
            with patch("mariner.server.api.subprocess.run") as run:
                run.return_value.returncode = 0
                response = self.client.post(url)
            expect(response.status_code).to_equal(200)
            expect(run.call_args.args[0]).to_equal(command)
            # Not left to hang a request thread if the command does.
            expect(run.call_args.kwargs["timeout"] <= 30).to_equal(True)

            # Refused: the account Mariner runs under may not have the right.
            with patch("mariner.server.api.subprocess.run") as run, self.assertLogs(
                "mariner.server.api", level="WARNING"
            ) as logs:
                run.return_value.returncode = 1
                run.return_value.stderr = b"Interactive authentication required.\nX"
                response = self.client.post(url)
            expect(response.status_code).to_equal(503)
            body = response.get_json()
            expect(body["code"]).to_equal("host_command_refused")
            expect("authentication" in response.get_data(as_text=True)).to_equal(False)
            expect("\n" in logs.records[-1].getMessage()).to_equal(False)

            for failure in (
                FileNotFoundError("shutdown"),
                subprocess.TimeoutExpired(command, 15),
            ):
                with patch(
                    "mariner.server.api.subprocess.run", side_effect=failure
                ), self.assertLogs("mariner.server.api", level="WARNING"):
                    response = self.client.post(url)
                expect(response.status_code).to_equal(503)
                expect(response.get_json()["code"]).to_equal("host_command_refused")

    def test_file_preview_of_a_name_in_any_script(self) -> None:
        # The name goes into a header, which carries plain characters only.
        self.fs.create_file(
            "/mnt/usb_share/模型 é.ctb", contents=self.ctb_file_contents
        )
        response = self.client.get("/api/file_preview?filename=模型 é.ctb")
        expect(response.status_code).to_equal(200)
        disposition = response.headers["Content-Disposition"]
        disposition.encode("latin-1")
        expect(disposition.isascii()).to_equal(True)
        expect(
            "filename*=UTF-8''%E6%A8%A1%E5%9E%8B%20%C3%A9.ctb.png" in disposition
        ).to_equal(True)
        # Shown where it is asked for, not saved: a page of another site
        # that had the browser ask could tell, from a download starting
        # or not, whether a file of that name exists.
        expect(disposition.startswith("inline; ")).to_equal(True)
        # An ordinary name is given both ways, for clients that know one.
        response = self.client.get("/api/file_preview?filename=foobar.ctb")
        expect(
            'filename="foobar.ctb.png"' in response.headers["Content-Disposition"]
        ).to_equal(True)

    def test_requests_from_another_site_are_refused(self) -> None:
        elsewhere = {"Sec-Fetch-Site": "cross-site"}
        for method, url in (
            ("get", "/api/print_status"),
            ("get", "/api/list_files"),
            ("post", "/api/printer/command/cancel_print"),
            ("post", "/api/delete_file?filename=foobar.ctb"),
            ("get", "/api/file_preview?filename=foobar.ctb"),
        ):
            response = getattr(self.client, method)(url, headers=elsewhere)
            expect(response.status_code).to_equal(403)
            expect(response.get_json()["code"]).to_equal("cross_site_request")
        expect(os.path.exists("/mnt/usb_share/foobar.ctb")).to_equal(True)
        self.printer_mock.stop_printing.assert_not_called()

    def test_requests_from_the_page_itself_are_served(self) -> None:
        for headers in (
            {"Sec-Fetch-Site": "same-origin"},
            {"Sec-Fetch-Site": "none"},
            {"Origin": "http://localhost"},
            {},
        ):
            response = self.client.get("/api/list_files", headers=headers)
            expect(response.status_code).to_equal(200)

    def test_the_page_s_own_requests_come_from_a_browser(self) -> None:
        # Over plain HTTP they say nothing of the site either.
        browser = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/153.0"}
        response = self.client.get("/api/list_files", headers=browser)
        expect(response.status_code).to_equal(200)

    def test_a_folder_that_cannot_be_made_is_refused_not_an_error(self) -> None:
        # A path longer than the system takes, say.
        with patch(
            "mariner.server.api.os.mkdir", side_effect=OSError(36, "File name too long")
        ), self.assertLogs("mariner.server.api", level="WARNING"):
            response = self.client.post("/api/create_directory?path=.&name=sub")
        expect(response.status_code).to_equal(400)

    def test_a_request_is_not_measured_once_it_has_arrived(self) -> None:
        # By then the web server has stored it: what room is left says
        # nothing of whether it fitted. A full drive must not turn away
        # what needs no room either.
        with patch("shutil.disk_usage", return_value=Mock(free=0, total=1, used=1)):
            response = self.client.post("/api/create_directory?path=.&name=sub")
            expect(response.status_code).to_equal(200)
            # Large enough to have been put in a file by the web server.
            data = b"x" * (600 * 1024)
            response = self.client.put("/uvtools/upload/large.ctb", data=data)
            expect(response.status_code != 507).to_equal(True)

    def test_an_upload_with_no_room_to_wait_in_says_so(self) -> None:
        # Raised while the form is read, before the upload route runs.
        with patch(
            "mariner.server.api.safe_filename",
            side_effect=OSError(errno.ENOSPC, "No space left on device"),
        ), self.assertLogs("mariner.server.app", level="WARNING"):
            data = {"file": (io.BytesIO(b"abcdef"), "myfile.ctb")}
            response = self.client.post("/api/upload_file", data=data)
        expect(response.status_code).to_equal(507)
        expect(response.get_json()["code"]).to_equal("upload_not_stored")

    def test_the_site_is_checked_before_anything_of_the_request_is_read(self) -> None:
        # Before the check of the token a form carries, which reads the
        # whole form, file included.
        application = self.client.application
        first = application.before_request_funcs[None][0]
        expect(first.__name__).to_equal("refuse_other_sites")
        with patch.dict(application.config, {"WTF_CSRF_ENABLED": True}):
            response = self.client.post(
                "/api/delete_file?filename=foobar.ctb",
                headers={"Origin": "http://evil.example"},
            )
        expect(response.status_code).to_equal(403)
        expect(response.get_json()["code"]).to_equal("cross_site_request")

    def test_a_browser_under_a_name_not_allowed_is_told_what_to_do(self) -> None:
        # A page to read, not data, where a page was asked for.
        response = self.client.get(
            "/", headers={"Host": "pi.tailnet.ts.net", "Accept": "text/html"}
        )
        expect(response.status_code).to_equal(403)
        expect(response.mimetype).to_equal("text/html")
        expect(response.headers["Cache-Control"]).to_equal("no-store")
        page = response.get_data(as_text=True)
        expect("allowed_hosts" in page).to_equal(True)
        expect("pi.tailnet.ts.net" in page).to_equal(True)
        # The name is the client's text.
        response = self.client.get(
            "/", headers={"Host": "<script>x</script>.example", "Accept": "text/html"}
        )
        page = response.get_data(as_text=True)
        expect("<script>" in page).to_equal(False)
        expect("&lt;script&gt;" in page).to_equal(True)
        # A name with an underscore, which not every library takes for one.
        response = self.client.get(
            "/", headers={"Host": "my_printer.example.org:5000", "Accept": "text/html"}
        )
        expect(
            'allowed_hosts = ["my_printer.example.org"]'
            in response.get_data(as_text=True)
        ).to_equal(True)
        # What a program asks for stays data.
        response = self.client.get(
            "/api/list_files", headers={"Host": "x.example", "Accept": "text/html"}
        )
        expect(response.mimetype).to_equal("application/json")

    def _page_with_its_token(self) -> str:
        """Ask for the page as a browser does; the token it carries."""
        from flask_wtf.csrf import generate_csrf

        with patch(
            "mariner.server.render_template",
            side_effect=lambda *a, **k: generate_csrf(),
        ):
            self.page_response = self.client.get("/")
        return self.page_response.get_data(as_text=True)

    def test_the_cookie_comes_along_when_a_link_to_mariner_is_followed(self) -> None:
        # Kept from requests another site has the browser send, but not
        # from a link followed from one: without it the page would be
        # given a new token, and every tab already open would hold an old
        # one that is refused.
        self._page_with_its_token()
        cookie = self.page_response.headers["Set-Cookie"]
        expect("SameSite=Lax" in cookie).to_equal(True)
        expect("HttpOnly" in cookie).to_equal(True)

    def test_a_page_left_open_can_still_stop_a_print_hours_later(self) -> None:
        import time

        application = self.client.application
        with patch.dict(application.config, {"WTF_CSRF_ENABLED": True}):
            token = self._page_with_its_token()
            for hours in (30, 20 * 24):
                later = time.time() + hours * 3600
                with patch("time.time", return_value=later):
                    response = self.client.post(
                        f"/api/create_directory?path=.&name=after-{hours}",
                        headers={"X-CSRFToken": token},
                    )
                expect(response.status_code).to_equal(200)
            # Without the token it is refused as before, in words the
            # page can show: a token goes stale when Mariner restarts.
            response = self.client.post("/api/printer/command/cancel_print")
            expect(response.status_code).to_equal(400)
            body = response.get_json()
            expect(body["code"]).to_equal("token_refused")
            expect("Reload" in body["description"]).to_equal(True)
            # And for a script, which has no page to reload.
            expect("/api/csrf_token" in body["description"]).to_equal(True)

    def test_a_page_whose_token_went_stale_can_ask_for_a_new_one(self) -> None:
        # After Mariner restarted, say: the page then sends its request
        # again without the person having to reload it.
        application = self.client.application
        with patch.dict(application.config, {"WTF_CSRF_ENABLED": True}):
            stale = {"X-CSRFToken": "made by the Mariner that is gone"}
            response = self.client.post(
                "/api/create_directory?path=.&name=new", headers=stale
            )
            expect(response.get_json()["code"]).to_equal("token_refused")
            response = self.client.get("/api/csrf_token")
            expect(response.status_code).to_equal(200)
            expect(response.headers["Cache-Control"]).to_equal("no-store")
            fresh = {"X-CSRFToken": response.get_json()["csrf_token"]}
            response = self.client.post(
                "/api/create_directory?path=.&name=new", headers=fresh
            )
            expect(response.status_code).to_equal(200)
        # Not for a page of another site to ask for.
        response = self.client.get(
            "/api/csrf_token", headers={"Referer": "http://evil.example/"}
        )
        expect(response.status_code).to_equal(403)

    def test_a_refusal_is_written_to_the_log(self) -> None:
        from mariner.server import refusals

        refusals.said.clear()
        with self.assertLogs("mariner.server.refusals", level="WARNING") as logs:
            self.client.get("/uvtools/files", headers={"User-Agent": "Mozilla/5.0"})
        message = logs.records[0].getMessage()
        for told in ("browser_not_served", "GET", "/uvtools/files", "127.0.0.1"):
            expect(told in message).to_equal(True)

    def test_the_page_is_not_kept_by_browsers_or_proxies(self) -> None:
        # It carries the token its requests are checked against.
        with patch("mariner.server.render_template", return_value="the page"):
            for url in ("/", "/files"):
                response = self.client.get(url)
                expect(response.headers["Cache-Control"]).to_equal("no-store")

    def test_following_a_link_to_the_page_from_another_site_works(self) -> None:
        # Only what acts or tells is refused, not the page.
        with patch("mariner.server.render_template", return_value="the page"):
            response = self.client.get(
                "/files",
                headers={"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate"},
            )
        expect(response.status_code).to_equal(200)

    def test_requests_under_a_name_from_the_wider_web_are_refused(self) -> None:
        for url in ("/api/list_files", "/"):
            response = self.client.get(url, headers={"Host": "evil.example"})
            expect(response.status_code).to_equal(403)
            expect(response.get_json()["code"]).to_equal("host_not_allowed")

    def test_upload_file_larger_than_allowed(self) -> None:
        data = {"file": (io.BytesIO(b"x" * 5000), "big.ctb")}
        with patch.dict(self.client.application.config, {"MAX_CONTENT_LENGTH": 2000}):
            response = self.client.post("/api/upload_file", data=data)
        expect(response.status_code).to_equal(413)
        body = response.get_json()
        expect(body["code"]).to_equal("file_too_large")
        expect("2048 MB" in body["description"]).to_equal(True)
        expect(os.path.exists("/mnt/usb_share/big.ctb")).to_equal(False)
        expect(self._leftovers()).to_equal([])

    def test_the_web_server_is_told_the_upload_limit(self) -> None:
        # With room for what a form adds around the file.
        limit = self.client.application.config["MAX_CONTENT_LENGTH"]
        expect(limit).to_equal(config.get_max_upload_bytes() + 1024 * 1024)

    def _stored(self, *parts: str) -> bytes:
        with open(config.get_files_directory().joinpath(*parts), "rb") as file:
            return file.read()

    def _leftovers(self, directory: str = "/mnt/usb_share") -> list:
        return [name for name in os.listdir(directory) if name.endswith(".part")]

    @staticmethod
    def _save_half_then_fail(destination: str, *args: Any, **kwargs: Any) -> None:
        with open(destination, "wb") as file:
            file.write(b"abc")
        raise OSError("disk full")

    def test_upload_file(self) -> None:
        data = {"file": (io.BytesIO(b"abcdef"), "myfile.ctb")}
        response = self.client.post("/api/upload_file", data=data)
        expect(response.status_code).to_equal(200)
        expect(response.get_json()).to_equal({"success": True})
        expect(self._stored("myfile.ctb")).to_equal(b"abcdef")
        expect(self._leftovers()).to_equal([])

    def test_upload_file_with_upper_case_extension(self) -> None:
        data = {"file": (io.BytesIO(b"abcdef"), "myfile.CtB")}
        response = self.client.post("/api/upload_file", data=data)
        expect(response.status_code).to_equal(200)
        expect(self._stored("myfile.CtB")).to_equal(b"abcdef")

    def test_upload_file_keeps_the_name_it_was_given(self) -> None:
        # Rewriting names loses the extension of a non-ASCII name entirely
        # and leaves the user looking for a file that is stored as something
        # else.
        for name in ("ma pièce (v2).ctb", "模型.ctb"):
            data = {"file": (io.BytesIO(b"abcdef"), name)}
            response = self.client.post("/api/upload_file", data=data)
            expect(response.status_code).to_equal(200)
            expect(self._stored(name)).to_equal(b"abcdef")

    def test_upload_file_with_unsafe_filename(self) -> None:
        for name in ("../../../etc/passwd.ctb", "john's model.ctb", "a\rb.ctb"):
            data = {"file": (io.BytesIO(b"abcdef"), name)}
            response = self.client.post("/api/upload_file", data=data)
            expect(response.status_code).to_equal(400)
        expect(os.path.exists("/etc/passwd.ctb")).to_equal(False)

    def test_upload_file_replaces_an_existing_file(self) -> None:
        data = {"file": (io.BytesIO(b"new contents"), "foobar.ctb")}
        response = self.client.post("/api/upload_file", data=data)
        expect(response.status_code).to_equal(200)
        expect(self._stored("foobar.ctb")).to_equal(b"new contents")
        expect(self._leftovers()).to_equal([])

    def test_upload_file_that_fails_leaves_nothing_behind(self) -> None:
        data = {"file": (io.BytesIO(b"abcdef"), "myfile.ctb")}
        # The failure comes after some bytes were written, so the test fails
        # if the half-written scratch file is not removed.
        with patch.object(
            FileStorage, "save", side_effect=self._save_half_then_fail
        ), self.assertLogs("mariner.server.api", level="WARNING") as logs:
            response = self.client.post("/api/upload_file", data=data)
        # Said in words the page can show: the usual cause is a full drive.
        expect(response.status_code).to_equal(500)
        body = response.get_json()
        expect(body["code"]).to_equal("upload_not_stored")
        expect("myfile.ctb" in body["description"]).to_equal(True)
        expect("disk full" in response.get_data(as_text=True)).to_equal(False)
        expect(len(logs.records)).to_equal(1)
        expect(os.path.exists("/mnt/usb_share/myfile.ctb")).to_equal(False)
        expect(self._leftovers()).to_equal([])

    def _printer_is_printing(self, selected_file: str) -> None:
        printer_access.forget_everything()
        self.printer_mock.get_print_status.return_value = PrintStatus(
            state=PrinterState.PRINTING, current_byte=5000, total_bytes=10000
        )
        self.printer_mock.get_selected_file.return_value = selected_file

    def test_upload_file_refuses_to_replace_the_file_being_printed(self) -> None:
        # The printer reads the file layer by layer for the whole print, so
        # swapping it underneath would ruin the print in progress.
        self._printer_is_printing("foobar.ctb")
        data = {"file": (io.BytesIO(b"new contents"), "foobar.ctb")}
        with patch.object(FileStorage, "save") as save_mock:
            response = self.client.post("/api/upload_file", data=data)
        expect(response.status_code).to_equal(409)
        body = response.get_json()
        expect(body["code"]).to_equal("file_in_use")
        expect(body["title"]).to_equal("File In Use")
        expect(body["description"]).to_equal(
            "foobar.ctb is in use by the print in progress. Wait for the print "
            "to finish or cancel it first, or store the file under another name."
        )
        # Refused before anything was written.
        save_mock.assert_not_called()
        expect(self._stored("foobar.ctb")).to_equal(self.ctb_file_contents)
        expect(self._leftovers()).to_equal([])

    def test_upload_file_with_another_name_while_printing(self) -> None:
        self._printer_is_printing("foobar.ctb")
        data = {"file": (io.BytesIO(b"abcdef"), "other.ctb")}
        response = self.client.post("/api/upload_file", data=data)
        expect(response.status_code).to_equal(200)
        expect(self._stored("other.ctb")).to_equal(b"abcdef")

    def test_upload_file_replaces_a_file_that_is_selected_but_not_printing(
        self,
    ) -> None:
        self.printer_mock.get_print_status.return_value = PrintStatus(
            state=PrinterState.IDLE, counters_seen=True
        )
        self.printer_mock.get_selected_file.return_value = "foobar.ctb"
        data = {"file": (io.BytesIO(b"new contents"), "foobar.ctb")}
        response = self.client.post("/api/upload_file", data=data)
        expect(response.status_code).to_equal(200)
        expect(self._stored("foobar.ctb")).to_equal(b"new contents")

    def test_upload_file_refuses_when_a_print_starts_while_it_is_written(self) -> None:
        # The first check passes, then a print starts while the file is being
        # written to disk. The check made as the file is moved into place
        # must still catch it.
        self.printer_mock.get_print_status.return_value = PrintStatus(
            state=PrinterState.IDLE, counters_seen=True
        )
        self.printer_mock.get_selected_file.return_value = "foobar.ctb"
        real_save = FileStorage.save

        def save_while_a_print_starts(
            storage: FileStorage, destination: str, *args: Any, **kwargs: Any
        ) -> None:
            real_save(storage, destination, *args, **kwargs)
            # Started from the printer's own screen, and noticed: the
            # remembered status is dropped as it would be once it expired.
            self._printer_is_printing("foobar.ctb")

        data = {"file": (io.BytesIO(b"new contents"), "foobar.ctb")}
        with patch.object(
            FileStorage, "save", autospec=True, side_effect=save_while_a_print_starts
        ):
            response = self.client.post("/api/upload_file", data=data)

        expect(response.status_code).to_equal(409)
        expect(self._stored("foobar.ctb")).to_equal(self.ctb_file_contents)
        expect(self._leftovers()).to_equal([])

    def _printer_is_silent(self) -> None:
        printer_access.forget_everything()
        self.printer_mock.get_print_status.return_value = PrintStatus(
            state=PrinterState.CLOSED, silent=True
        )

    def test_upload_file_does_not_replace_a_file_when_the_printer_is_silent(
        self,
    ) -> None:
        # With no answer there is no telling whether the file is being
        # printed, so it is left alone and the client is told why.
        self._printer_is_silent()
        data = {"file": (io.BytesIO(b"new contents"), "foobar.ctb")}
        response = self.client.post("/api/upload_file", data=data)
        expect(response.status_code).to_equal(409)
        expect(response.get_json()["code"]).to_equal("printer_not_answering")
        expect(self._stored("foobar.ctb")).to_equal(self.ctb_file_contents)
        expect(self._leftovers()).to_equal([])

    def test_upload_file_under_a_new_name_works_when_the_printer_is_silent(
        self,
    ) -> None:
        self._printer_is_silent()
        data = {"file": (io.BytesIO(b"abcdef"), "other.ctb")}
        response = self.client.post("/api/upload_file", data=data)
        expect(response.status_code).to_equal(200)
        expect(self._stored("other.ctb")).to_equal(b"abcdef")
        # A new file cannot be in use, so the printer is not even asked.
        self.printer_mock.get_print_status.assert_not_called()

    def test_upload_file_goes_through_once_the_printer_answers_again(self) -> None:
        self._printer_is_silent()
        data = {"file": (io.BytesIO(b"new contents"), "foobar.ctb")}
        expect(self.client.post("/api/upload_file", data=data).status_code).to_equal(
            409
        )

        # Reading the status asks the printer anew, which is what a client
        # does to retry.
        self.printer_mock.get_print_status.return_value = PrintStatus(
            state=PrinterState.IDLE, counters_seen=True
        )
        self.printer_mock.get_selected_file.return_value = ""
        expect(self.client.get("/api/print_status").get_json()["state"]).to_equal(
            "IDLE"
        )
        data = {"file": (io.BytesIO(b"new contents"), "foobar.ctb")}
        expect(self.client.post("/api/upload_file", data=data).status_code).to_equal(
            200
        )
        expect(self._stored("foobar.ctb")).to_equal(b"new contents")

    def test_upload_file_does_not_replace_a_file_when_the_printing_file_is_unknown(
        self,
    ) -> None:
        self.fs.create_file("/mnt/usb_share/other.ctb", contents=b"old")
        self._printer_is_printing("foobar.ctb")
        self.printer_mock.get_selected_file.side_effect = UnexpectedPrinterResponse(
            "ok\r\n"
        )
        data = {"file": (io.BytesIO(b"abcdef"), "other.ctb")}
        with patch("mariner.server.utils.time.sleep"):
            response = self.client.post("/api/upload_file", data=data)
        expect(response.status_code).to_equal(409)
        body = response.get_json()
        # Not "printer not answering": it answered, and it is printing.
        expect(body["code"]).to_equal("print_file_unknown")
        expect(body["title"]).to_equal("Print In Progress")
        expect(self._stored("other.ctb")).to_equal(b"old")

    def test_a_silent_printer_can_be_overridden_when_the_user_says_it_is_off(
        self,
    ) -> None:
        self._printer_is_silent()
        refused = self.client.post("/api/delete_file?filename=foobar.ctb")
        expect(refused.get_json()["can_be_overridden"]).to_equal(True)

        response = self.client.post(
            "/api/delete_file?filename=foobar.ctb&ignore_unreachable_printer=1"
        )
        expect(response.status_code).to_equal(200)
        expect(os.path.exists("/mnt/usb_share/foobar.ctb")).to_equal(False)

    def test_a_refusal_known_beforehand_writes_nothing(self) -> None:
        # Without the user's word, a silent printer is reason enough.
        self._printer_is_silent()
        with patch.object(FileStorage, "save") as save:
            data = {"file": (io.BytesIO(b"new contents"), "foobar.ctb")}
            response = self.client.post("/api/upload_file", data=data)
        expect(response.status_code).to_equal(409)
        save.assert_not_called()

        # With it, anything but silence still is.
        self._printer_is_printing("foobar.ctb")
        with patch.object(FileStorage, "save") as save:
            data = {"file": (io.BytesIO(b"new contents"), "foobar.ctb")}
            response = self.client.post(
                "/api/upload_file?ignore_unreachable_printer=1", data=data
            )
        expect(response.status_code).to_equal(409)
        save.assert_not_called()

    def test_an_overriding_upload_asks_the_silent_printer_only_once(self) -> None:
        # Giving up on a silent printer takes seconds each time. The first
        # request is the one that was refused and led the user to confirm.
        self._printer_is_silent()
        data = {"file": (io.BytesIO(b"new contents"), "foobar.ctb")}
        expect(self.client.post("/api/upload_file", data=data).status_code).to_equal(
            409
        )
        self.printer_mock.get_print_status.reset_mock()

        data = {"file": (io.BytesIO(b"new contents"), "foobar.ctb")}
        response = self.client.post(
            "/api/upload_file?ignore_unreachable_printer=1", data=data
        )
        expect(response.status_code).to_equal(200)
        expect(self.printer_mock.get_print_status.call_count).to_equal(1)

    def test_upload_file_cannot_reach_a_transfer_under_another_name(self) -> None:
        # Stands for the short alias FAT gives the same entry.
        self.fs.create_file(
            "/mnt/usb_share/.upload-0123456789abcdef.part", contents=b"half"
        )
        self.fs.create_link(
            "/mnt/usb_share/.upload-0123456789abcdef.part", "/mnt/usb_share/alias.ctb"
        )
        data = {"file": (io.BytesIO(b"new contents"), "alias.ctb")}
        response = self.client.post("/api/upload_file", data=data)
        expect(response.status_code).to_equal(400)
        with open("/mnt/usb_share/.upload-0123456789abcdef.part", "rb") as file:
            expect(file.read()).to_equal(b"half")

    def test_only_the_exact_value_asks_for_the_override(self) -> None:
        self._printer_is_silent()
        for value in ("0", "true", "", "11"):
            response = self.client.post(
                f"/api/delete_file?filename=foobar.ctb"
                f"&ignore_unreachable_printer={value}"
            )
            expect(response.status_code).to_equal(409)
        expect(os.path.exists("/mnt/usb_share/foobar.ctb")).to_equal(True)

    def test_delete_file_cannot_reach_a_transfer_that_began_meanwhile(self) -> None:
        # Stands for the short alias FAT gives a scratch file, asked for
        # just before the transfer creates it.
        self.fs.create_file("/mnt/usb_share/UPLOAD~1.PAR", contents=b"half")
        with patch("mariner.server.api.remove_entry") as remove:
            remove.side_effect = FileNotFoundError("hidden by now")
            response = self.client.post("/api/delete_file?filename=UPLOAD~1.PAR")
        expect(response.status_code).to_equal(404)
        remove.assert_called_once_with(pathlib.Path("/mnt/usb_share/UPLOAD~1.PAR"))

    def test_upload_file_trims_the_name_before_looking_at_its_extension(
        self,
    ) -> None:
        # As UVtools and slicers have it: "model.ctb " is model.ctb.
        data = {"file": (io.BytesIO(self.ctb_file_contents), "trimmed.ctb ")}
        response = self.client.post("/api/upload_file", data=data)
        expect(response.status_code).to_equal(200)
        expect(self._stored("trimmed.ctb")).to_equal(self.ctb_file_contents)

    def test_upload_onto_a_link_replaces_the_link_and_not_its_target(self) -> None:
        self.fs.create_file("/mnt/usb_share/sub/notes.txt", contents=b"notes")
        self.fs.create_symlink(
            "/mnt/usb_share/linked.ctb", "/mnt/usb_share/sub/notes.txt"
        )
        data = {"file": (io.BytesIO(b"new contents"), "linked.ctb")}
        response = self.client.post("/api/upload_file", data=data)
        expect(response.status_code).to_equal(200)
        expect(self._stored("sub/notes.txt")).to_equal(b"notes")
        expect(os.path.islink("/mnt/usb_share/linked.ctb")).to_equal(False)
        expect(self._stored("linked.ctb")).to_equal(b"new contents")

    def test_an_upload_can_override_a_silent_printer_too(self) -> None:
        self._printer_is_silent()
        data = {"file": (io.BytesIO(b"new contents"), "foobar.ctb")}
        response = self.client.post(
            "/api/upload_file?ignore_unreachable_printer=1", data=data
        )
        expect(response.status_code).to_equal(200)
        expect(self._stored("foobar.ctb")).to_equal(b"new contents")

    def test_an_override_does_not_go_through_if_the_printer_now_answers(
        self,
    ) -> None:
        # Refused because the printer was silent. Before the user confirms,
        # the printer comes back, printing that very file.
        self._printer_is_silent()
        expect(
            self.client.post("/api/delete_file?filename=foobar.ctb").status_code
        ).to_equal(409)
        self.printer_mock.get_print_status.return_value = PrintStatus(
            state=PrinterState.PRINTING,
            current_byte=5000,
            total_bytes=10000,
            counters_seen=True,
        )
        self.printer_mock.get_selected_file.return_value = "foobar.ctb"

        response = self.client.post(
            "/api/delete_file?filename=foobar.ctb&ignore_unreachable_printer=1"
        )
        expect(response.status_code).to_equal(409)
        expect(response.get_json()["code"]).to_equal("file_in_use")
        expect(os.path.exists("/mnt/usb_share/foobar.ctb")).to_equal(True)

    def test_a_print_in_progress_cannot_be_overridden(self) -> None:
        self._printer_is_printing("foobar.ctb")
        response = self.client.post(
            "/api/delete_file?filename=foobar.ctb&ignore_unreachable_printer=1"
        )
        expect(response.status_code).to_equal(409)
        expect(response.get_json()["can_be_overridden"]).to_equal(False)
        expect(os.path.exists("/mnt/usb_share/foobar.ctb")).to_equal(True)

        data = {"file": (io.BytesIO(b"new contents"), "foobar.ctb")}
        response = self.client.post(
            "/api/upload_file?ignore_unreachable_printer=1", data=data
        )
        expect(response.status_code).to_equal(409)
        expect(self._stored("foobar.ctb")).to_equal(self.ctb_file_contents)

    def test_a_file_is_in_use_from_the_moment_its_print_is_started(self) -> None:
        # For a moment after being told to print, the printer still says it
        # is idle. The file must be protected during that moment too.
        response = self.client.post(
            "/api/printer/command/start_print?filename=foobar.ctb"
        )
        expect(response.status_code).to_equal(200)

        response = self.client.post("/api/delete_file?filename=foobar.ctb")
        expect(response.status_code).to_equal(409)
        body = response.get_json()
        expect(body["code"]).to_equal("print_just_started")
        expect(body["title"]).to_equal("Print Just Started")
        expect(body["description"]).to_equal(
            "foobar.ctb is in use by a print that was started a moment ago. It "
            "stays protected for half a minute, even if that print was "
            "cancelled. Try again then."
        )
        expect(body["can_be_overridden"]).to_equal(False)
        expect(os.path.exists("/mnt/usb_share/foobar.ctb")).to_equal(True)

        data = {"file": (io.BytesIO(b"new contents"), "foobar.ctb")}
        expect(self.client.post("/api/upload_file", data=data).status_code).to_equal(
            409
        )
        expect(self._stored("foobar.ctb")).to_equal(self.ctb_file_contents)

    def test_a_start_whose_answer_was_lost_still_protects_the_file(self) -> None:
        self.printer_mock.start_printing.side_effect = UnexpectedPrinterResponse("\r\n")
        response = self.client.post(
            "/api/printer/command/start_print?filename=foobar.ctb"
        )
        expect(response.status_code).to_equal(500)
        response = self.client.post("/api/delete_file?filename=foobar.ctb")
        expect(response.status_code).to_equal(409)
        expect(os.path.exists("/mnt/usb_share/foobar.ctb")).to_equal(True)

    def test_upload_file_onto_the_name_of_a_folder(self) -> None:
        self.fs.create_dir("/mnt/usb_share/batch.ctb")
        data = {"file": (io.BytesIO(b"abcdef"), "batch.ctb")}
        response = self.client.post("/api/upload_file", data=data)
        expect(response.status_code).to_equal(400)
        expect(os.path.isdir("/mnt/usb_share/batch.ctb")).to_equal(True)
        expect(self._leftovers()).to_equal([])

    def _printer_answers_only_ok(self) -> None:
        printer_access.forget_everything()
        self.printer_mock.get_print_status.return_value = PrintStatus(
            state=PrinterState.IDLE
        )

    def test_an_unclear_answer_from_the_printer_has_its_own_explanation(
        self,
    ) -> None:
        self._printer_answers_only_ok()
        response = self.client.post("/api/delete_file?filename=foobar.ctb")
        expect(response.status_code).to_equal(409)
        body = response.get_json()
        expect(body["code"]).to_equal("printer_answer_unclear")
        expect(body["title"]).to_equal("Printer Answer Unclear")
        expect(body["description"]).to_equal(
            "Mariner could not get a clear answer from the printer, so there "
            "is no telling whether foobar.ctb is being printed, and it was "
            "left untouched. Try again in a moment."
        )
        expect(body["can_be_overridden"]).to_equal(False)

    def test_a_serial_port_that_could_not_be_used_cannot_be_overridden(self) -> None:
        # Mariner's own trouble (no permission, too many open files): the
        # printer was never asked, so it cannot be taken to be off.
        printer_access.forget_everything()
        self.printer_mock.get_print_status.return_value = PrintStatus(
            state=PrinterState.CLOSED
        )
        response = self.client.post(
            "/api/delete_file?filename=foobar.ctb&ignore_unreachable_printer=1"
        )
        expect(response.status_code).to_equal(409)
        body = response.get_json()
        expect(body["code"]).to_equal("printer_answer_unclear")
        expect(body["can_be_overridden"]).to_equal(False)
        expect(os.path.exists("/mnt/usb_share/foobar.ctb")).to_equal(True)

    def test_an_unclear_answer_from_the_printer_cannot_be_overridden(self) -> None:
        self._printer_answers_only_ok()
        response = self.client.post(
            "/api/delete_file?filename=foobar.ctb&ignore_unreachable_printer=1"
        )
        expect(response.status_code).to_equal(409)
        expect(response.get_json()["code"]).to_equal("printer_answer_unclear")
        expect(os.path.exists("/mnt/usb_share/foobar.ctb")).to_equal(True)

        data = {"file": (io.BytesIO(b"new contents"), "foobar.ctb")}
        response = self.client.post(
            "/api/upload_file?ignore_unreachable_printer=1", data=data
        )
        expect(response.status_code).to_equal(409)
        expect(self._stored("foobar.ctb")).to_equal(self.ctb_file_contents)

    def test_delete_file_that_someone_else_just_removed(self) -> None:
        with patch(
            "mariner.server.api.os.remove", side_effect=FileNotFoundError("gone")
        ):
            response = self.client.post("/api/delete_file?filename=foobar.ctb")
        expect(response.status_code).to_equal(404)

    def test_upload_file_into_a_folder_that_was_just_removed(self) -> None:
        self.fs.create_dir("/mnt/usb_share/batch")
        data = {"file": (io.BytesIO(b"contents"), "new.ctb")}
        with patch.object(
            FileStorage, "save", side_effect=FileNotFoundError("folder gone")
        ):
            response = self.client.post("/api/upload_file?path=batch", data=data)
        expect(response.status_code).to_equal(404)
        expect(self._leftovers()).to_equal([])

    def test_delete_file_is_refused_when_the_printer_is_silent(self) -> None:
        self._printer_is_silent()
        response = self.client.post("/api/delete_file?filename=foobar.ctb")
        expect(response.status_code).to_equal(409)
        body = response.get_json()
        expect(body["code"]).to_equal("printer_not_answering")
        expect(body["description"]).to_equal(
            "The printer did not answer, so there is no telling whether "
            "foobar.ctb is being printed, and it was left untouched. Check that "
            "the printer is on and connected, then try again."
        )
        expect(os.path.exists("/mnt/usb_share/foobar.ctb")).to_equal(True)

    def test_delete_file_refuses_the_file_being_printed(self) -> None:
        self._printer_is_printing("foobar.ctb")
        response = self.client.post("/api/delete_file?filename=foobar.ctb")
        expect(response.status_code).to_equal(409)
        body = response.get_json()
        expect(body["code"]).to_equal("file_in_use")
        # No advice about storing under another name: nothing is being stored.
        expect(body["description"]).to_equal(
            "foobar.ctb is in use by the print in progress. Wait for the print "
            "to finish or cancel it first."
        )
        expect(os.path.exists("/mnt/usb_share/foobar.ctb")).to_equal(True)

    def test_print_status_forgets_its_layer_estimate_when_the_printer_goes_silent(
        self,
    ) -> None:
        self.printer_mock.get_print_status.return_value = PrintStatus(
            state=PrinterState.CLOSED, silent=True
        )
        with patch("mariner.server.api.reset_progress_tracking") as reset_mock:
            response = self.client.get("/api/print_status")
        expect(response.get_json()["state"]).to_equal("CLOSED")
        reset_mock.assert_called_once_with()

    def test_print_status_when_the_file_being_printed_is_not_here(self) -> None:
        # Started from the printer's own screen, from a file Mariner cannot
        # see. The dashboard must keep working, without layer details.
        self._printer_is_printing("elsewhere.ctb")
        response = self.client.get("/api/print_status")
        expect(response.status_code).to_equal(200)
        expect(response.get_json()).to_equal(
            {"state": "PRINTING", "selected_file": "elsewhere.ctb", "progress": 50.0}
        )

    def test_print_status_when_the_file_being_printed_cannot_be_parsed(self) -> None:
        self.fs.create_file("/mnt/usb_share/corrupt.ctb", contents=b"not a ctb")
        self._printer_is_printing("corrupt.ctb")
        response = self.client.get("/api/print_status")
        expect(response.status_code).to_equal(200)
        expect(response.get_json()["state"]).to_equal("PRINTING")
        expect(response.get_json()["progress"]).to_equal(50.0)

    def test_upload_file_to_subdirectory(self) -> None:
        self.fs.create_dir("/mnt/usb_share/uploads/")
        data = {"file": (io.BytesIO(b"abcdef"), "myfile.ctb")}
        response = self.client.post("/api/upload_file?path=uploads", data=data)
        expect(response.status_code).to_equal(200)
        expect(self._stored("uploads", "myfile.ctb")).to_equal(b"abcdef")

    def test_upload_file_with_invalid_parent_path(self) -> None:
        data = {"file": (io.BytesIO(b"abcdef"), "myfile.ctb")}
        response = self.client.post("/api/upload_file?path=../../etc", data=data)
        expect(response.status_code).to_equal(400)

    def test_upload_file_to_missing_directory(self) -> None:
        data = {"file": (io.BytesIO(b"abcdef"), "myfile.ctb")}
        response = self.client.post("/api/upload_file?path=no_such_dir", data=data)
        expect(response.status_code).to_equal(400)

    def test_delete_file(self) -> None:
        expect(os.path.exists(config.get_files_directory() / "mariner.ctb")).to_equal(
            False
        )
        self.fs.create_file(
            "/mnt/usb_share/mariner.ctb", contents=self.ctb_file_contents
        )
        expect(os.path.exists(config.get_files_directory() / "mariner.ctb")).to_equal(
            True
        )

        response = self.client.post("/api/delete_file?filename=mariner.ctb")
        expect(response.status_code).to_equal(200)
        expect(response.get_json()).to_equal({"success": True})
        expect(os.path.exists(config.get_files_directory() / "mariner.ctb")).to_equal(
            False
        )

    def test_delete_file_removes_a_link_and_leaves_its_target(self) -> None:
        self.fs.create_symlink("/mnt/usb_share/link.ctb", "/mnt/usb_share/foobar.ctb")
        response = self.client.post("/api/delete_file?filename=link.ctb")
        expect(response.status_code).to_equal(200)
        expect(os.path.lexists("/mnt/usb_share/link.ctb")).to_equal(False)
        expect(os.path.exists("/mnt/usb_share/foobar.ctb")).to_equal(True)

    def test_delete_file_removes_a_link_whose_target_is_gone(self) -> None:
        # The listing shows it, so it must be possible to get rid of it.
        self.fs.create_symlink("/mnt/usb_share/dangling.ctb", "/mnt/usb_share/gone")
        response = self.client.post("/api/delete_file?filename=dangling.ctb")
        expect(response.status_code).to_equal(200)
        expect(os.path.lexists("/mnt/usb_share/dangling.ctb")).to_equal(False)

    def test_transfers_in_progress_are_out_of_reach_of_every_route(self) -> None:
        self.fs.create_file("/mnt/usb_share/.sdcp_uploads/abcd.part", contents=b"x")
        self.fs.create_file("/mnt/usb_share/.upload-0123abcd.part", contents=b"x")

        expect(
            self.client.get("/api/list_files?path=.sdcp_uploads").status_code
        ).to_equal(400)
        for hidden in (".sdcp_uploads/abcd.part", ".upload-0123abcd.part"):
            response = self.client.post(f"/api/delete_file?filename={hidden}")
            expect(response.status_code).to_equal(400)
            expect(
                self.client.get(f"/api/file_details?filename={hidden}").status_code
            ).to_equal(400)
        data = {"file": (io.BytesIO(b"abcdef"), "myfile.ctb")}
        expect(
            self.client.post(
                "/api/upload_file?path=.sdcp_uploads", data=data
            ).status_code
        ).to_equal(400)
        expect(
            self.client.post(
                "/api/create_directory?path=.sdcp_uploads&name=d"
            ).status_code
        ).to_equal(400)

        expect(os.listdir("/mnt/usb_share/.sdcp_uploads")).to_equal(["abcd.part"])
        expect(os.path.exists("/mnt/usb_share/.upload-0123abcd.part")).to_equal(True)

    def test_delete_file_that_is_not_file(self) -> None:
        self.fs.create_dir("/mnt/usb_share/mariner")
        with patch("os.remove") as remove_mock:
            response = self.client.post("/api/delete_file?filename=mariner")
        remove_mock.assert_not_called()
        expect(response.status_code).to_equal(400)

    def test_delete_file_with_invalid_path(self) -> None:
        response = self.client.post("/api/delete_file?filename=../../etc/passwd")
        expect(response.status_code).to_equal(400)

    def test_create_directory(self) -> None:
        response = self.client.post("/api/create_directory?path=.&name=my_project")
        expect(response.status_code).to_equal(200)
        expect(response.get_json()).to_equal({"success": True})
        expect(os.path.isdir(config.get_files_directory() / "my_project")).to_equal(
            True
        )

    def test_refusals_of_a_file_say_why(self) -> None:
        # In words the page can show, with a code it can translate: a bare
        # refusal reads "error 400" to whoever sent the file.
        import io

        def upload(name: str) -> Any:
            return self.client.post(
                "/api/upload_file",
                data={"file": (io.BytesIO(b"x"), name)},
                content_type="multipart/form-data",
            )

        for name, code in (
            ("bob's model.ctb", "name_not_allowed"),
            ("what?.ctb", "name_not_allowed"),
            ("notes.txt", "type_not_supported"),
            ("model", "type_not_supported"),
        ):
            response = upload(name)
            expect(response.status_code).to_equal(400)
            body = response.get_json()
            expect(body["code"]).to_equal(code)
            expect(len(body["description"]) > 20).to_equal(True)
        # The kinds that are taken are named.
        expect(".ctb" in upload("notes.txt").get_json()["description"]).to_equal(True)
        # The apostrophe, which is what most often gets a name refused.
        description = upload("bob's model.ctb").get_json()["description"]
        expect("apostrophe" in description).to_equal(True)

    def test_a_file_that_is_gone_is_said_to_be(self) -> None:
        # Removed from another tab, or through the slicer, since the list
        # was shown.
        response = self.client.post("/api/delete_file?filename=gone.ctb")
        expect(response.status_code).to_equal(404)
        expect(response.get_json()["code"]).to_equal("file_gone")
        response = self.client.post(
            "/api/printer/command/start_print?filename=gone.ctb"
        )
        expect(response.status_code).to_equal(404)
        expect(response.get_json()["code"]).to_equal("file_gone")
        self.printer_mock.start_printing.assert_not_called()

    def test_a_file_that_cannot_be_printed_is_said_to_be(self) -> None:
        self.fs.create_file("/mnt/usb_share/notes.txt", contents="x")
        response = self.client.post(
            "/api/printer/command/start_print?filename=notes.txt"
        )
        expect(response.status_code).to_equal(400)
        expect(response.get_json()["code"]).to_equal("type_not_supported")
        self.printer_mock.start_printing.assert_not_called()

    def test_create_directory_says_why_it_could_not(self) -> None:
        # In words the page can show, with a code it can translate.
        self.fs.create_dir("/mnt/usb_share/there")
        self.fs.create_file("/mnt/usb_share/taken.ctb")
        for name, code in (
            ("there", "folder_exists"),
            ("taken.ctb", "folder_exists"),
            ("..", "name_not_allowed"),
            ("a/b", "name_not_allowed"),
            ("", "name_not_allowed"),
            ("x" * 300, "name_not_allowed"),
        ):
            response = self.client.post(f"/api/create_directory?path=.&name={name}")
            expect(response.status_code).to_equal(400)
            body = response.get_json()
            expect(body["code"]).to_equal(code)
            expect(len(body["description"]) > 10).to_equal(True)
            if code == "name_not_allowed":
                # Whichever of its faults the name has is among those said.
                expect("255" in body["description"]).to_equal(True)
        with patch("os.mkdir", side_effect=OSError(36, "File name too long")):
            response = self.client.post("/api/create_directory?path=.&name=new")
        expect(response.status_code).to_equal(400)
        expect(response.get_json()["code"]).to_equal("folder_not_created")

    def test_create_directory_keeps_the_name_it_was_given(self) -> None:
        response = self.client.post(
            "/api/create_directory?path=.&name=mes%20pi%C3%A8ces"
        )
        expect(response.status_code).to_equal(200)
        expect(os.path.isdir(config.get_files_directory() / "mes pièces")).to_equal(
            True
        )

    def test_create_directory_with_unsafe_name(self) -> None:
        for name in (
            "..",
            "a%2Fb",
            "it%27s",
            "a%0Ab",
            "a%3Ab",
            "a%3F",
            # Reserved for transfers in progress, which listings hide.
            ".upload-0123456789abcdef.part",
            ".sdcp_uploads",
        ):
            response = self.client.post(f"/api/create_directory?path=.&name={name}")
            expect(response.status_code).to_equal(400)

    def test_create_directory_under_subdirectory(self) -> None:
        self.fs.create_dir("/mnt/usb_share/nested/")
        response = self.client.post("/api/create_directory?path=nested&name=sub")
        expect(response.status_code).to_equal(200)
        expect(os.path.isdir(config.get_files_directory() / "nested" / "sub")).to_equal(
            True
        )

    def test_create_directory_no_deeper_than_any_use_calls_for(self) -> None:
        # A chain of a thousand folders, made a request at a time, used to
        # keep Mariner from starting again.
        path = "."
        for level in range(1, 17):
            response = self.client.post(f"/api/create_directory?path={path}&name=d")
            expect(response.status_code).to_equal(200)
            path = "/".join(["d"] * level)
        response = self.client.post(f"/api/create_directory?path={path}&name=d")
        expect(response.status_code).to_equal(400)
        body = response.get_json()
        expect(body["code"]).to_equal("folder_too_deep")
        expect("16" in body["description"]).to_equal(True)
        expect(os.path.exists(f"/mnt/usb_share/{path}/d")).to_equal(False)

    def test_create_directory_duplicate(self) -> None:
        self.fs.create_dir("/mnt/usb_share/exists/")
        response = self.client.post("/api/create_directory?path=.&name=exists")
        expect(response.status_code).to_equal(400)

    def test_create_directory_invalid_parent_path(self) -> None:
        response = self.client.post("/api/create_directory?path=../etc&name=bad")
        expect(response.status_code).to_equal(400)

    def test_create_directory_missing_name(self) -> None:
        response = self.client.post("/api/create_directory?path=.")
        expect(response.status_code).to_equal(400)

    def test_get_index(self) -> None:
        with patch(
            "mariner.server.render_template", return_value=""
        ) as render_template_mock:
            response = self.client.get("/")
            render_template_mock.assert_called_with(
                "index.html",
                supported_extensions=ANY,
            )
        expect(response.status_code).to_equal(200)

    def test_get_spa_client_route_serves_index(self) -> None:
        with patch(
            "mariner.server.render_template", return_value=""
        ) as render_template_mock:
            response = self.client.get("/files")
            render_template_mock.assert_called_with(
                "index.html",
                supported_extensions=ANY,
            )
        expect(response.status_code).to_equal(200)
