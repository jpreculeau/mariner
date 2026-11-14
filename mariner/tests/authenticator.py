"""What a phone or a security key does, for tests: makes a key, and signs."""

import base64
import hashlib
import json
import struct
from typing import Any, Dict, Optional

from Crypto.Hash import SHA256
from Crypto.PublicKey import ECC, RSA
from Crypto.Signature import DSS, eddsa, pkcs1_15

ORIGIN = "https://saturn.example.org:5443"
RP_ID = "saturn.example.org"

PRESENT = 0x01
VERIFIED = 0x04
WITH_KEY = 0x40
WITH_EXTENSIONS = 0x80


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _head(major: int, value: int) -> bytes:
    if value < 24:
        return bytes([major << 5 | value])
    for extra, form in ((24, ">B"), (25, ">H"), (26, ">I"), (27, ">Q")):
        if value < 1 << (8 * struct.calcsize(form)):
            return bytes([major << 5 | extra]) + struct.pack(form, value)
    raise ValueError(value)


def cbor(value: Any) -> bytes:
    """Enough of CBOR to write what an authenticator sends."""
    if value is False:
        return b"\xf4"
    if value is True:
        return b"\xf5"
    if value is None:
        return b"\xf6"
    if isinstance(value, int):
        return _head(0, value) if value >= 0 else _head(1, -1 - value)
    if isinstance(value, bytes):
        return _head(2, len(value)) + value
    if isinstance(value, str):
        text = value.encode("utf-8")
        return _head(3, len(text)) + text
    if isinstance(value, list):
        return _head(4, len(value)) + b"".join(cbor(item) for item in value)
    if isinstance(value, dict):
        return _head(5, len(value)) + b"".join(
            cbor(key) + cbor(item) for key, item in value.items()
        )
    raise TypeError(type(value))


class Authenticator:
    def __init__(self, kind: str = "es256", rp_id: str = RP_ID) -> None:
        self.kind = kind
        self.rp_id = rp_id
        self.identifier = hashlib.sha256(kind.encode("ascii")).digest()
        self.count = 0
        if kind == "es256":
            self.key: Any = ECC.generate(curve="P-256")
        elif kind == "eddsa":
            self.key = ECC.generate(curve="Ed25519")
        else:
            self.key = RSA.generate(2048)

    def cose(self) -> Dict[int, Any]:
        if self.kind == "es256":
            point = self.key.pointQ
            return {
                1: 2,
                3: -7,
                -1: 1,
                -2: int(point.x).to_bytes(32, "big"),
                -3: int(point.y).to_bytes(32, "big"),
            }
        if self.kind == "eddsa":
            return {
                1: 1,
                3: -8,
                -1: 6,
                -2: self.key.public_key().export_key(format="raw"),
            }
        return {
            1: 3,
            3: -257,
            -1: self.key.n.to_bytes(256, "big"),
            -2: self.key.e.to_bytes(3, "big"),
        }

    def _sign(self, signed: bytes) -> bytes:
        if self.kind == "es256":
            return DSS.new(self.key, "fips-186-3", encoding="der").sign(
                SHA256.new(signed)
            )
        if self.kind == "eddsa":
            return eddsa.new(self.key, "rfc8032").sign(signed)
        return pkcs1_15.new(self.key).sign(SHA256.new(signed))

    def data(
        self,
        flags: int,
        with_key: bool = False,
        cose: Optional[Dict[int, Any]] = None,
        extensions: Optional[Dict[str, Any]] = None,
    ) -> bytes:
        out = hashlib.sha256(self.rp_id.encode("ascii")).digest()
        if with_key:
            flags |= WITH_KEY
        if extensions is not None:
            flags |= WITH_EXTENSIONS
        out += bytes([flags]) + struct.pack(">I", self.count)
        if with_key:
            out += bytes(16) + struct.pack(">H", len(self.identifier))
            out += self.identifier + cbor(self.cose() if cose is None else cose)
        if extensions is not None:
            out += cbor(extensions)
        return out

    @staticmethod
    def client(kind: str, challenge: str, origin: str = ORIGIN, **more: Any) -> bytes:
        said = {"type": kind, "challenge": challenge, "origin": origin, **more}
        return json.dumps(said).encode("utf-8")

    def create(
        self,
        challenge: str,
        origin: str = ORIGIN,
        flags: int = PRESENT | VERIFIED,
        **more: Any,
    ) -> Dict[str, bytes]:
        """What ``navigator.credentials.create`` gives the page."""
        data = self.data(flags, with_key=True, **more)
        return {
            "client": self.client("webauthn.create", challenge, origin),
            "attestation": cbor({"fmt": "none", "attStmt": {}, "authData": data}),
        }

    def get(
        self,
        challenge: str,
        origin: str = ORIGIN,
        flags: int = PRESENT | VERIFIED,
        kind: str = "webauthn.get",
    ) -> Dict[str, bytes]:
        """What ``navigator.credentials.get`` gives the page."""
        self.count += 1
        data = self.data(flags)
        client = self.client(kind, challenge, origin)
        return {
            "client": client,
            "data": data,
            "signature": self._sign(data + hashlib.sha256(client).digest()),
        }
