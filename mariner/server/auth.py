"""The password that opens Mariner's page, and who is signed in.

One password, for whoever is to drive the printer. It is kept as a hash
that does not give it away, in the folder Mariner keeps for itself
(``mariner.server.state``): it cannot be read back, only replaced.

The interfaces slicers speak (UVtools, SDCP) know nothing of passwords
and are not behind this one; each has a switch.
"""

import hashlib
import hmac
import ipaddress
import json
import logging
import math
import os
import stat
import secrets
import threading
import time
from typing import Any, Dict, List, Mapping, Optional, Tuple

from flask import (
    Blueprint,
    Response,
    current_app,
    jsonify,
    make_response,
    request,
    session,
)
from flask_wtf.csrf import generate_csrf

from mariner import config, passwords, totp
from mariner.passwords import PasswordNotAllowed  # noqa: F401
from mariner.server import journal, provenance, sessions, state

logger: logging.Logger = logging.getLogger(__name__)


class PasswordAlreadySet(Exception):
    pass


def _record() -> Optional[Dict[str, Any]]:
    """What is kept of the password; None if nothing usable is."""
    kept = state.read(passwords.KEPT_AS)
    if kept is None:
        return None
    try:
        record = json.loads(kept)
    except ValueError:
        return None
    return record if isinstance(record, dict) else None


def has_password() -> bool:
    """Whether one was set, readable or not.

    A record that cannot be read still counts: whoever comes first must
    not be offered to choose a new one because a file was damaged.
    """
    return state.exists(passwords.KEPT_AS)


def generation() -> Optional[str]:
    """What tells the password in place from those before it.

    Sessions hold it, and end when it changes.
    """
    record = _record()
    value = record.get("generation") if record else None
    return value if isinstance(value, str) and value else None


def out_of_reach() -> bool:
    """Whether the password cannot be told: the page then stays shut.

    The folder cannot be used, or a password is kept that cannot be
    read (put back from a copy under another account, or damaged): the
    right one would be called wrong for ever.
    """
    return state.is_makeshift() or (has_password() and generation() is None)


# One at a time: of several set at once, one is kept, and each is told
# whether it was its own.
_password_lock = threading.Lock()


def set_password(password: str, only_if_none: bool = False) -> str:
    """Keep *password*, and return what tells it from every other.

    With *only_if_none*, PasswordAlreadySet when there is one already:
    looked at and written in one go, so that of several chosen at once
    only one is.
    """
    record = passwords.record_for(password)
    with _password_lock:
        if only_if_none and has_password():
            raise PasswordAlreadySet()
        state.write(passwords.KEPT_AS, json.dumps(record).encode("ascii"))
    return str(record["generation"])


def clear_password() -> None:
    """Leave no password: the next visit is asked to choose one."""
    state.remove(passwords.KEPT_AS)


def check_password(candidate: str) -> bool:
    try:
        return passwords.matches(_record(), candidate)
    except UnicodeError:
        # Half of a pair of characters: nothing that was ever chosen.
        return False


# -- a password that is lost ------------------------------------------------

# Where the card's first drive is found once the computer is running: the
# one any computer can read and write when the card is put in it.
_BOOT_DIRECTORIES = ["/boot/firmware", "/boot"]
_ASKS_TO_CLEAR = ("reset-password", "reset-password.txt")
_SEEN_AS = "reset-seen"


def _remove_the_request(asked: str) -> None:
    os.unlink(asked)


def clear_if_asked_on_the_boot_drive() -> bool:
    """Clear the password if a file on the boot drive asks for it.

    A password that is lost cannot be read back, only cleared, and only
    by someone who has the computer in hand: a file named
    ``reset-password`` on the card's first drive. It is removed once
    obeyed. Where the service may not write there, what the file looked
    like is remembered instead, so that it is obeyed once.
    """
    for directory in _BOOT_DIRECTORIES:
        try:
            names = os.listdir(directory)
        except OSError:
            continue
        for name in names:
            if name.lower() not in _ASKS_TO_CLEAR:
                continue
            asked = os.path.join(directory, name)
            try:
                found = os.lstat(asked)
            except OSError:
                continue
            if not stat.S_ISREG(found.st_mode):
                continue
            looks = f"{asked}:{found.st_mtime_ns}:{found.st_size}".encode()
            if state.read(_SEEN_AS) == looks:
                continue
            clear_password()
            try:
                _remove_the_request(asked)
                state.remove(_SEEN_AS)
                logger.warning(
                    "The password was cleared, as %r asked; the file was removed",
                    asked,
                )
            except OSError:
                try:
                    state.write(_SEEN_AS, looks)
                except OSError as error:
                    # It will be obeyed again at the next start; that
                    # must not keep Mariner from starting now.
                    logger.warning("Could not note %r as obeyed: %s", asked, error)
                logger.warning(
                    "The password was cleared, as %r asked. The file could "
                    "not be removed: it is passed over from now on, until "
                    "it is written again",
                    asked,
                )
            return True
    return False


# -- attempts --------------------------------------------------------------

# Counted by address: counted for all comers together, anyone on the
# network would keep the owner out for as long as they liked, one wrong
# password every half minute. Only a few addresses have a count of their
# own, the rest share one: else trying passwords would only take changing
# address. Changing the password has a count of its own: wrong ones sent
# to sign in do not keep the owner from changing it.
_FREE_ATTEMPTS = 3
_LONGEST_WAIT_SECS = 30
_MOST_ADDRESSES = 8
# An address that sent nothing wrong for this long leaves its place.
_FORGOTTEN_AFTER_SECS = 600
_SHARED = "others"
_OWN = "from "
_OUTSIDE = "internet: "
_attempts_lock = threading.Lock()
# For each count: wrong ones so far, and when the last was looked at.
_attempts: Dict[str, Tuple[int, float]] = {}


def _place_of(address: Optional[str]) -> Optional[str]:
    """What stands for the computer at *address*, if it is one."""
    try:
        parsed = ipaddress.ip_address(address or "")
    except ValueError:
        return None
    if isinstance(parsed, ipaddress.IPv6Address):
        if parsed.ipv4_mapped is not None:
            return str(parsed.ipv4_mapped)
        # A computer gives itself as many of these as it likes, all in
        # the one network it is on.
        whole = ipaddress.ip_network((int(parsed), 64), strict=False)
        return str(whole.network_address)
    return str(parsed)


def count_of(address: Optional[str], now: Optional[float] = None) -> str:
    """The count the passwords sent from *address* go to."""
    place = _place_of(address)
    # The Internet apart from the local network: wrong passwords sent from
    # all over must not make a computer of the house wait its turn.
    apart = "" if provenance.is_local(address) else _OUTSIDE
    if place is None:
        return apart + _SHARED
    own = apart + _OWN + place
    moment = time.monotonic() if now is None else now
    with _attempts_lock:
        for name, (_, last) in list(_attempts.items()):
            if _OWN in name and last + _FORGOTTEN_AFTER_SECS < moment:
                del _attempts[name]
        if own in _attempts:
            return own
        taken = sum(1 for name in _attempts if name.startswith(apart + _OWN))
        return own if taken < _MOST_ADDRESSES else apart + _SHARED


def forget_attempts() -> None:
    global _closed_said_at
    with _attempts_lock:
        _attempts.clear()
        _internet_attempts.clear()
    _closed_said_at = 0.0
    journal.forget()
    forget_code_seen()


# From the Internet, addresses are had by the thousand: a count for each
# holds nobody. So the wrong passwords sent from all of it are counted
# together, and past this many within the hour signing in from the
# Internet is closed until they grow old. The local network is left as it
# is: the owner signs in at home whatever goes on outside.
INTERNET_FAILURES_AN_HOUR = 20
_HOUR_SECS = 3600
# When each was looked at.
_internet_attempts: List[float] = []


def claim_internet_attempt(now: Optional[float] = None) -> int:
    """Seconds until a password from the Internet is looked at; 0 for now.

    As above: one that is let through is counted as wrong at once, until
    ``note_internet_success`` says otherwise; one turned away is not.
    """
    moment = time.monotonic() if now is None else now
    with _attempts_lock:
        _internet_attempts[:] = [
            sent for sent in _internet_attempts if sent + _HOUR_SECS > moment
        ]
        if len(_internet_attempts) >= INTERNET_FAILURES_AN_HOUR:
            oldest = min(_internet_attempts)
            return max(1, math.ceil(oldest + _HOUR_SECS - moment))
        _internet_attempts.append(moment)
        return 0


def note_internet_success(claimed_at: float) -> None:
    """Take back the attempt claimed at *claimed_at*: it was not a wrong one."""
    with _attempts_lock:
        if claimed_at in _internet_attempts:
            _internet_attempts.remove(claimed_at)


def claim_attempt(count: str, now: Optional[float] = None) -> int:
    """Seconds to wait before a password is looked at; 0 to look at it now.

    Nothing for a few, then twice as long after each wrong one, up to
    half a minute. An attempt that is let through is counted as wrong at
    once, until ``note_success`` says otherwise: of several sent together,
    one is looked at. One that is turned away is not counted.
    """
    moment = time.monotonic() if now is None else now
    with _attempts_lock:
        failures, last = _attempts.get(count, (0, 0.0))
        if failures >= _FREE_ATTEMPTS:
            wait = min(_LONGEST_WAIT_SECS, 2 ** (failures - _FREE_ATTEMPTS))
            left = math.ceil(last + wait - moment)
            if left > 0:
                return left
        _attempts[count] = (failures + 1, moment)
        return 0


def note_success(count: str) -> None:
    with _attempts_lock:
        _attempts.pop(count, None)


# -- who is signed in ------------------------------------------------------

_SIGNED_IN_AS = "auth"


# Each session that signs in has a number of its own. Signing out keeps
# it, so that the cookie of that session is of no use from then on:
# copied beforehand, or put back by an answer that was on its way.
_SESSION_AS = "id"
_SIGNED_OUT_AS = "signed-out.json"
# More than anyone signs out of in the month a session lasts.
_MOST_SIGNED_OUT = 200
_signed_out_lock = threading.Lock()
_signed_out: Optional[Dict[str, float]] = None


def signed_out_list_is_usable() -> bool:
    """Whether what was signed out of can be read, or there is none.

    When it is there and cannot be read, the sessions signed out of
    would all work again: whoever starts Mariner then ends every session.
    """
    if not state.exists(_SIGNED_OUT_AS):
        return True
    try:
        kept = json.loads(state.read(_SIGNED_OUT_AS) or b"")
    except ValueError:
        return False
    return isinstance(kept, dict)


def start_signed_out_list_again() -> None:
    """Leave an empty list, once every session has been ended."""
    global _signed_out
    with _signed_out_lock:
        _signed_out = {}
        try:
            state.write(_SIGNED_OUT_AS, b"{}")
        except OSError as error:
            logger.warning("Could not keep what was signed out of: %s", error)


def forget_signed_out() -> None:
    """Read again what was kept. For tests."""
    global _signed_out
    with _signed_out_lock:
        _signed_out = None


def _signed_out_sessions() -> Dict[str, float]:
    """The sessions signed out of, each with when it would have ended."""
    global _signed_out
    if _signed_out is None:
        found: Dict[str, float] = {}
        try:
            kept = json.loads(state.read(_SIGNED_OUT_AS) or b"{}")
            if isinstance(kept, dict):
                found = {
                    str(number): float(until)
                    for number, until in kept.items()
                    if isinstance(until, (int, float))
                }
        except ValueError:
            pass
        _signed_out = found
    return _signed_out


def _note_signed_out(number: str) -> None:
    now = time.time()
    with _signed_out_lock:
        sessions_out = _signed_out_sessions()
        # Twice as long as a session lasts: the clock of a small board
        # can be behind when this is noted.
        sessions_out[number] = now + 2 * _SESSION_DAYS * 86400
        # Those that would have ended by now need no keeping, nor the
        # oldest beyond what anyone signs out of.
        lasting = sorted(
            ((until, one) for one, until in sessions_out.items() if until > now),
            reverse=True,
        )[:_MOST_SIGNED_OUT]
        sessions_out.clear()
        sessions_out.update({one: until for until, one in lasting})
        try:
            state.write(_SIGNED_OUT_AS, json.dumps(sessions_out).encode("ascii"))
        except OSError as error:
            # Kept in memory all the same, until Mariner restarts.
            logger.warning("Could not keep what was signed out of: %s", error)


_SESSION_DAYS = 30


def signed_in_with(held: Mapping[str, Any]) -> bool:
    """Whether a session holding *held* is signed in under the password
    in place, and was not signed out of."""
    current = generation()
    if current is None or held.get(_SIGNED_IN_AS) != current:
        return False
    number = held.get(_SESSION_AS)
    if not isinstance(number, str):
        return False
    with _signed_out_lock:
        return number not in _signed_out_sessions()


# The session's cookie is not enough. Cookies go by the name of the host
# and not by its port: the browser sends Mariner's to the page of any
# other program on the same computer, which could send it back as its
# own. So signing in also gives the page a key, which it keeps where only
# pages of this very address can read, and sends with each request; the
# session holds its hash.
KEY_HEADER = sessions.KEY_HEADER
_KEY_AS = "key"
# Asked for by the browser itself, for a picture in the page: it sends no
# key. Looking only.
_WITHOUT_KEY = (("GET", "/api/file_preview"),)


def _hash_of(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _came_in_with_the_code(held: Mapping[str, Any]) -> bool:
    """Whether a session is one the Internet is answered: it signed in
    with the one-time code that is in force. Done away with or replaced,
    a code ends what it opened from outside: the browser of a phone that
    was lost does not come back with the next one."""
    which = code_identity()
    return which is not None and held.get(_WITH_CODE_AS) == which


def let_in(held: Mapping[str, Any], key: str, from_internet: bool = False) -> bool:
    """Whether a session holding *held*, sent with *key*, is signed in.

    *from_internet*: only one that signed in with the one-time code. A
    phone signed in at home with the password alone is asked again once
    it has left the house, and so is whoever copied its cookie.
    """
    if not signed_in_with(held):
        return False
    if from_internet and not _came_in_with_the_code(held):
        return False
    expected = held.get(_KEY_AS)
    return isinstance(expected, str) and hmac.compare_digest(_hash_of(key), expected)


def _from_internet() -> bool:
    return not provenance.is_local(request.remote_addr)


def is_signed_in() -> bool:
    return let_in(session, request.headers.get(KEY_HEADER, ""), _from_internet())


def _sign_in(
    under: str,
    with_code: Optional[str] = None,
    tried: Optional[Mapping[str, Any]] = None,
) -> Response:
    """Sign this browser in *under* the password of that number.

    The answer carries the key of the page, and a token for the new
    session: the one the page holds went with the session it had.
    """
    # The session that was there ends: its cookie, copied or set again
    # by another program, must not go on working beside the new one.
    before = session.get(_SESSION_AS)
    if isinstance(before, str) and signed_in_with(session):
        _note_signed_out(before)
    # A new session: nothing a page held before signing in comes along.
    session.clear()
    key = secrets.token_urlsafe(32)
    session[_SIGNED_IN_AS] = under
    session[_SESSION_AS] = secrets.token_hex(8)
    session[_KEY_AS] = _hash_of(key)
    if with_code:
        # Which code it came in with: see ``_came_in_with_the_code``.
        session[_WITH_CODE_AS] = with_code
    session.permanent = True
    answer: Dict[str, Any] = {
        "success": True,
        "csrf_token": generate_csrf(),
        "page_key": key,
    }
    if tried is not None:
        # What was tried since the visit before.
        answer["wrong_since_last_visit"] = tried["wrong_passwords"]
        answer["wrong_codes_since_last_visit"] = tried["wrong_codes"]
        answer["wrong_since_last_visit_or_more"] = tried["or_more"]
    return jsonify(answer)


def _unavailable() -> Dict[str, str]:
    return {
        "code": "state_unavailable",
        "title": "Password Out Of Reach",
        "description": "Mariner cannot use the folder it keeps its password "
        f"in ({config.get_state_directory()}), or the password kept there, "
        "so its page stays shut. On the computer it runs on, give that "
        "folder and what it holds to the account Mariner runs under and "
        "make sure it can be written, then restart Mariner.",
    }


# Reached without being signed in: they are what signs in.
_OPEN_PATHS = ("/api/csrf_token",)
_OPEN_PREFIXES = ("/api/auth/",)


def refusal(
    path: str,
    held: Mapping[str, Any],
    key: str = "",
    method: str = "GET",
    address: Optional[str] = None,
) -> Optional[Dict[str, str]]:
    """Why a request for *path* is not answered to who holds *held* and
    sent *key* from *address*.

    None when it is: not one of the page's own addresses, one that signs
    in, or a session that is signed in.
    """
    if not path.startswith("/api/"):
        return None
    if path in _OPEN_PATHS or path.startswith(_OPEN_PREFIXES):
        return None
    if out_of_reach():
        return _unavailable()
    from_internet = address is not None and not provenance.is_local(address)
    if let_in(held, key, from_internet):
        return None
    if (method, path) in _WITHOUT_KEY and signed_in_with(held):
        if not from_internet or _came_in_with_the_code(held):
            return None
    if not has_password():
        return {
            "code": "password_not_set",
            "title": "No Password Yet",
            "description": "No password has been chosen for Mariner yet. "
            "Open its page in a browser and choose one.",
        }
    return {
        "code": "login_required",
        "title": "Sign In First",
        "description": "Sign in with Mariner's password first.",
    }


def status_of(refused: Mapping[str, str]) -> int:
    """The status a refusal is answered with."""
    return 503 if refused.get("code") == "state_unavailable" else 401


# -- the one-time code -------------------------------------------------------

# Asked, besides the password, of who signs in from the Internet (see
# mariner.totp). Kept with the last half minute a code served for: none
# opens anything twice.
_WITH_CODE_AS = "code"
_code_lock = threading.Lock()
# The same, should it not be possible to keep it.
_last_step_seen: Optional[int] = None
# Which code that was: what served for one is nothing to the next.
_last_step_seen_of: Optional[str] = None


def forget_code_seen() -> None:
    global _last_step_seen, _last_step_seen_of, _wrong_codes_seen
    _last_step_seen = None
    _last_step_seen_of = None
    _wrong_codes_seen = None


def _code_record() -> Dict[str, Any]:
    try:
        record = json.loads(state.read(totp.KEPT_AS) or b"")
    except ValueError:
        return {}
    return record if isinstance(record, dict) else {}


def _secret_in_force(record: Mapping[str, Any]) -> Optional[str]:
    secret = record.get("secret")
    return secret if isinstance(secret, str) and secret else None


def code_is_set() -> bool:
    return _secret_in_force(_code_record()) is not None


def code_identity() -> Optional[str]:
    """What tells the code in force from the one before, or the one
    after; None when there is none. Says nothing of the secret."""
    secret = _secret_in_force(_code_record())
    return None if secret is None else _identity_of(secret)


def _identity_of(secret: str) -> str:
    return hashlib.sha256(b"mariner one-time code " + secret.encode()).hexdigest()[:16]


def _last_step(
    record: Mapping[str, Any], moment: Optional[float] = None
) -> Optional[int]:
    """The last half minute a code served for.

    One later than any code can now be for is passed over: it served
    while the clock was ahead, and would else shut the Internet out until
    the clock caught up, a day or a year later. (That one code could then
    serve once more when its time comes: it would take a clock that was
    wrong and somebody who kept the code.)
    """
    kept = record.get("last")
    now = time.time() if moment is None else moment
    to_come = int(now) // totp.PERIOD_SECS + 1
    secret = _secret_in_force(record)
    seen = (
        _last_step_seen
        if secret is not None and _identity_of(secret) == _last_step_seen_of
        else None
    )
    steps = [step for step in (kept, seen) if isinstance(step, int) and step <= to_come]
    return max(steps) if steps else None


# With the password known, the code is all that is left to guess: three
# chances in a million at each try, which over months is no longer
# nothing. So wrong codes sent with the right password are counted, kept
# through restarts, and past this many signing in from the Internet is
# closed until somebody signs in from the local network.
WRONG_CODES_BEFORE_CLOSING = 10


# The same as it stands since Mariner started, should it not be possible
# to keep it; None until it changes.
_wrong_codes_seen: Optional[int] = None


def wrong_codes() -> int:
    if _wrong_codes_seen is not None:
        return _wrong_codes_seen
    kept = _code_record().get("wrong")
    return kept if isinstance(kept, int) else 0


def _count_wrong_codes(to: Optional[int] = None) -> int:
    """One more wrong code with the right password; or *to* that many."""
    global _wrong_codes_seen
    with _code_lock:
        record = _code_record()
        if _secret_in_force(record) is None:
            _wrong_codes_seen = None
            return 0
        kept = record.get("wrong")
        kept_count = kept if isinstance(kept, int) else 0
        was = kept_count if _wrong_codes_seen is None else _wrong_codes_seen
        now = was + 1 if to is None else to
        _wrong_codes_seen = now
        if now != kept_count:
            record["wrong"] = now
            try:
                state.write(totp.KEPT_AS, json.dumps(record).encode("ascii"))
            except OSError as error:
                logger.warning("The count of wrong codes could not be kept (%s)", error)
        return now


def start_code() -> str:
    """Make a secret for a phone to take in; in force once confirmed."""
    secret = totp.new_secret()
    with _code_lock:
        record = _code_record()
        record["pending"] = secret
        state.write(totp.KEPT_AS, json.dumps(record).encode("ascii"))
    return secret


def confirm_code(candidate: str, now: Optional[float] = None) -> bool:
    """Put the secret that was started in force, given a code of it."""
    global _last_step_seen, _last_step_seen_of, _wrong_codes_seen
    moment = time.time() if now is None else now
    with _code_lock:
        record = _code_record()
        pending = record.get("pending")
        if not isinstance(pending, str):
            return False
        step = totp.step_of(pending, candidate, moment)
        if step is None:
            return False
        state.write(
            totp.KEPT_AS,
            json.dumps({"secret": pending, "last": step}).encode("ascii"),
        )
        _last_step_seen = step
        _last_step_seen_of = _identity_of(pending)
        # Another code: what was guessed at the one before is nothing to it.
        _wrong_codes_seen = None
    return True


def remove_code() -> None:
    with _code_lock:
        state.remove(totp.KEPT_AS)
    forget_code_seen()


def code_step(candidate: str, now: Optional[float] = None) -> Optional[int]:
    """Which half minute *candidate* is the code of, if it can still serve."""
    moment = time.time() if now is None else now
    record = _code_record()
    secret = _secret_in_force(record)
    if secret is None:
        return None
    return totp.step_of(secret, candidate, moment, after=_last_step(record, moment))


def use_code_step(step: int, now: Optional[float] = None) -> bool:
    """Have the code of *step* serve; False if it, or a later one, has."""
    global _last_step_seen, _last_step_seen_of
    with _code_lock:
        record = _code_record()
        last = _last_step(record, now)
        if _secret_in_force(record) is None or (last is not None and step <= last):
            return False
        _last_step_seen = step
        _last_step_seen_of = _identity_of(str(_secret_in_force(record)))
        record["last"] = step
        try:
            state.write(totp.KEPT_AS, json.dumps(record).encode("ascii"))
        except OSError as error:
            # Held in memory until the next start.
            logger.warning("The code that served could not be kept (%s)", error)
    return True


def check_code(candidate: str, now: Optional[float] = None) -> bool:
    step = code_step(candidate, now)
    return step is not None and use_code_step(step, now)


# -- addresses -------------------------------------------------------------

auth_api = Blueprint("auth", __name__, url_prefix="/api/auth")


def _refuse(code: str, title: str, description: str, status: int) -> Response:
    body = {"code": code, "title": title, "description": description}
    return make_response(jsonify(body), status)


def _not_kept(error: OSError) -> Response:
    logger.error("Could not write to the state directory: %s", error)
    return make_response(jsonify(state.NOT_WRITTEN), 500)


_key_lock = threading.Lock()


def _use_the_key_that_is_kept() -> None:
    """Sign what follows with the key the next start will read.

    The commands about the password remove the key that is kept, and
    cannot reach the one a running Mariner holds: signed with that one,
    who signs in now would be signed out at the next start.
    """
    # One at a time: of two signing in together, neither makes a key
    # that the other replaces.
    with _key_lock:
        held = current_app.config.get("SECRET_KEY")
        if state.read("session.key") == held:
            return
        kept = state.session_key()
        # Not one that could not be written: each sign-in would end the
        # sessions of the others.
        if state.read("session.key") == kept:
            current_app.config["SECRET_KEY"] = kept


def _given(*names: str) -> Optional[Tuple[str, ...]]:
    """The texts sent under *names*, or None if any is not one."""
    try:
        body = request.get_json(silent=True)
    except RecursionError:
        # Nested beyond reason: nothing of what is asked for.
        return None
    if not isinstance(body, dict):
        return None
    values = tuple(body.get(name) for name in names)
    if not all(isinstance(value, str) for value in values):
        return None
    return values  # type: ignore[return-value]


def _not_a_password() -> Response:
    return _refuse(
        "password_missing",
        "No Password Given",
        "Send the password as text, in a JSON object.",
        400,
    )


@auth_api.route("/state", methods=["GET"])
def auth_state() -> Response:
    if out_of_reach():
        # Shut, and not for want of a password.
        return jsonify({"password_set": True, "signed_in": False, "unavailable": True})
    signed_in = is_signed_in()
    if signed_in:
        # The month starts again here: when the page is opened, not with
        # every answer (see SESSION_REFRESH_EACH_REQUEST).
        session.modified = True
    return jsonify(
        {
            "password_set": has_password(),
            "signed_in": signed_in,
            # For the page to ask for the code, or say that there is none.
            "from_internet": _from_internet(),
            "code_set": code_is_set(),
            # For the page not to offer what would be refused.
            "host_commands": provenance.refusal("/api/host/reboot", request.remote_addr)
            is None,
        }
    )


def _shut() -> Optional[Response]:
    """The answer when what is kept is out of reach; None when it is not."""
    if out_of_reach():
        return make_response(jsonify(_unavailable()), 503)
    return None


def _closed_answer(wait: int) -> Response:
    minutes = math.ceil(wait / 60)
    answer = _refuse(
        "sign_in_closed",
        "Sign-In Closed From The Internet",
        "Too many wrong passwords were sent from the Internet. Signing in "
        f"from there is closed for {minutes} minute{'' if minutes == 1 else 's'}"
        "; it works from the local network.",
        429,
    )
    answer.headers["Retry-After"] = str(wait)
    return answer


def _wait_answer(wait: int) -> Response:
    answer = _refuse(
        "too_many_attempts",
        "Too Many Attempts",
        "Too many wrong passwords. Try again in "
        f"{wait} second{'' if wait == 1 else 's'}.",
        429,
    )
    answer.headers["Retry-After"] = str(wait)
    return answer


# Said once in a while, not at each attempt turned away.
_closed_said_at = 0.0


def _say_closed(wait: int) -> None:
    global _closed_said_at
    now = time.monotonic()
    if _closed_said_at and now - _closed_said_at < 600:
        return
    _closed_said_at = now
    journal.note("sign_in_closed", request.remote_addr)
    logger.warning(
        "Signing in from the Internet is closed for %d s: %d wrong passwords "
        "were sent from there within the hour",
        wait,
        INTERNET_FAILURES_AN_HOUR,
    )


@auth_api.route("/setup", methods=["POST"])
def setup() -> Response:
    """Choose the password, when there is none."""
    shut = _shut()
    if shut is not None:
        return shut
    already = lambda: _refuse(  # noqa: E731
        "password_already_set",
        "Password Already Chosen",
        "A password has already been chosen. Sign in with it; if it is "
        "lost, Mariner's documentation says how to start over.",
        409,
    )
    if has_password():
        return already()
    if not provenance.is_local(request.remote_addr):
        # Else whoever finds the page first, anywhere, chooses it.
        return _refuse(
            "local_network_only",
            "Local Network Only",
            "The password is chosen from the local network, or with "
            "the command mariner set-password, not from the Internet.",
            403,
        )
    given = _given("password")
    if given is None:
        return _not_a_password()
    try:
        chosen = set_password(given[0], only_if_none=True)
    except PasswordNotAllowed as error:
        return _refuse(error.code, "Password Not Taken", error.description, 400)
    except PasswordAlreadySet:
        # Chosen by someone else in the meantime.
        return already()
    except OSError as error:
        return _not_kept(error)
    logger.warning("A password was chosen from %s", request.remote_addr)
    journal.note("password_chosen", request.remote_addr)
    _use_the_key_that_is_kept()
    return _sign_in(chosen)


@auth_api.route("/login", methods=["POST"])
def login() -> Response:
    shut = _shut()
    if shut is not None:
        return shut
    given = _given("password")
    if given is None:
        return _not_a_password()
    if not has_password():
        # Cleared since the page showed its form: said as it is, so that
        # the page offers to choose one.
        body = refusal("/api/auth-login", session) or {}
        return make_response(jsonify(body), status_of(body))
    from_internet = _from_internet()
    claimed_at = time.monotonic()
    if from_internet and not code_is_set():
        # Before the password is looked at: nothing is told of it.
        return _refuse(
            "code_not_set",
            "No One-Time Code Set Up",
            "Signing in from the Internet takes a one-time code besides the "
            "password, and none is set up. Set it up from the local network, "
            "in Mariner's settings.",
            403,
        )
    if from_internet and wrong_codes() >= WRONG_CODES_BEFORE_CLOSING:
        # Somebody has the password and is guessing at the code.
        return _refuse(
            "code_locked",
            "Sign-In Closed From The Internet",
            "Too many wrong one-time codes were sent with the right password: "
            "somebody else may know it. Signing in from the Internet is "
            "closed until somebody signs in from the local network.",
            403,
        )
    if from_internet:
        closed_for = claim_internet_attempt(claimed_at)
        if closed_for:
            _say_closed(closed_for)
            return _closed_answer(closed_for)
    count = count_of(request.remote_addr)
    wait = claim_attempt(count)
    if wait:
        # Turned away without being looked at: not one more wrong one.
        note_internet_success(claimed_at)
        return _wait_answer(wait)
    current = generation()
    right = current is not None and check_password(given[0])
    knows_the_password = right
    if from_internet:
        # Both are looked at whichever is wrong, and which one was is not
        # told. The code serves only once the password was right.
        body = request.get_json(silent=True)
        code = body.get("code") if isinstance(body, dict) else None
        step = code_step(code if isinstance(code, str) else "")
        right = right and step is not None and use_code_step(step)
    if knows_the_password and not right:
        # Told as a wrong password is, and noted for what it is: its
        # owner must learn that the password is known.
        logger.warning(
            "Right password and wrong one-time code from %s", request.remote_addr
        )
        journal.note("wrong_code", request.remote_addr)
        if _count_wrong_codes() == WRONG_CODES_BEFORE_CLOSING:
            journal.note("code_locked", request.remote_addr)
            logger.warning(
                "Signing in from the Internet is closed until somebody signs "
                "in from the local network: %d wrong one-time codes were sent "
                "with the right password",
                WRONG_CODES_BEFORE_CLOSING,
            )
    elif not right:
        logger.warning("Wrong password from %s", request.remote_addr)
        journal.note("wrong_password", request.remote_addr)
    if not right or current is None:
        return _refuse(
            "wrong_password",
            "Wrong Password",
            "This is not the password"
            + (", or not the code of the moment." if from_internet else "."),
            401,
        )
    note_success(count)
    note_internet_success(claimed_at)
    _use_the_key_that_is_kept()
    # The owner's own slips, or a guesser sent away by the owner's return.
    _count_wrong_codes(to=0)
    journal.note("signed_in", request.remote_addr)
    return _sign_in(
        current,
        with_code=code_identity() if from_internet else None,
        tried=journal.since_the_visit_before(),
    )


@auth_api.route("/logout", methods=["POST"])
def logout() -> Response:
    number = session.get(_SESSION_AS)
    # Only with the key of the page: the cookie alone, which other
    # programs on the same computer are sent, signs nobody out.
    if isinstance(number, str) and is_signed_in():
        _note_signed_out(number)
    session.clear()
    # With a token for what comes next, which is signing in again.
    return jsonify({"success": True, "csrf_token": generate_csrf()})


@auth_api.route("/password", methods=["POST"])
def change_password() -> Response:
    """Replace the password; every other session ends."""
    shut = _shut()
    if shut is not None:
        return shut
    if not is_signed_in():
        body = refusal("/api/auth-change", session) or {}
        return make_response(jsonify(body), status_of(body))
    given = _given("current", "new")
    if given is None:
        return _not_a_password()
    current, new = given
    wait = claim_attempt("change")
    if wait:
        return _wait_answer(wait)
    if not check_password(current):
        return _refuse(
            "wrong_password",
            "Wrong Password",
            "This is not the password in place.",
            401,
        )
    # The current one was right: whatever follows is not a wrong attempt.
    note_success("change")
    try:
        changed = set_password(new)
    except PasswordNotAllowed as error:
        return _refuse(error.code, "Password Not Taken", error.description, 400)
    except OSError as error:
        return _not_kept(error)
    # A new key for sessions too: what was signed with the old one, or
    # could be forged from a copy of it, is of no use.
    current_app.config["SECRET_KEY"] = state.new_session_key()
    logger.warning("The password was changed from %s", request.remote_addr)
    journal.note("password_changed", request.remote_addr)
    # What the session came in with, it keeps: changed from outside, the
    # password does not sign its owner out.
    came_with = session.get(_WITH_CODE_AS)
    return _sign_in(
        changed,
        with_code=came_with if _came_in_with_the_code(session) else None,
    )


def _rank(held: Mapping[str, Any], key: str) -> int:
    """How far a session is let in: with the key the page sent, signed
    in, or neither."""
    if let_in(held, key):
        return 2
    return 1 if signed_in_with(held) else 0


# Among the cookies a request carries, the session that goes with the
# key comes first, then one that is signed in.
sessions.rank = _rank


def _for_the_code() -> Optional[Response]:
    """Why the one-time code is not set up by this request; None if it is."""
    shut = _shut()
    if shut is not None:
        return shut
    if not is_signed_in():
        body = refusal("/api/auth-code", session) or {}
        return make_response(jsonify(body), status_of(body))
    if _from_internet():
        # Else whoever got in from outside could put a phone of theirs in
        # the place of the owner's.
        return _refuse(
            "local_network_only",
            "Local Network Only",
            "The one-time code is set up from the local network, not from "
            "the Internet.",
            403,
        )
    return None


def _unless_the_password_is_given() -> Optional[Response]:
    """What is answered when the request does not carry, as ``current``,
    the password in place; None when it does."""
    given = _given("current")
    if given is None:
        return _not_a_password()
    wait = claim_attempt("change")
    if wait:
        return _wait_answer(wait)
    if not check_password(given[0]):
        return _refuse(
            "wrong_password",
            "Wrong Password",
            "This is not the password in place.",
            401,
        )
    note_success("change")
    return None


@auth_api.route("/code/start", methods=["POST"])
def code_start() -> Response:
    refused = _for_the_code()
    if refused is not None:
        return refused
    if code_is_set():
        # Another in the place of the one in force: as for doing away
        # with it, a page left open is not enough.
        not_the_owner = _unless_the_password_is_given()
        if not_the_owner is not None:
            return not_the_owner
    try:
        secret = start_code()
    except OSError as error:
        return _not_kept(error)
    name = config.get_printer_display_name() or "Mariner"
    return jsonify({"secret": secret, "uri": totp.uri(secret, name)})


@auth_api.route("/code/confirm", methods=["POST"])
def code_confirm() -> Response:
    refused = _for_the_code()
    if refused is not None:
        return refused
    given = _given("code")
    try:
        confirmed = given is not None and confirm_code(given[0])
    except OSError as error:
        return _not_kept(error)
    if not confirmed:
        return _refuse(
            "wrong_code",
            "Wrong Code",
            "This is not the code of the moment. Check that the phone took "
            "the key in, and that its clock is right.",
            400,
        )
    logger.warning("A one-time code was set up from %s", request.remote_addr)
    journal.note("code_set", request.remote_addr)
    return jsonify({"success": True})


@auth_api.route("/code/remove", methods=["POST"])
def code_remove() -> Response:
    refused = _for_the_code()
    if refused is not None:
        return refused
    not_the_owner = _unless_the_password_is_given()
    if not_the_owner is not None:
        return not_the_owner
    try:
        remove_code()
    except OSError as error:
        return _not_kept(error)
    logger.warning("The one-time code was removed from %s", request.remote_addr)
    journal.note("code_removed", request.remote_addr)
    return jsonify({"success": True})


@auth_api.route("/journal", methods=["GET"])
def sign_ins() -> Response:
    """The last sign-ins and attempts, for who is signed in."""
    shut = _shut()
    if shut is not None:
        return shut
    if not is_signed_in():
        body = refusal("/api/auth-journal", session) or {}
        return make_response(jsonify(body), status_of(body))
    tried = journal.since_the_visit_before()
    return jsonify(
        {
            "entries": journal.entries(),
            "wrong_since_last_visit": tried["wrong_passwords"],
            "wrong_codes_since_last_visit": tried["wrong_codes"],
            "wrong_since_last_visit_or_more": tried["or_more"],
        }
    )
