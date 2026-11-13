"""One-time codes, as the applications of a phone give them (RFC 6238).

The second thing asked of who signs in from the Internet: a password that
was guessed, or read on its way, opens nothing without the phone. Apart
from the server, like ``mariner.passwords``, so that the commands which
set it up can be run without loading it.

SHA-1, six digits, thirty seconds: what every application takes.
"""

import base64
import binascii
import hashlib
import hmac
import secrets
import struct
from typing import Optional
from urllib.parse import quote

PERIOD_SECS = 30
DIGITS = 6
# The name of the file it is kept in, in the state directory.
KEPT_AS = "one-time-code"


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii")


def _key(secret: str) -> Optional[bytes]:
    try:
        key = base64.b32decode(secret.replace(" ", "").upper())
    except (binascii.Error, ValueError):
        return None
    return key or None


def _code(key: bytes, step: int) -> str:
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    start = digest[-1] & 0x0F
    end = start + 4
    number = struct.unpack(">I", digest[start:end])[0] & 0x7FFFFFFF
    return str(number % 10**DIGITS).zfill(DIGITS)


def code_at(secret: str, moment: float) -> Optional[str]:
    """The code *secret* gives at *moment*, in seconds since 1970."""
    key = _key(secret)
    return None if key is None else _code(key, int(moment) // PERIOD_SECS)


def step_of(
    secret: str, candidate: str, moment: float, after: Optional[int] = None
) -> Optional[int]:
    """Which thirty seconds *candidate* is the code of; None if it is not one.

    The one of *moment*, the one before or the one after: a phone's clock
    is a little off. Never one at or before *after*, the last that
    served: a code opens nothing twice.
    """
    key = _key(secret)
    typed = candidate.replace(" ", "")
    if key is None or len(typed) != DIGITS or not typed.isascii():
        return None
    if not typed.isdigit():
        return None
    now = int(moment) // PERIOD_SECS
    found = None
    # Every one is looked at, whichever matches.
    for step in (now - 1, now, now + 1):
        if step < 0:
            continue
        same = hmac.compare_digest(_code(key, step), typed)
        if same and (after is None or step > after) and found is None:
            found = step
    return found


def uri(secret: str, name: str) -> str:
    """What an application is given to take *secret* in, under *name*."""
    return (
        f"otpauth://totp/Mariner:{quote(name, safe='')}?secret={secret}"
        f"&issuer=Mariner&algorithm=SHA1&digits={DIGITS}&period={PERIOD_SECS}"
    )


def grouped(secret: str) -> str:
    """*secret* in groups of four, to be typed."""
    groups = [secret[at:][:4] for at in range(0, len(secret), 4)]
    return " ".join(groups)
