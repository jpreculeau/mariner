"""What Mariner answers in the clear once its page is served over HTTPS."""

import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from pyexpect import expect

from mariner import server
from mariner.server.app import app


class PlainPortTest(TestCase):
    def setUp(self) -> None:
        app.config["TESTING"] = True
        self.client = app.test_client()
        configured = patch.dict(app.config, {"HTTPS_PORT": 5443})
        configured.start()
        self.addCleanup(configured.stop)
        # Whether signed in is not what is tried here.
        let_in = patch("mariner.server.auth.let_in", return_value=True)
        let_in.start()
        self.addCleanup(let_in.stop)
        # Nor what the page is made of.
        page = patch("mariner.server.render_index", return_value="the page")
        page.start()
        self.addCleanup(page.stop)

    def test_the_page_asked_for_in_the_clear_is_sent_on_to_https(self) -> None:
        response = self.client.get("/", base_url="http://saturn.local:5050")
        expect(response.status_code).to_equal(307)
        expect(response.headers["Location"]).to_equal("https://saturn.local:5443/")

    def test_where_in_the_page_is_kept(self) -> None:
        response = self.client.get(
            "/files?sort=name", base_url="http://192.168.1.20:5050"
        )
        expect(response.headers["Location"]).to_equal(
            "https://192.168.1.20:5443/files?sort=name"
        )

    def test_an_address_of_the_newer_kind_keeps_its_brackets(self) -> None:
        response = self.client.get("/", base_url="http://[::1]:5050")
        expect(response.headers["Location"]).to_equal("https://[::1]:5443/")

    def test_the_usual_port_is_not_spelt_out(self) -> None:
        with patch.dict(app.config, {"HTTPS_PORT": 443}):
            response = self.client.get("/", base_url="http://saturn.local")
        expect(response.headers["Location"]).to_equal("https://saturn.local/")

    def test_nothing_of_the_page_s_own_addresses_is_answered_in_the_clear(
        self,
    ) -> None:
        # A password, a session, a command to the printer: none of it
        # where whoever shares the network reads it.
        for method, path in (
            ("GET", "/api/print_status"),
            ("GET", "/api/csrf_token"),
            ("GET", "/api/auth/state"),
            ("POST", "/api/auth/login"),
            ("POST", "/api/printer/command/pause_print"),
        ):
            response = self.client.open(
                path, method=method, base_url="http://saturn.local:5050"
            )
            expect(response.status_code).to_equal(403)
            body = response.get_json()
            expect(body["code"]).to_equal("https_required")
            expect("https://saturn.local:5443" in body["description"]).to_equal(True)

    def test_the_refusal_says_where_the_page_is(self) -> None:
        # For the page left open in the clear to go there by itself.
        response = self.client.get(
            "/api/print_status", base_url="http://saturn.local:5050"
        )
        expect(response.get_json()["address"]).to_equal("https://saturn.local:5443")

    def test_a_slicer_s_address_is_told_from_one_that_looks_like_it(self) -> None:
        response = self.client.get(
            "/uvtoolsx/files", base_url="http://saturn.local:5050"
        )
        expect(response.status_code).to_equal(307)

    def test_signing_in_over_https_needs_no_referer(self) -> None:
        # A script, or a browser set to say nothing of where it comes
        # from: other sites are told apart before this, by what they do
        # say (see mariner.server.origin).
        secured = "https://saturn.local:5443"
        # Whatever another test left the application with: the token is
        # asked for, as it is when Mariner runs.
        with patch.dict(app.config, {"WTF_CSRF_ENABLED": True}):
            token = self.client.get("/api/csrf_token", base_url=secured).get_json()[
                "csrf_token"
            ]
            without = self.client.post(
                "/api/auth/login", base_url=secured, json={"password": "x" * 12}
            )
            response = self.client.post(
                "/api/auth/login",
                base_url=secured,
                json={"password": "x" * 12},
                headers={"X-CSRFToken": token},
            )
        # The token is looked at...
        expect(without.get_json()["code"]).to_equal("token_refused")
        # ...and taken without a Referer: what is answered is about the
        # password.
        expect(response.get_json().get("code") == "token_refused").to_equal(False)
        expect(response.status_code).to_equal(401)

    def test_no_session_is_given_in_the_clear(self) -> None:
        response = self.client.get(
            "/api/csrf_token", base_url="http://saturn.local:5050"
        )
        expect("Set-Cookie" in response.headers).to_equal(False)

    def test_something_other_than_reading_the_page_is_not_sent_on(self) -> None:
        response = self.client.post("/", base_url="http://saturn.local:5050")
        expect(response.status_code).to_equal(403)
        expect(response.get_json()["code"]).to_equal("https_required")

    def test_slicers_are_still_answered_in_the_clear(self) -> None:
        # They speak nothing else.
        with tempfile.TemporaryDirectory() as files, patch(
            "mariner.config.get_files_directory", return_value=Path(files)
        ):
            response = self.client.get(
                "/uvtools/files",
                base_url="http://saturn.local:5050",
                headers={"User-Agent": "UVtools"},
            )
        expect(response.status_code).to_equal(200)

    def test_over_https_everything_is_answered_as_before(self) -> None:
        response = self.client.get("/", base_url="https://saturn.local:5443")
        expect(response.status_code).to_equal(200)
        response = self.client.get(
            "/api/csrf_token", base_url="https://saturn.local:5443"
        )
        expect(response.status_code).to_equal(200)

    def test_without_https_the_clear_is_all_there_is(self) -> None:
        with patch.dict(app.config, {"HTTPS_PORT": None}):
            response = self.client.get("/", base_url="http://saturn.local:5050")
            expect(response.status_code).to_equal(200)
            response = self.client.get(
                "/api/csrf_token", base_url="http://saturn.local:5050"
            )
            expect(response.status_code).to_equal(200)

    def test_the_session_s_cookie_goes_over_https_alone(self) -> None:
        secured = {
            "SESSION_COOKIE_SECURE": True,
            "SESSION_COOKIE_NAME": server.sessions.SECURED_COOKIE_NAME,
        }
        with patch.dict(app.config, secured):
            response = self.client.get(
                "/api/csrf_token", base_url="https://saturn.local:5443"
            )
        cookie = response.headers["Set-Cookie"]
        # Under this name a browser takes it only over HTTPS, for this
        # host alone, and from no other program of the computer in the
        # clear.
        expect(cookie.startswith("__Host-mariner_session=")).to_equal(True)
        expect("Secure" in cookie).to_equal(True)
        expect("Path=/" in cookie).to_equal(True)
        expect("Domain" in cookie).to_equal(False)

    def test_a_session_from_before_https_is_not_one(self) -> None:
        # Its cookie went in the clear, and may have been read.
        signer = app.session_interface.get_signing_serializer(app)  # type: ignore
        signed = signer.dumps({"held": 1})  # type: ignore
        secured = {
            "SESSION_COOKIE_SECURE": True,
            "SESSION_COOKIE_NAME": server.sessions.SECURED_COOKIE_NAME,
        }
        with patch.dict(app.config, secured):
            expect(server.sessions.read(app, f"mariner_session={signed}", "")).to_equal(
                {}
            )
            expect(
                server.sessions.read(app, f"__Host-mariner_session={signed}", "")
            ).to_equal({"held": 1})


class FromTheInternetTest(TestCase):
    """What is answered to who is not on the local network."""

    def setUp(self) -> None:
        app.config["TESTING"] = True
        self.client = app.test_client()
        self.client.environ_base["REMOTE_ADDR"] = "203.0.113.5"
        let_in = patch("mariner.server.auth.let_in", return_value=True)
        let_in.start()
        self.addCleanup(let_in.stop)

    def test_a_slicer_s_address_is_not_answered(self) -> None:
        response = self.client.get("/uvtools/files", headers={"User-Agent": "UVtools"})
        expect(response.status_code).to_equal(403)
        expect(response.get_json()["code"]).to_equal("local_network_only")

    def test_the_computer_is_not_stopped(self) -> None:
        with patch("mariner.server.api._run_host_command") as run:
            response = self.client.post("/api/host/shutdown")
        expect(response.status_code).to_equal(403)
        expect(response.get_json()["code"]).to_equal("local_network_only")
        run.assert_not_called()

    def test_the_page_is_answered(self) -> None:
        expect(self.client.get("/api/csrf_token").status_code).to_equal(200)

    def test_the_same_from_the_local_network_is_answered(self) -> None:
        self.client.environ_base["REMOTE_ADDR"] = "192.168.1.20"
        with tempfile.TemporaryDirectory() as files, patch(
            "mariner.config.get_files_directory", return_value=Path(files)
        ):
            response = self.client.get(
                "/uvtools/files", headers={"User-Agent": "UVtools"}
            )
        expect(response.status_code).to_equal(200)
