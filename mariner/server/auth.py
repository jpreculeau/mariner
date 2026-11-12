"""The password that opens Mariner's page, and who is signed in.

One password, for whoever is to drive the printer. It is kept as a hash
that does not give it away, in the folder Mariner keeps for itself
(``mariner.server.state``): it cannot be read back, only replaced.

The interfaces slicers speak (UVtools, SDCP) know nothing of passwords
and are not behind this one; each has a switch.
"""

import hashlib
import hmac
import json
import logging
import math
import os
import stat
import secrets
import threading
import time
from typing import Any, Dict, Mapping, Optional, TextIO, Tuple

from flask import Blueprint, Response, jsonify, make_response, request, session
from flask_wtf.csrf import generate_csrf

from mariner import config
from mariner.server import state

logger: logging.Logger = logging.getLogger(__name__)

MIN_LENGTH = 8
# Hashing is paid for by Mariner, for whoever sends one.
MAX_LENGTH = 1024

# The cost advised for a password typed by hand: about a tenth of a second
# and 16 MB on a small board. Kept with each hash, so that it can be
# raised later without locking out whoever set a password before.
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_HASH_BYTES = 32

_KEPT_AS = "password"


class PasswordNotAllowed(ValueError):
    def __init__(self, code: str, description: str) -> None:
        super().__init__(description)
        self.code = code
        self.description = description


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        dklen=_HASH_BYTES,
        maxmem=256 * n * r,
    )


def _record() -> Optional[Dict[str, Any]]:
    """What is kept of the password; None if nothing usable is."""
    kept = state.read(_KEPT_AS)
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
    return state.exists(_KEPT_AS)


def generation() -> Optional[str]:
    """What tells the password in place from those before it.

    Sessions hold it, and end when it changes.
    """
    record = _record()
    value = record.get("generation") if record else None
    return value if isinstance(value, str) and value else None


def set_password(password: str) -> None:
    if len(password) < MIN_LENGTH:
        raise PasswordNotAllowed(
            "password_too_short",
            f"A password has at least {MIN_LENGTH} characters.",
        )
    if len(password) > MAX_LENGTH:
        raise PasswordNotAllowed(
            "password_too_long",
            f"A password has at most {MAX_LENGTH} characters.",
        )
    salt = secrets.token_bytes(16)
    record = {
        "scheme": "scrypt",
        "n": _SCRYPT_N,
        "r": _SCRYPT_R,
        "p": _SCRYPT_P,
        "salt": salt.hex(),
        "hash": _scrypt(password, salt, _SCRYPT_N, _SCRYPT_R, _SCRYPT_P).hex(),
        "generation": secrets.token_hex(8),
    }
    state.write(_KEPT_AS, json.dumps(record).encode("ascii"))


def clear_password() -> None:
    """Leave no password: the next visit is asked to choose one."""
    state.remove(_KEPT_AS)


def _cost(record: Mapping[str, Any]) -> Optional[Tuple[int, int, int]]:
    n, r, p = record.get("n"), record.get("r"), record.get("p")
    for value in (n, r, p):
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            return None
    # Within what Mariner would ever have written: a record is not
    # trusted to say how much memory to take.
    if n & (n - 1) or n > 2**17 or r > 16 or p > 4:  # type: ignore[operator]
        return None
    return n, r, p  # type: ignore[return-value]


def check_password(candidate: str) -> bool:
    record = _record()
    if record is None or record.get("scheme") != "scrypt":
        return False
    if not candidate or len(candidate) > MAX_LENGTH:
        return False
    cost = _cost(record)
    try:
        salt = bytes.fromhex(str(record.get("salt", "")))
        expected = bytes.fromhex(str(record.get("hash", "")))
    except ValueError:
        return False
    if cost is None or not salt or len(expected) != _HASH_BYTES:
        return False
    return hmac.compare_digest(_scrypt(candidate, salt, *cost), expected)


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
                state.write(_SEEN_AS, looks)
                logger.warning(
                    "The password was cleared, as %r asked. The file could "
                    "not be removed: it is passed over from now on, until "
                    "it is written again",
                    asked,
                )
            return True
    return False


def clear_from_the_command_line(out: TextIO) -> int:
    """``mariner reset-password``: clear the password of the service.

    In the folder the configuration names, whoever runs the command: an
    administrator's own folder is not the service's.
    """
    kept = os.path.join(config.get_state_directory(), _KEPT_AS)
    try:
        os.unlink(kept)
    except FileNotFoundError:
        print("No password was set. Open Mariner's page to choose one.", file=out)
        return 0
    except OSError as error:
        print(
            f"The password could not be cleared ({error}). Run this command "
            "with sudo.",
            file=out,
        )
        return 1
    print(
        "The password was cleared. Open Mariner's page to choose a new one: "
        "until then, whoever opens it first can.",
        file=out,
    )
    return 0


# -- attempts --------------------------------------------------------------

# Counted for all comers together: there is one password, and one person
# who knows it. Counted by address, someone trying passwords would only
# have to change address.
_FREE_ATTEMPTS = 3
_LONGEST_WAIT_SECS = 30
_attempts_lock = threading.Lock()
_failures = 0
_last_failure_at = 0.0


def forget_attempts() -> None:
    global _failures, _last_failure_at
    with _attempts_lock:
        _failures = 0
        _last_failure_at = 0.0


def note_failure(now: Optional[float] = None) -> None:
    global _failures, _last_failure_at
    with _attempts_lock:
        _failures += 1
        _last_failure_at = time.monotonic() if now is None else now


def note_success() -> None:
    forget_attempts()


def wait_before_next_attempt(now: Optional[float] = None) -> int:
    """Seconds before another password is looked at; 0 if one is now.

    Nothing after a few wrong ones, then twice as long after each, up to
    half a minute: never so long that the owner is kept out for good by
    someone else's attempts.
    """
    with _attempts_lock:
        if _failures < _FREE_ATTEMPTS:
            return 0
        wait = min(_LONGEST_WAIT_SECS, 2 ** (_failures - _FREE_ATTEMPTS))
        left = _last_failure_at + wait - (time.monotonic() if now is None else now)
        return max(0, math.ceil(left))


# -- who is signed in ------------------------------------------------------

_SIGNED_IN_AS = "auth"


def signed_in_with(held: Mapping[str, Any]) -> bool:
    """Whether a session holding *held* is signed in under the password
    in place."""
    current = generation()
    return current is not None and held.get(_SIGNED_IN_AS) == current


def is_signed_in() -> bool:
    return signed_in_with(session)


def _sign_in() -> None:
    # A new session: nothing a page held before signing in comes along.
    session.clear()
    session[_SIGNED_IN_AS] = generation()
    session.permanent = True


# Reached without being signed in: they are what signs in.
_OPEN_PATHS = ("/api/csrf_token",)
_OPEN_PREFIXES = ("/api/auth/",)


def refusal(path: str, held: Mapping[str, Any]) -> Optional[Dict[str, str]]:
    """Why a request for *path* is not answered to who holds *held*.

    None when it is: not one of the page's own addresses, one that signs
    in, or a session that is signed in.
    """
    if not path.startswith("/api/"):
        return None
    if path in _OPEN_PATHS or path.startswith(_OPEN_PREFIXES):
        return None
    if signed_in_with(held):
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


# -- addresses -------------------------------------------------------------

auth_api = Blueprint("auth", __name__, url_prefix="/api/auth")


def _refuse(code: str, title: str, description: str, status: int) -> Response:
    body = {"code": code, "title": title, "description": description}
    return make_response(jsonify(body), status)


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


def _signed_in_answer() -> Response:
    # With a token for the new session: the one the page holds went with
    # the session it had.
    return jsonify({"success": True, "csrf_token": generate_csrf()})


@auth_api.route("/state", methods=["GET"])
def auth_state() -> Response:
    return jsonify({"password_set": has_password(), "signed_in": is_signed_in()})


@auth_api.route("/setup", methods=["POST"])
def setup() -> Response:
    """Choose the password, when there is none."""
    if has_password():
        return _refuse(
            "password_already_set",
            "Password Already Chosen",
            "A password has already been chosen. Sign in with it; if it is "
            "lost, Mariner's documentation says how to start over.",
            409,
        )
    given = _given("password")
    if given is None:
        return _not_a_password()
    try:
        set_password(given[0])
    except PasswordNotAllowed as error:
        return _refuse(error.code, "Password Not Taken", error.description, 400)
    logger.warning("A password was chosen from %s", request.remote_addr)
    _sign_in()
    return _signed_in_answer()


@auth_api.route("/login", methods=["POST"])
def login() -> Response:
    wait = wait_before_next_attempt()
    if wait:
        answer = _refuse(
            "too_many_attempts",
            "Too Many Attempts",
            f"Too many wrong passwords. Try again in {wait} seconds.",
            429,
        )
        answer.headers["Retry-After"] = str(wait)
        return answer
    given = _given("password")
    if given is None:
        return _not_a_password()
    if not check_password(given[0]):
        note_failure()
        logger.warning("Wrong password from %s", request.remote_addr)
        return _refuse(
            "wrong_password", "Wrong Password", "This is not the password.", 401
        )
    note_success()
    _sign_in()
    return _signed_in_answer()


@auth_api.route("/logout", methods=["POST"])
def logout() -> Response:
    session.clear()
    # With a token for what comes next, which is signing in again.
    return jsonify({"success": True, "csrf_token": generate_csrf()})


@auth_api.route("/password", methods=["POST"])
def change_password() -> Response:
    """Replace the password; every other session ends."""
    if not is_signed_in():
        body = refusal("/api/auth-change", session) or {}
        return make_response(jsonify(body), 401)
    wait = wait_before_next_attempt()
    if wait:
        answer = _refuse(
            "too_many_attempts",
            "Too Many Attempts",
            f"Too many wrong passwords. Try again in {wait} seconds.",
            429,
        )
        answer.headers["Retry-After"] = str(wait)
        return answer
    given = _given("current", "new")
    if given is None:
        return _not_a_password()
    current, new = given
    if not check_password(current):
        note_failure()
        return _refuse(
            "wrong_password",
            "Wrong Password",
            "This is not the password in place.",
            401,
        )
    try:
        set_password(new)
    except PasswordNotAllowed as error:
        return _refuse(error.code, "Password Not Taken", error.description, 400)
    note_success()
    logger.warning("The password was changed from %s", request.remote_addr)
    _sign_in()
    return _signed_in_answer()
