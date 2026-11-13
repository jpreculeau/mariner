"""What Mariner remembers of who signed in, and who tried.

For its owner to see, in the page's settings, that somebody has been at
the door: the last sign-ins, the wrong passwords, the changes made to
the password and the one-time code, with when and where from. Never
what was typed.

Kept with the rest of what Mariner keeps, the latest only. Where it
cannot be written, it is remembered until the next start.
"""

import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional

from mariner.server import provenance, state

logger: logging.Logger = logging.getLogger(__name__)

KEPT_AS = "sign-ins"
KEPT = 50
# What can be noted. The page words each of them.
WHATS = (
    "signed_in",
    "wrong_password",
    "sign_in_closed",
    "password_chosen",
    "password_changed",
    "code_set",
    "code_removed",
)

_lock = threading.Lock()
# The oldest first; None until read.
_entries: Optional[List[Dict[str, Any]]] = None
_said_unkept = False


def forget() -> None:
    global _entries, _said_unkept
    with _lock:
        _entries = None
        _said_unkept = False


def _is_one(entry: object) -> bool:
    return (
        isinstance(entry, dict)
        and isinstance(entry.get("at"), int)
        and entry.get("what") in WHATS
        and isinstance(entry.get("from"), str)
        and isinstance(entry.get("internet"), bool)
    )


def _read() -> List[Dict[str, Any]]:
    """The entries, read once. Called with the lock held."""
    global _entries
    if _entries is None:
        try:
            kept = json.loads(state.read(KEPT_AS) or b"[]")
        except (ValueError, OSError):
            kept = []
        found = kept if isinstance(kept, list) else []
        _entries = [entry for entry in found if _is_one(entry)][-KEPT:]
    return _entries


def note(what: str, address: object, now: Optional[float] = None) -> None:
    """Remember that *what* happened, from *address*."""
    global _said_unkept
    entry = {
        "at": int(time.time() if now is None else now),
        "what": what,
        "from": provenance.shown(address),
        "internet": not provenance.is_local(address),
    }
    with _lock:
        entries = _read()
        entries.append(entry)
        del entries[:-KEPT]
        try:
            state.write(KEPT_AS, json.dumps(entries).encode("ascii"))
        except OSError as error:
            if not _said_unkept:
                _said_unkept = True
                logger.warning(
                    "The journal of sign-ins could not be kept (%s): it is "
                    "remembered until Mariner next starts",
                    error,
                )


def entries() -> List[Dict[str, Any]]:
    """What is remembered, the latest first."""
    with _lock:
        return [dict(entry) for entry in reversed(_read())]


def wrong_since_the_visit_before() -> int:
    """How many wrong passwords were sent between the last sign-in and the
    one before it: what happened while the owner was away."""
    count = 0
    within = False
    for entry in entries():
        if entry["what"] in ("signed_in", "password_chosen"):
            if within:
                break
            within = True
        elif within and entry["what"] == "wrong_password":
            count += 1
    return count
