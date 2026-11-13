"""Holding when strangers lean on the door.

Reached from the Internet, Mariner is spoken to by whoever finds it. It
cannot be kept from being leaned on; it can be kept from falling, and its
owner from being shut out at home:

- the Internet holds only part of the connections Mariner takes at once,
  and one address of it a small share: the local network always finds
  room;
- one address, and the Internet as a whole, open only so many new
  connections in a while: each one over HTTPS costs the computer work;
- a connection from the Internet that asks nothing is not kept, and one
  that has been answered is not kept idle for long;
- a reader that reads nothing does not hold what serves it.

Addresses of the local network (see ``mariner.server.provenance``) are
under none of this. Nothing here knows of the web server: the figures,
and who comes in.
"""

import time
from typing import Dict, Iterable, List, Optional

from mariner.server import provenance

# Connections held at once: from the whole Internet, well under half of
# what Mariner takes (``mariner.server.CONNECTION_LIMIT``), and from one
# address of it (a browser opens six).
FROM_INTERNET = 24
PER_ADDRESS = 8
# New connections within this long.
KNOCKS_WITHIN_SECS = 10.0
KNOCKS_PER_ADDRESS = 30
KNOCKS_FROM_INTERNET = 150
# How long a connection from the Internet has to ask for something, and
# how long it is kept once answered with nothing more asked.
FIRST_REQUEST_SECS = 10.0
IDLE_SECS = 30.0
# How long what was asked for can go unread, not a byte of it, before
# its reader is taken for gone.
STALLED_SECS = 60.0


class Door:
    """Who comes in. One for all the ports Mariner listens on."""

    def __init__(self) -> None:
        # When each address of the Internet last knocked, and was let in.
        self._knocks: Dict[str, List[float]] = {}

    def remembered(self) -> int:
        return len(self._knocks)

    def _forget_the_old(self, now: float) -> None:
        since = now - KNOCKS_WITHIN_SECS
        for address in list(self._knocks):
            recent = [at for at in self._knocks[address] if at > since]
            if recent:
                self._knocks[address] = recent
            else:
                del self._knocks[address]

    def admits(
        self, address: object, held: Iterable[object], now: Optional[float] = None
    ) -> bool:
        """Whether a new connection from *address* comes in.

        *held*: where the connections open at this moment come from.
        """
        if provenance.is_local(address):
            return True
        moment = time.monotonic() if now is None else now
        name = provenance.place_of(address)
        outside = [
            provenance.place_of(one) for one in held if not provenance.is_local(one)
        ]
        if len(outside) >= FROM_INTERNET or outside.count(name) >= PER_ADDRESS:
            return False
        self._forget_the_old(moment)
        if len(self._knocks.get(name, ())) >= KNOCKS_PER_ADDRESS:
            return False
        if sum(len(knocks) for knocks in self._knocks.values()) >= (
            KNOCKS_FROM_INTERNET
        ):
            return False
        self._knocks.setdefault(name, []).append(moment)
        return True


def outstayed(
    address: object, asked: bool, opened_at: float, last_at: float, now: float
) -> bool:
    """Whether a connection that is asking nothing has been kept long enough.

    *asked*: whether it ever asked for something whole. *opened_at*,
    *last_at*: when it was opened, and when something last went through.
    """
    if provenance.is_local(address):
        return False
    if not asked:
        return now - opened_at > FIRST_REQUEST_SECS
    return now - last_at > IDLE_SECS
