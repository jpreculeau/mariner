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
an address that does nothing is stored like any other. Only the addresses
files are sent to take a body larger than the web server keeps in memory.
A body that does not say how large it is cannot be measured against the
room: it is taken in until the drive is full, and the connection then
closed without an answer.
The application makes them again: this reader belongs to one web server,
and the application must not depend on being run by it.
"""

import json
import logging
import shutil
import tempfile
import time
from typing import Any, Dict, Optional

from waitress import create_server
from waitress.channel import HTTPChannel
from waitress.parser import HTTPRequestParser
from waitress.server import BaseWSGIServer
from waitress.utilities import Error

from mariner.server import origin

logger: logging.Logger = logging.getLogger(__name__)

# Below this the web server keeps a body in memory, not in a file.
_KEPT_IN_MEMORY_BYTES = 512 * 1024

# Left free where uploads wait: that drive is the system's own, and
# filled to the last byte more than uploads would stop working.
KEPT_FREE_BYTES = 64 * 1024 * 1024
# Where a file is sent: the only requests with a body of any size.
UPLOAD_PREFIXES = ("/api/upload_file", "/uvtools/upload/")

# When a refusal for want of room was last written to the log, and how
# many have gone unwritten since.
_room_refusals_said: Dict[str, float] = {}
_SECONDS_BETWEEN_REFUSALS_SAID = 60.0

_REASONS = {
    403: "Forbidden",
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


def copies_kept(content_type: str) -> int:
    """How many times an upload is kept where uploads wait.

    Once by the web server. A form is kept once more as it is taken apart.
    """
    kind = content_type.split(";")[0].strip().lower()
    return 2 if kind == "multipart/form-data" else 1


def room_refusal(length: int, content_type: str) -> Optional[Dict[str, str]]:
    """Why a body of *length* bytes cannot wait where uploads do; else None."""
    if length <= _KEPT_IN_MEMORY_BYTES:
        return None
    try:
        free = shutil.disk_usage(tempfile.gettempdir()).free
    except OSError:
        return None
    if length * copies_kept(content_type) <= free - KEPT_FREE_BYTES:
        return None
    return no_room_body(free)


def no_room_body(free: Optional[int]) -> Dict[str, str]:
    """The answer to an upload there is no room for.

    *free* is the room there was before any of it arrived, when that is
    known: once some of it is stored the figure would mislead.
    """
    room = "" if free is None else f": {free // (1024 * 1024)} MB are free there"
    return {
        "code": "upload_not_stored",
        "title": "File Not Stored",
        "description": "There is not enough room where Mariner keeps a "
        f"file while it arrives{room}. A file sent from the web page needs "
        "twice its size there, one sent by a slicer its size.",
    }


def _too_large_body() -> Dict[str, str]:
    return {
        "code": "request_too_large",
        "title": "Request Too Large",
        "description": "Only a file being sent may be this large, or of no "
        "size said beforehand.",
    }


def _say_no_room(length: int) -> None:
    """Write a refusal for want of room to the log, but not every one."""
    now = time.monotonic()
    last = _room_refusals_said.get("last")
    unwritten = _room_refusals_said.get("unwritten", 0)
    if last is not None and now - last < _SECONDS_BETWEEN_REFUSALS_SAID:
        _room_refusals_said["unwritten"] = unwritten + 1
        return
    _room_refusals_said.update(last=now, unwritten=0)
    logger.warning(
        "Refused an upload of %d bytes: no room for it to wait in "
        "(%d more like it not written here since the last)",
        length,
        unwritten,
    )


class _Parser(HTTPRequestParser):
    def parse_header(self, header_plus: bytes) -> None:
        super().parse_header(header_plus)
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
            self._refuse(403, refusal.body())
            return
        if not self.path.startswith(UPLOAD_PREFIXES) and (
            self.chunked or self.content_length > _KEPT_IN_MEMORY_BYTES
        ):
            self._refuse(413, _too_large_body())
            return
        no_room = room_refusal(self.content_length, headers.get("Content-Type", ""))
        if no_room is not None:
            _say_no_room(self.content_length)
            self._refuse(507, no_room)

    def _refuse(self, code: int, body: Dict[str, str]) -> None:
        self.error = _Refused(code, body)
        self.completed = True


class _Channel(HTTPChannel):
    parser_class = _Parser

    def send_continue(self) -> None:
        """Tell a client that asked first to send its body, if it is wanted.

        Told to go on, a client sends all of a body nobody will read, and
        may never see the refusal that follows.
        """
        request = self.request
        if request is not None and isinstance(request.error, _Refused):
            return
        super().send_continue()


def create_guarded_server(application: Any, **settings: Any) -> BaseWSGIServer:
    """A web server for *application* that refuses before taking a body in."""
    server = create_server(application, **settings)
    # Listening on several addresses makes one server for each.
    listening = (
        [server]
        if isinstance(server, BaseWSGIServer)
        else [one for one in server.map.values() if isinstance(one, BaseWSGIServer)]
    )
    for one in listening:
        one.channel_class = _Channel
    return server


def serve(application: Any, **settings: Any) -> None:
    """As ``waitress.serve``, with the refusals made early."""
    create_guarded_server(application, **settings).run()
