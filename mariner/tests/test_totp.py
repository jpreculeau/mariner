"""One-time codes, as the applications of a phone give them (RFC 6238)."""

import base64
from unittest import TestCase

from pyexpect import expect

from mariner import totp

# The secret of the standard's own examples.
SECRET = base64.b32encode(b"12345678901234567890").decode("ascii")


class CodeTest(TestCase):
    def test_the_codes_are_those_of_the_standard(self) -> None:
        for moment, code in (
            (59, "287082"),
            (1111111109, "081804"),
            (1234567890, "005924"),
            (20000000000, "353130"),
        ):
            expect(totp.code_at(SECRET, moment)).to_equal(code)

    def test_a_new_secret_is_one_an_application_takes(self) -> None:
        secret = totp.new_secret()
        expect(len(base64.b32decode(secret))).to_equal(20)
        expect(secret == totp.new_secret()).to_equal(False)

    def test_the_address_given_to_an_application_names_mariner(self) -> None:
        expect(totp.uri(SECRET, "Saturn Plus")).to_equal(
            "otpauth://totp/Mariner:Saturn%20Plus?secret="
            + SECRET
            + "&issuer=Mariner&algorithm=SHA1&digits=6&period=30"
        )

    def test_the_secret_is_shown_in_groups_to_be_typed(self) -> None:
        expect(totp.grouped("ABCDEFGHIJ")).to_equal("ABCD EFGH IJ")


class MatchingTest(TestCase):
    def test_the_code_of_the_moment_is_taken(self) -> None:
        expect(totp.step_of(SECRET, "287082", 59)).to_equal(1)

    def test_as_it_is_typed(self) -> None:
        expect(totp.step_of(SECRET, " 287 082 ", 59)).to_equal(1)

    def test_the_one_before_and_the_one_after_are_too(self) -> None:
        # A phone's clock is a little off, and typing takes a moment.
        expect(totp.step_of(SECRET, "287082", 59 + 30)).to_equal(1)
        expect(totp.step_of(SECRET, "287082", 59 - 30)).to_equal(1)

    def test_an_older_one_is_not(self) -> None:
        expect(totp.step_of(SECRET, "287082", 59 + 60)).to_equal(None)

    def test_one_that_already_served_is_not_taken_again(self) -> None:
        # Read over a shoulder, or on the way: it opens nothing twice.
        expect(totp.step_of(SECRET, "287082", 59, after=1)).to_equal(None)
        expect(totp.step_of(SECRET, "287082", 59, after=0)).to_equal(1)

    def test_what_is_no_code_is_not_taken(self) -> None:
        for given in ("", "28708", "2870820", "abcdef", "２８７０８２", "287082\n1"):
            expect(totp.step_of(SECRET, given, 59)).to_equal(None)

    def test_a_secret_that_is_not_one_matches_nothing(self) -> None:
        expect(totp.step_of("not base32!", "287082", 59)).to_equal(None)
        expect(totp.step_of("", "287082", 59)).to_equal(None)
