"""Refusals made as soon as a request's headers are in, before its body.

The web server takes in the whole body of a request, and keeps it in a
file, before it hands the request to the application. A check made by the
application therefore comes after the body has been waited for and stored:
an upload under a name Mariner does not answer to, or from another site,
or larger than the room there is for it, was refused only once all of it
had arrived.

Here the same checks are made by the web server's own reader of headers,
for a request that has a body, so that what is refused is answered at once
and its body never taken in. A body that does not say how large it is
cannot be measured against the room: it is taken in until the drive is
full, and the connection then closed without an answer.
The application makes them again: this reader belongs to one web server,
and the application must not depend on being run by it.
"""

import json
import logging
import shutil
import tempfile
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

_REASONS = {403: "Forbidden", 507: "Insufficient Storage"}


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
    if length * copies_kept(content_type) <= free:
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


class _Parser(HTTPRequestParser):
    def parse_header(self, header_plus: bytes) -> None:
        super().parse_header(header_plus)
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
        refusal = origin.request_refusal(self.path, headers)
        if refusal is not None:
            self._refuse(403, refusal.body())
            return
        no_room = room_refusal(self.content_length, headers.get("Content-Type", ""))
        if no_room is not None:
            logger.warning(
                "Refused an upload of %d bytes: no room for it to wait in",
                self.content_length,
            )
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
