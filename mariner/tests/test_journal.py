"""What Mariner remembers of who signed in, and who tried."""

import time
from typing import Any, List

from pyexpect import expect

from mariner import totp
from mariner.server import auth, journal, state
from mariner.tests.test_auth import PASSWORD, _WithClient, _WithState

INTERNET = "203.0.113.5"
LOCAL = "192.168.1.20"


class JournalTest(_WithState):
    def test_it_is_empty_at_first(self) -> None:
        expect(journal.entries()).to_equal([])

    def test_what_happens_is_kept_the_latest_first(self) -> None:
        journal.note("wrong_password", INTERNET, now=100.0)
        journal.note("signed_in", LOCAL, now=200.0)
        expect(journal.entries()).to_equal(
            [
                {"at": 200, "what": "signed_in", "from": LOCAL, "internet": False},
                {
                    "at": 100,
                    "what": "wrong_password",
                    "from": INTERNET,
                    "internet": True,
                },
            ]
        )

    def test_it_outlasts_a_restart(self) -> None:
        journal.note("signed_in", LOCAL, now=200.0)
        state.forget()
        journal.forget()
        expect(len(journal.entries())).to_equal(1)

    def test_only_the_latest_are_kept(self) -> None:
        for sent in range(journal.KEPT + 30):
            journal.note("signed_in", LOCAL, now=float(sent))
        kept = journal.entries()
        expect(len(kept)).to_equal(journal.KEPT)
        expect(kept[0]["at"]).to_equal(journal.KEPT + 29)

    def test_wrong_ones_in_a_row_from_one_place_are_one_line(self) -> None:
        for sent in range(5):
            journal.note("wrong_password", INTERNET, now=10.0 + sent)
        kept = journal.entries()
        expect(len(kept)).to_equal(1)
        expect(kept[0]["count"]).to_equal(5)
        # When the last of them came.
        expect(kept[0]["at"]).to_equal(14)

    def test_wrong_ones_do_not_push_out_what_matters(self) -> None:
        # Sent by the hundred from as many addresses, they would leave no
        # trace of the sign-in an owner looks for.
        journal.note("signed_in", LOCAL, now=1.0)
        journal.note("code_removed", LOCAL, now=2.0)
        for sent in range(journal.KEPT * 3):
            journal.note(
                "wrong_password",
                f"203.0.{sent % 250}.{sent // 250 + 1}",
                now=10.0 + sent,
            )
        whats = [entry["what"] for entry in journal.entries()]
        expect("signed_in" in whats).to_equal(True)
        expect("code_removed" in whats).to_equal(True)
        expect(whats.count("wrong_password")).to_equal(journal.KEPT)
        # And the count above the list still says that somebody tried.
        journal.note("signed_in", LOCAL, now=5000.0)
        expect(journal.since_the_visit_before()["wrong_passwords"]).to_equal(
            journal.KEPT
        )

    def test_sign_in_being_closed_again_and_again_pushes_nothing_out(self) -> None:
        # A bot that keeps it closed for days: a line every ten minutes.
        journal.note("signed_in", LOCAL, now=1.0)
        journal.note("password_changed", LOCAL, now=2.0)
        for sent in range(journal.KEPT * 3):
            journal.note(
                "sign_in_closed", f"203.0.113.{sent % 200 + 1}", now=10.0 + sent
            )
        whats = [entry["what"] for entry in journal.entries()]
        expect("signed_in" in whats).to_equal(True)
        expect("password_changed" in whats).to_equal(True)

    def test_the_owner_s_own_slip_before_signing_in_is_not_somebody_trying(
        self,
    ) -> None:
        journal.note("signed_in", LOCAL, now=1.0)
        journal.note("wrong_password", INTERNET, now=2.0)
        journal.note("wrong_password", LOCAL, now=3.0)
        journal.note("wrong_password", LOCAL, now=4.0)
        journal.note("signed_in", LOCAL, now=5.0)
        expect(journal.since_the_visit_before()).to_equal(
            {"wrong_passwords": 1, "wrong_codes": 0, "or_more": False}
        )

    def test_a_slip_is_a_few_wrong_ones_just_before_and_never_a_wrong_code(
        self,
    ) -> None:
        # Behind a router that shows one address for everybody, or a
        # tunnel, strangers and the owner come from the same place: what
        # was tried for hours is not the owner's slip of the finger.
        router = "192.168.1.1"
        journal.note("signed_in", LOCAL, now=1.0)
        for sent in range(15):
            journal.note("wrong_password", router, now=100.0 + sent * 600)
        for sent in range(9):
            journal.note("wrong_code", router, now=10000.0 + sent * 60)
        journal.note("wrong_password", router, now=20000.0)
        journal.note("signed_in", router, now=20010.0)
        told = journal.since_the_visit_before()
        # The one just before signing in, and no other.
        expect(told["wrong_passwords"]).to_equal(15)
        expect(told["wrong_codes"]).to_equal(9)

    def test_a_wrong_one_minutes_before_is_no_slip(self) -> None:
        journal.note("signed_in", LOCAL, now=1.0)
        journal.note("wrong_password", LOCAL, now=1000.0)
        journal.note("signed_in", LOCAL, now=1301.0)
        expect(journal.since_the_visit_before()["wrong_passwords"]).to_equal(1)

    def test_a_wrong_one_within_the_minutes_before_is_a_slip(self) -> None:
        journal.note("signed_in", LOCAL, now=1.0)
        journal.note("wrong_password", LOCAL, now=1000.0)
        journal.note("signed_in", LOCAL, now=1300.0)
        expect(journal.since_the_visit_before()["wrong_passwords"]).to_equal(0)

    def test_slips_end_where_somebody_else_comes_between(self) -> None:
        journal.note("signed_in", LOCAL, now=1.0)
        journal.note("wrong_password", LOCAL, now=100.0)
        journal.note("wrong_password", "203.0.113.9", now=101.0)
        journal.note("wrong_password", LOCAL, now=102.0)
        journal.note("signed_in", LOCAL, now=103.0)
        # The last is the owner's; the stranger's, and what came before it.
        expect(journal.since_the_visit_before()["wrong_passwords"]).to_equal(2)

    def test_slips_end_where_a_wrong_code_comes_between(self) -> None:
        journal.note("signed_in", LOCAL, now=1.0)
        journal.note("wrong_password", LOCAL, now=100.0)
        journal.note("wrong_code", LOCAL, now=101.0)
        journal.note("wrong_password", LOCAL, now=102.0)
        journal.note("signed_in", LOCAL, now=103.0)
        expect(journal.since_the_visit_before()).to_equal(
            {"wrong_passwords": 1, "wrong_codes": 1, "or_more": False}
        )

    def test_more_than_a_few_just_before_are_not_all_slips(self) -> None:
        journal.note("signed_in", LOCAL, now=1.0)
        for sent in range(8):
            journal.note("wrong_password", LOCAL, now=100.0 + sent)
        journal.note("signed_in", LOCAL, now=110.0)
        expect(journal.since_the_visit_before()["wrong_passwords"]).to_equal(
            8 - journal.OWN_SLIPS
        )

    def test_more_is_said_when_the_oldest_line_kept_is_a_closing(self) -> None:
        journal.note("signed_in", LOCAL, now=1.0)
        for sent in range(journal.KEPT + 30):
            what = "sign_in_closed" if sent % 2 == 0 else "wrong_password"
            journal.note(what, f"203.0.{sent % 250}.{sent // 250 + 1}", now=10.0 + sent)
        journal.note("signed_in", LOCAL, now=5000.0)
        expect(journal.since_the_visit_before()["or_more"]).to_equal(True)

    def test_more_than_is_remembered_is_said_to_be_more(self) -> None:
        # From as many addresses: only the latest are kept, and the count
        # made of them is short of what was sent.
        journal.note("signed_in", LOCAL, now=1.0)
        for sent in range(journal.KEPT + 20):
            journal.note(
                "wrong_password",
                f"203.0.{sent % 250}.{sent // 250 + 1}",
                now=10.0 + sent,
            )
        journal.note("signed_in", LOCAL, now=5000.0)
        expect(journal.since_the_visit_before()).to_equal(
            {"wrong_passwords": journal.KEPT, "wrong_codes": 0, "or_more": True}
        )

    def test_wrong_codes_are_counted_for_what_they_are(self) -> None:
        journal.note("signed_in", LOCAL, now=1.0)
        for sent in range(3):
            journal.note("wrong_code", INTERNET, now=2.0 + sent)
        journal.note("wrong_password", INTERNET, now=8.0)
        journal.note("signed_in", LOCAL, now=9.0)
        expect(journal.since_the_visit_before()).to_equal(
            {"wrong_passwords": 1, "wrong_codes": 3, "or_more": False}
        )

    def test_the_count_adds_up_those_folded_into_one_line(self) -> None:
        journal.note("signed_in", LOCAL, now=1.0)
        for sent in range(7):
            journal.note("wrong_password", INTERNET, now=10.0 + sent)
        journal.note("signed_in", LOCAL, now=50.0)
        expect(journal.since_the_visit_before()["wrong_passwords"]).to_equal(7)

    def test_an_address_that_is_none_is_kept_as_it_is_read(self) -> None:
        # Whatever a header or a peer gives, nothing is kept that could
        # be mistaken for something else when shown.
        journal.note("wrong_password", "203.0.113.5\n<b>x</b>" + "9" * 200, now=1.0)
        shown = journal.entries()[0]["from"]
        expect(len(shown) <= 45).to_equal(True)
        expect("\n" in shown or "<" in shown).to_equal(False)

    def test_it_counts_the_wrong_ones_since_the_sign_in_before_this_one(
        self,
    ) -> None:
        journal.note("wrong_password", INTERNET, now=1.0)
        journal.note("signed_in", LOCAL, now=2.0)
        journal.note("wrong_password", INTERNET, now=3.0)
        journal.note("wrong_password", INTERNET, now=4.0)
        journal.note("sign_in_closed", INTERNET, now=5.0)
        journal.note("signed_in", LOCAL, now=6.0)
        # What happened while the owner was away.
        expect(journal.since_the_visit_before()["wrong_passwords"]).to_equal(2)
        journal.note("signed_in", LOCAL, now=7.0)
        expect(journal.since_the_visit_before()["wrong_passwords"]).to_equal(0)

    def test_a_file_that_cannot_be_read_is_an_empty_journal(self) -> None:
        state.write(journal.KEPT_AS, b"not json at all")
        journal.forget()
        expect(journal.entries()).to_equal([])
        journal.note("signed_in", LOCAL, now=2.0)
        expect(len(journal.entries())).to_equal(1)

    def test_what_cannot_be_kept_is_remembered_until_the_next_start(self) -> None:
        from unittest.mock import patch

        with patch.object(state, "write", side_effect=OSError("read-only")):
            journal.note("signed_in", LOCAL, now=2.0)
        expect(len(journal.entries())).to_equal(1)


class WhatIsNotedTest(_WithClient):
    def _from(self, address: str) -> Any:
        client = self.application.test_client()
        client.environ_base["REMOTE_ADDR"] = address
        return client

    def _whats(self) -> List[str]:
        return [entry["what"] for entry in journal.entries()]

    def test_choosing_signing_in_and_wrong_ones_are_noted(self) -> None:
        home = self._from(LOCAL)
        home.post("/api/auth/setup", json={"password": PASSWORD})
        self._from("192.168.1.99").post(
            "/api/auth/login", json={"password": "not the one at all"}
        )
        self._from(LOCAL).post("/api/auth/login", json={"password": PASSWORD})
        expect(self._whats()).to_equal(
            ["signed_in", "wrong_password", "password_chosen"]
        )
        expect(journal.entries()[1]["from"]).to_equal("192.168.1.99")

    def test_the_password_is_never_in_it(self) -> None:
        self._from(LOCAL).post("/api/auth/setup", json={"password": PASSWORD})
        self._from(LOCAL).post("/api/auth/login", json={"password": "a wrong secret!"})
        kept = state.read(journal.KEPT_AS) or b""
        expect(PASSWORD.encode() in kept).to_equal(False)
        expect(b"a wrong secret!" in kept).to_equal(False)

    def test_the_code_and_the_closing_are_noted(self) -> None:
        auth.set_password(PASSWORD)
        secret = auth.start_code()
        home = self._from(LOCAL)
        home.post("/api/auth/login", json={"password": PASSWORD})
        home.post(
            "/api/auth/code/confirm",
            json={"code": totp.code_at(secret, time.time())},
        )
        for sent in range(auth.INTERNET_FAILURES_AN_HOUR + 3):
            self._from(f"203.0.{sent}.5").post(
                "/api/auth/login", json={"password": "not the one at all"}
            )
            with auth._attempts_lock:
                auth._attempts.clear()
        whats = self._whats()
        expect(whats.count("code_set")).to_equal(1)
        expect(whats.count("wrong_password")).to_equal(auth.INTERNET_FAILURES_AN_HOUR)
        # Said once, not for each one turned away.
        expect(whats.count("sign_in_closed")).to_equal(1)

    def test_who_is_signed_in_reads_it(self) -> None:
        home = self._from(LOCAL)
        home.post("/api/auth/setup", json={"password": PASSWORD})
        answer = home.get("/api/auth/journal")
        expect(answer.status_code).to_equal(200)
        told = answer.get_json()
        expect(told["entries"][0]["what"]).to_equal("password_chosen")
        expect(told["wrong_since_last_visit"]).to_equal(0)

    def test_nobody_else_does(self) -> None:
        auth.set_password(PASSWORD)
        journal.note("signed_in", LOCAL, now=2.0)
        answer = self._from(LOCAL).get("/api/auth/journal")
        expect(answer.status_code).to_equal(401)
        expect("entries" in (answer.get_json() or {})).to_equal(False)

    def test_signing_in_says_how_many_tried_meanwhile(self) -> None:
        home = self._from(LOCAL)
        home.post("/api/auth/setup", json={"password": PASSWORD})
        for _ in range(2):
            self._from("192.168.1.99").post(
                "/api/auth/login", json={"password": "not the one at all"}
            )
        answer = self._from(LOCAL).post("/api/auth/login", json={"password": PASSWORD})
        told = answer.get_json()
        expect(told["wrong_since_last_visit"]).to_equal(2)
        expect(told["wrong_codes_since_last_visit"]).to_equal(0)
        expect(told["wrong_since_last_visit_or_more"]).to_equal(False)
