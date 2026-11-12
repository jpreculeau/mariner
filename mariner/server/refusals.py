"""What is said of a request that was not served: to the log, to the client.

Shared by the web server, the application and the SDCP service, and tied
to none of them.
"""

import json
import logging
import threading
import time
from typing import Dict, Hashable, Mapping, Optional, Tuple
from urllib.parse import urlsplit

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
        # Asked from the web server's threads and from SDCP's at once.
        self._lock = threading.Lock()

    def unwritten(self, kind: Hashable) -> Optional[int]:
        """None to keep quiet; else how many were kept quiet since the last."""
        now = time.monotonic()
        with self._lock:
            known = self._kinds.get(kind)
            if known is not None and now - known[0] < self._seconds:
                self._kinds[kind] = (known[0], known[1] + 1)
                return None
            if known is None and len(self._kinds) >= self._remembered:
                # A client can give itself any number of addresses. The
                # one written longest ago makes room.
                del self._kinds[next(iter(self._kinds))]
            # Put last: they are kept in the order they were written in.
            self._kinds.pop(kind, None)
            self._kinds[kind] = (now, 0)
            return known[1] if known is not None else 0

    def clear(self) -> None:
        with self._lock:
            self._kinds.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._kinds)


said = Sparingly()


# What a browser, a player of sound or video or a reader of feeds says
# with a request, and a slicer has no cause to.
NOT_SAID_BY_SLICERS = frozenset(
    ("accept-language", "range", "icy-metadata", "purpose", "sec-purpose")
)


def log(
    interface: str,
    peer: Optional[str],
    code: str,
    headers: Mapping[str, str],
    method: Optional[str] = None,
    path: Optional[str] = None,
) -> None:
    """Write a refused request to the log: who, what, why, and what it said.

    Enough to tell a slicer or a script turned away from a page that was.
    One line a minute for the same client and reason. That holds a page
    knocking through a browser, not a device of the network set on
    filling the log: it can come as any number of clients.
    """
    unwritten = said.unwritten((interface, peer, code))
    if unwritten is None:
        return
    also = sorted(name.lower() for name in headers.keys())
    also = [name for name in also if name in NOT_SAID_BY_SLICERS]
    logger.warning(
        "%s: refused %s %s from %s: %s (Host %s, Origin %s, Referer %s, "
        "Sec-Fetch-Site %s, User-Agent %s, also sent: %s; %d more like it not "
        "written here since the last)",
        interface,
        (method or "a request")[:16],
        _quoted(path) if path is not None else "",
        peer,
        code,
        _quoted(headers.get("Host")),
        _quoted(headers.get("Origin")),
        _quoted(_site_of(headers.get("Referer"))),
        _quoted(headers.get("Sec-Fetch-Site")),
        _quoted(headers.get("User-Agent")),
        ", ".join(also) or "none",
        unwritten,
    )


def _site_of(page: Optional[str]) -> Optional[str]:
    """The site a page address is on. The rest is where someone was there."""
    if page is None:
        return None
    try:
        parts = urlsplit(page)
    except ValueError:
        return "unreadable"
    try:
        name, port = parts.hostname, parts.port
    except ValueError:
        return "unreadable"
    if not parts.scheme or not name:
        return "unreadable"
    # Without the name and password an address can carry.
    return f"{parts.scheme}://{name}" + (f":{port}" if port else "")


def _quoted(value: Optional[str]) -> str:
    """What a client wrote, for the log: cut, then quoted.

    In that order, so that the mark that ends it is always there; and in
    one way whatever it holds, so that marks inside it are told from it.
    The method alone is only cut: the web server takes capitals only.
    """
    if value is None:
        return "none"
    return json.dumps(value[:100])


def log_no_room(length: int, peer: Optional[str], free: int, directory: str) -> None:
    unwritten = said.unwritten("no room")
    if unwritten is None:
        return
    logger.warning(
        "Refused an upload of %d bytes from %s: no room for it to wait in "
        "(%d MB free in %s; %d more like it not written here since the last)",
        length,
        peer,
        free // (1024 * 1024),
        _quoted(directory),
        unwritten,
    )


def no_room_body(free: Optional[int], kept_free: int = 0) -> Dict[str, str]:
    """The answer to an upload there is no room for.

    *free* is the room there was before any of it arrived, when that is
    known: once some of it is stored the figure would mislead. *kept_free*
    is what of it is not for uploads.
    """
    room = ""
    if free is not None:
        room = f": {free // (1024 * 1024)} MB are free there"
        if kept_free:
            room += (
                f", of which Mariner leaves {kept_free // (1024 * 1024)} MB "
                "to the system"
            )
    return {
        "code": "upload_not_stored",
        "title": "File Not Stored",
        "description": "There is not enough room where Mariner keeps a "
        f"file while it arrives{room}. A file sent from the web page needs "
        "twice its size there, one sent by a slicer its size.",
    }
