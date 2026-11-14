"""Access keys (passkeys), as browsers give them (WebAuthn).

A phone, a computer or a security key holds a key made for this Mariner
alone, and signs with it once its owner has shown a finger, a face or the
code of the device: nothing to remember, nothing a stranger can guess from
afar, and nothing a page that only looks like this one can ask for.

Apart from the server, like ``mariner.totp``: what is sent is read here
and believed only when everything in it holds. What the maker of the
device says about it (its "attestation") is not looked at: whose device
it is matters, not its brand.
"""

import base64
import binascii
import hashlib
import hmac
import json
import secrets
import struct
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from Crypto.Hash import SHA256
from Crypto.PublicKey import ECC, RSA
from Crypto.Signature import DSS, eddsa, pkcs1_15

# The name of the file they are kept in, in the state directory.
KEPT_AS = "access-keys"

# Far more than a browser sends; what is longer is not read at all.
_CLIENT_DATA_AT_MOST = 8 * 1024
_ATTESTATION_AT_MOST = 64 * 1024
_SIGNATURE_AT_MOST = 1024
_IDENTIFIER_AT_MOST = 1023
_RSA_BITS_AT_LEAST = 2048
# What an authenticator sends is three or four deep.
_CBOR_DEPTH_AT_MOST = 16

_PRESENT = 0x01
_VERIFIED = 0x04
_WITH_KEY = 0x40
_WITH_EXTENSIONS = 0x80

# The algorithms taken, as COSE numbers them: what phones, computers and
# security keys make.
ES256 = -7
EDDSA = -8
RS256 = -257
ALGORITHMS = (ES256, EDDSA, RS256)


class Refused(Exception):
    """What was sent does not hold; *code* says in what."""

    def __init__(self, code: str, description: str) -> None:
        super().__init__(description)
        self.code = code
        self.description = description


def _malformed(what: str) -> Refused:
    return Refused("malformed", f"This is not what a browser sends: {what}.")


def new_challenge() -> str:
    """What a key is asked to sign: never the same twice."""
    return _b64(secrets.token_bytes(32))


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _from_b64(text: Any) -> bytes:
    if not isinstance(text, str) or not text:
        raise ValueError("not text")
    try:
        return base64.b64decode(
            text + "=" * (-len(text) % 4), altchars=b"-_", validate=True
        )
    except binascii.Error as error:
        raise ValueError(str(error))


# --- CBOR, as far as authenticators write it (RFC 8949) -------------------


def cbor_first(data: bytes) -> Tuple[Any, bytes]:
    """The first value written in *data*, and what follows it.

    Whole numbers, bytes, text, lists, maps, true, false and nothing: what
    authenticators write. Anything else is refused, and so is whatever
    says it is longer than what was sent.
    """
    value, end = _cbor_at(data, 0, 0)
    return value, data[end:]


def _cbor_head(data: bytes, at: int) -> Tuple[int, int, int]:
    if at >= len(data):
        raise _malformed("it ends too soon")
    major, extra = data[at] >> 5, data[at] & 0x1F
    at += 1
    if extra < 24:
        return major, extra, at
    if extra > 27:
        raise _malformed("a length that is not set")
    size = 1 << (extra - 24)
    if at + size > len(data):
        raise _malformed("it ends too soon")
    end = at + size
    return major, int.from_bytes(data[at:end], "big"), end


def _cbor_at(data: bytes, at: int, depth: int) -> Tuple[Any, int]:
    if depth > _CBOR_DEPTH_AT_MOST:
        raise _malformed("lists within lists without end")
    start = at
    major, value, at = _cbor_head(data, at)
    if major == 0:
        return value, at
    if major == 1:
        return -1 - value, at
    if major in (2, 3):
        if value > len(data) - at:
            raise _malformed("it ends too soon")
        end = at + value
        held = data[at:end]
        if major == 2:
            return held, end
        try:
            return held.decode("utf-8"), end
        except UnicodeDecodeError:
            raise _malformed("a text that is not one")
    if major == 4:
        # Each of them takes one byte at least.
        if value > len(data) - at:
            raise _malformed("it ends too soon")
        items: List[Any] = []
        for _ in range(value):
            item, at = _cbor_at(data, at, depth + 1)
            items.append(item)
        return items, at
    if major == 5:
        if value > (len(data) - at) // 2:
            raise _malformed("it ends too soon")
        pairs: Dict[Any, Any] = {}
        for _ in range(value):
            key, at = _cbor_at(data, at, depth + 1)
            # A list is no name for anything; nor is true, which Python
            # would take for the number one.
            if isinstance(key, bool) or not isinstance(key, (int, str)):
                raise _malformed("a name that is neither a number nor a text")
            if key in pairs:
                raise _malformed("a name given twice")
            pairs[key], at = _cbor_at(data, at, depth + 1)
        return pairs, at
    if major == 7 and data[start] in (0xF4, 0xF5, 0xF6):
        return {0xF4: False, 0xF5: True, 0xF6: None}[data[start]], at
    raise _malformed("a kind of value no authenticator writes")


# --- The public key of an access key (COSE, RFC 9052 and 9053) -------------


def _not_supported(what: str) -> Refused:
    return Refused("key_not_supported", f"This kind of key is not taken: {what}.")


def _number(held: Any, length: int) -> int:
    """A coordinate of *length* bytes, as a number."""
    if not isinstance(held, bytes) or len(held) != length:
        raise _not_supported("a part of it is missing or of the wrong length")
    return int.from_bytes(held, "big")


def _verifier(cose: Any) -> Tuple[int, Any]:
    """The algorithm of the key written in *cose*, and what checks a
    signature made with it: called with what was signed and the signature,
    it raises ValueError when that one is not of this key."""
    if not isinstance(cose, dict):
        raise _not_supported("it is not written as a key is")
    kind, algorithm = cose.get(1), cose.get(3)
    try:
        if algorithm == ES256 and kind == 2 and cose.get(-1) == 1:
            point = ECC.construct(
                curve="P-256",
                point_x=_number(cose.get(-2), 32),
                point_y=_number(cose.get(-3), 32),
            )
            check = DSS.new(point, "fips-186-3", encoding="der")
            return ES256, lambda signed, signature: check.verify(
                SHA256.new(signed), signature
            )
        if algorithm == EDDSA and kind == 1 and cose.get(-1) == 6:
            held = cose.get(-2)
            if not isinstance(held, bytes) or len(held) != 32:
                raise _not_supported("a part of it is missing or of the wrong length")
            edwards = eddsa.new(eddsa.import_public_key(held), "rfc8032")
            return EDDSA, lambda signed, signature: edwards.verify(signed, signature)
        if algorithm == RS256 and kind == 3:
            modulus, exponent = cose.get(-1), cose.get(-2)
            if not isinstance(modulus, bytes) or not isinstance(exponent, bytes):
                raise _not_supported("a part of it is missing")
            n = int.from_bytes(modulus, "big")
            if n.bit_length() < _RSA_BITS_AT_LEAST or len(exponent) > 8:
                raise _not_supported("it is too short to be relied on")
            rsa = pkcs1_15.new(RSA.construct((n, int.from_bytes(exponent, "big"))))
            return RS256, lambda signed, signature: rsa.verify(
                SHA256.new(signed), signature
            )
    except (ValueError, TypeError) as error:
        # A point that is not on the curve, a modulus that is none.
        raise _not_supported(str(error) or "it is not a key")
    raise _not_supported("its algorithm")


# --- What the page and the authenticator say -------------------------------


def _client_said(
    client_data: bytes, kind: str, challenge: str, origins: Sequence[str]
) -> None:
    """Whether what the browser says it did is what was asked of it."""
    if not isinstance(client_data, bytes) or len(client_data) > _CLIENT_DATA_AT_MOST:
        raise _malformed("what the page says is too long")
    try:
        said = json.loads(client_data.decode("utf-8"))
    except (ValueError, RecursionError):
        raise _malformed("what the page says cannot be read")
    if not isinstance(said, dict):
        raise _malformed("what the page says cannot be read")
    if said.get("type") != kind:
        raise Refused("wrong_type", "This was made for something else.")
    answered = said.get("challenge")
    if not isinstance(answered, str) or not hmac.compare_digest(
        answered.encode("utf-8"), challenge.encode("utf-8")
    ):
        raise Refused("wrong_challenge", "This does not answer what was asked.")
    # The address of the page as the browser itself gives it: a page that
    # only looks like this one has another, and cannot change it. Nor is
    # the page taken when shown inside one of another site.
    if said.get("origin") not in origins or said.get("crossOrigin") is True:
        raise Refused("wrong_origin", "This was made on another site.")


def _authenticator_said(
    data: Any, rp_id: str, with_key: bool
) -> Tuple[int, bool, bytes]:
    """The count the authenticator gives, whether extensions are written
    at the end, and what follows its head.

    Whether it was made for this name, with its owner there and checked
    (a finger, a face, the code of the device), is looked at here.
    """
    if not isinstance(data, bytes) or len(data) < 37:
        raise _malformed("what the authenticator says is cut short")
    if len(data) > _ATTESTATION_AT_MOST:
        raise _malformed("what the authenticator says is too long")
    made_for, flags = data[:32], data[32]
    (count,) = struct.unpack(">I", data[33:37])
    if bool(flags & _WITH_KEY) != with_key:
        raise _malformed("a key where none is expected, or none where one is")
    if not hmac.compare_digest(
        made_for, hashlib.sha256(rp_id.encode("utf-8")).digest()
    ):
        raise Refused("wrong_site", "This key was made for another name.")
    if not flags & _PRESENT or not flags & _VERIFIED:
        raise Refused(
            "user_not_verified",
            "The device did not check who was there (a finger, a face or its code).",
        )
    return count, bool(flags & _WITH_EXTENSIONS), data[37:]


def _nothing_but_extensions(rest: bytes, extended: bool) -> None:
    if extended:
        _, rest = cbor_first(rest)
    if rest:
        raise _malformed("what the authenticator says goes on")


def registered(
    client_data: bytes,
    attestation: bytes,
    challenge: str,
    origins: Sequence[str],
    rp_id: str,
) -> Dict[str, Any]:
    """What to keep of the key a browser has just made, or Refused.

    *challenge* is what was given to sign, *origins* the addresses the page
    may be at, *rp_id* the name the key is made for. What is given back is
    plain enough to be written as JSON: ``id``, ``key``, ``alg``, ``count``.
    """
    _client_said(client_data, "webauthn.create", challenge, origins)
    if not isinstance(attestation, bytes) or len(attestation) > _ATTESTATION_AT_MOST:
        raise _malformed("what the authenticator says is too long")
    stated, rest = cbor_first(attestation)
    if rest or not isinstance(stated, dict):
        raise _malformed("what the authenticator says cannot be read")
    count, extended, rest = _authenticator_said(
        stated.get("authData"), rp_id, with_key=True
    )
    if len(rest) < 18:
        raise _malformed("the key is cut short")
    (length,) = struct.unpack(">H", rest[16:18])
    if not 0 < length <= _IDENTIFIER_AT_MOST or len(rest) < 18 + length:
        raise _malformed("the key is cut short")
    end = 18 + length
    identifier, written = rest[18:end], rest[end:]
    try:
        cose, after = cbor_first(written)
    except Refused:
        raise _not_supported("it cannot be read")
    _nothing_but_extensions(after, extended)
    algorithm, _ = _verifier(cose)
    return {
        "id": _b64(identifier),
        # The key alone, as it was written, without what follows it.
        "key": _b64(written[: len(written) - len(after)]),
        "alg": algorithm,
        "count": count,
    }


def asserted(
    credential: Mapping[str, Any],
    client_data: bytes,
    authenticator_data: bytes,
    signature: bytes,
    challenge: str,
    origins: Sequence[str],
    rp_id: str,
) -> int:
    """The count to keep once the key in *credential* has signed, or
    Refused: *credential* is what ``registered`` gave."""
    _client_said(client_data, "webauthn.get", challenge, origins)
    count, extended, rest = _authenticator_said(
        authenticator_data, rp_id, with_key=False
    )
    _nothing_but_extensions(rest, extended)
    try:
        cose, rest = cbor_first(_from_b64(credential.get("key")))
    except (ValueError, Refused):
        raise _not_supported("what is kept of it cannot be read")
    if rest:
        raise _not_supported("what is kept of it cannot be read")
    _, verify = _verifier(cose)
    wrong = Refused("wrong_signature", "This is not signed by the key.")
    if not isinstance(signature, bytes) or not 0 < len(signature) <= _SIGNATURE_AT_MOST:
        raise wrong
    try:
        verify(authenticator_data + hashlib.sha256(client_data).digest(), signature)
    except (ValueError, TypeError):
        raise wrong
    kept = credential.get("count")
    before = kept if isinstance(kept, int) and not isinstance(kept, bool) else 0
    # Keys that count never count backwards: one that does has a copy
    # somewhere. Those kept in step between the devices of one account do
    # not count at all, and stay at nothing.
    if (count or before) and count <= before:
        raise Refused(
            "key_copied",
            "This key counts backwards: there may be a copy of it. Remove it and "
            "register it again.",
        )
    return count
