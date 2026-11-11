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
            order, ["logging", "cleanup", "cache warm-up", "providers", "serve"]
        )
