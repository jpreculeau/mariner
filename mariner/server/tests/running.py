"""Run a real server for a test, and fail the test if the server falls."""

import threading
from typing import Any, List
from unittest import TestCase


def run_checked(test: TestCase, server: Any) -> List[BaseException]:
    """Serve with *server* until the end of *test*.

    What its loop raises, other than at being closed when the test ends,
    fails the test: a server that falls closes every connection, which
    looks from a client like the closing a test may be waiting for.
    Returns the list those errors are put in.
    """
    raised: List[BaseException] = []
    state = {"closing": False}

    def run() -> None:
        try:
            server.run()
        except BaseException as error:
            if not state["closing"]:
                raised.append(error)

    def close() -> None:
        state["closing"] = True
        # What still serves a request ends before the server is closed
        # under it.
        server.task_dispatcher.shutdown()
        server.close()
        test.assertEqual(raised, [], "the server fell while the test ran")

    threading.Thread(target=run, daemon=True).start()
    test.addCleanup(close)
    return raised
