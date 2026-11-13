"""The one-time code asked of who signs in from the Internet."""

import time
from typing import Any

from pyexpect import expect

from mariner import totp
from mariner.server import auth, state
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

    def test_the_page_is_told_where_it_is_seen_from(self) -> None:
        expect(self.state_of(self._from(LOCAL))).to_equal(
            {
                "password_set": True,
                "signed_in": False,
                "from_internet": False,
                "code_set": False,
            }
        )
        _set_up()
        told = self.state_of(self._from(INTERNET))
        expect(told["from_internet"]).to_equal(True)
        expect(told["code_set"]).to_equal(True)

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

    def test_doing_away_with_it_asks_for_the_password(self) -> None:
        _set_up()
        wrong = self.client.post("/api/auth/code/remove", json={"current": "not it"})
        expect(wrong.status_code).to_equal(401)
        expect(auth.code_is_set()).to_equal(True)
        right = self.client.post("/api/auth/code/remove", json={"current": PASSWORD})
        expect(right.status_code).to_equal(200)
        expect(auth.code_is_set()).to_equal(False)
