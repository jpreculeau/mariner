import json
import tempfile
from pathlib import Path
from typing import Any

from flask.testing import FlaskClient
from unittest import TestCase
from unittest.mock import patch

from pyexpect import expect

from mariner import passwords
from mariner.server import app as application, auth, state

PASSWORD = "correct horse battery"


class _WithState(TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        state.forget()
        self.addCleanup(state.forget)
        patcher = patch(
            "mariner.config.get_state_directory", return_value=str(self.root / "s")
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        auth.forget_attempts()
        # Fast: the real cost is measured once, below.
        cost = patch.object(passwords, "SCRYPT_N", 2**4)
        cost.start()
        self.addCleanup(cost.stop)


class PasswordTest(_WithState):
    def test_there_is_none_at_first(self) -> None:
        expect(auth.has_password()).to_equal(False)
        expect(auth.check_password(PASSWORD)).to_equal(False)
        expect(auth.check_password("")).to_equal(False)

    def test_the_one_that_was_set_is_the_one_that_is_taken(self) -> None:
        auth.set_password(PASSWORD)
        expect(auth.has_password()).to_equal(True)
        expect(auth.check_password(PASSWORD)).to_equal(True)
        expect(auth.check_password(PASSWORD + " ")).to_equal(False)
        expect(auth.check_password(PASSWORD.upper())).to_equal(False)

    def test_it_is_kept_as_a_hash_that_does_not_give_it_away(self) -> None:
        auth.set_password(PASSWORD)
        kept = (self.root / "s" / "password").read_bytes()
        expect(PASSWORD.encode() in kept).to_equal(False)
        record = json.loads(kept)
        expect(record["scheme"]).to_equal("scrypt")
        # Salted: the same password twice does not give the same hash.
        auth.set_password(PASSWORD)
        again = json.loads((self.root / "s" / "password").read_bytes())
        expect(again["salt"] == record["salt"]).to_equal(False)
        expect(again["hash"] == record["hash"]).to_equal(False)

    def test_it_outlasts_a_restart(self) -> None:
        auth.set_password(PASSWORD)
        state.forget()
        expect(auth.check_password(PASSWORD)).to_equal(True)

    def test_it_is_checked_with_the_cost_it_was_set_with(self) -> None:
        # The cost can be raised in a later version without locking out
        # whoever set a password before.
        auth.set_password(PASSWORD)
        with patch.object(passwords, "SCRYPT_N", 2**5):
            expect(auth.check_password(PASSWORD)).to_equal(True)

    def test_the_real_cost_is_one_a_small_board_can_pay(self) -> None:
        # And high enough to slow down whoever holds the file: the cost
        # scrypt is advised at for a password typed by hand.
        self.addCleanup(patch.stopall)
        patch.stopall()
        expect(passwords.SCRYPT_N).to_equal(2**14)
        expect(passwords.SCRYPT_R).to_equal(8)

    def test_one_everybody_tries_first_is_refused(self) -> None:
        for common in (
            "password",
            "12345678",
            "Motdepasse",
            "MARINER123",
            "azertyuiop",
        ):
            with self.assertRaises(auth.PasswordNotAllowed) as refused:
                auth.set_password(common)
            expect(refused.exception.code).to_equal("password_too_common")

    def test_setting_one_tells_which_it_is(self) -> None:
        # So that who set it is signed in under that one, and no other.
        number = auth.set_password(PASSWORD)
        expect(number).to_equal(auth.generation())

    def test_one_is_not_chosen_where_there_is_one(self) -> None:
        auth.set_password(PASSWORD)
        with self.assertRaises(auth.PasswordAlreadySet):
            auth.set_password("another one!", only_if_none=True)
        expect(auth.check_password(PASSWORD)).to_equal(True)

    def test_a_short_one_is_refused(self) -> None:
        for short in ("", "1234567", "é" * 7):
            with self.assertRaises(auth.PasswordNotAllowed):
                auth.set_password(short)
        expect(auth.has_password()).to_equal(False)
        auth.set_password("é" * 8)

    def test_one_too_long_to_be_one_is_refused(self) -> None:
        # Hashing is paid for by Mariner, for whoever sends it.
        with self.assertRaises(auth.PasswordNotAllowed):
            auth.set_password("a" * 1025)
        auth.set_password(PASSWORD)
        expect(auth.check_password("a" * 100_000)).to_equal(False)

    def test_a_record_that_cannot_be_read_takes_no_password(self) -> None:
        # Not "any": a file cut short must not open the door.
        auth.set_password(PASSWORD)
        for broken in (b"", b"{", b"[]", b'{"scheme": "plain", "hash": "x"}'):
            state.write("password", broken)
            expect(auth.check_password(PASSWORD)).to_equal(False)
            # It still counts as set: whoever comes first must not be
            # offered to choose a new one.
            expect(auth.has_password()).to_equal(True)

    def test_clearing_it_leaves_none(self) -> None:
        auth.set_password(PASSWORD)
        auth.clear_password()
        expect(auth.has_password()).to_equal(False)
        expect(auth.check_password(PASSWORD)).to_equal(False)

    def test_each_one_set_has_a_number_of_its_own(self) -> None:
        # By which the sessions opened under the one before are ended.
        auth.set_password(PASSWORD)
        first = auth.generation()
        auth.set_password(PASSWORD)
        expect(auth.generation() == first).to_equal(False)
        auth.clear_password()
        auth.set_password(PASSWORD)
        expect(auth.generation() in (first,)).to_equal(False)


class AttemptsTest(_WithState):
    def _claims(self, times: int, now: float) -> list:
        return [auth.claim_attempt("others", now=now) for _ in range(times)]

    def test_a_few_wrong_ones_cost_nothing(self) -> None:
        expect(self._claims(3, now=100.0)).to_equal([0, 0, 0])

    def test_more_of_them_have_the_next_wait_longer_each_time(self) -> None:
        self._claims(3, now=100.0)
        waits = []
        now = 100.0
        for _ in range(8):
            wait = auth.claim_attempt("others", now=now)
            waits.append(wait)
            now += wait
            # Once it has waited, it is looked at; and is wrong again.
            expect(auth.claim_attempt("others", now=now)).to_equal(0)
        expect(waits[:5]).to_equal([1, 2, 4, 8, 16])
        # Never so long that the owner is kept out for good by someone
        # else's attempts.
        expect(max(waits)).to_equal(30)

    def test_the_wait_runs_out(self) -> None:
        self._claims(5, now=100.0)
        # Three for nothing, a fourth after a second, and so on: here two
        # were turned away, which counts for nothing.
        expect(auth.claim_attempt("others", now=100.0)).to_equal(1)
        expect(auth.claim_attempt("others", now=100.5)).to_equal(1)
        expect(auth.claim_attempt("others", now=101.0)).to_equal(0)

    def test_one_that_is_turned_away_is_not_counted(self) -> None:
        self._claims(3, now=100.0)
        for _ in range(50):
            expect(auth.claim_attempt("others", now=100.0)).to_equal(1)
        expect(auth.claim_attempt("others", now=101.0)).to_equal(0)
        expect(auth.claim_attempt("others", now=101.0)).to_equal(2)

    def test_only_one_of_several_at_once_is_looked_at(self) -> None:
        # Sent together to get several looked at for one wait.
        import threading

        self._claims(3, now=100.0)
        got = []

        def claim() -> None:
            got.append(auth.claim_attempt("others", now=101.0))

        threads = [threading.Thread(target=claim) for _ in range(16)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        expect(got.count(0)).to_equal(1)

    def test_the_right_one_starts_the_count_again(self) -> None:
        self._claims(8, now=100.0)
        auth.note_success("others")
        expect(self._claims(3, now=100.0)).to_equal([0, 0, 0])

    def test_each_address_has_a_count_of_its_own(self) -> None:
        # Else anyone on the network could keep the owner out for as
        # long as they like, a wrong password every half minute.
        theirs = auth.count_of("192.0.2.7", now=100.0)
        for _ in range(10):
            auth.claim_attempt(theirs, now=100.0)
        expect(auth.claim_attempt(theirs, now=100.0) > 0).to_equal(True)
        mine = auth.count_of("192.0.2.8", now=100.0)
        expect(mine == theirs).to_equal(False)
        expect([auth.claim_attempt(mine, now=100.0) for _ in range(3)]).to_equal(
            [0, 0, 0]
        )

    def test_addresses_beyond_a_few_share_one_count(self) -> None:
        # Else trying passwords would only take changing address.
        for number in range(auth._MOST_ADDRESSES):
            auth.claim_attempt(auth.count_of(f"192.0.2.{number}", now=100.0), now=100.0)
        ninth = auth.count_of("192.0.2.100", now=100.0)
        tenth = auth.count_of("192.0.2.101", now=100.0)
        expect(ninth).to_equal(tenth)
        # One that has its count keeps it.
        expect(auth.count_of("192.0.2.3", now=100.0) == ninth).to_equal(False)

    def test_an_address_left_alone_makes_room_for_another(self) -> None:
        for number in range(auth._MOST_ADDRESSES):
            auth.claim_attempt(auth.count_of(f"192.0.2.{number}", now=100.0), now=100.0)
        shared = auth.count_of("192.0.2.100", now=100.0)
        later = 100.0 + auth._FORGOTTEN_AFTER_SECS + 1
        expect(auth.count_of("192.0.2.100", now=later) == shared).to_equal(False)

    def test_the_addresses_of_one_network_share_a_count(self) -> None:
        # A computer has as many as it likes of these.
        expect(auth.count_of("2001:db8:1:2::7", now=100.0)).to_equal(
            auth.count_of("2001:db8:1:2:aaaa::9", now=100.0)
        )
        expect(
            auth.count_of("2001:db8:1:3::7", now=100.0)
            == auth.count_of("2001:db8:1:2::7", now=100.0)
        ).to_equal(False)
        # The same computer, written the other way.
        expect(auth.count_of("::ffff:192.0.2.7", now=100.0)).to_equal(
            auth.count_of("192.0.2.7", now=100.0)
        )

    def test_one_that_is_no_address_is_counted_with_the_rest(self) -> None:
        expect(auth.count_of(None, now=100.0)).to_equal(
            auth.count_of("not an address", now=100.0)
        )


class _Page(FlaskClient):
    """A client that does as the page does: it keeps the key signing in
    gives it, and sends it with each request."""

    def open(self, *args: Any, **kwargs: Any) -> Any:
        response = super().open(*args, **kwargs)
        body = response.get_json(silent=True) if response.is_json else None
        if isinstance(body, dict) and "page_key" in body:
            self.environ_base["HTTP_X_MARINER_KEY"] = body["page_key"]
        return response


class _WithClient(_WithState):
    def setUp(self) -> None:
        super().setUp()
        self.application = application.app
        as_the_page = patch.object(self.application, "test_client_class", _Page)
        as_the_page.start()
        self.addCleanup(as_the_page.stop)
        patcher = patch.dict(self.application.config, {"WTF_CSRF_ENABLED": False})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = self.application.test_client()

    def post(self, path: str, **body: Any) -> Any:
        return self.client.post(path, json=body)

    def state_of(self, client: Any = None) -> Any:
        return (client or self.client).get("/api/auth/state").get_json()


class FirstVisitTest(_WithClient):
    def test_the_page_is_told_that_a_password_is_to_be_chosen(self) -> None:
        expect(self.state_of()).to_equal({"password_set": False, "signed_in": False})

    def test_nothing_else_is_answered_until_one_is(self) -> None:
        for path in ("/api/print_status", "/api/list_files", "/api/settings"):
            response = self.client.get(path)
            expect(response.status_code).to_equal(401)
            expect(response.get_json()["code"]).to_equal("password_not_set")
        response = self.client.post("/api/printer/command/cancel_print")
        expect(response.status_code).to_equal(401)

    def test_choosing_one_signs_in(self) -> None:
        response = self.post("/api/auth/setup", password=PASSWORD)
        expect(response.status_code).to_equal(200)
        expect(self.state_of()).to_equal({"password_set": True, "signed_in": True})
        expect(auth.check_password(PASSWORD)).to_equal(True)

    def test_signing_in_when_there_is_none_says_that_one_is_to_be_chosen(
        self,
    ) -> None:
        # The page left on its form to sign in, and the password cleared
        # since: "wrong password" would be said for ever.
        response = self.post("/api/auth/login", password=PASSWORD)
        expect(response.status_code).to_equal(401)
        expect(response.get_json()["code"]).to_equal("password_not_set")

    def test_one_that_cannot_be_kept_is_said_as_such(self) -> None:
        # A drive that is full or read-only: not the words for a file
        # that is being sent, and not "unexpected error".
        for cause in (OSError(28, "No space left on device"), PermissionError()):
            with patch.object(state, "write", side_effect=cause):
                response = self.post("/api/auth/setup", password=PASSWORD)
            expect(response.status_code).to_equal(500)
            expect(response.get_json()["code"]).to_equal("state_not_written")
        expect(self.state_of()["signed_in"]).to_equal(False)

    def test_the_key_of_sessions_is_the_one_kept_when_one_is_chosen(self) -> None:
        # ``mariner reset-password`` removed the key while Mariner ran:
        # signed with the one in memory, the session would end at the
        # next start.
        restored = patch.dict(self.application.config, {"SECRET_KEY": b"m" * 32})
        restored.start()
        self.addCleanup(restored.stop)
        state.remove("session.key")
        self.post("/api/auth/setup", password=PASSWORD)
        expect(state.read("session.key")).to_equal(
            self.application.config["SECRET_KEY"]
        )
        expect(self.state_of()["signed_in"]).to_equal(True)

    def test_one_that_is_too_short_is_refused_with_the_reason(self) -> None:
        response = self.post("/api/auth/setup", password="short")
        expect(response.status_code).to_equal(400)
        expect(response.get_json()["code"]).to_equal("password_too_short")
        expect(auth.has_password()).to_equal(False)

    def test_what_is_not_a_password_is_refused(self) -> None:
        for body in ({}, {"password": 12345678}, {"password": None}, []):
            response = self.client.post("/api/auth/setup", json=body)
            expect(response.status_code).to_equal(400)
        response = self.client.post("/api/auth/setup", data="password=longenough")
        expect(response.status_code).to_equal(400)
        expect(auth.has_password()).to_equal(False)

    def test_of_several_choosing_at_once_one_is_taken_and_one_signed_in(
        self,
    ) -> None:
        # The others must not come out signed in under a password that
        # is not theirs.
        import threading
        import time

        slow = passwords.scrypt

        def hashed(*args: Any) -> bytes:
            time.sleep(0.05)
            return slow(*args)

        clients = [self.application.test_client() for _ in range(4)]
        answers: list = [None] * 4

        def choose(index: int) -> None:
            answers[index] = clients[index].post(
                "/api/auth/setup", json={"password": f"password of {index}!"}
            )

        with patch.object(passwords, "scrypt", side_effect=hashed):
            threads = [threading.Thread(target=choose, args=(i,)) for i in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        codes = sorted(answer.status_code for answer in answers)
        expect(codes).to_equal([200, 409, 409, 409])
        signed_in = [self.state_of(client)["signed_in"] for client in clients]
        expect(signed_in.count(True)).to_equal(1)
        winner = signed_in.index(True)
        expect(answers[winner].status_code).to_equal(200)
        expect(auth.check_password(f"password of {winner}!")).to_equal(True)

    def test_it_can_be_chosen_only_once(self) -> None:
        # Else anyone could choose another, and be let in.
        self.post("/api/auth/setup", password=PASSWORD)
        other = self.application.test_client()
        response = other.post("/api/auth/setup", json={"password": "another one!"})
        expect(response.status_code).to_equal(409)
        expect(response.get_json()["code"]).to_equal("password_already_set")
        expect(auth.check_password(PASSWORD)).to_equal(True)
        expect(self.state_of(other)["signed_in"]).to_equal(False)


class SignInTest(_WithClient):
    def setUp(self) -> None:
        super().setUp()
        auth.set_password(PASSWORD)

    def test_the_key_of_sessions_is_the_one_kept_when_signing_in(self) -> None:
        # ``mariner set-password`` removed the key while Mariner ran.
        restored = patch.dict(self.application.config, {"SECRET_KEY": b"m" * 32})
        restored.start()
        self.addCleanup(restored.stop)
        state.remove("session.key")
        self.post("/api/auth/login", password=PASSWORD)
        expect(state.read("session.key")).to_equal(
            self.application.config["SECRET_KEY"]
        )
        expect(self.state_of()["signed_in"]).to_equal(True)

    def test_a_wrong_password_does_not_change_the_key_of_sessions(self) -> None:
        restored = patch.dict(self.application.config, {"SECRET_KEY": b"m" * 32})
        restored.start()
        self.addCleanup(restored.stop)
        state.remove("session.key")
        self.post("/api/auth/login", password="not the one")
        expect(self.application.config["SECRET_KEY"]).to_equal(b"m" * 32)

    def test_without_signing_in_nothing_is_answered(self) -> None:
        for path in ("/api/print_status", "/api/list_files", "/api/settings"):
            response = self.client.get(path)
            expect(response.status_code).to_equal(401)
            expect(response.get_json()["code"]).to_equal("login_required")
        for path in (
            "/api/printer/command/cancel_print",
            "/api/delete_file?filename=foobar.ctb",
            "/api/host/shutdown",
            "/api/create_directory?path=.&name=x",
        ):
            expect(self.client.post(path).status_code).to_equal(401)

    def test_an_address_that_does_not_exist_is_not_told_apart(self) -> None:
        # Nothing of what there is is given away to who is not signed in.
        expect(self.client.get("/api/nothing_here").status_code).to_equal(401)

    def test_the_page_itself_is_still_served(self) -> None:
        # It is what asks for the password. The token it needs too.
        expect(self.client.get("/api/csrf_token").status_code).to_equal(200)
        expect(self.state_of()).to_equal({"password_set": True, "signed_in": False})

    def test_the_right_password_signs_in(self) -> None:
        response = self.post("/api/auth/login", password=PASSWORD)
        expect(response.status_code).to_equal(200)
        expect(self.state_of()["signed_in"]).to_equal(True)
        # And what was closed is answered (here: no such folder).
        response = self.client.get("/api/list_files?path=nowhere")
        expect(response.status_code).to_equal(404)

    def test_a_wrong_one_does_not(self) -> None:
        response = self.post("/api/auth/login", password="not the one")
        expect(response.status_code).to_equal(401)
        expect(response.get_json()["code"]).to_equal("wrong_password")
        expect(self.state_of()["signed_in"]).to_equal(False)

    def test_the_cookie_cannot_be_read_by_scripts_nor_sent_by_other_sites(
        self,
    ) -> None:
        response = self.post("/api/auth/login", password=PASSWORD)
        cookie = response.headers["Set-Cookie"]
        expect(cookie.startswith("mariner_session=")).to_equal(True)
        expect("HttpOnly" in cookie).to_equal(True)
        expect("SameSite=Lax" in cookie).to_equal(True)
        expect("Path=/" in cookie).to_equal(True)
        # Kept for a month, not for the life of the browser's window.
        expect("Expires=" in cookie).to_equal(True)

    def test_too_many_wrong_ones_have_the_next_wait(self) -> None:
        for _ in range(3):
            self.post("/api/auth/login", password="not the one")
        with patch.object(auth, "check_password") as checked:
            response = self.post("/api/auth/login", password=PASSWORD)
        expect(response.status_code).to_equal(429)
        expect(response.get_json()["code"]).to_equal("too_many_attempts")
        expect(int(response.headers["Retry-After"]) >= 1).to_equal(True)
        # One second is not "1 seconds".
        expect(" 1 seconds" in response.get_json()["description"]).to_equal(False)
        # Not even looked at: that is the point.
        checked.assert_not_called()

    def test_signing_out_ends_the_session(self) -> None:
        self.post("/api/auth/login", password=PASSWORD)
        response = self.post("/api/auth/logout")
        expect(response.status_code).to_equal(200)
        # With a token for what comes next, which is signing in again.
        expect(len(response.get_json()["csrf_token"]) > 20).to_equal(True)
        expect(self.state_of()["signed_in"]).to_equal(False)
        expect(self.client.get("/api/print_status").status_code).to_equal(401)

    def test_a_session_is_new_at_each_sign_in(self) -> None:
        # What a page held before signing in is not what it holds after:
        # a token planted beforehand is of no use.
        with self.client.session_transaction() as before:
            before["planted"] = "x"
        self.post("/api/auth/login", password=PASSWORD)
        with self.client.session_transaction() as after:
            expect("planted" in after).to_equal(False)


class StayingSignedOutTest(_WithClient):
    """Signing out, or changing the password, is not undone by the answer
    to a request that was on its way."""

    def setUp(self) -> None:
        super().setUp()
        auth.set_password(PASSWORD)
        self.post("/api/auth/login", password=PASSWORD)

    def test_an_ordinary_answer_sets_no_cookie(self) -> None:
        # The printer's status is asked for every few seconds and can
        # take ten to come: its answer, leaving after the one to signing
        # out, would put the signed-in cookie back.
        for path in ("/api/list_files?path=nowhere", "/api/settings"):
            response = self.client.get(path)
            expect("Set-Cookie" in response.headers).to_equal(False)

    def test_the_month_starts_again_when_the_page_is_opened(self) -> None:
        # Which is when it asks where it stands.
        response = self.client.get("/api/auth/state")
        expect(response.get_json()["signed_in"]).to_equal(True)
        expect("Expires=" in response.headers["Set-Cookie"]).to_equal(True)

    def test_it_does_not_for_who_is_not_signed_in(self) -> None:
        other = self.application.test_client()
        response = other.get("/api/auth/state")
        expect("Set-Cookie" in response.headers).to_equal(False)

    def test_the_cookie_of_a_session_signed_out_of_is_of_no_use(self) -> None:
        # Copied beforehand, or put back by an answer on its way.
        with self.client.session_transaction() as held:
            before = dict(held)
        key = self.client.environ_base["HTTP_X_MARINER_KEY"]
        self.post("/api/auth/logout")
        expect(auth.let_in(before, key)).to_equal(False)
        # Nor after a restart: what was signed out of is kept.
        auth.forget_signed_out()
        expect(auth.let_in(before, key)).to_equal(False)

    def test_another_session_is_left_alone(self) -> None:
        other = self.application.test_client()
        other.post("/api/auth/login", json={"password": PASSWORD})
        self.post("/api/auth/logout")
        expect(self.state_of(other)["signed_in"]).to_equal(True)

    def test_many_sessions_signed_out_of_all_stay_so(self) -> None:
        clients = []
        for _ in range(30):
            client = self.application.test_client()
            client.post("/api/auth/login", json={"password": PASSWORD})
            with client.session_transaction() as held:
                clients.append((dict(held), client.environ_base["HTTP_X_MARINER_KEY"]))
            client.post("/api/auth/logout")
        expect([auth.let_in(held, key) for held, key in clients]).to_equal([False] * 30)

    def test_what_is_kept_of_signed_out_sessions_does_not_grow_for_ever(self) -> None:
        for _ in range(auth._MOST_SIGNED_OUT + 20):
            client = self.application.test_client()
            client.post("/api/auth/login", json={"password": PASSWORD})
            client.post("/api/auth/logout")
        kept = json.loads(state.read("signed-out.json") or b"{}")
        expect(len(kept) <= auth._MOST_SIGNED_OUT).to_equal(True)

    def test_a_session_older_than_a_month_is_not_taken(self) -> None:
        from freezegun import freeze_time

        with freeze_time("2026-01-01"):
            fresh = self.application.test_client()
            fresh.post("/api/auth/login", json={"password": PASSWORD})
            expect(self.state_of(fresh)["signed_in"]).to_equal(True)
        with freeze_time("2026-02-05"):
            expect(self.state_of(fresh)["signed_in"]).to_equal(False)

    def test_the_count_of_wrong_ones_starts_again_at_the_right_one(self) -> None:
        other = self.application.test_client()
        for _ in range(2):
            other.post("/api/auth/login", json={"password": "not the one"})
        other.post("/api/auth/login", json={"password": PASSWORD})
        for _ in range(3):
            response = other.post("/api/auth/login", json={"password": "wrong again"})
            expect(response.status_code).to_equal(401)

    def test_the_password_is_asked_for_before_the_token(self) -> None:
        # Checking the token reads the whole form, file included.
        with patch.dict(self.application.config, {"WTF_CSRF_ENABLED": True}):
            other = self.application.test_client()
            response = other.post("/api/upload_file", data={"file": "x"})
        expect(response.status_code).to_equal(401)


class ChangeTest(_WithClient):
    def setUp(self) -> None:
        super().setUp()
        auth.set_password(PASSWORD)
        self.post("/api/auth/login", password=PASSWORD)

    def test_one_that_cannot_be_kept_is_not_a_wrong_password(self) -> None:
        with patch.object(state, "write", side_effect=OSError(30, "Read-only")):
            for _ in range(4):
                response = self.post(
                    "/api/auth/password", current=PASSWORD, new="new password!"
                )
                expect(response.status_code).to_equal(500)
                expect(response.get_json()["code"]).to_equal("state_not_written")
        # The drive put right: no wait for wrong passwords nobody sent.
        response = self.post(
            "/api/auth/password", current=PASSWORD, new="new password!"
        )
        expect(response.status_code).to_equal(200)

    def test_a_new_one_that_is_refused_is_not_a_wrong_password(self) -> None:
        for _ in range(4):
            response = self.post("/api/auth/password", current=PASSWORD, new="short")
            expect(response.get_json()["code"]).to_equal("password_too_short")

    def test_changing_it_asks_for_the_one_in_place(self) -> None:
        response = self.post("/api/auth/password", current="wrong", new="new password!")
        expect(response.status_code).to_equal(401)
        expect(response.get_json()["code"]).to_equal("wrong_password")
        expect(auth.check_password(PASSWORD)).to_equal(True)

    def test_it_is_changed_and_this_page_stays_signed_in(self) -> None:
        response = self.post(
            "/api/auth/password", current=PASSWORD, new="new password!"
        )
        expect(response.status_code).to_equal(200)
        expect(auth.check_password("new password!")).to_equal(True)
        expect(auth.check_password(PASSWORD)).to_equal(False)
        expect(self.state_of()["signed_in"]).to_equal(True)

    def test_the_other_pages_are_signed_out(self) -> None:
        # Someone who got hold of the old one is put out by the new.
        other = self.application.test_client()
        other.post("/api/auth/login", json={"password": PASSWORD})
        expect(self.state_of(other)["signed_in"]).to_equal(True)
        self.post("/api/auth/password", current=PASSWORD, new="new password!")
        expect(self.state_of(other)["signed_in"]).to_equal(False)

    def test_a_new_one_that_is_too_short_is_refused(self) -> None:
        response = self.post("/api/auth/password", current=PASSWORD, new="short")
        expect(response.status_code).to_equal(400)
        expect(response.get_json()["code"]).to_equal("password_too_short")
        expect(auth.check_password(PASSWORD)).to_equal(True)

    def test_it_is_not_changed_by_who_is_not_signed_in(self) -> None:
        other = self.application.test_client()
        response = other.post(
            "/api/auth/password", json={"current": PASSWORD, "new": "new password!"}
        )
        expect(response.status_code).to_equal(401)
        expect(auth.check_password(PASSWORD)).to_equal(True)

    def test_clearing_the_password_ends_every_session(self) -> None:
        auth.clear_password()
        expect(self.state_of()).to_equal({"password_set": False, "signed_in": False})
        # And one chosen anew does not bring them back.
        auth.set_password(PASSWORD)
        expect(self.state_of()["signed_in"]).to_equal(False)


class OtherCookiesTest(_WithClient):
    def setUp(self) -> None:
        super().setUp()
        auth.set_password(PASSWORD)
        response = self.post("/api/auth/login", password=PASSWORD)
        self.own = response.headers["Set-Cookie"].split(";")[0]

    def _signed_in(self, cookie_header: str) -> bool:
        # As a browser sends it: the test client would send its own.
        with self.application.test_request_context(
            "/api/auth/state", headers={"Cookie": cookie_header}
        ):
            from flask import session

            # The session alone: the key the page sends with it is in
            # PageKeyTest.
            return auth.signed_in_with(session)

    def test_the_cookie_it_gave_signs_in(self) -> None:
        expect(self._signed_in(self.own)).to_equal(True)

    def test_a_cookie_of_the_same_name_set_by_something_else_is_passed_over(
        self,
    ) -> None:
        # Another program on the same computer (a camera's page, on
        # another port) can set one for the same name of host. The
        # browser then sends both, the other's first.
        for header in (
            f"mariner_session=not-ours; {self.own}",
            f"{self.own}; mariner_session=not-ours",
            f"mariner_session=; mariner_session=a.b.c; other=1; {self.own}",
        ):
            expect(self._signed_in(header)).to_equal(True)

    def test_a_cookie_that_is_not_ours_alone_signs_nobody_in(self) -> None:
        for header in ("mariner_session=not-ours", "", "session=" + self.own[16:]):
            expect(self._signed_in(header)).to_equal(False)

    def test_a_cookie_signed_with_another_key_signs_nobody_in(self) -> None:
        with patch.dict(self.application.config, {"SECRET_KEY": b"x" * 32}):
            expect(self._signed_in(self.own)).to_equal(False)

    def test_only_so_many_are_tried(self) -> None:
        # Each costs a signature to check. More than a browser would send
        # under every path and form of the name there is.
        some = "; ".join(["mariner_session=x"] * 20)
        expect(self._signed_in(f"{some}; {self.own}")).to_equal(True)
        many = "; ".join(["mariner_session=x"] * 50)
        expect(self._signed_in(f"{many}; {self.own}")).to_equal(False)

    def test_one_that_is_signed_in_comes_before_one_that_is_not(self) -> None:
        # Anyone is given a cookie Mariner signed, by asking for a token.
        # Set by another program for a longer path, the browser sends it
        # first: taken, it would sign the reader out for as long as it
        # lasts.
        fresh = self.application.test_client()
        given = fresh.get("/api/csrf_token").headers["Set-Cookie"].split(";")[0]
        expect(self._signed_in(given)).to_equal(False)
        expect(self._signed_in(f"{given}; {self.own}")).to_equal(True)
        expect(self._signed_in(f"{self.own}; {given}")).to_equal(True)

    def test_one_that_is_not_signed_in_is_still_a_session(self) -> None:
        # Its token is what lets the page sign in.
        fresh = self.application.test_client()
        given = fresh.get("/api/csrf_token").headers["Set-Cookie"].split(";")[0]
        from mariner.server import sessions

        held = sessions.read(self.application, f"mariner_session=x; {given}")
        expect("csrf_token" in held).to_equal(True)

    def test_a_cookie_too_long_to_be_one_is_passed_over(self) -> None:
        long = "mariner_session=" + "a" * 5000
        expect(self._signed_in(f"{long}; {self.own}")).to_equal(True)


class StartingOverTest(_WithState):
    """A password that is lost cannot be read back: it is cleared, by
    someone who has the computer in hand."""

    def setUp(self) -> None:
        super().setUp()
        auth.set_password(PASSWORD)
        self.boot = self.root / "boot"
        self.boot.mkdir()
        places = patch.object(auth, "_BOOT_DIRECTORIES", [str(self.boot)])
        places.start()
        self.addCleanup(places.stop)

    def test_nothing_is_cleared_when_nothing_asks(self) -> None:
        expect(auth.clear_if_asked_on_the_boot_drive()).to_equal(False)
        expect(auth.check_password(PASSWORD)).to_equal(True)

    def test_a_file_left_on_the_boot_drive_clears_it(self) -> None:
        # Written from any computer the card is put in.
        (self.boot / "reset-password").write_bytes(b"")
        with self.assertLogs("mariner.server.auth", level="WARNING"):
            expect(auth.clear_if_asked_on_the_boot_drive()).to_equal(True)
        expect(auth.has_password()).to_equal(False)
        # Removed, so that the next start does not clear the new one.
        expect((self.boot / "reset-password").exists()).to_equal(False)

    def test_the_name_may_have_the_ending_a_computer_adds(self) -> None:
        for name in ("reset-password.txt", "RESET-PASSWORD.TXT", "Reset-Password"):
            auth.set_password(PASSWORD)
            (self.boot / name).write_bytes(b"anything")
            with self.assertLogs("mariner.server.auth", level="WARNING"):
                expect(auth.clear_if_asked_on_the_boot_drive()).to_equal(True)
            expect(auth.has_password()).to_equal(False)

    def test_a_file_that_cannot_be_removed_clears_it_once(self) -> None:
        # The service may not write to that drive. The password chosen
        # next must then not be cleared at every start.
        asked = self.boot / "reset-password"
        asked.write_bytes(b"")
        with patch.object(
            auth, "_remove_the_request", side_effect=PermissionError("read-only")
        ):
            with self.assertLogs("mariner.server.auth", level="WARNING"):
                expect(auth.clear_if_asked_on_the_boot_drive()).to_equal(True)
            auth.set_password(PASSWORD)
            expect(auth.clear_if_asked_on_the_boot_drive()).to_equal(False)
        expect(auth.check_password(PASSWORD)).to_equal(True)

    def test_the_same_file_written_again_clears_it_again(self) -> None:
        import os

        asked = self.boot / "reset-password"
        asked.write_bytes(b"")
        with patch.object(
            auth, "_remove_the_request", side_effect=PermissionError("read-only")
        ):
            with self.assertLogs("mariner.server.auth", level="WARNING"):
                auth.clear_if_asked_on_the_boot_drive()
            auth.set_password(PASSWORD)
            os.utime(asked, (2_000_000_000, 2_000_000_000))
            with self.assertLogs("mariner.server.auth", level="WARNING"):
                expect(auth.clear_if_asked_on_the_boot_drive()).to_equal(True)
        expect(auth.has_password()).to_equal(False)

    def test_a_folder_of_that_name_asks_nothing(self) -> None:
        (self.boot / "reset-password").mkdir()
        expect(auth.clear_if_asked_on_the_boot_drive()).to_equal(False)
        expect(auth.check_password(PASSWORD)).to_equal(True)

    def test_a_boot_drive_that_is_not_there_asks_nothing(self) -> None:
        with patch.object(auth, "_BOOT_DIRECTORIES", [str(self.root / "none")]):
            expect(auth.clear_if_asked_on_the_boot_drive()).to_equal(False)


class NothingKeptTest(_WithClient):
    """The folder of what is kept cannot be used: the page stays shut,
    rather than offer whoever comes first to choose a password."""

    def setUp(self) -> None:
        super().setUp()
        makeshift = patch.object(state, "is_makeshift", return_value=True)
        makeshift.start()
        self.addCleanup(makeshift.stop)

    def test_no_password_is_offered_to_be_chosen(self) -> None:
        response = self.post("/api/auth/setup", password=PASSWORD)
        expect(response.status_code).to_equal(503)
        expect(response.get_json()["code"]).to_equal("state_unavailable")
        expect(auth.has_password()).to_equal(False)

    def test_the_page_is_told_so(self) -> None:
        body = self.state_of()
        expect(body["signed_in"]).to_equal(False)
        expect(body["unavailable"]).to_equal(True)

    def test_nothing_is_answered(self) -> None:
        response = self.client.get("/api/list_files")
        expect(response.status_code).to_equal(503)
        expect(response.get_json()["code"]).to_equal("state_unavailable")
        # It names the folder, for whoever is to put it right.
        expect(str(self.root / "s") in response.get_json()["description"]).to_equal(
            True
        )

    def test_nor_is_a_password_looked_at(self) -> None:
        response = self.post("/api/auth/login", password=PASSWORD)
        expect(response.status_code).to_equal(503)


class PageKeyTest(_WithClient):
    """Cookies go by the name of the host, not by its port: the page of
    any other program on the same computer is sent Mariner's. What the
    page itself keeps is not."""

    def setUp(self) -> None:
        super().setUp()
        auth.set_password(PASSWORD)
        answer = self.post("/api/auth/login", password=PASSWORD)
        self.key = answer.get_json()["page_key"]
        # From here on, what holds the cookie without the key: the page
        # of another program on the same computer.
        del self.client.environ_base["HTTP_X_MARINER_KEY"]

    def test_signing_in_gives_the_page_a_key_of_its_own(self) -> None:
        expect(len(self.key) >= 32).to_equal(True)
        other = self.application.test_client()
        again = other.post("/api/auth/login", json={"password": PASSWORD})
        expect(again.get_json()["page_key"] == self.key).to_equal(False)

    def test_the_cookie_alone_is_not_enough(self) -> None:
        expect(self.client.get("/api/list_files").status_code).to_equal(401)
        expect(self.client.get("/api/settings").status_code).to_equal(401)
        expect(self.client.post("/api/host/shutdown").status_code).to_equal(401)
        expect(self.state_of()["signed_in"]).to_equal(False)

    def test_with_the_key_it_is(self) -> None:
        headers = {"X-Mariner-Key": self.key}
        response = self.client.get("/api/list_files?path=nowhere", headers=headers)
        expect(response.status_code).to_equal(404)
        state_now = self.client.get("/api/auth/state", headers=headers).get_json()
        expect(state_now["signed_in"]).to_equal(True)

    def test_a_wrong_key_is_not(self) -> None:
        for wrong in ("", "x", self.key + "x", self.key[:-1]):
            response = self.client.get(
                "/api/list_files", headers={"X-Mariner-Key": wrong}
            )
            expect(response.status_code).to_equal(401)

    def test_the_key_of_another_session_is_not(self) -> None:
        other = self.application.test_client()
        theirs = other.post("/api/auth/login", json={"password": PASSWORD}).get_json()[
            "page_key"
        ]
        response = self.client.get("/api/list_files", headers={"X-Mariner-Key": theirs})
        expect(response.status_code).to_equal(401)

    def test_a_picture_is_shown_without_it(self) -> None:
        # A picture in a page is asked for by the browser, which sends
        # no key. Only that, and only to look.
        response = self.client.get("/api/file_preview?filename=nowhere.ctb")
        expect(response.status_code == 401).to_equal(False)
        response = self.client.post("/api/file_preview?filename=nowhere.ctb")
        expect(response.status_code).to_equal(401)

    def test_it_is_kept_as_a_hash_in_the_session(self) -> None:
        with self.client.session_transaction() as held:
            expect(self.key in str(dict(held))).to_equal(False)

    def test_changing_the_password_gives_a_new_one(self) -> None:
        answer = self.client.post(
            "/api/auth/password",
            json={"current": PASSWORD, "new": "new password!"},
            headers={"X-Mariner-Key": self.key},
        )
        expect(answer.status_code).to_equal(200)
        new = answer.get_json()["page_key"]
        expect(new == self.key).to_equal(False)
        response = self.client.get("/api/settings", headers={"X-Mariner-Key": new})
        expect(response.status_code).to_equal(200)


class OnlyTheCookieTest(_WithClient):
    """What a program that is sent the cookie, and not the key, can do to
    the reader: nothing that lasts."""

    def setUp(self) -> None:
        super().setUp()
        auth.set_password(PASSWORD)
        self.post("/api/auth/login", password=PASSWORD)
        self.key = self.client.environ_base["HTTP_X_MARINER_KEY"]
        with self.client.session_transaction() as held:
            self.held = dict(held)

    def _without_the_key(self) -> Any:
        other = self.application.test_client()
        other.environ_base.pop("HTTP_X_MARINER_KEY", None)
        with other.session_transaction() as held:
            held.update(self.held)
        return other

    def test_it_cannot_sign_the_reader_out(self) -> None:
        thief = self._without_the_key()
        thief.post("/api/auth/logout")
        expect(auth.let_in(self.held, self.key)).to_equal(True)

    def test_it_cannot_use_up_the_attempts_of_the_reader(self) -> None:
        # Its wrong passwords are counted with those of everyone else.
        thief = self._without_the_key()
        for _ in range(6):
            thief.post("/api/auth/login", json={"password": "not the one"})
        answer = self.client.post(
            "/api/auth/password", json={"current": PASSWORD, "new": "new password!"}
        )
        expect(answer.status_code).to_equal(200)

    def test_the_reader_does_not_wait_for_the_wrong_ones_of_another_computer(
        self,
    ) -> None:
        # Signed out, which is when it matters; and as the page is then:
        # it has forgotten its key.
        self.post("/api/auth/logout")
        stranger = self.application.test_client()
        stranger.environ_base["REMOTE_ADDR"] = "192.0.2.99"
        for _ in range(6):
            stranger.post("/api/auth/login", json={"password": "not the one"})
        expect(
            stranger.post("/api/auth/login", json={"password": PASSWORD}).status_code
        ).to_equal(429)
        reader = self.application.test_client()
        expect(
            reader.post("/api/auth/login", json={"password": PASSWORD}).status_code
        ).to_equal(200)

    def test_signing_out_leaves_nothing_in_the_session(self) -> None:
        self.post("/api/auth/logout")
        with self.client.session_transaction() as held:
            left = {name for name in held if not name.startswith("csrf")}
        expect(left).to_equal(set())

    def test_wrong_current_passwords_are_counted_when_changing_it(self) -> None:
        for _ in range(3):
            self.post("/api/auth/password", current="wrong", new="new password!")
        answer = self.post("/api/auth/password", current=PASSWORD, new="new password!")
        expect(answer.status_code).to_equal(429)

    def test_another_session_of_the_same_reader_does_not_come_before_this_one(
        self,
    ) -> None:
        # Signed in on a phone too: that session's cookie, set here by
        # another program for a longer path, is sent first, with this
        # page's key.
        from mariner.server import sessions

        phone = self.application.test_client()
        answer = phone.post("/api/auth/login", json={"password": PASSWORD})
        theirs = answer.headers["Set-Cookie"].split(";")[0]
        mine = self.client.get("/api/auth/state").headers["Set-Cookie"].split(";")[0]
        for header in (f"{theirs}; {mine}", f"{mine}; {theirs}"):
            held = sessions.read(self.application, header, self.key)
            expect(auth.let_in(held, self.key)).to_equal(True)

    def test_signing_in_again_ends_the_session_that_was_there(self) -> None:
        self.post("/api/auth/login", password=PASSWORD)
        expect(auth.let_in(self.held, self.key)).to_equal(False)

    def test_changing_the_password_makes_a_new_key_for_sessions(self) -> None:
        # What was signed with the old one, or forged from a copy of it,
        # is of no use.
        before = self.application.config["SECRET_KEY"]
        self.addCleanup(self.application.config.__setitem__, "SECRET_KEY", before)
        answer = self.client.post(
            "/api/auth/password", json={"current": PASSWORD, "new": "new password!"}
        )
        expect(answer.status_code).to_equal(200)
        expect(self.application.config["SECRET_KEY"] == before).to_equal(False)
        expect(state.read("session.key")).to_equal(
            self.application.config["SECRET_KEY"]
        )
        expect(self.state_of()["signed_in"]).to_equal(True)


class SignedOutListTest(_WithState):
    def setUp(self) -> None:
        super().setUp()
        auth.forget_signed_out()
        self.addCleanup(auth.forget_signed_out)

    def test_it_is_usable_when_there_is_none(self) -> None:
        expect(auth.signed_out_list_is_usable()).to_equal(True)

    def test_it_is_usable_when_it_reads(self) -> None:
        auth._note_signed_out("abc")
        auth.forget_signed_out()
        expect(auth.signed_out_list_is_usable()).to_equal(True)

    def test_it_is_not_when_it_is_there_and_cannot_be_read(self) -> None:
        # Then every session signed out of would work again: the caller
        # ends them all.
        import os

        auth._note_signed_out("abc")
        for spoil in (
            lambda path: os.chmod(path, 0o644),
            lambda path: path.write_bytes(b"{"),
            lambda path: path.write_bytes(b"[]"),
        ):
            auth.forget_signed_out()
            path = self.root / "s" / "signed-out.json"
            os.chmod(path, 0o600)
            path.write_bytes(b"{}")
            spoil(path)
            expect(auth.signed_out_list_is_usable()).to_equal(False)

    def test_what_is_signed_out_of_is_kept_longer_than_a_session_lasts(self) -> None:
        # The clock of a small board can be behind when it is noted.
        import time

        auth._note_signed_out("abc")
        kept = json.loads(state.read("signed-out.json") or b"{}")
        expect(kept["abc"] > time.time() + 45 * 86400).to_equal(True)
