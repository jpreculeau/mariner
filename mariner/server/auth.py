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
from typing import Any, Dict, Mapping, Optional, Tuple

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

from mariner import config, passwords
from mariner.passwords import PasswordNotAllowed  # noqa: F401
from mariner.server import sessions, state

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
    return passwords.matches(_record(), candidate)


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
    if place is None:
        return _SHARED
    own = _OWN + place
    moment = time.monotonic() if now is None else now
    with _attempts_lock:
        for name, (_, last) in list(_attempts.items()):
            if name.startswith(_OWN) and last + _FORGOTTEN_AFTER_SECS < moment:
                del _attempts[name]
        if own in _attempts:
            return own
        taken = sum(1 for name in _attempts if name.startswith(_OWN))
        return own if taken < _MOST_ADDRESSES else _SHARED


def forget_attempts() -> None:
    with _attempts_lock:
        _attempts.clear()


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


def let_in(held: Mapping[str, Any], key: str) -> bool:
    """Whether a session holding *held*, sent with *key*, is signed in."""
    if not signed_in_with(held):
        return False
    expected = held.get(_KEY_AS)
    return isinstance(expected, str) and hmac.compare_digest(_hash_of(key), expected)


def is_signed_in() -> bool:
    return let_in(session, request.headers.get(KEY_HEADER, ""))


def _sign_in(under: str) -> Response:
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
    session.permanent = True
    return jsonify({"success": True, "csrf_token": generate_csrf(), "page_key": key})


def _unavailable() -> Dict[str, str]:
    return {
        "code": "state_unavailable",
        "title": "Password Out Of Reach",
        "description": "Mariner cannot use the folder it keeps its password "
        f"in ({config.get_state_directory()}), so its page stays shut. On the "
        "computer it runs on, give that folder to the account Mariner runs "
        "under and make sure it can be written, then restart Mariner.",
    }


# Reached without being signed in: they are what signs in.
_OPEN_PATHS = ("/api/csrf_token",)
_OPEN_PREFIXES = ("/api/auth/",)


def refusal(
    path: str, held: Mapping[str, Any], key: str = "", method: str = "GET"
) -> Optional[Dict[str, str]]:
    """Why a request for *path* is not answered to who holds *held* and
    sent *key*.

    None when it is: not one of the page's own addresses, one that signs
    in, or a session that is signed in.
    """
    if not path.startswith("/api/"):
        return None
    if path in _OPEN_PATHS or path.startswith(_OPEN_PREFIXES):
        return None
    if state.is_makeshift():
        return _unavailable()
    if let_in(held, key):
        return None
    if (method, path) in _WITHOUT_KEY and signed_in_with(held):
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
    body = request.get_json(silent=True)
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
    if state.is_makeshift():
        # Shut, and not for want of a password.
        return jsonify({"password_set": True, "signed_in": False, "unavailable": True})
    signed_in = is_signed_in()
    if signed_in:
        # The month starts again here: when the page is opened, not with
        # every answer (see SESSION_REFRESH_EACH_REQUEST).
        session.modified = True
    return jsonify({"password_set": has_password(), "signed_in": signed_in})


def _shut() -> Optional[Response]:
    """The answer when what is kept is out of reach; None when it is not."""
    if state.is_makeshift():
        return make_response(jsonify(_unavailable()), 503)
    return None


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
    count = count_of(request.remote_addr)
    wait = claim_attempt(count)
    if wait:
        return _wait_answer(wait)
    current = generation()
    if current is None or not check_password(given[0]):
        logger.warning("Wrong password from %s", request.remote_addr)
        return _refuse(
            "wrong_password", "Wrong Password", "This is not the password.", 401
        )
    note_success(count)
    _use_the_key_that_is_kept()
    return _sign_in(current)


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
    return _sign_in(changed)


def _rank(held: Mapping[str, Any], key: str) -> int:
    """How far a session is let in: with the key the page sent, signed
    in, or neither."""
    if let_in(held, key):
        return 2
    return 1 if signed_in_with(held) else 0


# Among the cookies a request carries, the session that goes with the
# key comes first, then one that is signed in.
sessions.rank = _rank
