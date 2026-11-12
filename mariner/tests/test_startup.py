from typing import Any, Callable, List
from unittest import TestCase
from unittest.mock import patch

from mariner import server


class StartupTest(TestCase):
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
            server, "serve"
        ) as serve:
            server.main()
        return serve

    def test_the_web_server_takes_uploads_up_to_the_limit(self) -> None:
        # Left to itself it refuses anything over a gigabyte.
        with patch.object(
            server.config, "get_max_upload_bytes", return_value=3 * 1024**3
        ), patch.object(server, "use_spool_directory"):
            serve = self._started()
        self.assertEqual(
            serve.call_args.kwargs["max_request_body_size"], 3 * 1024**3 + 1024**2
        )

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
