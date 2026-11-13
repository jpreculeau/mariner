"""HTTPS for Mariner's page, spoken by the web server itself.

The web server Mariner uses knows nothing of TLS, and a Raspberry Pi
Zero has no room for a second program in front of it. A connection of
the web server is taken as it is, and what it reads and writes goes
through a TLS engine that works on memory: the web server goes on
believing that it reads and writes plain bytes on a socket that never
blocks.
"""

import logging
import os
import re
import ssl
import threading
import time
from typing import Any, Optional, Type

from waitress.channel import HTTPChannel

logger: logging.Logger = logging.getLogger(__name__)

# Encrypted bytes that wait for the client to take them: past this much,
# nothing more is encrypted until some have gone.
_MOST_WAITING = 256 * 1024
# What is read from the engine at a time.
_READ_AT_ONCE = 64 * 1024
# How long a connection that is to be closed may go on sending what is
# left for its client.
_LONGEST_FAREWELL_SECS = 30


def context(certificate: str, key: str) -> ssl.SSLContext:
    """What a server needs to speak TLS with *certificate* and its *key*."""
    made = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    made.minimum_version = ssl.TLSVersion.TLSv1_2
    # A key kept under a password is refused, not asked for on a
    # terminal nobody sits at.
    made.load_cert_chain(certificate, key, password=lambda: "")
    return made


class Watched:
    """A certificate and its key, taken anew when their files change.

    A certificate is renewed every other month or so, by a program of its
    own. ``look`` is called now and then by the thread that speaks TLS;
    connections under way keep the certificate they began with.
    """

    def __init__(self, live: ssl.SSLContext, certificate: str, key: str) -> None:
        self._live = live
        self._files = (certificate, key)
        self._in_use = self._stamp()
        # What was last said to be unusable: said once.
        self._refused: object = None

    def _stamp(self) -> object:
        try:
            found = [os.stat(one) for one in self._files]
        except OSError as error:
            return str(error)
        return [(one.st_mtime_ns, one.st_size, one.st_ino) for one in found]

    def look(self) -> None:
        stamp = self._stamp()
        if stamp == self._in_use or stamp == self._refused:
            return
        try:
            # Whole, and made for each other: looked at apart, so that
            # what is in use is left alone by a pair that is not.
            context(*self._files)
            self._live.load_cert_chain(*self._files, password=lambda: "")
        except (OSError, ssl.SSLError, ValueError) as error:
            self._refused = stamp
            logger.error(
                "The certificate in %s or its key in %s changed and cannot "
                "be used (%s): the one in use is kept",
                *self._files,
                error,
            )
            return
        self._in_use = stamp
        self._refused = None
        logger.info("Took the renewed certificate in %s", self._files[0])


# What is taken over of the web server's connection, and relied on.
_RELIED_ON = (
    "handle_read",
    "handle_write",
    "handle_close",
    "readable",
    "writable",
    "received",
    "send",
    "parser_class",
)
# What a browser that asked in the clear is told, in the clear.
_NOT_IN_THE_CLEAR = (
    b"HTTP/1.1 400 Bad Request\r\n"
    b"Content-Type: text/plain; charset=utf-8\r\n"
    b"Connection: close\r\n"
    b"\r\n"
    b"This port of Mariner speaks HTTPS: the address begins with "
    b"https://, not http://.\r\n"
)
_REQUEST = re.compile(rb"[A-Z]{3,8} \S+ HTTP/1\.[01]\r?\n")


class _Closed(Exception):
    """The client ended the conversation, or spoke something else."""


def secured(base: Type[HTTPChannel], using: ssl.SSLContext) -> Type[HTTPChannel]:
    """A kind of connection like *base* that speaks TLS with *using*."""
    # Of the web server's own connection too: Mariner's kind of it has
    # some of these of its own, which call the web server's.
    missing = [
        name
        for name in _RELIED_ON
        if not callable(getattr(base, name, None))
        or not callable(getattr(HTTPChannel, name, None))
    ]
    if missing:
        # Said at start, not found out by a page that does not open.
        raise RuntimeError(
            "This version of the waitress web server is not made as the one "
            f"Mariner's HTTPS was written for (no {', '.join(missing)}): "
            "install the version Mariner asks for, or set enabled = false "
            "under [https] and put a relay in front of Mariner."
        )

    class Secured(base):  # type: ignore[valid-type, misc]
        def __init__(self, server: Any, sock: Any, addr: Any, adj: Any, **more: Any):
            # One at a time through the engine: the web server reads in
            # one thread and may write from another.
            self._tls_lock = threading.RLock()
            self._arrived = ssl.MemoryBIO()
            self._leaving = ssl.MemoryBIO()
            self._tls = using.wrap_bio(self._arrived, self._leaving, server_side=True)
            self._greeted = False
            # Encrypted, and not yet taken by the client.
            self._waiting = b""
            self._close_asked_at: Optional[float] = None
            # The connection failed while the engine was held: to be
            # closed by the thread that runs the connections.
            self._broken = False
            # Whether anything came from the client yet.
            self._heard = False
            super().__init__(server, sock, addr, adj, **more)

        # -- what the web server asks of a socket ------------------------

        def parser_class(self, adj: Any) -> Any:
            parser = super().parser_class(adj)
            parser.secured = True
            return parser

        def recv(self, buffer_size: int) -> bytes:
            raise NotImplementedError("read through handle_read")

        def handle_read(self) -> None:
            try:
                raw = self.socket.recv(self.adj.recv_bytes)
            except BlockingIOError:
                return
            except OSError:
                self._end()
                return
            if not raw:
                # The client hung up.
                self._end()
                return
            if not self._heard:
                self._heard = True
                if _REQUEST.match(raw):
                    # A browser given http:// with the port of HTTPS.
                    try:
                        self.socket.send(_NOT_IN_THE_CLEAR)
                    except OSError:
                        pass
                    self._end()
                    return
            plain, finished = b"", False
            with self._tls_lock:
                try:
                    self._arrived.write(raw)
                    plain = self._decrypted()
                    self._push()
                except _Closed:
                    finished = True
                except OSError:
                    self._broken = True
                if len(self._waiting) > 2 * _MOST_WAITING:
                    # A client that has the engine answer it again and
                    # again, and takes none of the answers.
                    self._broken = True
            # Never while holding the engine: see ``_end``.
            if self._broken:
                self._end()
            elif finished:
                # Nothing more will come from the client; what is left
                # of an answer still goes to it.
                self.handle_close()
            elif plain:
                self.last_activity = time.time()
                self.received(plain)

        def send(self, data: bytes, do_close: bool = True) -> int:
            """Take *data* to be sent encrypted; how much of it was taken.

            No more than there is room for: what waits encrypted for a
            client slow to take it stays small, however much the web
            server hands over at a time.
            """
            with self._tls_lock:
                if self._broken or not self._greeted:
                    return 0
                room = _MOST_WAITING - len(self._waiting)
                if room <= 0:
                    return 0
                taken = data[:room]
                try:
                    self._tls.write(taken)
                    self._push()
                    return len(taken)
                except (ssl.SSLError, OSError):
                    # Closed by the thread that runs the connections, at
                    # its next turn: see ``writable`` and ``_end``.
                    self._broken = True
                    self._waiting = b""
            return 0

        def writable(self) -> bool:
            return self._broken or bool(self._waiting) or bool(super().writable())

        def handle_write(self) -> None:
            with self._tls_lock:
                if not self._broken:
                    try:
                        self._push()
                    except OSError:
                        self._broken = True
                waiting = bool(self._waiting)
            if self._broken:
                self._end()
                return
            if self._close_asked_at is not None:
                # Only what is left to send keeps it open.
                overdue = time.time() - self._close_asked_at > _LONGEST_FAREWELL_SECS
                if not waiting or overdue:
                    self._end()
                return
            if waiting:
                # Not before the client has what was encrypted for it.
                return
            super().handle_write()

        def readable(self) -> bool:
            if self._close_asked_at is not None or self._broken:
                return False
            if not self._greeted:
                return True
            return bool(super().readable())

        def handle_close(self) -> None:
            """Close, once the client has what was encrypted for it.

            The web server closes as soon as it has handed over the last
            of an answer; handed to the engine, part of it may still wait.
            """
            if self._waiting and self.connected and not self._broken:
                if self._close_asked_at is None:
                    self._close_asked_at = time.time()
                return
            self._end()

        def drop(self) -> None:
            # As the connection it is made of, and with nothing more
            # encrypted for a client that is not to have it: see
            # ``handle_write``, which ends a connection that is broken.
            self._broken = True
            super().drop()

        # -- the engine --------------------------------------------------

        def _end(self) -> None:
            """Close now, whatever waits.

            Never called by a thread that holds the engine (``_tls_lock``):
            closing takes the lock of what the web server has to send, and
            a thread of the web server that holds that one may be waiting
            for the engine. Each would wait for the other for ever, and
            with them every connection, on every port.
            """
            self._waiting = b""
            self._close_asked_at = None
            super().handle_close()

        def _decrypted(self) -> bytes:
            """What the client sent, in the clear; greets it first."""
            try:
                if not self._greeted:
                    try:
                        self._tls.do_handshake()
                    except ssl.SSLWantReadError:
                        return b""
                    self._greeted = True
                pieces = []
                while True:
                    try:
                        piece = self._tls.read(_READ_AT_ONCE)
                    except ssl.SSLWantReadError:
                        break
                    if not piece:
                        if not pieces:
                            raise _Closed()
                        break
                    pieces.append(piece)
                return b"".join(pieces)
            except ssl.SSLZeroReturnError:
                raise _Closed()
            except ssl.SSLError as error:
                # Not TLS at all (a browser asked for http:// on this
                # port), or a client that does not take the certificate.
                logger.debug("TLS with %s failed: %s", self.addr, error)
                raise _Closed()

        def _push(self) -> None:
            """Send the client as much as it takes of what is encrypted."""
            fresh = self._leaving.read()
            if fresh:
                self._waiting += fresh
            while self._waiting:
                try:
                    sent = self.socket.send(self._waiting)
                except BlockingIOError:
                    return
                if not sent:
                    return
                self._waiting = self._waiting[sent:]

    Secured.__name__ = f"Secured{base.__name__}"
    return Secured
