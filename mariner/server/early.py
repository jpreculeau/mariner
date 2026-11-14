"""Refusals made as soon as a request's headers are in, before its body.

The web server takes in the whole body of a request, and keeps it in a
file, before it hands the request to the application. A check made by the
application therefore comes after the body has been waited for and stored:
an upload under a name Mariner does not answer to, or from another site,
or larger than the room there is for it, was refused only once all of it
had arrived.

Here the same checks are made by the web server's own reader of headers,
for a request that has a body, so that what is refused is answered at once
and its body never taken in. Wherever the request is sent: a body sent to
an address that does nothing is stored like any other. Only addresses
that begin as those files are sent to take a body larger than the web
server keeps in memory.
A body that does not say how large it is cannot be measured against the
room: it is taken in until the drive is full, and the connection then
closed without an answer.

The application makes the checks of name and site again, and alone for a
request without a body: this reader belongs to one web server,
and the application must not depend on being run by it.

Here too, since Mariner can be reached from the Internet, what keeps it
standing when leaned on (the figures are in ``mariner.server.load``): who
comes in (``_admitting``), the round that closes connections which ask
nothing (``_tidying``), and the guard against a reader that reads nothing
(``_Channel._flush_outbufs_below_high_watermark``).
"""

import fcntl
import json
import logging
import os
import shutil
import socket
import struct
import tempfile
import termios
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from waitress import create_server
from waitress.channel import ClientDisconnected, HTTPChannel
from waitress.parser import HTTPRequestParser
from waitress.server import BaseWSGIServer
from waitress.utilities import Error

from mariner import config
from mariner.server import load, origin, provenance, refusals

logger: logging.Logger = logging.getLogger(__name__)

# Left free where uploads wait: as Mariner is installed that drive is the
# system's own, and filled to the last byte more than uploads would stop
# working.
KEPT_FREE_BYTES = 64 * 1024 * 1024
# Where a file is sent: the only requests with a body of any size.
UPLOAD_PREFIXES = ("/api/upload_file", "/uvtools/upload/")

# Why a request (its method, path and headers, and the address it came
# from) is not answered until its sender signs in; None if it is. Set by
# whoever starts the server: this module knows nothing of passwords.
password_refusal: Optional[
    Callable[
        [str, str, Dict[str, str], Optional[str]],
        Optional[Dict[str, str]],
    ]
] = None
# Why a request (its path and headers) that came in the clear is not
# answered there; None if it is. Set by whoever starts the server, when
# the page is served over HTTPS.
plain_refusal: Optional[Callable[[str, Dict[str, str]], Optional[Dict[str, str]]]] = (
    None
)

_REASONS = {
    401: "Unauthorized",
    403: "Forbidden",
    503: "Service Unavailable",
    413: "Request Entity Too Large",
    507: "Insufficient Storage",
}


class _Refused(Error):
    """An answer the web server gives by itself, in Mariner's form."""

    def __init__(self, code: int, body: Dict[str, str]) -> None:
        super().__init__(json.dumps(body))
        self.code = code
        self.reason = _REASONS[code]

    def to_response(self, ident: Optional[str] = None) -> Any:
        headers = [("Content-Type", "application/json")]
        headers.extend(origin.ANSWER_HEADERS.items())
        return f"{self.code} {self.reason}", headers, self.body.encode("utf-8")


def files_share_the_drive() -> bool:
    """Whether files are kept on the drive uploads wait on.

    Not as Mariner is installed: files go to a drive of their own.
    """
    try:
        waiting = os.stat(tempfile.gettempdir()).st_dev
        kept = os.stat(config.get_files_directory()).st_dev
    except OSError:
        return False
    return waiting == kept


def copies_kept(content_type: str) -> int:
    """How many times an upload is on the drive uploads wait on, at most.

    Once by the web server. A form is kept once more as it is taken apart.
    The file itself is one more where files are kept on that same drive.
    """
    kind = content_type.split(";")[0].strip().lower()
    copies = 2 if kind == "multipart/form-data" else 1
    return copies + 1 if files_share_the_drive() else copies


def room_refusal(
    length: int, content_type: str, kept_in_memory: int, peer: Optional[str] = None
) -> Optional[Dict[str, str]]:
    """Why a body of *length* bytes cannot wait where uploads do; else None.

    Below *kept_in_memory* bytes the web server does not put it in a file.
    """
    if length < kept_in_memory:
        return None
    try:
        free = shutil.disk_usage(tempfile.gettempdir()).free
    except OSError:
        return None
    if length * copies_kept(content_type) <= free - KEPT_FREE_BYTES:
        return None
    refusals.log_no_room(length, peer, free, tempfile.gettempdir())
    return refusals.no_room_body(free, KEPT_FREE_BYTES)


def _too_large_body() -> Dict[str, str]:
    return {
        "code": "request_too_large",
        "title": "Request Too Large",
        "description": "Only a file being sent may be this large, or of no "
        "size said beforehand.",
    }


class _Parser(HTTPRequestParser):
    # Whose request this is, for the log. Set by the channel.
    peer: Optional[str] = None
    # Whether it came over TLS. Set by the channel.
    secured: bool = False

    def parse_header(self, header_plus: bytes) -> None:
        super().parse_header(header_plus)
        if self.secured:
            # What the application is told the request came by.
            self.url_scheme = "https"
        if (
            self.error is not None
            or self.content_length > self.adj.max_request_body_size
        ):
            # Refused by the web server itself: malformed, or larger than
            # anything may be.
            return
        if not self.content_length and not self.chunked:
            # No body to spare the drive: the application answers, and has
            # more to say to a person than is said here.
            return
        # As the application will see them: "SEC_FETCH_SITE" for
        # "Sec-Fetch-Site".
        headers = {
            name.replace("_", "-").title(): value
            for name, value in self.headers.items()
        }
        # Wherever it is sent: a body is stored whether or not anything
        # at that address would read it.
        refusal = origin.body_refusal(self.path, headers)
        if refusal is not None:
            self._log(refusal.code, headers)
            self._refuse(403, refusal.body())
            return
        not_local = provenance.refusal(self.path, self.peer)
        if not_local is not None:
            self._log(not_local["code"], headers)
            self._refuse(403, not_local)
            return
        if plain_refusal is not None and not self.secured:
            in_the_clear = plain_refusal(self.path, headers)
            if in_the_clear is not None:
                self._refuse(403, in_the_clear)
                return
        if password_refusal is not None:
            not_signed_in = password_refusal(
                self.command, self.path, headers, self.peer
            )
            if not_signed_in is not None:
                # Not written to the log: it is what a page left open
                # past its session sends, and says nothing of an attack.
                shut = not_signed_in.get("code") == "state_unavailable"
                self._refuse(503 if shut else 401, not_signed_in)
                return
        # Below this the web server keeps a body in memory, not in a file.
        kept_in_memory = self.adj.inbuf_overflow
        if not self.path.startswith(UPLOAD_PREFIXES) and (
            self.chunked or self.content_length >= kept_in_memory
        ):
            self._log("request_too_large", headers)
            self._refuse(413, _too_large_body())
            return
        no_room = room_refusal(
            self.content_length,
            headers.get("Content-Type", ""),
            kept_in_memory,
            self.peer,
        )
        if no_room is not None:
            self._refuse(507, no_room)

    def _log(self, code: str, headers: Dict[str, str]) -> None:
        refusals.log("Web", self.peer, code, headers, self.command, self.path)

    def _refuse(self, code: int, body: Dict[str, str]) -> None:
        self.error = _Refused(code, body)
        self.completed = True


class _Channel(HTTPChannel):
    # Whether anything came from the client yet. A connection over TLS
    # (see mariner.server.tls) sets it on what comes encrypted, before
    # anything reaches ``received``: what it decrypts is never looked at
    # here as the first bytes of a connection.
    _heard = False
    # Whether it ever asked for something: see mariner.server.load.
    _asked = False
    # Its reader reads nothing any more: to be closed, by the thread
    # that closes.
    _gone = False
    # Since when a request has been coming without the end of its
    # headers; None when none is.
    _headers_since: Optional[float] = None
    # More was asked at once, from the Internet, than is answered: closed
    # once what is answered has been.
    _cut_short = False
    # How many of the requests last received have been answered.
    _answered_of_these = 0

    def _address(self) -> Optional[str]:
        return str(self.addr[0]) if isinstance(self.addr, tuple) else None

    def drop(self) -> None:
        """Have this connection closed, whatever is left to send.

        Not closed here: this is called as the connections are gone
        round, while the web server is listing those it will wait on. One
        closed under it is still on that list, and waiting on a closed
        connection brings the whole server down. So it is marked and
        hung up on; the web server then finds it ended, as it does one
        its client left, and closes it where it closes the others.
        """
        self.will_close = True
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            # Gone already.
            pass

    def _left_to_take(self) -> int:
        """How much of what was asked for its reader has yet to take:
        what waits here, and what the computer holds for it."""
        left = int(self.total_outbufs_len) + len(getattr(self, "_waiting", b""))
        try:
            held = fcntl.ioctl(self.socket.fileno(), termios.TIOCOUTQ, b"\0" * 4)
            left += int(struct.unpack("i", held)[0])
        except (OSError, ValueError, AttributeError):
            # Not told on this system: what waits here will have to do.
            pass
        return left

    def write_soon(self, data: Any) -> int:
        """As the web server's, for a reader that still reads."""
        if self._gone:
            raise ClientDisconnected
        written = int(super().write_soon(data))
        if self._gone:
            raise ClientDisconnected
        return written

    def _flush_outbufs_below_high_watermark(self) -> None:
        """As the web server's, without waiting for ever on a reader.

        What serves a request waits here, when much is left to send, for
        the reader to take some of it. One that asks for much and reads
        nothing would hold it for good, and a few of them everything
        Mariner has to serve with. Past ``load.stalled_after`` without a
        byte taken, the reader is taken for gone: nothing more is written
        for it (see ``write_soon``) and the connection is closed at the
        next round (see ``_tidying``).
        """
        if self._gone or self.total_outbufs_len <= self.adj.outbuf_high_watermark:
            return
        with self.outbuf_lock:
            (_, exception) = self._flush_exception(self._flush_some, do_close=False)
            left = self._left_to_take()
            since = time.monotonic()
            patience = load.stalled_after(self._address())
            while self.connected and (
                exception or self.total_outbufs_len > self.adj.outbuf_high_watermark
            ):
                try:
                    self.server.pull_trigger()
                except OSError:
                    # The server is being closed under it.
                    return
                self.outbuf_lock.wait(min(1.0, patience))
                if exception:
                    # The thread that closes has been told.
                    return
                now = time.monotonic()
                still = self._left_to_take()
                if still < left:
                    left = still
                    since = now
                elif now - since > patience:
                    self._gone = True
                    logger.warning(
                        "%s reads nothing of what it asked for: closed",
                        self.addr[0] if isinstance(self.addr, tuple) else self.addr,
                    )
                    return

    def received(self, data: bytes) -> bool:
        if not self._heard:
            self._heard = True
            if data[:2] == b"\x16\x03":
                # The greeting of TLS: a browser given https:// with the
                # port that is in the clear. Left to wait for the end of
                # headers that never come, it would for half a minute.
                self.will_close = True
                return False
        self._answered_of_these = 0
        took = bool(super().received(data))
        request = self.request
        if request is None or request.headers_finished:
            self._headers_since = None
        elif self._headers_since is None:
            self._headers_since = time.time()
        if request is not None and request.headers_finished:
            # Something is being sent: whole requests are seen by
            # ``service``, which may already have answered them.
            self._asked = True
        self._hold_to_a_few()
        return took

    def _hold_to_a_few(self) -> None:
        """Answer only a few of the requests the Internet sent in one go.

        See ``load.ASKED_AT_ONCE``. Those past them are let go of, and the
        connection is closed once the few are answered: it cannot be told
        which of its requests were dropped.
        """
        if len(self.requests) <= load.ASKED_AT_ONCE:
            return
        if provenance.is_local(self._address()):
            return
        with self.requests_lock:
            # Less those already answered since they came. Never the
            # first of those left: it may be the one being answered.
            few = max(1, load.ASKED_AT_ONCE - self._answered_of_these)
            dropped = self.requests[few:]
            del self.requests[few:]
            self._cut_short = True
        for request in dropped:
            request.close()

    def service(self) -> None:
        self._asked = True
        super().service()
        self._answered_of_these += 1
        if self._cut_short:
            with self.requests_lock:
                if not self.requests:
                    self.close_when_flushed = True
            try:
                self.server.pull_trigger()
            except OSError:
                # The server is being closed under it.
                pass

    def parser_class(self, adj: Any) -> _Parser:
        """A reader of headers that knows whose request it reads.

        In the place of the class the web server keeps under this name
        and calls to make one.
        """
        parser = _Parser(adj)
        parser.peer = str(self.addr[0])
        return parser

    def send_continue(self) -> None:
        """Tell a client that asked first to send its body, if it is wanted.

        Told to go on, a client sends all of a body nobody will read, and
        may never see the refusal that follows. Refused here, or by the
        web server itself as larger than anything may be.
        """
        request = self.request
        if request is not None and request.completed:
            # Nothing more is wanted: refused, here or by the web server
            # itself; or no body announced, in which case the web server
            # would wait for one all the same.
            return
        super().send_continue()


def create_guarded_server(
    application: Any,
    tls: Optional[Any] = None,
    tls_port: Optional[int] = None,
    tls_files: Optional[Tuple[str, str]] = None,
    **settings: Any,
) -> BaseWSGIServer:
    """A web server for *application* that refuses before taking a body in.

    With *tls* (see ``mariner.server.tls.context``) it speaks HTTPS: on
    every port it listens on, or on *tls_port* alone when one is named.
    With *tls_files*, the certificate and key *tls* was made of, they are
    taken anew when they change.
    """
    _check_the_web_server()
    # How often the connections are gone round: see ``_tidying``.
    settings.setdefault("cleanup_interval", 5)
    server = create_server(application, **settings)
    # Listening on several addresses makes one server for each.
    listening = (
        [server]
        if isinstance(server, BaseWSGIServer)
        else [one for one in server.map.values() if isinstance(one, BaseWSGIServer)]
    )
    door = load.Door()
    renewed: Optional[Callable[[], None]] = None
    if tls is not None and tls_files is not None:
        from mariner.server.tls import Watched

        # Its files are looked at as the connections are gone round.
        renewed = Watched(tls, *tls_files).look
    for one in listening:
        channels: Any = _Channel
        # Named as a number or, listening on several, as text.
        if tls is not None and (
            tls_port is None or int(one.effective_port) == int(tls_port)
        ):
            from mariner.server.tls import secured

            channels = secured(_Channel, tls)
        one.channel_class = _admitting(channels, door, listening)
        one.maintenance = _tidying(one, one.maintenance, renewed)
        # Once a round, whatever the number of ports.
        renewed = None
    return server


# What is taken over, or called, of the web server's inner workings.
_RELIED_ON = {
    HTTPChannel: (
        "write_soon",
        "_flush_outbufs_below_high_watermark",
        "_flush_exception",
        "_flush_some",
        "received",
        "service",
        "send_continue",
        "handle_close",
    ),
    BaseWSGIServer: ("maintenance", "pull_trigger"),
}


def _check_the_web_server() -> None:
    """Say at start that the web server is no longer made the same.

    The guards of this module stand on names it does not promise to
    keep. Renamed, they would be passed by without a word: Mariner would
    start, and hold nothing.
    """
    for made, names in _RELIED_ON.items():
        for name in names:
            if not callable(getattr(made, name, None)):
                raise RuntimeError(
                    f"waitress is not made as Mariner expects: its "
                    f"{made.__name__} has no {name}. Mariner needs a "
                    "version of waitress it was tried with (3.0)"
                )


def _held(servers: List[BaseWSGIServer]) -> List[Any]:
    """Where the connections open at this moment come from."""
    return [
        channel.addr[0] if isinstance(channel.addr, tuple) else None
        for one in servers
        for channel in list(one.active_channels.values())
    ]


def _admitting(channels: Any, door: load.Door, servers: List[BaseWSGIServer]) -> Any:
    """What the web server calls with a new connection: *channels*, for
    those *door* lets in. See ``mariner.server.load``."""

    def admit(
        server: Any, connection: Any, addr: Any, adj: Any, map: Any = None
    ) -> Any:
        address = addr[0] if isinstance(addr, tuple) else None
        if not door.admits(address, _held(servers)):
            _say_turned_away(address)
            connection.close()
            return None
        return channels(server, connection, addr, adj, map=map)

    # For who wants to know what the connections let in are made of.
    admit.channels = channels  # type: ignore[attr-defined]
    return admit


# Said once in a while, with how many: not a line for each.
_turned_away = {"count": 0, "said_at": 0.0}


def _say_turned_away(address: object) -> None:
    _turned_away["count"] += 1
    now = time.monotonic()
    if _turned_away["said_at"] and now - _turned_away["said_at"] < 60:
        return
    logger.warning(
        "Too many connections from the Internet: %d turned away, the last " "from %s",
        _turned_away["count"],
        address,
    )
    _turned_away["count"] = 0
    _turned_away["said_at"] = now


def _tidying(
    server: BaseWSGIServer,
    usual: Callable[[float], None],
    also: Optional[Callable[[], None]] = None,
) -> Any:
    """The web server's round of its connections, and Mariner's after it:
    those whose reader is gone, and those of the Internet that ask nothing
    (see ``mariner.server.load``). Run by the thread that closes."""

    def maintenance(now: float) -> None:
        usual(now)
        if also is not None:
            also()
        for channel in list(server.active_channels.values()):
            address = channel.addr[0] if isinstance(channel.addr, tuple) else None
            coming_since = getattr(channel, "_headers_since", None)
            if (
                getattr(channel, "_gone", False)
                or (
                    not channel.requests
                    and load.outstayed(
                        address,
                        getattr(channel, "_asked", True),
                        channel.creation_time,
                        channel.last_activity,
                        now,
                    )
                )
                # A byte now and then would hold a place for good.
                or (
                    coming_since is not None
                    and load.outstayed(address, False, coming_since, now, now)
                )
            ):
                channel.drop()

    return maintenance


def serve(
    application: Any,
    once_listening: Optional[Callable[[], None]] = None,
    **settings: Any,
) -> None:
    """As ``waitress.serve``, with the refusals made early.

    *once_listening* is called when the ports are had, before anything
    is served.
    """
    server = create_guarded_server(application, **settings)
    if once_listening is not None:
        once_listening()
    server.run()
