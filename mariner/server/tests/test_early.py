"""Refusals made as soon as a request's headers are in, before its body."""

import json
import shutil
import socket
import threading
import time
from typing import Any, Dict, List, Tuple
from unittest import TestCase
from unittest.mock import patch

from pyexpect import expect

from mariner.server import early, refusals


class EarlyRefusalTest(TestCase):
    def setUp(self) -> None:
        self.called: List[str] = []

        def application(environ: Dict[str, Any], start_response: Any) -> List[bytes]:
            self.called.append(environ["PATH_INFO"])
            environ["wsgi.input"].read()
            start_response("200 OK", [("Content-Type", "text/plain")])
            return [b"served"]

        self.server = early.create_guarded_server(
            application, host="127.0.0.1", port=0, max_request_body_size=10**9
        )
        self.port = self.server.effective_port

        def run() -> None:
            try:
                self.server.run()
            except OSError:
                # Closed under it, at the end of the test.
                pass

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.addCleanup(self.server.close)
        # Before that, let what is being answered finish.
        self.addCleanup(self.server.task_dispatcher.shutdown)

    def _exchange(
        self, head: str, body: bytes = b"", wait_for_body: bool = False
    ) -> Tuple[int, Dict[str, str], bytes]:
        """Send the headers alone, unless told to send the body too."""
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as sock:
            sock.sendall(head.replace("\n", "\r\n").encode() + b"\r\n")
            if wait_for_body:
                sock.sendall(body)
            received = b""
            while True:
                piece = sock.recv(65536)
                if not piece:
                    break
                received += piece
                if b"\r\n\r\n" in received:
                    top, _, rest = received.partition(b"\r\n\r\n")
                    length = [
                        int(line.split(b":")[1])
                        for line in top.split(b"\r\n")
                        if line.lower().startswith(b"content-length")
                    ]
                    if length and len(rest) >= length[0]:
                        break
        top, _, rest = received.partition(b"\r\n\r\n")
        lines = top.decode("latin-1").split("\r\n")
        headers = dict(line.split(": ", 1) for line in lines[1:])
        return int(lines[0].split()[1]), headers, rest

    def test_an_ordinary_request_is_served(self) -> None:
        status, _, body = self._exchange(
            "GET /api/list_files HTTP/1.1\nHost: 127.0.0.1\n"
        )
        expect((status, body)).to_equal((200, b"served"))
        status, _, body = self._exchange(
            "POST /api/upload_file HTTP/1.1\nHost: 127.0.0.1\nContent-Length: 5\n",
            b"hello",
            wait_for_body=True,
        )
        expect((status, body)).to_equal((200, b"served"))

    def test_a_foreign_name_is_refused_before_the_body_is_sent(self) -> None:
        # The answer comes though not one byte of the announced body does:
        # nothing of it was waited for, or kept.
        started = time.monotonic()
        status, headers, body = self._exchange(
            "POST /api/upload_file HTTP/1.1\nHost: evil.example\n"
            "Content-Length: 500000000\n"
        )
        expect(status).to_equal(403)
        expect(json.loads(body)["code"]).to_equal("host_not_allowed")
        expect(headers["Content-Type"]).to_equal("application/json")
        expect(headers["X-Content-Type-Options"]).to_equal("nosniff")
        expect(time.monotonic() - started < 3).to_equal(True)
        expect(self.called).to_equal([])

    def test_another_site_is_refused_before_the_body_is_sent(self) -> None:
        for path, extra, code in (
            ("/api/upload_file", "Origin: http://evil.example\n", "cross_site_request"),
            (
                "/uvtools/upload/x.ctb",
                "Origin: http://evil.example\n",
                "cross_site_request",
            ),
            (
                "/uvtools/upload/x.ctb",
                "User-Agent: Mozilla/5.0 (X11)\n",
                "browser_not_served",
            ),
            ("/uvtools/upload/x.ctb", "Icy-MetaData: 1\n", "browser_not_served"),
        ):
            status, _, body = self._exchange(
                f"POST {path} HTTP/1.1\nHost: 127.0.0.1\n{extra}"
                "Content-Length: 500000000\n"
            )
            expect(status).to_equal(403)
            expect(json.loads(body)["code"]).to_equal(code)
        expect(self.called).to_equal([])

    def _asking_for_the_password(self) -> None:
        def unless_signed_in(method: str, path: str, headers: Dict[str, str]) -> Any:
            cookies = headers.get("Cookie", "")
            if path.startswith("/api/") and "signed-in" not in cookies:
                return {"code": "login_required"}
            return None

        patcher = patch.object(early, "password_refusal", unless_signed_in)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_body_for_the_page_is_not_taken_in_the_clear_under_https(
        self,
    ) -> None:
        patcher = patch.object(
            early,
            "plain_refusal",
            lambda path, headers: (
                {"code": "https_required"} if path.startswith("/api/") else None
            ),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        status, _, body = self._exchange(
            "POST /api/upload_file HTTP/1.1\nHost: 127.0.0.1\n"
            "Content-Length: 500000000\n"
        )
        expect(status).to_equal(403)
        expect(json.loads(body)["code"]).to_equal("https_required")
        expect(self.called).to_equal([])
        # A slicer's file still is.
        status, _, _ = self._exchange(
            "PUT /uvtools/upload/x.ctb HTTP/1.1\nHost: 127.0.0.1\n"
            "Content-Length: 5\n",
            b"hello",
            wait_for_body=True,
        )
        expect(status).to_equal(200)

    def test_https_asked_of_the_port_in_the_clear_is_hung_up_on_at_once(
        self,
    ) -> None:
        # Left to itself the web server waits for the end of headers that
        # will never come, and the browser for half a minute.
        started = time.monotonic()
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as sock:
            sock.sendall(b"\x16\x03\x01\x02\x00\x01\x00\x01\xfc\x03\x03" + b"x" * 200)
            expect(sock.recv(1024)).to_equal(b"")
        expect(time.monotonic() - started < 2).to_equal(True)
        expect(self.called).to_equal([])

    def test_a_password_out_of_reach_is_not_said_as_one_to_give(self) -> None:
        patcher = patch.object(
            early,
            "password_refusal",
            lambda method, path, headers: {"code": "state_unavailable"},
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        status, _, body = self._exchange(
            "POST /api/upload_file HTTP/1.1\nHost: 127.0.0.1\n"
            "Content-Length: 500000000\n"
        )
        expect(status).to_equal(503)
        expect(json.loads(body)["code"]).to_equal("state_unavailable")

    def test_who_is_not_signed_in_is_refused_before_the_body_is_sent(self) -> None:
        # Else anyone could have two gigabytes written to the drive, to be
        # told only then that a password is asked for.
        self._asking_for_the_password()
        status, _, body = self._exchange(
            "POST /api/upload_file HTTP/1.1\nHost: 127.0.0.1\n"
            "Content-Length: 500000000\n"
        )
        expect(status).to_equal(401)
        expect(json.loads(body)["code"]).to_equal("login_required")
        expect(self.called).to_equal([])

    def test_who_is_signed_in_has_the_body_taken(self) -> None:
        self._asking_for_the_password()
        status, _, body = self._exchange(
            "POST /api/upload_file HTTP/1.1\nHost: 127.0.0.1\n"
            "Cookie: mariner_session=signed-in\nContent-Length: 4\n",
            b"data",
            wait_for_body=True,
        )
        expect(status).to_equal(200)
        expect(self.called).to_equal(["/api/upload_file"])

    def test_a_slicer_is_not_asked_for_a_password(self) -> None:
        # It would not know what to answer: its addresses have a switch.
        self._asking_for_the_password()
        status, _, _ = self._exchange(
            "POST /uvtools/upload/model.ctb HTTP/1.1\nHost: 127.0.0.1\n"
            "Content-Length: 4\n",
            b"data",
            wait_for_body=True,
        )
        expect(status).to_equal(200)

    def test_a_request_without_a_body_is_left_to_the_application(self) -> None:
        # Nothing to spare the drive, and the application answers a person
        # who opened Mariner under a foreign name with a page to read.
        status, _, body = self._exchange("GET / HTTP/1.1\nHost: evil.example\n")
        expect((status, body)).to_equal((200, b"served"))
        expect(self.called).to_equal(["/"])

    def test_a_body_sent_in_pieces_is_refused_before_it_too(self) -> None:
        status, _, body = self._exchange(
            "POST /api/upload_file HTTP/1.1\nHost: evil.example\n"
            "Transfer-Encoding: chunked\n"
        )
        expect(status).to_equal(403)
        expect(self.called).to_equal([])

    def test_a_client_that_asks_before_sending_is_not_told_to_go_on(self) -> None:
        # "Expect: 100-continue" asks whether the body is wanted. Told to
        # go on, the client sends all of it and may miss the refusal.
        status, _, _ = self._exchange(
            "PUT /uvtools/upload/x.ctb HTTP/1.1\nHost: evil.example\n"
            "Expect: 100-continue\nContent-Length: 500000000\n"
        )
        expect(status).to_equal(403)
        # One that is welcome still is.
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as sock:
            sock.sendall(
                b"PUT /uvtools/upload/x.ctb HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                b"Expect: 100-continue\r\nContent-Length: 5\r\n\r\n"
            )
            expect(sock.recv(12)).to_equal(b"HTTP/1.1 100")

    def test_another_site_s_body_is_not_taken_in_wherever_it_is_sent(self) -> None:
        # A page can have a browser post to any address, not only to the
        # ones that act: the body would be stored all the same.
        for path in ("/", "/files", "/assets/x.js", "/no/such/thing"):
            status, _, body = self._exchange(
                f"POST {path} HTTP/1.1\nHost: 127.0.0.1\n"
                "Origin: http://evil.example\nContent-Length: 500000000\n"
            )
            expect(status).to_equal(403)
            expect(json.loads(body)["code"]).to_equal("cross_site_request")
        expect(self.called).to_equal([])

    def test_a_slicer_s_interface_that_is_off_takes_no_file(self) -> None:
        with patch.object(early, "UPLOAD_PREFIXES", ("/api/upload_file",)):
            status, _, body = self._exchange(
                "PUT /uvtools/upload/x.ctb HTTP/1.1\nHost: 127.0.0.1\n"
                "Content-Length: 600000\n"
            )
        expect(status).to_equal(413)
        expect(json.loads(body)["code"]).to_equal("request_too_large")
        expect(self.called).to_equal([])

    def test_only_a_file_being_sent_may_be_large(self) -> None:
        for path, extra in (
            ("/api/create_directory", "Content-Length: 600000\n"),
            ("/", "Content-Length: 600000\n"),
            ("/uvtools/print/x.ctb", "Content-Length: 600000\n"),
            # Of no known size.
            ("/api/create_directory", "Transfer-Encoding: chunked\n"),
        ):
            status, headers, body = self._exchange(
                f"POST {path} HTTP/1.1\nHost: 127.0.0.1\n{extra}"
            )
            expect(status).to_equal(413)
            expect(json.loads(body)["code"]).to_equal("request_too_large")
        expect(self.called).to_equal([])
        # What goes with an ordinary request is taken.
        status, _, _ = self._exchange(
            "POST /api/create_directory HTTP/1.1\nHost: 127.0.0.1\n"
            "Content-Length: 300000\n",
            b"x" * 300000,
            wait_for_body=True,
        )
        expect(status).to_equal(200)
        # And a file of unknown size, where files are sent.
        status, _, _ = self._exchange(
            "PUT /uvtools/upload/x.ctb HTTP/1.1\nHost: 127.0.0.1\n"
            "Transfer-Encoding: chunked\n",
            b"5\r\nhello\r\n0\r\n\r\n",
            wait_for_body=True,
        )
        expect(status).to_equal(200)

    def test_some_room_is_left_on_the_drive(self) -> None:
        # The drive uploads wait on is the system's own: filled to the
        # last byte, more than uploads would stop working.
        usage = shutil.disk_usage("/")
        import tempfile

        reserve = early.KEPT_FREE_BYTES
        expect(reserve).to_equal(64 * 1024 * 1024)
        refusals.said.clear()
        with patch.object(
            early.shutil,
            "disk_usage",
            return_value=usage._replace(free=reserve + 2 * 1024 * 1024),
        ) as measured, self.assertLogs(
            "mariner.server.refusals", level="WARNING"
        ) as logs:
            status, _, body = self._exchange(
                "PUT /uvtools/upload/x.ctb HTTP/1.1\nHost: 127.0.0.1\n"
                "Content-Length: 3000000\n"
            )
        expect(status).to_equal(507)
        # The place uploads wait in is the one measured.
        measured.assert_called_with(tempfile.gettempdir())
        # Said in full: 66 MB free and a file of 3 would not add up.
        description = json.loads(body)["description"]
        expect("66 MB are free" in description).to_equal(True)
        expect("64 MB" in description).to_equal(True)
        message = logs.records[0].getMessage()
        expect("127.0.0.1" in message).to_equal(True)
        expect(tempfile.gettempdir() in message).to_equal(True)

    def test_what_the_web_server_refuses_itself_is_left_to_it(self) -> None:
        # Larger than any file may be: not a matter of room.
        usage = shutil.disk_usage("/")
        refusals.said.clear()
        with patch.object(
            early.shutil, "disk_usage", return_value=usage._replace(free=0)
        ), self.assertNoLogs("mariner.server.refusals", level="WARNING"):
            status, _, _ = self._exchange(
                "PUT /uvtools/upload/x.ctb HTTP/1.1\nHost: 127.0.0.1\n"
                "Content-Length: 2000000000\n"
            )
        expect(status).to_equal(413)

    def test_refusals_for_want_of_room_do_not_fill_the_log(self) -> None:
        usage = shutil.disk_usage("/")
        refusals.said.clear()
        with patch.object(
            early.shutil, "disk_usage", return_value=usage._replace(free=0)
        ), self.assertLogs("mariner.server.refusals", level="WARNING") as logs:
            for _ in range(20):
                status, _, _ = self._exchange(
                    "PUT /uvtools/upload/x.ctb HTTP/1.1\nHost: 127.0.0.1\n"
                    "Content-Length: 900000000\n"
                )
                expect(status).to_equal(507)
        expect(len(logs.records)).to_equal(1)

    def test_a_request_refused_as_too_large_is_written_to_the_log(self) -> None:
        refusals.said.clear()
        with self.assertLogs("mariner.server.refusals", level="WARNING") as logs:
            self._exchange(
                "POST /api/create_directory HTTP/1.1\nHost: 127.0.0.1\n"
                "Content-Length: 600000\n"
            )
        message = logs.records[0].getMessage()
        for told in ("request_too_large", "POST", "/api/create_directory"):
            expect(told in message).to_equal(True)

    def test_one_with_nothing_to_send_is_answered_not_told_to_go_on(self) -> None:
        # Told to go on, the web server then waits for a body that is not
        # coming.
        for head in (
            "POST /api/delete_file HTTP/1.1\nHost: 127.0.0.1\n"
            "Expect: 100-continue\nContent-Length: 0\n",
            "GET /api/list_files HTTP/1.1\nHost: 127.0.0.1\nExpect: 100-continue\n",
        ):
            status, _, body = self._exchange(head)
            expect((status, body)).to_equal((200, b"served"))

    def test_a_file_kept_on_the_drive_uploads_wait_on_counts_once_more(self) -> None:
        usage = shutil.disk_usage("/")
        free = early.KEPT_FREE_BYTES + 2_000_000
        with patch.object(
            early.shutil, "disk_usage", return_value=usage._replace(free=free)
        ):
            for shared, status in ((False, 200), (True, 507)):
                with patch.object(early, "files_share_the_drive", return_value=shared):
                    answered, _, _ = self._exchange(
                        "PUT /uvtools/upload/x.ctb HTTP/1.1\nHost: 127.0.0.1\n"
                        "Content-Length: 1100000\n",
                        b"x" * 1100000 if status == 200 else b"",
                        wait_for_body=status == 200,
                    )
                    expect(answered).to_equal(status)

    def test_how_many_times_an_upload_is_kept(self) -> None:
        form, raw = "Multipart/Form-Data; boundary=x", "application/octet-stream"
        with patch.object(early, "files_share_the_drive", return_value=False):
            expect((early.copies_kept(form), early.copies_kept(raw))).to_equal((2, 1))
        with patch.object(early, "files_share_the_drive", return_value=True):
            expect((early.copies_kept(form), early.copies_kept(raw))).to_equal((3, 2))

    def test_whether_files_are_kept_on_the_drive_uploads_wait_on(self) -> None:
        import pathlib
        import tempfile

        here = pathlib.Path(tempfile.gettempdir())
        with patch.object(early.config, "get_files_directory", return_value=here):
            expect(early.files_share_the_drive()).to_equal(True)
        for elsewhere in ("/proc", "/no/such/place"):
            with patch.object(
                early.config,
                "get_files_directory",
                return_value=pathlib.Path(elsewhere),
            ):
                expect(early.files_share_the_drive()).to_equal(False)

    def test_one_too_large_for_anything_is_not_told_to_go_on_either(self) -> None:
        # The web server refuses it itself, but only once it has answered
        # the question.
        for extra in ("", "Origin: http://evil.example\n"):
            status, _, _ = self._exchange(
                "PUT /uvtools/upload/x.ctb HTTP/1.1\nHost: 127.0.0.1\n"
                f"{extra}Expect: 100-continue\nContent-Length: 2000000000\n"
            )
            expect(status).to_equal(413)

    def test_a_refusal_is_written_to_the_log_with_who_was_refused(self) -> None:
        refusals.said.clear()
        with self.assertLogs("mariner.server.refusals", level="WARNING") as logs:
            self._exchange(
                "POST /api/upload_file HTTP/1.1\nHost: evil.example\n"
                "Content-Length: 500000000\n"
            )
        message = logs.records[0].getMessage()
        expect("127.0.0.1" in message).to_equal(True)
        expect("host_not_allowed" in message).to_equal(True)

    def test_a_drive_that_cannot_be_measured_does_not_refuse(self) -> None:
        with patch.object(early.shutil, "disk_usage", side_effect=OSError("gone")):
            status, _, _ = self._exchange(
                "PUT /uvtools/upload/x.ctb HTTP/1.1\nHost: 127.0.0.1\n"
                "Content-Length: 600000\n",
                b"x" * 600000,
                wait_for_body=True,
            )
        expect(status).to_equal(200)

    def test_every_address_listened_on_refuses_early(self) -> None:
        server = early.create_guarded_server(
            lambda environ, start_response: [], listen="127.0.0.1:0 127.0.0.1:0"
        )
        self.addCleanup(server.close)
        listening = [
            one for one in server.map.values() if hasattr(one, "channel_class")
        ]
        expect(len(listening)).to_equal(2)
        for one in listening:
            expect(one.channel_class).to_equal(early._Channel)

    def test_a_page_may_be_asked_for_from_another_site(self) -> None:
        status, _, _ = self._exchange(
            "GET /files HTTP/1.1\nHost: 127.0.0.1\nReferer: http://other.example/\n"
        )
        expect(status).to_equal(200)

    def test_an_upload_larger_than_the_room_to_wait_in_is_refused_at_once(
        self,
    ) -> None:
        usage = shutil.disk_usage("/")
        with patch.object(
            early.shutil,
            "disk_usage",
            return_value=usage._replace(free=early.KEPT_FREE_BYTES + 1_000_000),
        ):
            # Once in the room for a slicer's upload, twice for a form: the
            # web server keeps it, and so does the reading of the form.
            for path, kind, length, status in (
                ("/uvtools/upload/x.ctb", "application/octet-stream", 900_000, 200),
                ("/uvtools/upload/x.ctb", "application/octet-stream", 1_100_000, 507),
                ("/api/upload_file", "multipart/form-data; boundary=x", 400_000, 200),
                ("/api/upload_file", "multipart/form-data; boundary=x", 600_000, 507),
            ):
                answered, _, body = self._exchange(
                    f"POST {path} HTTP/1.1\nHost: 127.0.0.1\n"
                    f"Content-Type: {kind}\nContent-Length: {length}\n",
                    b"x" * length if status == 200 else b"",
                    wait_for_body=status == 200,
                )
                expect(answered).to_equal(status)
                if status == 507:
                    expect(json.loads(body)["code"]).to_equal("upload_not_stored")

    def test_a_small_request_is_not_measured_against_the_room(self) -> None:
        usage = shutil.disk_usage("/")
        with patch.object(
            early.shutil, "disk_usage", return_value=usage._replace(free=0)
        ):
            status, _, _ = self._exchange(
                "POST /api/printer/command/pause_print HTTP/1.1\nHost: 127.0.0.1\n"
                "Content-Length: 20\n",
                b"x" * 20,
                wait_for_body=True,
            )
        expect(status).to_equal(200)
