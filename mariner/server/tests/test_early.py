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

from mariner.server import early


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
        thread = threading.Thread(target=self.server.run, daemon=True)
        thread.start()
        self.addCleanup(self.server.close)

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
            early.shutil, "disk_usage", return_value=usage._replace(free=1_000_000)
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
