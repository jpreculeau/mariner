"""HTTPS spoken by the web server itself, over real connections."""

import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import warnings
from pathlib import Path
from typing import Any, Dict, List, Tuple
from unittest import TestCase, skipUnless
from unittest.mock import patch

from pyexpect import expect

from mariner.server import early, tls

LARGE = 5 * 1024 * 1024


def _certificate(folder: Path) -> Tuple[str, str]:
    certificate, key = str(folder / "cert.pem"), str(folder / "key.pem")
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "ec",
            "-pkeyopt",
            "ec_paramgen_curve:prime256v1",
            "-nodes",
            "-keyout",
            key,
            "-out",
            certificate,
            "-days",
            "2",
            "-subj",
            "/CN=localhost",
        ],
        check=True,
        capture_output=True,
    )
    return certificate, key


@skipUnless(shutil.which("openssl"), "needs the openssl command")
class SecuredConnectionTest(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.folder = tempfile.TemporaryDirectory()
        cls.certificate, cls.key = _certificate(Path(cls.folder.name))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.folder.cleanup()

    def setUp(self) -> None:
        self.seen: List[Dict[str, Any]] = []

        def application(environ: Dict[str, Any], start_response: Any) -> List[bytes]:
            body = environ["wsgi.input"].read()
            self.seen.append(
                {
                    "path": environ["PATH_INFO"],
                    "scheme": environ["wsgi.url_scheme"],
                    "length": len(body),
                }
            )
            if environ["PATH_INFO"] == "/large":
                answer = b"0123456789abcdef" * (LARGE // 16)
            else:
                answer = b"served " + str(len(body)).encode()
            start_response(
                "200 OK",
                [("Content-Type", "text/plain"), ("Content-Length", str(len(answer)))],
            )
            return [answer]

        self.server = early.create_guarded_server(
            application,
            host="127.0.0.1",
            port=0,
            max_request_body_size=10**9,
            # Short, for the test of a connection that says nothing.
            channel_timeout=1,
            cleanup_interval=1,
            tls=tls.context(self.certificate, self.key),
        )
        self.port = self.server.effective_port

        def run() -> None:
            try:
                self.server.run()
            except OSError:
                # Closed under it, at the end of the test.
                pass

        threading.Thread(target=run, daemon=True).start()
        self.addCleanup(self.server.close)
        self.addCleanup(self.server.task_dispatcher.shutdown)

    def _connected(self) -> ssl.SSLSocket:
        trusting = ssl.create_default_context(cafile=self.certificate)
        raw = socket.create_connection(("127.0.0.1", self.port), timeout=10)
        secured = trusting.wrap_socket(raw, server_hostname="localhost")
        self.addCleanup(secured.close)
        return secured

    @staticmethod
    def _answer(connection: Any, pause: float = 0.0, piece: int = 65536) -> bytes:
        """Read one answer, by its announced length."""
        received = b""
        while b"\r\n\r\n" not in received:
            more = connection.recv(piece)
            if not more:
                return received
            received += more
        head, _, body = received.partition(b"\r\n\r\n")
        length = 0
        for line in head.split(b"\r\n"):
            if line.lower().startswith(b"content-length:"):
                length = int(line.split(b":")[1])
        while len(body) < length:
            if pause:
                time.sleep(pause)
            more = connection.recv(piece)
            if not more:
                break
            body += more
        return head + b"\r\n\r\n" + body

    def test_a_request_is_served_and_said_to_have_come_by_https(self) -> None:
        connection = self._connected()
        connection.sendall(b"GET /hello HTTP/1.1\r\nHost: localhost\r\n\r\n")
        answer = self._answer(connection)
        expect(answer.startswith(b"HTTP/1.1 200")).to_equal(True)
        expect(answer.endswith(b"served 0")).to_equal(True)
        expect(self.seen).to_equal([{"path": "/hello", "scheme": "https", "length": 0}])

    def test_several_requests_go_over_one_connection(self) -> None:
        connection = self._connected()
        for number in range(3):
            connection.sendall(
                f"GET /again{number} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode()
            )
            expect(self._answer(connection).endswith(b"served 0")).to_equal(True)
        expect([one["path"] for one in self.seen]).to_equal(
            ["/again0", "/again1", "/again2"]
        )

    def test_a_large_file_sent_arrives_whole(self) -> None:
        connection = self._connected()
        connection.sendall(
            b"POST /api/upload_file HTTP/1.1\r\nHost: localhost\r\n"
            b"Content-Length: " + str(LARGE).encode() + b"\r\n\r\n"
        )
        connection.sendall(b"x" * LARGE)
        answer = self._answer(connection)
        expect(answer.endswith(b"served " + str(LARGE).encode())).to_equal(True)

    def test_a_large_answer_arrives_whole(self) -> None:
        connection = self._connected()
        connection.sendall(b"GET /large HTTP/1.1\r\nHost: localhost\r\n\r\n")
        body = self._answer(connection).partition(b"\r\n\r\n")[2]
        expect(len(body)).to_equal(LARGE)
        expect(body == b"0123456789abcdef" * (LARGE // 16)).to_equal(True)

    def test_a_client_slow_to_read_gets_all_of_a_large_answer(self) -> None:
        connection = self._connected()
        connection.sendall(b"GET /large HTTP/1.1\r\nHost: localhost\r\n\r\n")
        body = self._answer(connection, pause=0.002, piece=16384).partition(
            b"\r\n\r\n"
        )[2]
        expect(len(body)).to_equal(LARGE)

    def test_an_answer_is_whole_before_the_connection_is_closed(self) -> None:
        # The web server closes as soon as it has handed over the last
        # of the answer: what was encrypted must still reach the client.
        connection = self._connected()
        connection.sendall(
            b"GET /large HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
        )
        received = b""
        while True:
            time.sleep(0.001)
            more = connection.recv(16384)
            if not more:
                break
            received += more
        expect(len(received.partition(b"\r\n\r\n")[2])).to_equal(LARGE)

    def test_what_is_not_tls_is_hung_up_on_and_the_server_goes_on(self) -> None:
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as plain:
            plain.sendall(b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n")
            # Nothing of the application is said in the clear.
            expect(b"served" in plain.recv(65536)).to_equal(False)
        expect(self.seen).to_equal([])
        connection = self._connected()
        connection.sendall(b"GET /after HTTP/1.1\r\nHost: localhost\r\n\r\n")
        expect(self._answer(connection).endswith(b"served 0")).to_equal(True)

    def test_a_client_that_leaves_while_greeting_does_no_harm(self) -> None:
        for _ in range(5):
            with socket.create_connection(("127.0.0.1", self.port), timeout=5) as raw:
                raw.sendall(b"\x16\x03\x01\x00\x05hello")
        connection = self._connected()
        connection.sendall(b"GET /after HTTP/1.1\r\nHost: localhost\r\n\r\n")
        expect(self._answer(connection).endswith(b"served 0")).to_equal(True)

    def test_a_connection_that_never_finishes_greeting_is_not_kept(self) -> None:
        # It holds one of the few connections there are.
        with socket.create_connection(("127.0.0.1", self.port), timeout=10) as raw:
            raw.sendall(b"\x16\x03\x01")
            raw.settimeout(8)
            started = time.monotonic()
            expect(raw.recv(1024)).to_equal(b"")
            expect(time.monotonic() - started < 6).to_equal(True)

    def test_a_connection_that_says_nothing_after_greeting_is_not_kept(
        self,
    ) -> None:
        connection = self._connected()
        connection.settimeout(8)
        started = time.monotonic()
        expect(connection.recv(1024)).to_equal(b"")
        expect(time.monotonic() - started < 6).to_equal(True)

    def test_a_file_whose_sender_leaves_halfway_does_no_harm(self) -> None:
        connection = self._connected()
        connection.sendall(
            b"POST /api/upload_file HTTP/1.1\r\nHost: localhost\r\n"
            b"Content-Length: 5000000\r\n\r\n" + b"x" * 100000
        )
        connection.close()
        after = self._connected()
        after.sendall(b"GET /after HTTP/1.1\r\nHost: localhost\r\n\r\n")
        expect(self._answer(after).endswith(b"served 0")).to_equal(True)
        expect([one["path"] for one in self.seen]).to_equal(["/after"])

    def test_the_old_forms_of_tls_are_not_spoken(self) -> None:
        old = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        old.check_hostname = False
        old.verify_mode = ssl.CERT_NONE
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            old.minimum_version = ssl.TLSVersion.TLSv1
            old.maximum_version = ssl.TLSVersion.TLSv1_1
        old.set_ciphers("DEFAULT:@SECLEVEL=0")
        raw = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        self.addCleanup(raw.close)
        with self.assertRaises((ssl.SSLError, ConnectionError)):
            old.wrap_socket(raw)

    def test_many_at_once_are_each_answered(self) -> None:
        answers: List[bool] = []

        def ask(number: int) -> None:
            connection = self._connected()
            connection.sendall(
                f"GET /many{number} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode()
            )
            answers.append(self._answer(connection).endswith(b"served 0"))

        threads = [threading.Thread(target=ask, args=(n,)) for n in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        expect(answers).to_equal([True] * 12)

    def test_what_is_refused_in_the_clear_is_not_refused_over_tls(self) -> None:
        patcher = patch.object(
            early, "plain_refusal", lambda path, headers: {"code": "https_required"}
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        connection = self._connected()
        connection.sendall(
            b"POST /api/upload_file HTTP/1.1\r\nHost: localhost\r\n"
            b"Content-Length: 5\r\n\r\nhello"
        )
        expect(self._answer(connection).endswith(b"served 5")).to_equal(True)

    def test_a_refusal_before_the_body_is_read_through_tls_too(self) -> None:
        # What the web server refuses on the headers alone.
        connection = self._connected()
        connection.sendall(
            b"POST /api/create_directory HTTP/1.1\r\nHost: localhost\r\n"
            b"Content-Length: 600000\r\n\r\n"
        )
        answer = self._answer(connection)
        expect(answer.startswith(b"HTTP/1.1 413")).to_equal(True)
        expect(self.seen).to_equal([])


@skipUnless(shutil.which("openssl"), "needs the openssl command")
class TwoPortsTest(TestCase):
    """As Mariner listens: in the clear on one port, over TLS on another."""

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.certificate, key = _certificate(Path(folder.name))
        self.schemes: List[str] = []

        def application(environ: Dict[str, Any], start_response: Any) -> List[bytes]:
            self.schemes.append(environ["wsgi.url_scheme"])
            start_response("200 OK", [("Content-Length", "6")])
            return [b"served"]

        # Two ports that are free, as the configuration would name them.
        ports = []
        for _ in range(2):
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                ports.append(probe.getsockname()[1])
        self.plain, self.secured = ports
        self.server = early.create_guarded_server(
            application,
            listen=f"127.0.0.1:{self.plain} 127.0.0.1:{self.secured}",
            tls=tls.context(self.certificate, key),
            tls_port=self.secured,
        )

        def run() -> None:
            try:
                self.server.run()
            except OSError:
                pass

        threading.Thread(target=run, daemon=True).start()
        self.addCleanup(self.server.close)

    def test_the_one_named_speaks_tls_and_the_other_does_not(self) -> None:
        with socket.create_connection(("127.0.0.1", self.plain), timeout=5) as raw:
            raw.sendall(b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n")
            answer = SecuredConnectionTest._answer(raw)
            expect(answer.endswith(b"served")).to_equal(True)
        trusting = ssl.create_default_context(cafile=self.certificate)
        with socket.create_connection(("127.0.0.1", self.secured), timeout=5) as raw:
            with trusting.wrap_socket(raw, server_hostname="localhost") as secured:
                secured.sendall(b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n")
                answer = SecuredConnectionTest._answer(secured)
                expect(answer.endswith(b"served")).to_equal(True)
        expect(self.schemes).to_equal(["http", "https"])
