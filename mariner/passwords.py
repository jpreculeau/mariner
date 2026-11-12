"""Hashing Mariner's password, and nothing else.

Apart from the server so that the commands which set or clear the
password can be run without loading it: run by an administrator, the
server would make its folders as that account, where the service would
then refuse them.
"""

import hashlib
import hmac
import os
import secrets
from typing import Any, Dict, Mapping, Optional, Tuple

MIN_LENGTH = 8
# Hashing is paid for by Mariner, for whoever sends one.
MAX_LENGTH = 1024

# The cost advised for a password typed by hand: about a tenth of a second
# and 16 MB on a small board. Kept with each hash, so that it can be
# raised later without locking out whoever set a password before.
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
HASH_BYTES = 32

# The name of the file the hash is kept in, in the state directory.
KEPT_AS = "password"

# What everybody tries first, in the languages of the page. Not a judge of
# passwords: only the handful that are no password at all.
_TOO_COMMON = frozenset(
    """
    password password1 password123 passw0rd 12345678 123456789 1234567890
    11111111 00000000 87654321 qwertyui qwertyuiop qwerty123 azertyui
    azertyuiop azerty123 iloveyou letmein123 admin123 administrator
    motdepasse motdepasse1 mariner mariner1 mariner123 mariner2 printer123
    imprimante changeme welcome1 raspberry raspberrypi
    """.split()
)


class PasswordNotAllowed(ValueError):
    def __init__(self, code: str, description: str) -> None:
        super().__init__(description)
        self.code = code
        self.description = description


def scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        dklen=HASH_BYTES,
        maxmem=256 * n * r,
    )


def record_for(password: str) -> Dict[str, Any]:
    """What is kept of *password*; PasswordNotAllowed if it is not one."""
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
    if password.lower() in _TOO_COMMON:
        raise PasswordNotAllowed(
            "password_too_common",
            "This password is among the first anyone would try. Choose another.",
        )
    salt = secrets.token_bytes(16)
    return {
        "scheme": "scrypt",
        "n": SCRYPT_N,
        "r": SCRYPT_R,
        "p": SCRYPT_P,
        "salt": salt.hex(),
        "hash": scrypt(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P).hex(),
        # What tells this password from every other: sessions hold it,
        # and end when it changes.
        "generation": secrets.token_hex(8),
    }


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


def matches(record: Optional[Mapping[str, Any]], candidate: str) -> bool:
    """Whether *candidate* is the password *record* was made from."""
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
    if cost is None or not salt or len(expected) != HASH_BYTES:
        return False
    return hmac.compare_digest(scrypt(candidate, salt, *cost), expected)


def kept_path(state_directory: str) -> str:
    return os.path.join(os.path.expanduser(state_directory), KEPT_AS)
