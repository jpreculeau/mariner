"""Access keys (passkeys): what a phone or a security key sends is read,
and believed only when everything in it holds."""

import json
from typing import Any
from unittest import TestCase

from pyexpect import expect

from mariner import webauthn
from mariner.tests.authenticator import (
    ORIGIN,
    PRESENT,
    RP_ID,
    VERIFIED,
    Authenticator,
    b64,
    cbor,
)

ORIGINS = (ORIGIN,)


def _refused(test: TestCase, code: str, call: Any, *given: Any, **named: Any) -> None:
    with test.assertRaises(webauthn.Refused) as raised:
        call(*given, **named)
    expect(raised.exception.code).to_equal(code)


class CborTest(TestCase):
    def test_what_the_standard_gives_as_examples_is_read(self) -> None:
        # RFC 8949, appendix A.
        for written, meant in (
            ("00", 0),
            ("17", 23),
            ("1818", 24),
            ("1903e8", 1000),
            ("1a000f4240", 1000000),
            ("1b000000e8d4a51000", 1000000000000),
            ("20", -1),
            ("3863", -100),
            ("3903e7", -1000),
            ("f4", False),
            ("f5", True),
            ("f6", None),
            ("40", b""),
            ("4401020304", b"\x01\x02\x03\x04"),
            ("60", ""),
            ("6449455446", "IETF"),
            ("62c3bc", "ü"),
            ("80", []),
            ("83010203", [1, 2, 3]),
            ("8301820203820405", [1, [2, 3], [4, 5]]),
            ("a0", {}),
            ("a201020304", {1: 2, 3: 4}),
            ("a26161016162820203", {"a": 1, "b": [2, 3]}),
        ):
            value, rest = webauthn.cbor_first(bytes.fromhex(written))
            expect(value).to_equal(meant)
            expect(rest).to_equal(b"")

    def test_what_follows_is_given_back(self) -> None:
        expect(webauthn.cbor_first(bytes.fromhex("0102"))).to_equal((1, b"\x02"))

    def test_what_an_authenticator_has_no_use_for_is_refused(self) -> None:
        for name, written in (
            ("nothing", ""),
            ("cut short", "19"),
            ("bytes cut short", "4401"),
            ("a text that is not one", "62c328"),
            ("a length that lies", "5b7fffffffffffffff"),
            ("a list that lies", "9b00000000ffffffff"),
            ("of no set length", "5f4101ff"),
            ("a list of no set length", "9f01ff"),
            ("a tag", "c11a514b67b0"),
            ("a number with a point", "f93c00"),
            ("undefined", "f7"),
            ("a key twice", "a201020103"),
            ("a key that is a list", "a1800102"),
            ("too deep", "81" * 40 + "00"),
        ):
            with self.subTest(name):
                with self.assertRaises(webauthn.Refused):
                    webauthn.cbor_first(bytes.fromhex(written))


class RegisteredTest(TestCase):
    def setUp(self) -> None:
        self.challenge = webauthn.new_challenge()

    def _registered(self, sent: Any, **changed: Any) -> Any:
        named = {"challenge": self.challenge, "origins": ORIGINS, "rp_id": RP_ID}
        named.update(changed)
        return webauthn.registered(sent["client"], sent["attestation"], **named)

    def test_a_challenge_is_new_each_time(self) -> None:
        expect(len(self.challenge)).to_equal(43)
        expect(webauthn.new_challenge()).not_to_equal(self.challenge)

    def test_a_key_of_each_kind_is_taken(self) -> None:
        for kind, algorithm in (("es256", -7), ("eddsa", -8), ("rs256", -257)):
            with self.subTest(kind):
                phone = Authenticator(kind)
                kept = self._registered(phone.create(self.challenge))
                expect(kept["id"]).to_equal(b64(phone.identifier))
                expect(kept["alg"]).to_equal(algorithm)
                expect(kept["count"]).to_equal(0)
                # What is kept can be written to a file as it is.
                json.dumps(kept)

    def test_extensions_after_the_key_do_not_matter(self) -> None:
        phone = Authenticator()
        sent = phone.create(self.challenge, extensions={"credProtect": 2})
        expect(self._registered(sent)["id"]).to_equal(b64(phone.identifier))

    def test_another_challenge_is_refused(self) -> None:
        sent = Authenticator().create(webauthn.new_challenge())
        _refused(self, "wrong_challenge", self._registered, sent)

    def test_another_site_is_refused(self) -> None:
        for origin in (
            "https://evil.example.org:5443",
            "https://saturn.example.org",
            "http://saturn.example.org:5443",
            "https://saturn.example.org:5443/",
        ):
            with self.subTest(origin):
                sent = Authenticator().create(self.challenge, origin=origin)
                _refused(self, "wrong_origin", self._registered, sent)

    def test_what_was_made_to_sign_in_does_not_register(self) -> None:
        phone = Authenticator()
        sent = phone.create(self.challenge)
        sent["client"] = phone.client("webauthn.get", self.challenge)
        _refused(self, "wrong_type", self._registered, sent)

    def test_a_page_inside_another_is_refused(self) -> None:
        phone = Authenticator()
        sent = phone.create(self.challenge)
        sent["client"] = phone.client(
            "webauthn.create", self.challenge, crossOrigin=True
        )
        _refused(self, "wrong_origin", self._registered, sent)

    def test_a_key_made_for_another_name_is_refused(self) -> None:
        sent = Authenticator(rp_id="evil.example.org").create(self.challenge)
        _refused(self, "wrong_site", self._registered, sent)

    def test_nobody_there_or_nobody_checked_is_refused(self) -> None:
        for flags in (0, VERIFIED, PRESENT):
            with self.subTest(flags=flags):
                sent = Authenticator().create(self.challenge, flags=flags)
                _refused(self, "user_not_verified", self._registered, sent)

    def test_what_holds_no_key_is_refused(self) -> None:
        phone = Authenticator()
        sent = phone.create(self.challenge)
        data = phone.data(PRESENT | VERIFIED)
        sent["attestation"] = cbor({"fmt": "none", "attStmt": {}, "authData": data})
        _refused(self, "malformed", self._registered, sent)

    def test_a_key_that_is_not_said_to_be_there_is_not_taken(self) -> None:
        phone = Authenticator()
        data = bytearray(phone.data(PRESENT | VERIFIED, with_key=True))
        data[32] &= ~0x40
        sent = phone.create(self.challenge)
        sent["attestation"] = cbor(
            {"fmt": "none", "attStmt": {}, "authData": bytes(data)}
        )
        _refused(self, "malformed", self._registered, sent)

    def test_a_key_of_a_kind_not_known_is_refused(self) -> None:
        phone = Authenticator()
        for name, cose in (
            ("another algorithm", {**phone.cose(), 3: -35}),
            ("another curve", {**phone.cose(), -1: 2}),
            ("a kind that does not go with it", {**phone.cose(), 1: 1}),
            ("no algorithm", {1: 2, -1: 1}),
            ("not a map", [1, 2]),
        ):
            with self.subTest(name):
                sent = phone.create(self.challenge, cose=cose)
                _refused(self, "key_not_supported", self._registered, sent)

    def test_a_key_that_is_none_is_refused(self) -> None:
        phone = Authenticator()
        for name, cose in (
            ("a point off the curve", {**phone.cose(), -3: bytes(31) + b"\x05"}),
            ("a coordinate too short", {**phone.cose(), -2: b"\x01"}),
            ("a coordinate that is a number", {**phone.cose(), -2: 5}),
        ):
            with self.subTest(name):
                sent = phone.create(self.challenge, cose=cose)
                _refused(self, "key_not_supported", self._registered, sent)
        weak = Authenticator("rs256")
        cose = {**weak.cose(), -1: (2**1023 + 1).to_bytes(128, "big")}
        _refused(
            self,
            "key_not_supported",
            self._registered,
            weak.create(self.challenge, cose=cose),
        )

    def test_what_is_not_what_a_browser_sends_is_refused(self) -> None:
        good = Authenticator().create(self.challenge)
        for name, client, attestation in (
            ("no JSON", b"\xff\xfe", good["attestation"]),
            ("JSON that is a list", b"[]", good["attestation"]),
            ("no CBOR", good["client"], b"\xff"),
            ("CBOR that is a list", good["client"], cbor([1])),
            ("no data in it", good["client"], cbor({"fmt": "none"})),
            ("data cut short", good["client"], cbor({"authData": bytes(36)})),
            ("more after it", good["client"], good["attestation"] + b"\x00"),
            ("too much of it", good["client"] + b" " * 70000, good["attestation"]),
        ):
            with self.subTest(name):
                _refused(
                    self,
                    "malformed",
                    self._registered,
                    {"client": client, "attestation": attestation},
                )

    def test_bytes_left_after_the_key_are_refused(self) -> None:
        phone = Authenticator()
        data = phone.data(PRESENT | VERIFIED, with_key=True) + b"\x00"
        sent = phone.create(self.challenge)
        sent["attestation"] = cbor({"fmt": "none", "attStmt": {}, "authData": data})
        _refused(self, "malformed", self._registered, sent)


class AssertedTest(TestCase):
    def setUp(self) -> None:
        self.phone = Authenticator()
        first = webauthn.new_challenge()
        self.kept = webauthn.registered(
            **self._named(self.phone.create(first), first, registering=True)
        )
        self.challenge = webauthn.new_challenge()

    @staticmethod
    def _named(sent: Any, challenge: str, registering: bool = False) -> Any:
        named = {"challenge": challenge, "origins": ORIGINS, "rp_id": RP_ID}
        if registering:
            named.update(client_data=sent["client"], attestation=sent["attestation"])
        return named

    def _asserted(self, sent: Any, **changed: Any) -> int:
        named = self._named(sent, self.challenge)
        named.update(changed)
        return webauthn.asserted(
            self.kept, sent["client"], sent["data"], sent["signature"], **named
        )

    def test_the_key_that_was_registered_signs_in(self) -> None:
        expect(self._asserted(self.phone.get(self.challenge))).to_equal(1)

    def test_so_does_one_of_each_kind(self) -> None:
        for kind in ("eddsa", "rs256"):
            with self.subTest(kind):
                self.phone = Authenticator(kind)
                first = webauthn.new_challenge()
                self.kept = webauthn.registered(
                    **self._named(self.phone.create(first), first, registering=True)
                )
                expect(self._asserted(self.phone.get(self.challenge))).to_equal(1)

    def test_another_key_does_not(self) -> None:
        other = Authenticator()
        _refused(self, "wrong_signature", self._asserted, other.get(self.challenge))

    def test_what_was_signed_cannot_be_changed(self) -> None:
        sent = self.phone.get(self.challenge)
        for name, changed in (
            ("the data", {**sent, "data": sent["data"][:-1] + b"\x09"}),
            ("the signature", {**sent, "signature": sent["signature"][:-1] + b"\x00"}),
            ("no signature", {**sent, "signature": b""}),
            ("what the page said", {**sent, "client": sent["client"] + b" "}),
        ):
            with self.subTest(name):
                _refused(self, "wrong_signature", self._asserted, changed)

    def test_an_answer_to_another_challenge_is_refused(self) -> None:
        sent = self.phone.get(webauthn.new_challenge())
        _refused(self, "wrong_challenge", self._asserted, sent)

    def test_an_answer_given_to_another_site_is_refused(self) -> None:
        sent = self.phone.get(self.challenge, origin="https://evil.example.org")
        _refused(self, "wrong_origin", self._asserted, sent)

    def test_what_was_made_to_register_does_not_sign_in(self) -> None:
        sent = self.phone.get(self.challenge, kind="webauthn.create")
        _refused(self, "wrong_type", self._asserted, sent)

    def test_nobody_checked_is_refused(self) -> None:
        sent = self.phone.get(self.challenge, flags=PRESENT)
        _refused(self, "user_not_verified", self._asserted, sent)

    def test_a_name_that_is_not_this_one_is_refused(self) -> None:
        sent = self.phone.get(self.challenge)
        _refused(self, "wrong_site", self._asserted, sent, rp_id="other.example.org")

    def test_a_count_that_goes_back_tells_of_a_copy(self) -> None:
        self.kept["count"] = 7
        self.phone.count = 3
        _refused(self, "key_copied", self._asserted, self.phone.get(self.challenge))

    def test_keys_that_do_not_count_are_taken(self) -> None:
        # Those kept in step between the devices of one account stay at 0.
        self.phone.count = -1
        expect(self._asserted(self.phone.get(self.challenge))).to_equal(0)

    def test_a_record_that_was_damaged_signs_nobody_in(self) -> None:
        sent = self.phone.get(self.challenge)
        for name, kept in (
            ("no key", {**self.kept, "key": ""}),
            ("a key that is not one", {**self.kept, "key": "AAAA"}),
            ("a key that is a number", {**self.kept, "key": 5}),
        ):
            with self.subTest(name):
                self.kept = kept
                _refused(self, "key_not_supported", self._asserted, sent)

    def test_what_is_not_what_a_browser_sends_is_refused(self) -> None:
        sent = self.phone.get(self.challenge)
        for name, changed in (
            ("data cut short", {**sent, "data": sent["data"][:36]}),
            ("data that goes on", {**sent, "data": sent["data"] + b"\x00"}),
            ("no JSON", {**sent, "client": b"{"}),
        ):
            with self.subTest(name):
                _refused(self, "malformed", self._asserted, changed)
