"""HTTPS spoken by the web server itself, over real connections."""

import os
import shutil
import socket
import ssl
import struct
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
from waitress.channel import HTTPChannel

from mariner.server import early, tls

LARGE = 5 * 1024 * 1024
HUGE = 24 * 1024 * 1024


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
            if environ["PATH_INFO"] == "/huge":
                answer = b"0123456789abcdef" * (HUGE // 16)
            elif environ["PATH_INFO"] == "/large":
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
            # Low, so that the threads that answer write to the client
            # themselves, as they do for an answer of some size.
            outbuf_high_watermark=65536,
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

    def test_a_very_large_answer_is_whole_before_the_connection_is_closed(
        self,
    ) -> None:
        # More than the system holds for a connection: what waits in the
        # engine when the web server closes is the end of the answer.
        trusting = ssl.create_default_context(cafile=self.certificate)
        raw = socket.socket()
        # A client that takes little at a time: the end of the answer
        # is still in the engine when the web server has done with it.
        raw.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8192)
        raw.settimeout(20)
        raw.connect(("127.0.0.1", int(self.port)))
        connection = trusting.wrap_socket(raw, server_hostname="localhost")
        self.addCleanup(connection.close)
        connection.sendall(
            b"GET /huge HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
        )
        received = 0
        while True:
            # Slower than the server sends.
            time.sleep(0.0003)
            more = connection.recv(65536)
            if not more:
                break
            received += len(more)
        self.assertGreater(received, HUGE)

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

    def test_a_browser_that_asks_in_the_clear_is_told_to_ask_over_https(
        self,
    ) -> None:
        # An address typed with http:// and the port of HTTPS: an empty
        # answer says nothing of what to do.
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as plain:
            plain.sendall(b"GET /files HTTP/1.1\r\nHost: localhost\r\n\r\n")
            answer = b""
            while True:
                more = plain.recv(65536)
                if not more:
                    break
                answer += more
        expect(answer.startswith(b"HTTP/1.1 400 ")).to_equal(True)
        expect(b"https://" in answer).to_equal(True)
        # Nothing of the application is said in the clear.
        expect(b"served" in answer).to_equal(False)
        expect(self.seen).to_equal([])

    def test_what_is_neither_tls_nor_a_request_is_hung_up_on(self) -> None:
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as plain:
            plain.sendall(b"\x00\x01\x02 nothing known\r\n\r\n")
            expect(plain.recv(65536)).to_equal(b"")
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

    def test_clients_that_cut_the_line_while_answered_do_not_stop_the_server(
        self,
    ) -> None:
        # The web server writes from several threads: closing a broken
        # connection while one of them wrote to it left both waiting for
        # each other, and nothing was answered any more, on any port.
        # Whether they wait for each other is a matter of chance: what is
        # looked at is what makes it possible, a connection closed by a
        # thread that holds the engine.
        closed_holding_the_engine: List[bool] = []
        really_close = HTTPChannel.handle_close

        def close(channel: Any) -> None:
            closed_holding_the_engine.append(channel._tls_lock._is_owned())
            really_close(channel)

        watched = patch.object(HTTPChannel, "handle_close", close)
        watched.start()
        self.addCleanup(watched.stop)
        careless = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        careless.check_hostname = False
        careless.verify_mode = ssl.CERT_NONE
        for attempt in range(60):
            raw = socket.socket()
            raw.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
            raw.settimeout(5)
            raw.connect(("127.0.0.1", int(self.port)))
            connection = careless.wrap_socket(raw)
            connection.sendall(b"GET /large HTTP/1.1\r\nHost: localhost\r\n\r\n" * 30)
            time.sleep(0.0005 + (attempt % 8) * 0.001)
            # Reset, not closed: the server learns of it while writing.
            connection.setsockopt(
                socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0)
            )
            connection.close()
        after = self._connected()
        after.settimeout(10)
        after.sendall(b"GET /after HTTP/1.1\r\nHost: localhost\r\n\r\n")
        expect(self._answer(after).endswith(b"served 0")).to_equal(True)
        expect(len(closed_holding_the_engine) > 0).to_equal(True)
        expect(any(closed_holding_the_engine)).to_equal(False)

    def test_little_is_kept_encrypted_for_a_client_that_does_not_read(
        self,
    ) -> None:
        # Not the whole of an answer, in the memory of a small board.
        connection = self._connected()
        connection.sendall(b"GET /huge HTTP/1.1\r\nHost: localhost\r\n\r\n")
        time.sleep(1.0)
        kept = [
            len(channel._waiting)
            for channel in list(self.server._map.values())
            if hasattr(channel, "_waiting")
        ]
        expect(len(kept)).to_equal(1)
        self.assertLess(kept[0], 2 * tls._MOST_WAITING)

    def test_a_file_sent_slowly_is_not_taken_for_a_connection_that_says_nothing(
        self,
    ) -> None:
        # Slower than the time a silent connection is given.
        connection = self._connected()
        connection.sendall(
            b"POST /api/upload_file HTTP/1.1\r\nHost: localhost\r\n"
            b"Content-Length: 6\r\n\r\n"
        )
        for piece in (b"a", b"b", b"c", b"d", b"e", b"f"):
            time.sleep(0.5)
            connection.sendall(piece)
        expect(self._answer(connection).endswith(b"served 6")).to_equal(True)

    def test_a_connection_that_failed_while_written_to_is_closed_at_the_next_turn(
        self,
    ) -> None:
        # Noted by the thread that was writing, which may not close it:
        # the thread that runs the connections must be brought to.
        connection = self._connected()
        connection.sendall(b"GET /first HTTP/1.1\r\nHost: localhost\r\n\r\n")
        self._answer(connection)
        channel = next(
            one for one in list(self.server._map.values()) if hasattr(one, "_broken")
        )
        channel._broken = True
        expect(channel.writable()).to_equal(True)
        expect(channel.readable()).to_equal(False)
        self.server.pull_trigger()
        connection.settimeout(5)
        expect(connection.recv(1024)).to_equal(b"")

    def test_what_comes_decrypted_is_not_taken_for_a_greeting_of_tls(self) -> None:
        # The first bytes of a request, read from under TLS, may be any:
        # hanging up on the greeting of TLS is for the port in the clear.
        connection = self._connected()
        connection.sendall(b"\x16\x03\x01 not a request\r\n\r\n")
        answer = self._answer(connection)
        # Answered by the web server as what it is: a request it cannot
        # read.
        expect(answer.startswith(b"HTTP/1.")).to_equal(True)
        expect(b" 400 " in answer.split(b"\r\n")[0]).to_equal(True)

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

    def test_readers_that_read_nothing_do_not_stop_the_answers(self) -> None:
        # As many as there are threads to answer, and one more: each asks
        # for much, several times over, and takes none of it.
        from mariner.server import load

        with patch.object(load, "STALLED_SECS", 1.0):
            readers = [self._connected() for _ in range(5)]
            for deaf in readers:
                deaf.sendall(b"GET /huge HTTP/1.1\r\nHost: localhost\r\n\r\n" * 4)
            time.sleep(0.5)
            other = self._connected()
            other.settimeout(10)
            started = time.monotonic()
            other.sendall(b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n")
            expect(self._answer(other).endswith(b"served 0")).to_equal(True)
            expect(time.monotonic() - started < 9).to_equal(True)
            # Before the server is closed under what still serves them.
            for deaf in readers:
                deaf.close()
            time.sleep(1.5)


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


class ContextTest(TestCase):
    def test_the_old_forms_of_tls_are_left_out_by_mariner_itself(self) -> None:
        # Not by what the system happens to allow.
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        made = tls.context(*_certificate(Path(folder.name)))
        expect(made.minimum_version).to_equal(ssl.TLSVersion.TLSv1_2)

    def test_a_web_server_that_is_no_longer_made_the_same_is_not_served_blind(
        self,
    ) -> None:
        # What is taken over of the web server's connection is its inner
        # workings: a new version that changed them is said at start, not
        # found out by a page that does not open.
        class Changed:
            def handle_read(self) -> None:
                pass

        with self.assertRaises(RuntimeError) as refused:
            tls.secured(Changed, ssl.create_default_context())  # type: ignore
        expect("waitress" in str(refused.exception)).to_equal(True)

    def test_what_is_looked_at_is_the_web_server_s_own_connection(self) -> None:
        # Not only what Mariner's own kind of connection adds to it.
        gone = patch.object(HTTPChannel, "received", None)
        gone.start()
        self.addCleanup(gone.stop)
        with self.assertRaises(RuntimeError) as refused:
            tls.secured(early._Channel, ssl.create_default_context())
        expect("received" in str(refused.exception)).to_equal(True)

    def test_a_key_under_a_password_is_never_asked_for(self) -> None:
        with patch.object(ssl.SSLContext, "load_cert_chain") as loaded:
            tls.context("c.pem", "k.pem")
        answer = loaded.call_args.kwargs["password"]
        # Something to call, that gives nothing: with none, the system
        # asks on the terminal.
        expect(answer()).to_equal("")


@skipUnless(shutil.which("openssl"), "needs the openssl command")
class RenewedCertificateTest(TestCase):
    """A certificate is renewed every other month or so, by a program of
    its own: Mariner takes the new one without being restarted."""

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.certificate, self.key = _certificate(self.folder)
        self.live = tls.context(self.certificate, self.key)
        self.watched = tls.Watched(self.live, self.certificate, self.key)

    def _renewed(self) -> Tuple[str, str]:
        other = self.folder / "new"
        other.mkdir(exist_ok=True)
        return _certificate(other)

    def _put(self, certificate: str, key: str) -> None:
        # As the programs that renew do: each file replaced in one go.
        for made, used in ((certificate, self.certificate), (key, self.key)):
            scratch = used + ".new"
            shutil.copyfile(made, scratch)
            os.replace(scratch, used)

    def _served(self) -> bytes:
        """The certificate a client is shown by a server that uses ``live``."""
        client = ssl.create_default_context()
        client.check_hostname = False
        client.verify_mode = ssl.CERT_NONE
        to_server, to_client = ssl.MemoryBIO(), ssl.MemoryBIO()
        server = self.live.wrap_bio(to_server, to_client, server_side=True)
        asking = client.wrap_bio(to_client, to_server)
        for _ in range(10):
            for side in (asking, server):
                try:
                    side.do_handshake()
                except ssl.SSLWantReadError:
                    pass
        shown = asking.getpeercert(binary_form=True)
        assert shown is not None
        return shown

    def _der(self, certificate: str) -> bytes:
        return ssl.PEM_cert_to_DER_cert(Path(certificate).read_text())

    def test_nothing_changes_while_the_files_do_not(self) -> None:
        with patch.object(self.live, "load_cert_chain") as loaded:
            self.watched.look()
            self.watched.look()
        loaded.assert_not_called()

    def test_a_renewed_certificate_is_taken_at_the_next_look(self) -> None:
        new_certificate, new_key = self._renewed()
        expect(self._served()).to_equal(self._der(self.certificate))
        self._put(new_certificate, new_key)
        with self.assertLogs("mariner.server.tls", level="INFO") as logged:
            self.watched.look()
        expect(self._served()).to_equal(self._der(new_certificate))
        expect("renewed" in " ".join(logged.output)).to_equal(True)

    def test_half_of_a_renewal_leaves_the_one_in_use(self) -> None:
        # Seen between the two files: the certificate is new, its key is
        # not yet.
        new_certificate, new_key = self._renewed()
        before = self._der(self.certificate)
        shutil.copyfile(new_certificate, self.certificate)
        with self.assertLogs("mariner.server.tls", level="ERROR"):
            self.watched.look()
        expect(self._served()).to_equal(before)
        # Said once, not at every look.
        with self.assertNoLogs("mariner.server.tls", level="ERROR"):
            self.watched.look()
        # And taken once whole.
        shutil.copyfile(new_key, self.key)
        self.watched.look()
        expect(self._served()).to_equal(self._der(new_certificate))

    def test_files_that_are_gone_leave_the_one_in_use(self) -> None:
        before = self._der(self.certificate)
        os.unlink(self.key)
        with self.assertLogs("mariner.server.tls", level="ERROR"):
            self.watched.look()
        expect(self._served()).to_equal(before)

    def test_the_server_looks_as_it_goes_round_its_connections(self) -> None:
        looked = threading.Event()
        with patch.object(tls.Watched, "look", side_effect=lambda: looked.set()):
            server = early.create_guarded_server(
                lambda environ, start_response: [],
                host="127.0.0.1",
                port=0,
                cleanup_interval=1,
                asyncore_loop_timeout=1,
                tls=self.live,
                tls_files=(self.certificate, self.key),
            )
            self.addCleanup(server.close)

            def run() -> None:
                try:
                    server.run()
                except OSError:
                    pass

            threading.Thread(target=run, daemon=True).start()
            expect(looked.wait(5)).to_equal(True)
