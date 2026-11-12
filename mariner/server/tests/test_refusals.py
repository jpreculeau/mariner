from unittest import TestCase
from unittest.mock import patch

from pyexpect import expect

from mariner.server import refusals


class SparinglyTest(TestCase):
    def setUp(self) -> None:
        self.said = refusals.Sparingly(seconds=60.0, remembered=4)
        self.now = 1000.0
        patcher = patch.object(refusals.time, "monotonic", lambda: self.now)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_first_of_its_kind_is_written(self) -> None:
        expect(self.said.unwritten(("192.168.1.9", "a"))).to_equal(0)

    def test_the_same_again_is_kept_quiet_for_a_while(self) -> None:
        key = ("192.168.1.9", "a")
        self.said.unwritten(key)
        for _ in range(5):
            self.now += 10
            expect(self.said.unwritten(key)).to_equal(None)
        # Then written, with how many were not.
        self.now += 10
        expect(self.said.unwritten(key)).to_equal(5)
        expect(self.said.unwritten(key)).to_equal(None)

    def test_another_client_or_reason_is_another_kind(self) -> None:
        self.said.unwritten(("192.168.1.9", "a"))
        expect(self.said.unwritten(("192.168.1.10", "a"))).to_equal(0)
        expect(self.said.unwritten(("192.168.1.9", "b"))).to_equal(0)

    def test_only_so_many_kinds_are_remembered(self) -> None:
        # A client can give itself any number of addresses.
        for number in range(50):
            self.said.unwritten((str(number), "a"))
        expect(len(self.said) <= 4).to_equal(True)


class LogTest(TestCase):
    def setUp(self) -> None:
        refusals.said.clear()

    def test_a_refusal_is_written_with_what_the_client_said(self) -> None:
        headers = {
            "Host": "evil.example",
            "Origin": "http://o.example\nX",
            "Referer": "http://r.example/page",
            "Sec-Fetch-Site": "cross-site",
            "User-Agent": "Agent/1.0",
        }
        with self.assertLogs("mariner.server.refusals", level="WARNING") as logs:
            refusals.log("Web", "192.168.1.99", "host_not_allowed", headers)
        message = logs.records[0].getMessage()
        for told in (
            "Web",
            "192.168.1.99",
            "host_not_allowed",
            "evil.example",
            "o.example",
            "r.example/page",
            "cross-site",
            "Agent/1.0",
        ):
            expect(told in message).to_equal(True)
        expect("\n" in message).to_equal(False)

    def test_what_the_client_said_is_cut(self) -> None:
        for name in ("Host", "Origin", "Referer", "Sec-Fetch-Site", "User-Agent"):
            refusals.said.clear()
            with self.assertLogs("mariner.server.refusals", level="WARNING") as logs:
                refusals.log("Web", "192.168.1.99", "x", {name: "y" * 5000})
            expect(len(logs.records[0].getMessage()) < 700).to_equal(True)

    def test_the_same_refusal_is_written_once_a_minute(self) -> None:
        with self.assertLogs("mariner.server.refusals", level="WARNING") as logs:
            for _ in range(50):
                refusals.log("Web", "192.168.1.99", "x", {})
            # Another interface, client or reason is another matter.
            refusals.log("SDCP", "192.168.1.99", "x", {})
            refusals.log("Web", "192.168.1.98", "x", {})
            refusals.log("Web", "192.168.1.99", "y", {})
        expect(len(logs.records)).to_equal(4)
        with patch.object(refusals.time, "monotonic", return_value=10**9):
            with self.assertLogs("mariner.server.refusals", level="WARNING") as logs:
                refusals.log("Web", "192.168.1.99", "x", {})
        expect("49" in logs.records[0].getMessage()).to_equal(True)
