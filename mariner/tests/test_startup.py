from typing import Any, Callable, List
from unittest import TestCase
from unittest.mock import patch

from pyexpect import expect

from mariner import server


class StartupTest(TestCase):
    def setUp(self) -> None:
        # Starting sets these for the web server: not for the tests that
        # run after these.
        for name in ("password_refusal", "plain_refusal", "UPLOAD_PREFIXES"):
            self.addCleanup(setattr, server.early, name, getattr(server.early, name))
        # Nor what it sets for the application.
        kept = patch.dict(server.flask_app.config)
        kept.start()
        self.addCleanup(kept.stop)
        # No certificate is looked for, nor made, unless a test says so.
        looked_for = patch.object(server.certificate, "in_use", return_value=None)
        self.certificate = looked_for.start()
        self.addCleanup(looked_for.stop)
        # Whatever the configuration of who runs the tests says.
        for name, value in (("get_http_host", "0.0.0.0"), ("get_http_port", 5050)):
            where = patch.object(server.config, name, return_value=value)
            where.start()
            self.addCleanup(where.stop)

    def test_unfinished_transfers_are_cleared_before_anything_else_runs(self) -> None:
        order: List[str] = []

        def record(name: str) -> Callable[..., Any]:
            def recorder(*args: Any, **kwargs: Any) -> Any:
                order.append(name)
                return recorder

            # Returning itself lets it stand in for a class whose instance
            # is then started, as CacheBootstrapper().start() is.
            recorder.start = lambda: None  # type: ignore[attr-defined]
            return recorder

        with patch.object(
            server.logging, "basicConfig", side_effect=record("logging")
        ), patch.object(server.logging.getLogger(), "handlers", []), patch.object(
            server, "keep_requests_on_one_line", side_effect=record("log filter")
        ), patch.object(
            server, "empty_cache", side_effect=record("cache emptied")
        ), patch.object(
            server, "remove_stale_scratch_files", side_effect=record("cleanup")
        ), patch.object(
            server, "CacheBootstrapper", side_effect=record("cache warm-up")
        ), patch.object(
            server, "start_providers", side_effect=record("providers")
        ), patch.object(
            server, "serve", side_effect=record("serve")
        ), patch.object(
            server.state, "session_key", return_value=b"k" * 32
        ), patch.object(
            server.auth, "clear_if_asked_on_the_boot_drive"
        ):
            server.main()

        # The cleanup comes after logging is set up, so it can report what it
        # removed, and before anything that reads or writes the files
        # directory: the cache warm-up walks it, the providers and the web
        # server can start transfers into it.
        self.assertEqual(
            order,
            [
                "logging",
                # Once the handlers exist, and before anything can be logged
                # about a request.
                "log filter",
                "cleanup",
                # What was remembered of files that are gone since goes
                # too; the warm-up reads again those that are there.
                "cache emptied",
                "cache warm-up",
                "providers",
                "serve",
            ],
        )

    def _started(self, **patches: Any) -> Any:
        with patch.object(server.logging, "basicConfig"), patch.object(
            server.logging.getLogger(), "handlers", []
        ), patch.object(server, "empty_cache"), patch.object(
            server, "remove_stale_scratch_files"
        ), patch.object(
            server, "CacheBootstrapper"
        ), patch.object(
            server, "start_providers"
        ), patch.object(
            server.state, "session_key", return_value=b"k" * 32
        ), patch.object(
            server.auth, "clear_if_asked_on_the_boot_drive"
        ) as self.asked_on_the_boot_drive, patch.object(
            server, "serve"
        ) as serve:
            server.main()
        return serve

    def test_the_web_server_asks_for_the_password_before_taking_a_body(self) -> None:
        # With the session the request's cookies make, as the application
        # itself would.
        with patch.object(server, "use_spool_directory"):
            self._started()
        with patch.object(server.sessions, "read", return_value={"held": 1}) as read:
            with patch.object(
                server.auth, "refusal", return_value={"code": "x"}
            ) as refusal:
                answer = server.early.password_refusal(
                    "POST",
                    "/api/upload_file",
                    {"Cookie": "a=b", "X-Mariner-Key": "the key"},
                )
        self.assertEqual(answer, {"code": "x"})
        read.assert_called_once_with(server.flask_app, "a=b", "the key")
        refusal.assert_called_once_with(
            "/api/upload_file", {"held": 1}, "the key", "POST"
        )

    def test_a_password_that_is_lost_is_looked_for_on_the_boot_drive(self) -> None:
        with patch.object(server, "use_spool_directory"):
            self._started()
        self.asked_on_the_boot_drive.assert_called_once_with()

    def test_every_session_ends_when_what_was_signed_out_of_cannot_be_read(
        self,
    ) -> None:
        with patch.object(server, "use_spool_directory"), patch.object(
            server.auth, "signed_out_list_is_usable", return_value=False
        ), patch.object(
            server.state, "new_session_key", return_value=b"n" * 32
        ) as renewed, patch.object(
            server.auth, "start_signed_out_list_again"
        ) as again:
            with self.assertLogs("mariner.server", level="WARNING"):
                self._started()
        renewed.assert_called_once_with()
        again.assert_called_once_with()
        self.assertEqual(server.flask_app.config["SECRET_KEY"], b"n" * 32)

    def test_sessions_are_signed_with_the_key_that_is_kept(self) -> None:
        # The same at every start: a page left open goes on working, and
        # whoever is signed in stays so.
        with patch.object(server, "use_spool_directory"):
            self._started()
        self.assertEqual(server.flask_app.config["SECRET_KEY"], b"k" * 32)

    def test_a_slicer_s_interface_that_is_off_is_sent_no_file(self) -> None:
        for running, expected in (
            (True, ("/api/upload_file", "/uvtools/upload/")),
            (False, ("/api/upload_file",)),
        ):
            with patch.object(
                server.config, "get_uvtools_enabled", return_value=running
            ), patch.object(server, "use_spool_directory"):
                self._started()
            self.assertEqual(server.early.UPLOAD_PREFIXES, expected)

    def test_the_web_server_takes_uploads_up_to_the_limit(self) -> None:
        # Left to itself it refuses anything over a gigabyte.
        with patch.object(
            server.config, "get_max_upload_bytes", return_value=3 * 1024**3
        ), patch.object(server, "use_spool_directory"):
            serve = self._started()
        self.assertEqual(
            serve.call_args.kwargs["max_request_body_size"], 3 * 1024**3 + 1024**2
        )

    def test_a_connection_that_says_nothing_is_not_kept_for_long(self) -> None:
        # There are only so many: held open and silent, they would keep
        # everyone else out for as long.
        with patch.object(server, "use_spool_directory"):
            serve = self._started()
        timeout = serve.call_args.kwargs["channel_timeout"]
        # Not so short that a phone that hesitates in the middle of an
        # upload loses it.
        self.assertGreaterEqual(timeout, 45)
        self.assertLessEqual(timeout, 90)

    def test_entries_that_can_match_nothing_are_said_at_start(self) -> None:
        with patch.object(
            server.origin, "unusable_entries", return_value=["an entry"]
        ), patch.object(server, "use_spool_directory"), self.assertLogs(
            "mariner.server", level="WARNING"
        ) as logs:
            self._started()
        self.assertTrue(any("an entry" in r.getMessage() for r in logs.records))

    def test_the_web_server_is_the_one_that_refuses_early(self) -> None:
        from mariner.server import early

        self.assertIs(server.serve, early.serve)

    def test_settings_passed_over_are_said_at_start(self) -> None:
        with patch.object(
            server.config, "ignored_settings", return_value=["one thing"]
        ), patch.object(server, "use_spool_directory"), self.assertLogs(
            "mariner.server", level="WARNING"
        ) as logs:
            self._started()
        self.assertTrue(any("one thing" in r.getMessage() for r in logs.records))

    def test_the_web_server_takes_a_bounded_number_of_connections(self) -> None:
        # Each can hold an upload waiting on the drive.
        with patch.object(server, "use_spool_directory"):
            serve = self._started()
        self.assertLessEqual(serve.call_args.kwargs["connection_limit"], 32)

    def test_uploads_wait_on_the_drive_not_in_memory(self) -> None:
        # The web server keeps an upload in a temporary file until it is
        # whole, and on current systems /tmp is memory.
        import tempfile

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.addCleanup(setattr, tempfile, "tempdir", tempfile.tempdir)
        with patch.object(
            server.config, "get_spool_directory", return_value=directory.name
        ):
            server.use_spool_directory()
        self.assertEqual(tempfile.gettempdir(), directory.name)

    def test_a_spool_directory_that_cannot_be_used_is_said_and_passed(self) -> None:
        import tempfile

        before = tempfile.gettempdir()
        self.addCleanup(setattr, tempfile, "tempdir", tempfile.tempdir)
        with patch.object(
            server.config, "get_spool_directory", return_value="/nonexistent/spool"
        ), self.assertLogs("mariner.server", level="WARNING"):
            server.use_spool_directory()
        self.assertEqual(tempfile.gettempdir(), before)

    def test_the_spool_directory_is_set_before_the_web_server_starts(self) -> None:
        order: List[str] = []
        with patch.object(
            server, "use_spool_directory", side_effect=lambda: order.append("spool")
        ):
            serve = self._started()
            serve.assert_called_once()
        self.assertEqual(order, ["spool"])

    def test_without_a_certificate_the_page_is_served_in_the_clear(self) -> None:
        with patch.object(server, "use_spool_directory"):
            serve = self._started()
        settings = serve.call_args.kwargs
        expect(settings["host"]).to_equal("0.0.0.0")
        expect(settings["port"]).to_equal(5050)
        expect(settings.get("tls")).to_equal(None)
        expect(server.flask_app.config["HTTPS_PORT"]).to_equal(None)
        expect(server.flask_app.config["SESSION_COOKIE_SECURE"]).to_equal(False)
        expect(server.flask_app.config["SESSION_COOKIE_NAME"]).to_equal(
            "mariner_session"
        )
        expect(server.early.plain_refusal).to_equal(None)

    def test_with_a_certificate_the_page_is_served_over_https_beside_the_clear(
        self,
    ) -> None:
        self.certificate.return_value = ("/c.pem", "/k.pem")
        with patch.object(server, "use_spool_directory"), patch.object(
            server.tls, "context", return_value="the context"
        ) as context:
            serve = self._started()
        context.assert_called_once_with("/c.pem", "/k.pem")
        settings = serve.call_args.kwargs
        expect(settings["listen"]).to_equal("0.0.0.0:5050 0.0.0.0:5443")
        expect("host" in settings or "port" in settings).to_equal(False)
        expect(settings["tls"]).to_equal("the context")
        expect(settings["tls_port"]).to_equal(5443)
        expect(server.flask_app.config["HTTPS_PORT"]).to_equal(5443)
        expect(server.flask_app.config["SESSION_COOKIE_SECURE"]).to_equal(True)
        expect(server.flask_app.config["SESSION_COOKIE_NAME"]).to_equal(
            "__Host-mariner_session"
        )

    def test_under_https_the_web_server_takes_no_body_for_the_page_in_the_clear(
        self,
    ) -> None:
        self.certificate.return_value = ("/c.pem", "/k.pem")
        with patch.object(server, "use_spool_directory"), patch.object(
            server.tls, "context"
        ):
            self._started()
        refused = server.early.plain_refusal(
            "/api/upload_file", {"Host": "saturn.local:5050"}
        )
        expect(refused["code"]).to_equal("https_required")
        expect("https://saturn.local:5443" in refused["description"]).to_equal(True)
        expect(
            server.early.plain_refusal("/uvtools/upload/x.ctb", {"Host": "saturn"})
        ).to_equal(None)

    def test_an_address_of_the_newer_kind_is_listened_on_in_brackets(self) -> None:
        self.certificate.return_value = ("/c.pem", "/k.pem")
        with patch.object(server, "use_spool_directory"), patch.object(
            server.tls, "context"
        ), patch.object(server.config, "get_http_host", return_value="::"):
            serve = self._started()
        expect(serve.call_args.kwargs["listen"]).to_equal("[::]:5050 [::]:5443")

    def test_one_port_for_both_leaves_the_page_in_the_clear_and_says_so(
        self,
    ) -> None:
        self.certificate.return_value = ("/c.pem", "/k.pem")
        with patch.object(server, "use_spool_directory"), patch.object(
            server.tls, "context"
        ), patch.object(server.config, "get_https_port", return_value=5050):
            with self.assertLogs("mariner.server", level="ERROR"):
                serve = self._started()
        expect(serve.call_args.kwargs.get("tls")).to_equal(None)
        expect(server.flask_app.config["HTTPS_PORT"]).to_equal(None)
