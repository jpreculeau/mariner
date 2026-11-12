import io
import logging
from unittest import TestCase

from pyexpect import expect

from mariner.server import keep_requests_on_one_line


class RequestLogTest(TestCase):
    def setUp(self) -> None:
        self.stream = io.StringIO()
        self.handler = logging.StreamHandler(self.stream)
        root = logging.getLogger()
        root.addHandler(self.handler)
        self.addCleanup(root.removeHandler, self.handler)
        keep_requests_on_one_line()

    def test_a_request_path_cannot_start_a_log_line(self) -> None:
        # The web server logs the path of a request it could not finish,
        # as the client sent it.
        path = "/api/x\nWARNING:forged\r\u2028more\x85end"
        logging.getLogger("waitress").warning(
            "Client disconnected while serving %s", path
        )
        written = self.stream.getvalue()
        expect(written.splitlines()).to_equal([written.rstrip("\n")])
        expect("\\nWARNING:forged\\r\\u2028more\\x85end" in written).to_equal(True)

    def test_the_loggers_below_are_covered_too(self) -> None:
        logging.getLogger("waitress.queue").warning("Task queue depth is %s\nx", 3)
        expect(len(self.stream.getvalue().splitlines())).to_equal(1)

    def test_an_ordinary_line_is_left_as_it_is(self) -> None:
        logging.getLogger("waitress").warning("Serving on %s", "http://0.0.0.0:5050")
        expect(self.stream.getvalue()).to_equal("Serving on http://0.0.0.0:5050\n")

    def test_installing_it_twice_escapes_once(self) -> None:
        keep_requests_on_one_line()
        expect(len(self.handler.filters)).to_equal(1)
        logging.getLogger("waitress").warning("a\nb")
        expect(self.stream.getvalue()).to_equal("a\\nb\n")

    def test_mariner_own_lines_are_not_touched(self) -> None:
        logging.getLogger("mariner.somewhere").warning("two\nlines")
        expect(self.stream.getvalue()).to_equal("two\nlines\n")
