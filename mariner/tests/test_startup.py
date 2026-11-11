from typing import List
from unittest import TestCase
from unittest.mock import patch

from mariner import server


class StartupTest(TestCase):
    def test_unfinished_transfers_are_cleared_before_anything_is_served(self) -> None:
        order: List[str] = []

        def record(name: str):  # type: ignore[no-untyped-def]
            return lambda *args, **kwargs: order.append(name)

        with patch.object(server, "CacheBootstrapper"), patch.object(
            server.logging, "basicConfig", side_effect=record("logging")
        ), patch.object(server.logging.getLogger(), "handlers", []), patch.object(
            server, "remove_stale_scratch_files", side_effect=record("cleanup")
        ), patch.object(
            server, "start_providers", side_effect=record("providers")
        ), patch.object(
            server, "serve", side_effect=record("serve")
        ):
            server.main()

        # After logging is set up, so the cleanup can report what it removed,
        # and before anything that could start a new transfer.
        self.assertEqual(order, ["logging", "cleanup", "providers", "serve"])
