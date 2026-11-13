"""The one-time code asked of who signs in from the Internet."""

import time
from typing import Any
from unittest.mock import patch

from pyexpect import expect

from mariner import totp
from mariner.server import auth, journal, state
from mariner.tests.test_auth import PASSWORD, _WithClient, _WithState

INTERNET = "203.0.113.5"
LOCAL = "192.168.1.20"


def _code(secret: str, later: int = 0) -> str:
    return totp.code_at(secret, time.time() + later) or ""


def _set_up() -> str:
    secret = auth.start_code()
    expect(auth.confirm_code(_code(secret))).to_equal(True)
    return secret


class CodeKeptTest(_WithState):
    def test_there_is_none_at_first(self) -> None:
        expect(auth.code_is_set()).to_equal(False)
        expect(auth.check_code("123456")).to_equal(False)

    def test_one_is_in_force_once_a_code_of_it_was_given(self) -> None:
        # Else a phone that never took the secret in would lock its owner
        # out of the Internet.
        secret = auth.start_code()
        expect(auth.code_is_set()).to_equal(False)
        expect(auth.confirm_code("000000")).to_equal(False)
        expect(auth.code_is_set()).to_equal(False)
        expect(auth.confirm_code(_code(secret))).to_equal(True)
        expect(auth.code_is_set()).to_equal(True)

    def test_it_is_kept_where_only_mariner_reads(self) -> None:
        _set_up()
        kept = self.root / "s" / totp.KEPT_AS
        expect(kept.stat().st_mode & 0o077).to_equal(0)

    def test_a_code_is_taken_once(self) -> None:
        secret = _set_up()
        # The one that confirmed it has served.
        expect(auth.check_code(_code(secret))).to_equal(False)
        after = _code(secret, 30)
        expect(auth.check_code(after)).to_equal(True)
        expect(auth.check_code(after)).to_equal(False)

    def test_which_holds_through_a_restart(self) -> None:
        secret = _set_up()
        after = _code(secret, 30)
        expect(auth.check_code(after)).to_equal(True)
        state.forget()
        auth.forget_code_seen()
        expect(auth.code_is_set()).to_equal(True)
        expect(auth.check_code(after)).to_equal(False)

    def test_another_takes_its_place_only_once_confirmed(self) -> None:
        old = _set_up()
        new = auth.start_code()
        expect(auth.code_step(_code(old, 30)) is None).to_equal(False)
        expect(auth.confirm_code(_code(new))).to_equal(True)
        expect(auth.check_code(_code(old, 30))).to_equal(False)
        expect(auth.check_code(_code(new, 30))).to_equal(True)

    def test_it_can_be_done_away_with(self) -> None:
        _set_up()
        auth.remove_code()
        expect(auth.code_is_set()).to_equal(False)


class _FromPlaces(_WithClient):
    def setUp(self) -> None:
        super().setUp()
        auth.set_password(PASSWORD)

    def _from(self, address: str) -> Any:
        client = self.application.test_client()
        client.environ_base["REMOTE_ADDR"] = address
        return client

    def _sign_in(self, client: Any, **more: Any) -> Any:
        return client.post("/api/auth/login", json={"password": PASSWORD, **more})


class SignInFromTheInternetTest(_FromPlaces):
    def test_without_a_code_set_up_nobody_signs_in_from_there(self) -> None:
        response = self._sign_in(self._from(INTERNET))
        expect(response.status_code).to_equal(403)
        expect(response.get_json()["code"]).to_equal("code_not_set")

    def test_which_tells_nothing_of_the_password(self) -> None:
        wrong = self._from(INTERNET).post(
            "/api/auth/login", json={"password": "not the one at all"}
        )
        expect(wrong.status_code).to_equal(403)
        expect(wrong.get_json()["code"]).to_equal("code_not_set")

    def test_the_password_and_the_code_sign_in(self) -> None:
        secret = _set_up()
        client = self._from(INTERNET)
        response = self._sign_in(client, code=_code(secret, 30))
        expect(response.status_code).to_equal(200)
        expect(self.state_of(client)["signed_in"]).to_equal(True)

    def test_the_password_alone_does_not(self) -> None:
        _set_up()
        response = self._sign_in(self._from(INTERNET))
        expect(response.status_code).to_equal(401)
        expect(response.get_json()["code"]).to_equal("wrong_password")

    def test_nor_with_a_wrong_code_and_it_is_said_the_same(self) -> None:
        secret = _set_up()
        wrong_code = self._sign_in(self._from(INTERNET), code="000000")
        wrong_password = self._from("198.51.100.9").post(
            "/api/auth/login",
            json={"password": "not the one at all", "code": _code(secret, 30)},
        )
        expect(wrong_code.status_code).to_equal(401)
        # Which of the two was wrong is not told.
        expect(wrong_code.get_json()).to_equal(wrong_password.get_json())

    def test_a_code_sent_with_a_wrong_password_still_serves(self) -> None:
        # The owner's slip of the finger does not cost half a minute.
        secret = _set_up()
        code = _code(secret, 30)
        client = self._from(INTERNET)
        client.post(
            "/api/auth/login", json={"password": "not the one at all", "code": code}
        )
        expect(self._sign_in(client, code=code).status_code).to_equal(200)

    def test_a_code_signs_in_once(self) -> None:
        secret = _set_up()
        code = _code(secret, 30)
        expect(self._sign_in(self._from(INTERNET), code=code).status_code).to_equal(200)
        again = self._sign_in(self._from("198.51.100.9"), code=code)
        expect(again.status_code).to_equal(401)

    def test_on_the_local_network_the_password_is_enough(self) -> None:
        _set_up()
        expect(self._sign_in(self._from(LOCAL)).status_code).to_equal(200)


class SessionsAndPlacesTest(_FromPlaces):
    def test_one_signed_in_at_home_is_not_signed_in_from_the_internet(self) -> None:
        # A phone that leaves the house, or a cookie that was copied.
        _set_up()
        client = self._from(LOCAL)
        self._sign_in(client)
        expect(self.state_of(client)["signed_in"]).to_equal(True)
        client.environ_base["REMOTE_ADDR"] = INTERNET
        expect(self.state_of(client)["signed_in"]).to_equal(False)
        response = client.get("/api/settings")
        expect(response.status_code).to_equal(401)
        expect(response.get_json()["code"]).to_equal("login_required")
        # And is again, back home.
        client.environ_base["REMOTE_ADDR"] = LOCAL
        expect(self.state_of(client)["signed_in"]).to_equal(True)

    def test_one_signed_in_with_the_code_is_signed_in_everywhere(self) -> None:
        secret = _set_up()
        client = self._from(INTERNET)
        self._sign_in(client, code=_code(secret, 30))
        expect(client.get("/api/settings").status_code).to_equal(200)
        client.environ_base["REMOTE_ADDR"] = LOCAL
        expect(client.get("/api/settings").status_code).to_equal(200)

    def test_doing_away_with_the_code_ends_what_it_opened_from_outside(self) -> None:
        # Nobody signs in from the Internet without one: nobody stays
        # signed in from there either.
        secret = _set_up()
        client = self._from(INTERNET)
        self._sign_in(client, code=_code(secret, 30))
        auth.remove_code()
        expect(self.state_of(client)["signed_in"]).to_equal(False)
        expect(client.get("/api/settings").status_code).to_equal(401)
        # At home it holds.
        client.environ_base["REMOTE_ADDR"] = LOCAL
        expect(client.get("/api/settings").status_code).to_equal(200)

    def test_a_new_code_does_not_bring_back_what_the_old_one_opened(self) -> None:
        # A phone that was lost: its browser holds a session. The code is
        # done away with and set up on the new phone.
        secret = _set_up()
        lost = self._from(INTERNET)
        self._sign_in(lost, code=_code(secret, 30))
        auth.remove_code()
        _set_up()
        expect(self.state_of(lost)["signed_in"]).to_equal(False)
        expect(lost.get("/api/settings").status_code).to_equal(401)

    def test_nor_does_replacing_the_phone(self) -> None:
        secret = _set_up()
        old = self._from(INTERNET)
        self._sign_in(old, code=_code(secret, 30))
        _set_up()
        expect(old.get("/api/settings").status_code).to_equal(401)

    def test_changing_the_password_from_outside_leaves_one_signed_in(self) -> None:
        secret = _set_up()
        client = self._from(INTERNET)
        self._sign_in(client, code=_code(secret, 30))
        changed = client.post(
            "/api/auth/password",
            json={"current": PASSWORD, "new": "another one, longer!"},
        )
        expect(changed.status_code).to_equal(200)
        client.environ_base["HTTP_X_MARINER_KEY"] = changed.get_json()["page_key"]
        expect(self.state_of(client)["signed_in"]).to_equal(True)
        expect(client.get("/api/settings").status_code).to_equal(200)

    def test_changing_it_at_home_does_not_make_a_session_for_outside(self) -> None:
        _set_up()
        client = self._from(LOCAL)
        self._sign_in(client)
        changed = client.post(
            "/api/auth/password",
            json={"current": PASSWORD, "new": "another one, longer!"},
        )
        client.environ_base["HTTP_X_MARINER_KEY"] = changed.get_json()["page_key"]
        client.environ_base["REMOTE_ADDR"] = INTERNET
        expect(self.state_of(client)["signed_in"]).to_equal(False)

    def test_the_page_is_told_where_it_is_seen_from(self) -> None:
        expect(self.state_of(self._from(LOCAL))).to_equal(
            {
                "password_set": True,
                "signed_in": False,
                "from_internet": False,
                "code_set": False,
                "host_commands": True,
            }
        )
        _set_up()
        told = self.state_of(self._from(INTERNET))
        expect(told["from_internet"]).to_equal(True)
        expect(told["code_set"]).to_equal(True)
        # For the page not to offer what would be refused.
        expect(told["host_commands"]).to_equal(False)
        with patch("mariner.config.get_host_commands_from_internet", return_value=True):
            expect(self.state_of(self._from(INTERNET))["host_commands"]).to_equal(True)

    def test_a_body_is_not_taken_in_from_a_session_without_the_code(self) -> None:
        # What the web server asks before storing a file.
        _set_up()
        client = self._from(LOCAL)
        self._sign_in(client)
        with client.session_transaction() as held:
            session = dict(held)
        key = client.environ_base["HTTP_X_MARINER_KEY"]
        expect(auth.refusal("/api/upload_file", session, key, "POST", LOCAL)).to_equal(
            None
        )
        refused = auth.refusal("/api/upload_file", session, key, "POST", INTERNET)
        assert refused is not None
        expect(refused["code"]).to_equal("login_required")


class SettingItUpTest(_FromPlaces):
    def setUp(self) -> None:
        super().setUp()
        self.client = self._from(LOCAL)
        self._sign_in(self.client)

    def test_it_is_set_up_by_who_is_signed_in(self) -> None:
        stranger = self._from(LOCAL)
        expect(stranger.post("/api/auth/code/start").status_code).to_equal(401)
        expect(auth.code_is_set()).to_equal(False)

    def test_and_from_the_local_network_alone(self) -> None:
        secret = _set_up()
        outside = self._from(INTERNET)
        self._sign_in(outside, code=_code(secret, 30))
        for path in ("/api/auth/code/start", "/api/auth/code/remove"):
            response = outside.post(path, json={"current": PASSWORD})
            expect(response.status_code).to_equal(403)
            expect(response.get_json()["code"]).to_equal("local_network_only")
        expect(auth.code_is_set()).to_equal(True)

    def test_starting_gives_what_the_phone_takes_in(self) -> None:
        with_name = self.client.post("/api/auth/code/start").get_json()
        expect(len(with_name["secret"])).to_equal(32)
        expect(with_name["uri"].startswith("otpauth://totp/Mariner:")).to_equal(True)
        expect(with_name["secret"] in with_name["uri"]).to_equal(True)
        expect(auth.code_is_set()).to_equal(False)

    def test_a_right_code_puts_it_in_force(self) -> None:
        secret = self.client.post("/api/auth/code/start").get_json()["secret"]
        wrong = self.client.post("/api/auth/code/confirm", json={"code": "000000"})
        expect(wrong.status_code).to_equal(400)
        expect(wrong.get_json()["code"]).to_equal("wrong_code")
        right = self.client.post("/api/auth/code/confirm", json={"code": _code(secret)})
        expect(right.status_code).to_equal(200)
        expect(self.state_of()["code_set"]).to_equal(True)

    def test_putting_another_in_its_place_asks_for_the_password(self) -> None:
        # A page left open at home is not enough to move the code to
        # another phone.
        _set_up()
        without = self.client.post("/api/auth/code/start")
        expect(without.status_code).to_equal(400)
        wrong = self.client.post("/api/auth/code/start", json={"current": "not it"})
        expect(wrong.status_code).to_equal(401)
        expect(wrong.get_json()["code"]).to_equal("wrong_password")
        right = self.client.post("/api/auth/code/start", json={"current": PASSWORD})
        expect(right.status_code).to_equal(200)
        expect(len(right.get_json()["secret"])).to_equal(32)

    def test_doing_away_with_it_asks_for_the_password(self) -> None:
        _set_up()
        wrong = self.client.post("/api/auth/code/remove", json={"current": "not it"})
        expect(wrong.status_code).to_equal(401)
        expect(auth.code_is_set()).to_equal(True)
        right = self.client.post("/api/auth/code/remove", json={"current": PASSWORD})
        expect(right.status_code).to_equal(200)
        expect(auth.code_is_set()).to_equal(False)


class PasswordKnownTest(_FromPlaces):
    """Whoever has the password and not the phone is left to guess the
    code: one chance in some hundred thousand at each try."""

    def _guess(self, address: str = INTERNET) -> Any:
        with auth._attempts_lock:
            # As if time had passed: only what follows is looked at here.
            auth._attempts.clear()
            auth._internet_attempts.clear()
        return self._sign_in(self._from(address), code="000000")

    def test_wrong_codes_with_the_right_password_are_noted_as_such(self) -> None:
        # For the owner to learn that the password is known.
        _set_up()
        answer = self._guess()
        # The stranger is told what a wrong password is told.
        expect(answer.get_json()["code"]).to_equal("wrong_password")
        expect(journal.entries()[0]["what"]).to_equal("wrong_code")
        self._from(INTERNET).post(
            "/api/auth/login", json={"password": "not the one at all", "code": "000000"}
        )
        expect(journal.entries()[0]["what"]).to_equal("wrong_password")

    def test_after_some_of_them_the_internet_is_closed_until_home_signs_in(
        self,
    ) -> None:
        secret = _set_up()
        for _ in range(auth.WRONG_CODES_BEFORE_CLOSING):
            expect(self._guess().status_code).to_equal(401)
        # Even with the right code: the guessing could go on for months.
        with auth._attempts_lock:
            auth._attempts.clear()
            auth._internet_attempts.clear()
        closed = self._sign_in(self._from("198.51.100.9"), code=_code(secret, 30))
        expect(closed.status_code).to_equal(403)
        expect(closed.get_json()["code"]).to_equal("code_locked")
        expect(
            "code_locked" in [entry["what"] for entry in journal.entries()]
        ).to_equal(True)
        # Home is as it was, and opens the Internet again.
        expect(self._sign_in(self._from(LOCAL)).status_code).to_equal(200)
        opened = self._sign_in(self._from("198.51.100.9"), code=_code(secret, 30))
        expect(opened.status_code).to_equal(200)

    def test_which_a_restart_does_not_undo(self) -> None:
        _set_up()
        for _ in range(auth.WRONG_CODES_BEFORE_CLOSING):
            self._guess()
        state.forget()
        auth.forget_attempts()
        expect(self._guess().get_json()["code"]).to_equal("code_locked")

    def test_the_owner_s_own_slips_are_forgotten_at_the_next_sign_in(self) -> None:
        secret = _set_up()
        for _ in range(auth.WRONG_CODES_BEFORE_CLOSING - 1):
            self._guess()
        with auth._attempts_lock:
            auth._attempts.clear()
            auth._internet_attempts.clear()
        expect(
            self._sign_in(self._from(INTERNET), code=_code(secret, 30)).status_code
        ).to_equal(200)
        for _ in range(auth.WRONG_CODES_BEFORE_CLOSING - 1):
            expect(self._guess().status_code).to_equal(401)

    def test_they_are_counted_even_where_nothing_can_be_kept(self) -> None:
        # A card gone read-only: the page stays open, and so must this.
        _set_up()
        real = state.write

        def not_the_code(name: str, content: bytes) -> None:
            if name == totp.KEPT_AS:
                raise OSError(30, "Read-only file system")
            real(name, content)

        with patch.object(state, "write", side_effect=not_the_code):
            for _ in range(auth.WRONG_CODES_BEFORE_CLOSING):
                self._guess()
            expect(self._guess().get_json()["code"]).to_equal("code_locked")

    def test_a_new_code_starts_from_nothing(self) -> None:
        _set_up()
        for _ in range(auth.WRONG_CODES_BEFORE_CLOSING):
            self._guess()
        _set_up()
        expect(self._guess().get_json()["code"]).to_equal("wrong_password")


class ClockTest(_WithState):
    def test_a_code_that_served_while_the_clock_was_ahead_does_not_shut_it(
        self,
    ) -> None:
        secret = auth.start_code()
        now = 1_800_000_000.0
        expect(auth.confirm_code(totp.code_at(secret, now) or "", now=now)).to_equal(
            True
        )
        ahead = now + 86400
        expect(auth.check_code(totp.code_at(secret, ahead) or "", now=ahead)).to_equal(
            True
        )
        # Put right, the clock is a day behind the last code that served.
        later = now + 120
        expect(auth.check_code(totp.code_at(secret, later) or "", now=later)).to_equal(
            True
        )
        # And still none serves twice.
        expect(auth.check_code(totp.code_at(secret, later) or "", now=later)).to_equal(
            False
        )


class OddBodiesTest(_FromPlaces):
    def test_a_password_that_is_no_text_is_a_wrong_one(self) -> None:
        # Half of a pair of characters, which cannot be written down.
        answer = self._from(LOCAL).post(
            "/api/auth/login",
            data='{"password": "\\ud800 not the one at all"}',
            content_type="application/json",
        )
        expect(answer.status_code).to_equal(401)
        expect(journal.entries()[0]["what"]).to_equal("wrong_password")

    def test_a_new_password_that_is_no_text_is_not_taken(self) -> None:
        answer = self._from(LOCAL).post("/api/auth/login", json={"password": PASSWORD})
        client = self._from(LOCAL)
        client.post("/api/auth/login", json={"password": PASSWORD})
        answer = client.post(
            "/api/auth/password",
            data='{"current": "%s", "new": "\\ud800 correct horse battery"}' % PASSWORD,
            content_type="application/json",
        )
        expect(answer.status_code).to_equal(400)
        expect(answer.get_json()["code"]).to_equal("password_not_text")
        expect(auth.check_password(PASSWORD)).to_equal(True)

    def test_a_body_nested_beyond_reason_is_no_password(self) -> None:
        deep = "[" * 100000 + "]" * 100000
        answer = self._from(LOCAL).post(
            "/api/auth/login", data=deep, content_type="application/json"
        )
        expect(answer.status_code).to_equal(400)


class CountsApartTest(_FromPlaces):
    def test_wrong_ones_from_the_internet_do_not_make_home_wait(self) -> None:
        secret = _set_up()
        for sent in range(25):
            self._from(f"198.51.100.{sent + 1}").post(
                "/api/auth/login",
                json={"password": "not the one at all", "code": _code(secret)},
            )
        # A computer of the house that has no count of its own yet.
        answer = self._sign_in(self._from("192.168.1.60"))
        expect(answer.status_code).to_equal(200)
