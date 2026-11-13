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
_WRONG = "wrong_password"
# What a stranger can have noted as often as wished: kept apart from what
# the owner looks for, so that it pushes none of it out.
_NOISE = (_WRONG, "sign_in_closed")
# What can be noted. The page words each of them.
WHATS = (
    "signed_in",
    "wrong_password",
    "wrong_code",
    "code_locked",
    "sign_in_closed",
    "password_chosen",
    "password_changed",
    "code_set",
    "code_removed",
)

_lock = threading.Lock()
# What is remembered, the oldest first; None until read. Wrong passwords
# apart from the rest: sent by the hundred, from as many addresses, they
# must not push out the sign-in or the change an owner looks for.
_events: Optional[List[Dict[str, Any]]] = None
_wrong: List[Dict[str, Any]] = []
_said_unkept = False


def forget() -> None:
    global _events, _wrong, _said_unkept
    with _lock:
        _events = None
        _wrong = []
        _said_unkept = False


def _is_one(entry: object) -> bool:
    return (
        isinstance(entry, dict)
        and isinstance(entry.get("at"), int)
        and entry.get("what") in WHATS
        and isinstance(entry.get("from"), str)
        and isinstance(entry.get("internet"), bool)
        and isinstance(entry.get("count", 1), int)
        and isinstance(entry.get("n", 0), int)
    )


def _read() -> None:
    """Read what is kept, once. Called with the lock held."""
    global _events, _wrong
    if _events is not None:
        return
    try:
        kept = json.loads(state.read(KEPT_AS) or b"[]")
    except (ValueError, OSError):
        kept = []
    found = (
        [entry for entry in kept if _is_one(entry)] if isinstance(kept, list) else []
    )
    _wrong = [entry for entry in found if entry["what"] in _NOISE][-KEPT:]
    _events = [entry for entry in found if entry["what"] not in _NOISE][-KEPT:]


def _all() -> List[Dict[str, Any]]:
    """Both, in the order they came. Called with the lock held."""
    _read()
    return sorted((_events or []) + _wrong, key=lambda entry: entry.get("n", 0))


def note(what: str, address: object, now: Optional[float] = None) -> None:
    """Remember that *what* happened, from *address*."""
    global _said_unkept
    entry: Dict[str, Any] = {
        "at": int(time.time() if now is None else now),
        "what": what,
        "from": provenance.shown(address),
        "internet": not provenance.is_local(address),
    }
    with _lock:
        _read()
        assert _events is not None
        # Its place among the others: two can come within one second.
        latest = max([one.get("n", 0) for one in _events + _wrong] or [0])
        entry["n"] = latest + 1
        if what not in _NOISE:
            _events.append(entry)
            del _events[:-KEPT]
        elif (
            _wrong
            and _wrong[-1]["what"] == what
            and _wrong[-1]["from"] == entry["from"]
            and _wrong[-1].get("n", 0) == latest
        ):
            # One after the other from one place, with nothing between:
            # one line, with how many.
            _wrong[-1]["count"] = _wrong[-1].get("count", 1) + 1
            _wrong[-1]["at"] = entry["at"]
            _wrong[-1]["n"] = entry["n"]
        else:
            _wrong.append(entry)
            del _wrong[:-KEPT]
        try:
            state.write(KEPT_AS, json.dumps(_all()).encode("ascii"))
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
        return [
            {name: value for name, value in entry.items() if name != "n"}
            for entry in reversed(_all())
        ]


def since_the_visit_before() -> Dict[str, int]:
    """What was tried between the last sign-in and the one before it,
    while the owner was away: wrong passwords, and wrong one-time codes
    sent with the right password, which say that the password is known.

    Not what came from the same place just before that last sign-in: the
    owner's own slips of the finger.
    """
    passwords = codes = 0
    within = False
    where: Optional[str] = None
    own_slips = True
    for entry in entries():
        what = entry["what"]
        if what in ("signed_in", "password_chosen"):
            if within:
                break
            within = True
            where = entry["from"]
            continue
        if not within:
            continue
        if what not in (_WRONG, "wrong_code"):
            continue
        if own_slips and entry["from"] == where:
            continue
        own_slips = False
        if what == _WRONG:
            passwords += entry.get("count", 1)
        else:
            codes += entry.get("count", 1)
    return {"wrong_passwords": passwords, "wrong_codes": codes}


def wrong_since_the_visit_before() -> int:
    return since_the_visit_before()["wrong_passwords"]
