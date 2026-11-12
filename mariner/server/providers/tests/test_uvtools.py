import os
import pathlib
from typing import Any
from unittest.mock import Mock, patch

from flask.testing import FlaskClient
from pyfakefs.fake_filesystem import FakeFilesystem
from pyfakefs.fake_filesystem_unittest import TestCase
from pyexpect import expect

from mariner import config
from mariner.config import _get_config
from mariner.exceptions import UnexpectedPrinterResponse
from mariner.printer import ChiTuPrinter, PrinterState, PrintStatus
from mariner.server import printer_access
from mariner.server.app import app


class UVToolsProviderTest(TestCase):
    ctb_file_contents: bytes
    client: FlaskClient
    fs: FakeFilesystem
    printer_mock: Any
    printer_patcher: Any

    def setUp(self) -> None:
        path = (
            pathlib.Path(__file__).parent.parent.parent.parent.absolute()
            / "file_formats"
            / "tests"
            / "stairs.ctb"
        )
        with open(path, "rb") as f:
            self.ctb_file_contents = f.read()

        _get_config.cache_clear()
        self.setUpPyfakefs(
            additional_skip_names=["importlib.metadata"],
        )
        self.fs.create_file(
            "/mnt/usb_share/foobar.ctb", contents=self.ctb_file_contents
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

    def tearDown(self) -> None:
        self.printer_patcher.stop()

    # ---- Upload ----

    def test_upload_file_via_post(self) -> None:
        response = self.client.post(
            "/uvtools/upload/mymodel.ctb",
            data=self.ctb_file_contents,
            content_type="application/octet-stream",
        )
        expect(response.status_code).to_equal(200)
        expect(response.get_json()["success"]).to_equal(True)
        expect(os.path.isfile(config.get_files_directory() / "mymodel.ctb")).to_equal(
            True
        )

    def test_upload_file_via_put(self) -> None:
        response = self.client.put(
            "/uvtools/upload/mymodel.ctb",
            data=self.ctb_file_contents,
            content_type="application/octet-stream",
        )
        expect(response.status_code).to_equal(200)
        expect(response.get_json()["success"]).to_equal(True)

    def test_upload_file_rejects_unsupported_extension(self) -> None:
        response = self.client.post(
            "/uvtools/upload/image.jpg",
            data=b"fake",
            content_type="application/octet-stream",
        )
        expect(response.status_code).to_equal(400)

    def test_requests_from_another_site_are_refused(self) -> None:
        # These routes act on a plain GET, which any page can have a
        # browser send: an image address is enough.
        for url in ("/uvtools/delete/foobar.ctb", "/uvtools/print/foobar.ctb"):
            for headers in (
                {"Sec-Fetch-Site": "cross-site"},
                {"Origin": "http://evil.example"},
                {"Host": "evil.example"},
            ):
                response = self.client.get(url, headers=headers)
                expect(response.status_code).to_equal(403)
        expect(os.path.isfile(config.get_files_directory() / "foobar.ctb")).to_equal(
            True
        )
        self.printer_mock.start_printing.assert_not_called()

    def test_an_error_nobody_planned_for_is_answered_and_logged_safely(self) -> None:
        with patch(
            "mariner.server.providers.uvtools.start_print",
            side_effect=RuntimeError("secret detail"),
        ), self.assertLogs("mariner.server.app", level="ERROR") as logs:
            response = self.client.get("/uvtools/print/model%E2%80%A8FORGED.ctb")
        expect(response.status_code).to_equal(500)
        expect("secret" in response.get_data(as_text=True)).to_equal(False)
        expect(len(logs.records)).to_equal(1)
        expect("\u2028" in logs.records[0].getMessage()).to_equal(False)

    def test_a_browser_is_refused_whatever_it_says_of_the_site(self) -> None:
        # Over plain HTTP, which is how the printer is reached, a browser
        # says nothing of the site for a link followed or a picture
        # loaded: such a request looks like a slicer's but for the name
        # the browser gives itself, which a page cannot change. Mariner's
        # own page never asks for these addresses.
        browser = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/153.0"}
        for url in (
            "/uvtools/delete/foobar.ctb",
            "/uvtools/print/foobar.ctb",
            "/uvtools/stop",
            "/uvtools/pause",
            "/uvtools/resume",
            "/uvtools/files",
            "/uvtools/status",
        ):
            response = self.client.get(url, headers=browser)
            expect(response.status_code).to_equal(403)
            expect(response.get_json()["code"]).to_equal("browser_not_served")
        expect(os.path.isfile(config.get_files_directory() / "foobar.ctb")).to_equal(
            True
        )
        self.printer_mock.start_printing.assert_not_called()
        self.printer_mock.stop_printing.assert_not_called()

    def test_a_slicer_is_served(self) -> None:
        response = self.client.get("/uvtools/delete/foobar.ctb")
        expect(response.status_code).to_equal(200)

    def test_upload_file_larger_than_allowed(self) -> None:
        with patch.dict(self.client.application.config, {"MAX_CONTENT_LENGTH": 2000}):
            response = self.client.post(
                "/uvtools/upload/big.ctb",
                data=b"x" * 5000,
                content_type="application/octet-stream",
            )
        expect(response.status_code).to_equal(413)
        expect(response.get_json()["code"]).to_equal("file_too_large")
        names = os.listdir(config.get_files_directory())
        expect("big.ctb" in names).to_equal(False)
        expect([name for name in names if name.endswith(".part")]).to_equal([])

    def test_upload_file_is_written_as_it_arrives(self) -> None:
        # Not held whole in memory first: a file can be larger than what
        # the board has.
        payload = bytes(range(256)) * 4096 * 3
        written = []
        real_open = open

        def recording_open(
            path: Any, mode: str = "r", *args: Any, **kwargs: Any
        ) -> Any:
            file = real_open(path, mode, *args, **kwargs)
            if "w" in mode and str(path).endswith(".part"):
                real_write = file.write

                def write(data: bytes) -> int:
                    written.append(len(data))
                    return int(real_write(data))

                file.write = write  # type: ignore[method-assign]
            return file

        with patch("builtins.open", side_effect=recording_open):
            response = self.client.post(
                "/uvtools/upload/large.ctb",
                data=payload,
                content_type="application/octet-stream",
            )
        expect(response.status_code).to_equal(200)
        with open(config.get_files_directory() / "large.ctb", "rb") as file:
            expect(file.read() == payload).to_equal(True)
        expect(sum(written)).to_equal(len(payload))
        expect(max(written) <= 1024 * 1024).to_equal(True)
        expect(len(written) >= 3).to_equal(True)

    def test_upload_file_rejects_empty_body(self) -> None:
        response = self.client.post(
            "/uvtools/upload/mymodel.ctb",
            data=b"",
            content_type="application/octet-stream",
        )
        expect(response.status_code).to_equal(400)

    def test_upload_preserves_the_filename(self) -> None:
        # The name has to survive unchanged: UVTools asks to print and delete
        # under the name it uploaded, and a rewritten one would not be found.
        name = "bracket_6(1).stl_1_0.050_2.500.ctb"
        response = self.client.post(
            f"/uvtools/upload/{name}",
            data=self.ctb_file_contents,
            content_type="application/octet-stream",
        )
        expect(response.status_code).to_equal(200)
        expect(response.get_json()["filename"]).to_equal(name)
        expect(os.path.isfile(config.get_files_directory() / name)).to_equal(True)

    def test_uploaded_name_can_be_printed_and_deleted_verbatim(self) -> None:
        name = "bracket_6(1).stl_1_0.050_2.500.ctb"
        self.client.post(
            f"/uvtools/upload/{name}",
            data=self.ctb_file_contents,
            content_type="application/octet-stream",
        )

        expect(self.client.get(f"/uvtools/print/{name}").status_code).to_equal(200)
        self.printer_mock.start_printing.assert_called_once_with(name)

        # The file cannot be deleted while it prints; once the print is over
        # it goes by the same name too.
        expect(self.client.get(f"/uvtools/delete/{name}").status_code).to_equal(409)
        printer_access.forget_everything()
        expect(self.client.get(f"/uvtools/delete/{name}").status_code).to_equal(200)
        expect(os.path.isfile(config.get_files_directory() / name)).to_equal(False)

    def test_upload_rejects_a_backslash_in_the_filename(self) -> None:
        response = self.client.post(
            "/uvtools/upload/..\\..\\evil.ctb",
            data=b"fake-ctb-data",
            content_type="application/octet-stream",
        )
        expect(response.status_code).to_equal(400)
        expect(os.path.isfile(config.get_files_directory() / "evil.ctb")).to_equal(
            False
        )

    # ---- Print ----

    def test_print_file(self) -> None:
        response = self.client.get("/uvtools/print/foobar.ctb")
        expect(response.status_code).to_equal(200)
        expect(response.get_json()).to_equal({"success": True})
        self.printer_mock.start_printing.assert_called_once_with("foobar.ctb")

    def test_print_file_refuses_a_quote(self) -> None:
        self.fs.create_file("/mnt/usb_share/it's.ctb", contents=b"x")
        response = self.client.get("/uvtools/print/it%27s.ctb")
        expect(response.status_code).to_equal(400)
        self.printer_mock.start_printing.assert_not_called()

    def test_upload_replaces_an_existing_file(self) -> None:
        response = self.client.post(
            "/uvtools/upload/foobar.ctb",
            data=b"new contents",
            content_type="application/octet-stream",
        )
        expect(response.status_code).to_equal(200)
        with open(config.get_files_directory() / "foobar.ctb", "rb") as file:
            expect(file.read()).to_equal(b"new contents")
        leftovers = [n for n in os.listdir("/mnt/usb_share") if n.endswith(".part")]
        expect(leftovers).to_equal([])

    def _printer_is_printing(self, selected_file: str) -> None:
        printer_access.forget_everything()
        self.printer_mock.get_print_status.return_value = PrintStatus(
            state=PrinterState.PRINTING, current_byte=5000, total_bytes=10000
        )
        self.printer_mock.get_selected_file.return_value = selected_file

    def test_upload_refuses_to_replace_the_file_being_printed(self) -> None:
        self._printer_is_printing("foobar.ctb")
        response = self.client.post(
            "/uvtools/upload/foobar.ctb",
            data=b"new contents",
            content_type="application/octet-stream",
        )
        expect(response.status_code).to_equal(409)
        with open(config.get_files_directory() / "foobar.ctb", "rb") as file:
            expect(file.read()).to_equal(self.ctb_file_contents)

    def test_delete_refuses_the_file_being_printed(self) -> None:
        self._printer_is_printing("foobar.ctb")
        response = self.client.get("/uvtools/delete/foobar.ctb")
        expect(response.status_code).to_equal(409)
        expect(os.path.isfile(config.get_files_directory() / "foobar.ctb")).to_equal(
            True
        )

    def test_print_file_refuses_an_unsupported_file(self) -> None:
        self.fs.create_file("/mnt/usb_share/notes.txt", contents=b"x")
        response = self.client.get("/uvtools/print/notes.txt")
        expect(response.status_code).to_equal(400)
        self.printer_mock.start_printing.assert_not_called()

    def test_get_files_survives_a_broken_symlink(self) -> None:
        self.fs.create_symlink("/mnt/usb_share/dangling.ctb", "/mnt/usb_share/gone")
        response = self.client.get("/uvtools/files")
        expect(response.status_code).to_equal(200)
        expect("foobar.ctb" in response.get_json()["files"]).to_equal(True)

    def test_delete_works_for_a_file_whose_name_could_no_longer_be_uploaded(
        self,
    ) -> None:
        # Stored before names were restricted. It must not be stuck there.
        self.fs.create_file("/mnt/usb_share/it's (v2).ctb", contents=b"x")
        response = self.client.get("/uvtools/delete/it%27s%20(v2).ctb")
        expect(response.status_code).to_equal(200)
        expect(os.path.exists("/mnt/usb_share/it's (v2).ctb")).to_equal(False)

    def test_delete_removes_a_link_whose_target_is_gone(self) -> None:
        self.fs.create_symlink("/mnt/usb_share/dangling.ctb", "/mnt/usb_share/gone")
        response = self.client.get("/uvtools/delete/dangling.ctb")
        expect(response.status_code).to_equal(200)
        expect(os.path.lexists("/mnt/usb_share/dangling.ctb")).to_equal(False)

    def test_delete_cannot_reach_a_transfer_in_progress(self) -> None:
        self.fs.create_file("/mnt/usb_share/.upload-0123abcd.part", contents=b"x")
        response = self.client.get("/uvtools/delete/.upload-0123abcd.part")
        expect(response.status_code).to_equal(400)
        expect(os.path.exists("/mnt/usb_share/.upload-0123abcd.part")).to_equal(True)

    def test_delete_refuses_to_leave_the_files_directory(self) -> None:
        self.fs.create_file("/mnt/outside.ctb", contents=b"x")
        for name in ("..", "..%5Coutside.ctb"):
            response = self.client.get(f"/uvtools/delete/{name}")
            expect(response.status_code).to_equal(400)
        expect(os.path.exists("/mnt/outside.ctb")).to_equal(True)

    def test_upload_refusal_writes_nothing(self) -> None:
        self._printer_is_printing("foobar.ctb")
        with patch(
            "mariner.server.providers.uvtools._write_as_it_arrives"
        ) as write_mock:
            response = self.client.post(
                "/uvtools/upload/foobar.ctb",
                data=b"new contents",
                content_type="application/octet-stream",
            )
        expect(response.status_code).to_equal(409)
        write_mock.assert_not_called()

    def test_delete_of_a_file_someone_else_just_removed(self) -> None:
        with patch(
            "mariner.server.providers.uvtools.os.remove",
            side_effect=FileNotFoundError("gone"),
        ):
            response = self.client.get("/uvtools/delete/foobar.ctb")
        expect(response.status_code).to_equal(404)

    def test_upload_whose_folder_was_just_removed(self) -> None:
        with patch(
            "mariner.server.providers.uvtools._write_as_it_arrives",
            side_effect=FileNotFoundError("gone"),
        ):
            response = self.client.post(
                "/uvtools/upload/new.ctb",
                data=b"contents",
                content_type="application/octet-stream",
            )
        expect(response.status_code).to_equal(404)

    def test_a_refused_name_cannot_add_lines_to_the_log(self) -> None:
        with self.assertLogs("mariner.server.providers.uvtools", "WARNING") as logs:
            response = self.client.get("/uvtools/delete/a%5Cb%0AWARNING%20forged")
        expect(response.status_code).to_equal(400)
        expect(len(logs.records)).to_equal(1)
        expect("\n" in logs.records[0].getMessage()).to_equal(False)

    def test_a_refused_upload_name_cannot_add_lines_to_the_log(self) -> None:
        with self.assertLogs("mariner.server.providers.uvtools", "WARNING") as logs:
            response = self.client.post(
                "/uvtools/upload/a%5Cb%0AWARNING%20forged.ctb",
                data=b"contents",
                content_type="application/octet-stream",
            )
        expect(response.status_code).to_equal(400)
        expect(len(logs.records)).to_equal(1)
        expect("\n" in logs.records[0].getMessage()).to_equal(False)

    def test_a_refused_deletion_cannot_add_lines_to_the_log(self) -> None:
        self.fs.create_file("/mnt/usb_share/x\nWARNING forged.ctb", contents=b"x")
        self._printer_is_printing("x\nWARNING forged.ctb")
        with self.assertLogs("mariner.server.providers.uvtools", "WARNING") as logs:
            response = self.client.get("/uvtools/delete/x%0AWARNING%20forged.ctb")
        expect(response.status_code).to_equal(409)
        expect("\n" in logs.records[0].getMessage()).to_equal(False)

    def test_print_is_refused_while_a_print_is_running(self) -> None:
        self._printer_is_printing("other.ctb")
        response = self.client.get("/uvtools/print/foobar.ctb")
        expect(response.status_code).to_equal(409)
        self.printer_mock.start_printing.assert_not_called()

    def test_a_stopped_print_still_protects_its_file_for_a_moment(self) -> None:
        self.client.get("/uvtools/print/foobar.ctb")
        expect(self.client.get("/uvtools/stop").status_code).to_equal(200)
        expect(self.client.get("/uvtools/delete/foobar.ctb").status_code).to_equal(409)

    def test_a_command_the_printer_turns_down_cannot_add_lines_to_the_log(
        self,
    ) -> None:
        # These routes take a file name they do not use. An error must not
        # put it in the log as it came.
        self.printer_mock.pause_printing.side_effect = UnexpectedPrinterResponse("")
        self.printer_mock.resume_printing.side_effect = UnexpectedPrinterResponse("")
        self.printer_mock.stop_printing.side_effect = UnexpectedPrinterResponse("")
        with self.assertLogs(level="WARNING") as logs:
            for command in ("pause", "resume", "stop"):
                response = self.client.get(
                    f"/uvtools/{command}/x%0AWARNING:mariner:FORGED%20LINE"
                )
                expect(response.status_code).to_equal(500)
                expect(response.get_json()).to_equal({"success": False})
        expect(len(logs.records)).to_equal(3)
        for record in logs.records:
            expect(record.name).to_equal("mariner.server.providers.uvtools")
            expect("FORGED" in record.getMessage()).to_equal(False)

    def test_upload_onto_a_link_replaces_the_link_and_not_its_target(self) -> None:
        self.fs.create_file("/mnt/usb_share/sub/notes.txt", contents=b"notes")
        self.fs.create_symlink(
            "/mnt/usb_share/linked.ctb", "/mnt/usb_share/sub/notes.txt"
        )
        response = self.client.post(
            "/uvtools/upload/linked.ctb",
            data=b"new contents",
            content_type="application/octet-stream",
        )
        expect(response.status_code).to_equal(200)
        with open("/mnt/usb_share/sub/notes.txt", "rb") as file:
            expect(file.read()).to_equal(b"notes")
        expect(os.path.islink("/mnt/usb_share/linked.ctb")).to_equal(False)
        with open("/mnt/usb_share/linked.ctb", "rb") as file:
            expect(file.read()).to_equal(b"new contents")

    def test_an_upload_that_cannot_be_stored_cannot_add_lines_to_the_log(
        self,
    ) -> None:
        # A full disk, say. Left unhandled, the server would log the
        # request path, client text, as it came.
        with patch(
            "mariner.server.providers.uvtools._write_as_it_arrives",
            side_effect=OSError(28, "No space left"),
        ):
            with self.assertLogs(level="WARNING") as logs:
                response = self.client.post(
                    "/uvtools/upload/model%E2%80%A8FORGED.ctb%0A",
                    data=b"contents",
                    content_type="application/octet-stream",
                )
                expect(response.status_code).to_equal(400)
                response = self.client.post(
                    "/uvtools/upload/model.ctb",
                    data=b"contents",
                    content_type="application/octet-stream",
                )
                expect(response.status_code).to_equal(500)
        expect(len(logs.records)).to_equal(2)
        for record in logs.records:
            expect(record.name).to_equal("mariner.server.providers.uvtools")
            expect("\n" in record.getMessage()).to_equal(False)
            expect("\u2028" in record.getMessage()).to_equal(False)

    def test_an_upload_name_ending_in_a_line_break_is_refused(self) -> None:
        response = self.client.post(
            "/uvtools/upload/%0AFORGED.ctb",
            data=b"contents",
            content_type="application/octet-stream",
        )
        expect(response.status_code).to_equal(400)
        expect(os.listdir("/mnt/usb_share")).to_equal(["foobar.ctb"])

    def test_print_of_a_file_that_is_gone(self) -> None:
        response = self.client.get("/uvtools/print/gone.ctb")
        expect(response.status_code).to_equal(404)
        self.printer_mock.start_printing.assert_not_called()

    def test_delete_cannot_reach_a_transfer_that_began_meanwhile(self) -> None:
        with patch("mariner.server.providers.uvtools.remove_entry") as remove:
            remove.side_effect = FileNotFoundError("hidden by now")
            response = self.client.get("/uvtools/delete/foobar.ctb")
        expect(response.status_code).to_equal(404)
        remove.assert_called_once_with(pathlib.Path("/mnt/usb_share/foobar.ctb"))

    def test_get_files_survives_an_entry_that_cannot_be_asked_what_it_is(
        self,
    ) -> None:
        with patch(
            "mariner.server.providers.uvtools.is_regular_file",
            side_effect=lambda entry: entry.name != "loop.ctb",
        ) as asked:
            self.fs.create_file("/mnt/usb_share/loop.ctb", contents=b"x")
            response = self.client.get("/uvtools/files")
        expect(response.get_json()["files"]).to_equal(["foobar.ctb"])
        expect(asked.call_count).to_equal(2)

    def test_delete_is_refused_when_the_printer_is_silent(self) -> None:
        printer_access.forget_everything()
        self.printer_mock.get_print_status.return_value = PrintStatus(
            state=PrinterState.CLOSED, silent=True
        )
        response = self.client.get("/uvtools/delete/foobar.ctb")
        expect(response.status_code).to_equal(409)
        expect(os.path.isfile(config.get_files_directory() / "foobar.ctb")).to_equal(
            True
        )

    def test_upload_refuses_when_the_print_starts_during_the_upload(self) -> None:
        # The first check passes; the print starts while the file is being
        # written. The check made as it is moved into place must catch it.
        from mariner.server.providers import uvtools

        real_write = uvtools._write_as_it_arrives

        def write_while_a_print_starts(stream: Any, path: pathlib.Path) -> int:
            written = real_write(stream, path)
            self._printer_is_printing("foobar.ctb")
            return written

        with patch.object(
            uvtools, "_write_as_it_arrives", side_effect=write_while_a_print_starts
        ):
            response = self.client.post(
                "/uvtools/upload/foobar.ctb",
                data=b"new contents",
                content_type="application/octet-stream",
            )

        expect(response.status_code).to_equal(409)
        with open(config.get_files_directory() / "foobar.ctb", "rb") as file:
            expect(file.read()).to_equal(self.ctb_file_contents)
        leftovers = [n for n in os.listdir("/mnt/usb_share") if n.endswith(".part")]
        expect(leftovers).to_equal([])

    def test_upload_onto_the_name_of_a_folder(self) -> None:
        self.fs.create_dir("/mnt/usb_share/batch.ctb")
        response = self.client.post(
            "/uvtools/upload/batch.ctb",
            data=b"new contents",
            content_type="application/octet-stream",
        )
        expect(response.status_code).to_equal(400)
        expect(os.path.isdir("/mnt/usb_share/batch.ctb")).to_equal(True)

    def test_print_file_not_found(self) -> None:
        response = self.client.get("/uvtools/print/missing.ctb")
        expect(response.status_code).to_equal(404)

    # ---- Delete ----

    def test_delete_file(self) -> None:
        expect(os.path.isfile(config.get_files_directory() / "foobar.ctb")).to_equal(
            True
        )
        response = self.client.get("/uvtools/delete/foobar.ctb")
        expect(response.status_code).to_equal(200)
        expect(os.path.isfile(config.get_files_directory() / "foobar.ctb")).to_equal(
            False
        )

    def test_delete_file_not_found(self) -> None:
        response = self.client.get("/uvtools/delete/nope.ctb")
        expect(response.status_code).to_equal(404)

    # ---- Pause / Resume / Stop ----

    def test_pause_print(self) -> None:
        response = self.client.get("/uvtools/pause")
        expect(response.status_code).to_equal(200)
        self.printer_mock.pause_printing.assert_called_once()

    def test_pause_print_with_filename(self) -> None:
        response = self.client.get("/uvtools/pause/foobar.ctb")
        expect(response.status_code).to_equal(200)
        self.printer_mock.pause_printing.assert_called_once()

    def test_resume_print(self) -> None:
        response = self.client.get("/uvtools/resume")
        expect(response.status_code).to_equal(200)
        self.printer_mock.resume_printing.assert_called_once()

    def test_stop_print(self) -> None:
        response = self.client.get("/uvtools/stop")
        expect(response.status_code).to_equal(200)
        self.printer_mock.stop_printing.assert_called_once()

    def test_stop_print_with_filename(self) -> None:
        response = self.client.get("/uvtools/stop/foobar.ctb")
        expect(response.status_code).to_equal(200)
        self.printer_mock.stop_printing.assert_called_once()

    # ---- Get Files ----

    def test_get_files(self) -> None:
        response = self.client.get("/uvtools/files")
        expect(response.status_code).to_equal(200)
        data = response.get_json()
        expect("foobar.ctb" in data["files"]).to_equal(True)

    # ---- Print Status ----

    def test_print_status_printing(self) -> None:
        self.printer_mock.get_selected_file.return_value = "foobar.ctb"
        self.printer_mock.get_print_status.return_value = PrintStatus(
            state=PrinterState.PRINTING,
            current_byte=256537,
            total_bytes=832745,
        )
        response = self.client.get("/uvtools/status")
        expect(response.status_code).to_equal(200)
        data = response.get_json()
        expect(data["state"]).to_equal("PRINTING")
        expect(data["selected_file"]).to_equal("foobar.ctb")

    def test_print_status_idle(self) -> None:
        self.printer_mock.get_selected_file.return_value = ""
        self.printer_mock.get_print_status.return_value = PrintStatus(
            state=PrinterState.IDLE,
        )
        response = self.client.get("/uvtools/status")
        expect(response.status_code).to_equal(200)
        data = response.get_json()
        expect(data["state"]).to_equal("IDLE")

    # ---- Printer Info ----

    def test_printer_info(self) -> None:
        self.printer_mock.get_firmware_version.return_value = "V4.9.2"
        response = self.client.get("/uvtools/info")
        expect(response.status_code).to_equal(200)
        data = response.get_json()
        expect(data["name"]).to_equal("Mariner")
        expect(data["firmware"]).to_equal("V4.9.2")
        expect(".ctb" in data["extensions"]).to_equal(True)
