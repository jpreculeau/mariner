"""Holding when strangers lean on the door."""

import shutil
import socket
import ssl
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List
from unittest import TestCase, skipUnless
from unittest.mock import patch

from pyexpect import expect

from mariner.server import early, load, tls

OUTSIDE = "203.0.113.5"
OTHER = "198.51.100.9"
HOME = "192.168.1.20"


class DoorTest(TestCase):
    def setUp(self) -> None:
        self.door = load.Door()

    def test_the_local_network_always_comes_in(self) -> None:
        crowd = [OUTSIDE] * 500 + [HOME] * 50
        for moment in range(500):
            expect(self.door.admits(HOME, crowd, now=moment / 100)).to_equal(True)

    def test_one_address_of_the_internet_holds_only_so_many(self) -> None:
        held = [OUTSIDE] * (load.PER_ADDRESS - 1)
        expect(self.door.admits(OUTSIDE, held, now=0.0)).to_equal(True)
        held.append(OUTSIDE)
        expect(self.door.admits(OUTSIDE, held, now=1.0)).to_equal(False)
        # Which takes nothing from another.
        expect(self.door.admits(OTHER, held, now=1.0)).to_equal(True)

    def test_over_ipv6_one_network_is_one_address(self) -> None:
        # Whoever has one has billions of them.
        held = [f"2001:db8:1:2::{n:x}" for n in range(1, load.PER_ADDRESS + 1)]
        expect(self.door.admits("2001:db8:1:2:ffff::9", held, now=0.0)).to_equal(False)
        expect(self.door.admits("2001:db8:1:3::9", held, now=0.0)).to_equal(True)
        door = load.Door()
        for knock in range(load.KNOCKS_PER_ADDRESS):
            door.admits(f"2001:db8:5:5::{knock + 1:x}", [], now=0.0)
        expect(door.admits("2001:db8:5:5:abcd::1", [], now=1.0)).to_equal(False)

    def test_the_internet_as_a_whole_leaves_room_for_the_local_network(self) -> None:
        held = [f"203.0.{n // 250}.{n % 250}" for n in range(load.FROM_INTERNET)]
        expect(self.door.admits(OTHER, held, now=0.0)).to_equal(False)
        expect(self.door.admits(HOME, held, now=0.0)).to_equal(True)
        expect(self.door.admits(OTHER, held[1:], now=0.0)).to_equal(True)

    def test_one_address_knocks_only_so_often(self) -> None:
        # Each new connection over HTTPS costs the computer some work.
        for knock in range(load.KNOCKS_PER_ADDRESS):
            expect(self.door.admits(OUTSIDE, [], now=knock / 100)).to_equal(True)
        expect(self.door.admits(OUTSIDE, [], now=1.0)).to_equal(False)
        expect(self.door.admits(OTHER, [], now=1.0)).to_equal(True)
        # And again once those are old.
        later = load.KNOCKS_WITHIN_SECS + 1.0
        expect(self.door.admits(OUTSIDE, [], now=later)).to_equal(True)

    def test_nor_does_the_internet_as_a_whole(self) -> None:
        for knock in range(load.KNOCKS_FROM_INTERNET):
            address = f"203.0.{knock // 250}.{knock % 250}"
            expect(self.door.admits(address, [], now=0.0)).to_equal(True)
        expect(self.door.admits(OTHER, [], now=1.0)).to_equal(False)
        expect(self.door.admits(HOME, [], now=1.0)).to_equal(True)

    def test_one_turned_away_is_not_one_more_knock(self) -> None:
        for knock in range(load.KNOCKS_PER_ADDRESS * 5):
            self.door.admits(OUTSIDE, [], now=0.0)
        later = load.KNOCKS_WITHIN_SECS + 0.5
        expect(self.door.admits(OUTSIDE, [], now=later)).to_equal(True)

    def test_what_it_remembers_does_not_grow_without_end(self) -> None:
        for knock in range(20000):
            address = f"2001:db8:{knock:x}::1"
            self.door.admits(address, [], now=knock / 10)
        expect(self.door.remembered() <= load.KNOCKS_FROM_INTERNET).to_equal(True)


class RoomTest(TestCase):
    def test_the_internet_is_left_less_than_half_of_the_room(self) -> None:
        from mariner import server

        expect(load.FROM_INTERNET * 2 < server.CONNECTION_LIMIT).to_equal(True)
        expect(load.PER_ADDRESS < load.FROM_INTERNET).to_equal(True)


class _Served(TestCase):
    """A real server, on a port of this computer."""

    BODY = b"served"
    SETTINGS: Dict[str, Any] = {}

    def setUp(self) -> None:
        def application(environ: Dict[str, Any], start_response: Any) -> List[bytes]:
            start_response("200 OK", [("Content-Length", str(len(self.BODY)))])
            return [self.BODY]

        self.server = early.create_guarded_server(
            application, host="127.0.0.1", port=0, **self._settings()
        )
        self.port = int(self.server.effective_port)

        self.raised: List[BaseException] = []
        self.closing = False

        def run() -> None:
            try:
                self.server.run()
            except BaseException as error:
                # Closed under it at the end of the test, and nothing else:
                # a server that falls is not one that holds.
                if not self.closing:
                    self.raised.append(error)

        threading.Thread(target=run, daemon=True).start()
        self.addCleanup(self._close)

    def _settings(self) -> Dict[str, Any]:
        return dict(self.SETTINGS)

    def _close(self) -> None:
        self.closing = True
        self.server.close()
        expect(self.raised).to_equal([])

    def _still_answers(self) -> None:
        """The server goes on, after what it did to one connection."""
        # Past the round in which a connection closed would be met again.
        time.sleep(1.5)
        expect(self.raised).to_equal([])
        answer = self._asked(self._connected())
        expect(answer.startswith(b"HTTP/1.1 200")).to_equal(True)

    def _connected(self, receive_buffer: int = 0) -> socket.socket:
        connection = socket.socket()
        if receive_buffer:
            connection.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, receive_buffer)
        connection.settimeout(8)
        connection.connect(("127.0.0.1", self.port))
        self.addCleanup(connection.close)
        return connection

    def _asked(self, connection: socket.socket) -> bytes:
        connection.sendall(b"GET / HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
        # The whole of a short answer, which can come in two pieces: what
        # is left of it would be taken later for something said.
        answer = b""
        try:
            while not answer.endswith(self.BODY[-64:]) or b"\r\n\r\n" not in answer:
                piece = connection.recv(65536)
                if not piece:
                    break
                answer += piece
                if len(self.BODY) > 65536:
                    # Enough to know it is answered.
                    break
        except (ConnectionError, socket.timeout):
            pass
        return answer

    def _is_shut(self, connection: socket.socket, within: float) -> bool:
        connection.settimeout(within)
        try:
            return connection.recv(1) == b""
        except ConnectionError:
            return True
        except socket.timeout:
            return False

    def _is_shut_for_good(self, connection: socket.socket, within: float) -> bool:
        """As ``_is_shut``, for one that has much left to read first."""
        connection.settimeout(within)
        until = time.monotonic() + within
        try:
            while time.monotonic() < until:
                if connection.recv(1024 * 1024) == b"":
                    return True
        except ConnectionError:
            return True
        except socket.timeout:
            return False
        return False


class CrowdAtTheDoorTest(_Served):
    def test_one_address_of_the_internet_is_held_to_its_share(self) -> None:
        with patch.object(early.provenance, "is_local", return_value=False):
            held = [self._connected() for _ in range(load.PER_ADDRESS)]
            for one in held:
                expect(self._asked(one).startswith(b"HTTP/1.1 200")).to_equal(True)
            more = self._connected()
            expect(self._asked(more)).to_equal(b"")

    def test_the_local_network_is_not(self) -> None:
        held = [self._connected() for _ in range(load.PER_ADDRESS + 3)]
        for one in held:
            expect(self._asked(one).startswith(b"HTTP/1.1 200")).to_equal(True)


class SilentVisitorTest(_Served):
    SETTINGS = {"cleanup_interval": 1, "asyncore_loop_timeout": 1}

    def test_one_from_the_internet_that_asks_nothing_is_not_kept(self) -> None:
        # Each holds a place, at no cost to who holds it.
        with patch.object(
            early.provenance, "is_local", return_value=False
        ), patch.object(load, "FIRST_REQUEST_SECS", 0.5):
            silent = self._connected()
            half = self._connected()
            half.sendall(b"GET / HTTP/1.1\r\nHost: 127.0")
            expect(self._is_shut(silent, within=5)).to_equal(True)
            expect(self._is_shut(half, within=5)).to_equal(True)
        self._still_answers()

    def test_one_that_asked_is_kept_a_while_and_not_for_long(self) -> None:
        with patch.object(
            early.provenance, "is_local", return_value=False
        ), patch.object(load, "FIRST_REQUEST_SECS", 0.5), patch.object(
            load, "IDLE_SECS", 3.0
        ):
            asked = self._connected()
            expect(self._asked(asked).startswith(b"HTTP/1.1 200")).to_equal(True)
            expect(self._is_shut(asked, within=1.5)).to_equal(False)
            expect(self._is_shut(asked, within=6)).to_equal(True)
        self._still_answers()

    def test_one_that_asked_cannot_take_for_ever_over_the_next(self) -> None:
        # A byte now and then: it would hold its place for good.
        with patch.object(
            early.provenance, "is_local", return_value=False
        ), patch.object(load, "FIRST_REQUEST_SECS", 1.0), patch.object(
            load, "IDLE_SECS", 30.0
        ):
            slow = self._connected()
            expect(self._asked(slow).startswith(b"HTTP/1.1 200")).to_equal(True)
            started = time.monotonic()
            shut = False
            for piece in b"GET / HTTP/1.1\r\nHost: 12":
                try:
                    slow.sendall(bytes([piece]))
                except ConnectionError:
                    shut = True
                    break
                if self._is_shut(slow, within=0.4):
                    shut = True
                    break
            expect(shut).to_equal(True)
            expect(time.monotonic() - started < 6).to_equal(True)
        self._still_answers()

    def test_the_local_network_is_left_its_time(self) -> None:
        with patch.object(load, "FIRST_REQUEST_SECS", 0.5):
            silent = self._connected()
            expect(self._is_shut(silent, within=3)).to_equal(False)


class ReaderThatDoesNotReadTest(_Served):
    # More than the computer's own buffers swallow.
    BODY = b"x" * (24 * 1024 * 1024)
    SETTINGS = {
        "threads": 1,
        "outbuf_high_watermark": 65536,
        "cleanup_interval": 1,
        "asyncore_loop_timeout": 1,
    }

    def test_it_does_not_keep_the_others_waiting(self) -> None:
        # Asked for much, several times over, by who then reads nothing:
        # what serves it would wait for ever, and with it everybody else.
        with patch.object(load, "STALLED_SECS", 1.0):
            deaf = self._connected(receive_buffer=4096)
            deaf.sendall(b"GET / HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n" * 4)
            time.sleep(0.5)
            other = self._connected()
            started = time.monotonic()
            answer = self._asked(other)
            expect(answer.startswith(b"HTTP/1.1 200")).to_equal(True)
            expect(time.monotonic() - started < 6).to_equal(True)
            # And is closed at the next round, which the server outlives.
            expect(self._is_shut_for_good(deaf, within=6)).to_equal(True)
        self._still_answers()

    def test_one_that_reads_slowly_is_served_to_the_end(self) -> None:
        with patch.object(load, "STALLED_SECS", 1.0):
            slow = self._connected(receive_buffer=32768)
            slow.sendall(b"GET / HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n" * 2)
            taken = 0
            wanted = 2 * len(self.BODY)
            started = time.monotonic()
            while taken < wanted:
                piece = slow.recv(1024 * 1024)
                if not piece:
                    break
                taken += len(piece)
                # Slower than it could, never still for long.
                time.sleep(0.004)
            expect(taken >= wanted).to_equal(True)
            # Long enough to have been taken for gone, had it been.
            expect(time.monotonic() - started > 2.5).to_equal(True)


@skipUnless(shutil.which("openssl"), "needs the openssl command")
class SilentVisitorOverTlsTest(_Served):
    SETTINGS = {"cleanup_interval": 1, "asyncore_loop_timeout": 1}

    def _settings(self) -> Dict[str, Any]:
        from mariner.server.tests.test_tls import _certificate

        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.certificate, key = _certificate(Path(folder.name))
        return {**self.SETTINGS, "tls": tls.context(self.certificate, key)}

    def _greeted(self) -> ssl.SSLSocket:
        trusting = ssl.create_default_context(cafile=self.certificate)
        secured = trusting.wrap_socket(self._connected(), server_hostname="localhost")
        self.addCleanup(secured.close)
        return secured

    def _asked(self, connection: socket.socket) -> bytes:
        return super()._asked(
            connection
            if isinstance(connection, ssl.SSLSocket)
            else self._greet(connection)
        )

    def _greet(self, connection: socket.socket) -> ssl.SSLSocket:
        trusting = ssl.create_default_context(cafile=self.certificate)
        return trusting.wrap_socket(connection, server_hostname="localhost")

    def test_one_that_says_nothing_or_only_greets_is_not_kept(self) -> None:
        with patch.object(
            early.provenance, "is_local", return_value=False
        ), patch.object(load, "FIRST_REQUEST_SECS", 0.5):
            silent = self._connected()
            greeted = self._greeted()
            expect(self._is_shut(silent, within=5)).to_equal(True)
            expect(self._is_shut(greeted, within=5)).to_equal(True)
        self._still_answers()


class WebServerStillMadeTheSameTest(TestCase):
    def test_what_is_relied_on_of_the_web_server_is_looked_for_at_start(self) -> None:
        # Its inner workings: a version that renamed one would leave the
        # guards above doing nothing, and nobody the wiser.
        from waitress.channel import HTTPChannel

        gone = patch.object(HTTPChannel, "_flush_outbufs_below_high_watermark", None)
        gone.start()
        self.addCleanup(gone.stop)
        with self.assertRaises(RuntimeError) as refused:
            early.create_guarded_server(
                lambda environ, start_response: [], host="127.0.0.1", port=0
            )
        expect("waitress" in str(refused.exception)).to_equal(True)
