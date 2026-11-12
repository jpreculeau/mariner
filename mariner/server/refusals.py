"""What is said of a request that was not served: to the log, to the client.

Shared by the web server, the application and the SDCP service, and tied
to none of them.
"""

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
            # A client can give itself any number of addresses.
            self._kinds.clear()
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
    What the client wrote is quoted, and cut: it is its text.
    """
    unwritten = said.unwritten((interface, peer, code))
    if unwritten is None:
        return
    logger.warning(
        "%s: refused a request from %s: %s (Host %.100r, Origin %.100r, "
        "Referer %.100r, Sec-Fetch-Site %.40r, User-Agent %.100r; %d more "
        "like it not written here since the last)",
        interface,
        peer,
        code,
        headers.get("Host"),
        headers.get("Origin"),
        headers.get("Referer"),
        headers.get("Sec-Fetch-Site"),
        headers.get("User-Agent"),
        unwritten,
    )


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
