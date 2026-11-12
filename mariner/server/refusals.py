"""What is said of a request that was not served: to the log, to the client.

Shared by the web server, the application and the SDCP service, and tied
to none of them.
"""

import json
import logging
import time
from typing import Dict, Hashable, Mapping, Optional, Tuple

logger: logging.Logger = logging.getLogger(__name__)


class Sparingly:
    """Decides which of many like events gets a line in the log.

    A page can have a browser knock without end, and a line for each knock
    would fill the drive the log is on. The first of a kind is written,
    then one a minute at most, with how many were not.
    """

    def __init__(self, seconds: float = 60.0, remembered: int = 256) -> None:
        self._seconds = seconds
        self._remembered = remembered
        self._kinds: Dict[Hashable, Tuple[float, int]] = {}

    def unwritten(self, kind: Hashable) -> Optional[int]:
        """None to keep quiet; else how many were kept quiet since the last."""
        now = time.monotonic()
        known = self._kinds.get(kind)
        if known is not None and now - known[0] < self._seconds:
            self._kinds[kind] = (known[0], known[1] + 1)
            return None
        if known is None and len(self._kinds) >= self._remembered:
            # A client can give itself any number of addresses. The
            # oldest known makes room.
            del self._kinds[next(iter(self._kinds))]
        self._kinds[kind] = (now, 0)
        return known[1] if known is not None else 0

    def clear(self) -> None:
        self._kinds.clear()

    def __len__(self) -> int:
        return len(self._kinds)


said = Sparingly()


def log(
    interface: str, peer: Optional[str], code: str, headers: Mapping[str, str]
) -> None:
    """Write a refused request to the log: who, why, and what it said.

    Enough to tell a slicer or a script turned away from a page that was.
    One line a minute for the same client and reason. That holds a page
    knocking through a browser, not a device of the network set on
    filling the log: it can come as any number of clients.
    """
    unwritten = said.unwritten((interface, peer, code))
    if unwritten is None:
        return
    logger.warning(
        "%s: refused a request from %s: %s (Host %s, Origin %s, Referer %s, "
        "Sec-Fetch-Site %s, User-Agent %s; %d more like it not written here "
        "since the last)",
        interface,
        peer,
        code,
        _quoted(headers.get("Host")),
        _quoted(headers.get("Origin")),
        _quoted(headers.get("Referer")),
        _quoted(headers.get("Sec-Fetch-Site")),
        _quoted(headers.get("User-Agent")),
        unwritten,
    )


def _quoted(value: Optional[str]) -> str:
    """What a client wrote, for the log: cut, then quoted.

    In that order, so that the mark that ends it is always there; and in
    one way whatever it holds, so that marks inside it are told from it.
    """
    if value is None:
        return "none"
    return json.dumps(value[:100])


def log_no_room(length: int) -> None:
    unwritten = said.unwritten("no room")
    if unwritten is None:
        return
    logger.warning(
        "Refused an upload of %d bytes: no room for it to wait in "
        "(%d more like it not written here since the last)",
        length,
        unwritten,
    )


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
