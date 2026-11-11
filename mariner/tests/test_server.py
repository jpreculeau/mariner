import hashlib
import io
import os
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
from mariner.server.utils import read_cached_sliced_model_file


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
        printer_access.forget_status()
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
            side_effect=read_cached_sliced_model_file.__wrapped__,
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

    def test_command_cancel_print(self) -> None:
        response = self.client.post("/api/printer/command/cancel_print")
        expect(response.get_json()).to_equal({"success": True})
        self.printer_mock.stop_printing.assert_called_once_with()

    def test_error_handling_while_stopping_print(self) -> None:
        self.printer_mock.stop_printing.side_effect = UnexpectedPrinterResponse(
            "foobar\r\n"
        )
        response = self.client.post("/api/printer/command/cancel_print")
        expect(response.status_code).to_equal(500)
        expect(response.get_json()).to_equal(
            {
                "title": "Unexpected Printer Response",
                "description": "The printer returned an unexpected response: "
                + "'foobar\\r\\n'",
                "traceback": ANY,
            }
        )
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

    def test_upload_file_replaces_an_existing_file_in_one_step(self) -> None:
        data = {"file": (io.BytesIO(b"new contents"), "foobar.ctb")}
        response = self.client.post("/api/upload_file", data=data)
        expect(response.status_code).to_equal(200)
        expect(self._stored("foobar.ctb")).to_equal(b"new contents")
        expect(self._leftovers()).to_equal([])

    def test_upload_file_that_fails_leaves_nothing_behind(self) -> None:
        data = {"file": (io.BytesIO(b"abcdef"), "myfile.ctb")}
        # The failure comes after some bytes were written, so the test fails
        # if the half-written scratch file is not removed.
        with patch.object(FileStorage, "save", side_effect=self._save_half_then_fail):
            with self.assertRaises(OSError):
                self.client.post("/api/upload_file", data=data)
        expect(os.path.exists("/mnt/usb_share/myfile.ctb")).to_equal(False)
        expect(self._leftovers()).to_equal([])

    def _printer_is_printing(self, selected_file: str) -> None:
        printer_access.forget_status()
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
        printer_access.forget_status()
        self.printer_mock.get_print_status.return_value = PrintStatus(
            state=PrinterState.CLOSED
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
        expect(response.get_json()["code"]).to_equal("file_in_use")
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

    def test_delete_file_is_refused_when_the_printer_is_silent(self) -> None:
        self._printer_is_silent()
        response = self.client.post("/api/delete_file?filename=foobar.ctb")
        expect(response.status_code).to_equal(409)
        body = response.get_json()
        expect(body["code"]).to_equal("printer_not_answering")
        expect(body["description"]).to_equal(
            "The printer did not say whether foobar.ctb is being printed, so it "
            "was left untouched. Check that the printer is on and connected, "
            "then try again."
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
            state=PrinterState.CLOSED
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
