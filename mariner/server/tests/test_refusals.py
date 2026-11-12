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

    def test_the_one_to_make_room_is_the_one_written_longest_ago(self) -> None:
        # Not the one first seen: that one may have been written just now.
        for kind in ("a", "b", "c", "d"):
            self.said.unwritten(kind)
        self.now += 60
        expect(self.said.unwritten("a")).to_equal(0)
        self.said.unwritten("e")
        # "b" made room; "a", written last, is still kept quiet.
        expect(self.said.unwritten("a")).to_equal(None)
        expect(self.said.unwritten("b")).to_equal(0)

    def test_another_client_or_reason_is_another_kind(self) -> None:
        self.said.unwritten(("192.168.1.9", "a"))
        expect(self.said.unwritten(("192.168.1.10", "a"))).to_equal(0)
        expect(self.said.unwritten(("192.168.1.9", "b"))).to_equal(0)

    def test_only_so_many_kinds_are_remembered(self) -> None:
        # A client can give itself any number of addresses.
        for number in range(49):
            self.said.unwritten((str(number), "a"))
        expect(len(self.said)).to_equal(4)
        # The oldest make room: the latest are still known, with their count.
        for latest in ("45", "46", "47", "48"):
            expect(self.said.unwritten((latest, "a"))).to_equal(None)
        self.now += 60
        expect(self.said.unwritten(("48", "a"))).to_equal(1)


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
            refusals.log(
                "Web",
                "192.168.1.99",
                "host_not_allowed",
                headers,
                "POST",
                "/api/delete_file",
            )
        message = logs.records[0].getMessage()
        for told in (
            "Web",
            "192.168.1.99",
            "host_not_allowed",
            "POST",
            "/api/delete_file",
            "evil.example",
            "o.example",
            "http://r.example",
            "cross-site",
            "Agent/1.0",
        ):
            expect(told in message).to_equal(True)
        expect("\n" in message).to_equal(False)

    def test_of_the_page_a_request_came_from_only_the_site_is_kept(self) -> None:
        # The rest is where someone was on another site.
        headers = {"Referer": "https://mail.example/inbox/letter?to=someone"}
        with self.assertLogs("mariner.server.refusals", level="WARNING") as logs:
            refusals.log("Web", "192.168.1.99", "x", headers)
        message = logs.records[0].getMessage()
        expect("https://mail.example" in message).to_equal(True)
        expect("inbox" in message or "someone" in message).to_equal(False)
        # One that cannot be read is said to be so.
        refusals.said.clear()
        with self.assertLogs("mariner.server.refusals", level="WARNING") as logs:
            refusals.log("Web", "192.168.1.99", "x", {"Referer": "http://[x/a"})
        expect("unreadable" in logs.records[0].getMessage()).to_equal(True)

    def test_the_method_is_cut_like_the_rest(self) -> None:
        with self.assertLogs("mariner.server.refusals", level="WARNING") as logs:
            refusals.log("Web", "192.168.1.99", "x", {}, "M" * 60000, "/api/x")
        expect(len(logs.records[0].getMessage()) < 700).to_equal(True)

    def test_a_name_and_password_in_the_page_address_are_left_out(self) -> None:
        headers = {"Referer": "http://user:secretpw@evil.example:8080/page"}
        with self.assertLogs("mariner.server.refusals", level="WARNING") as logs:
            refusals.log("Web", "192.168.1.99", "x", headers)
        message = logs.records[0].getMessage()
        expect("http://evil.example:8080" in message).to_equal(True)
        expect("secretpw" in message or "user" in message).to_equal(False)

    def test_what_only_browsers_and_players_say_is_named(self) -> None:
        # Else a script refused for it looks like any other in the log.
        headers = {"User-Agent": "curl/8.5.0", "range": "bytes=0-", "Accept": "*/*"}
        with self.assertLogs("mariner.server.refusals", level="WARNING") as logs:
            refusals.log("Web", "192.168.1.99", "browser_not_served", headers)
        message = logs.records[0].getMessage()
        expect("also sent: range" in message.lower()).to_equal(True)
        expect("accept" in message.lower().replace("also sent", "")).to_equal(False)

    def test_many_at_once_are_counted_right(self) -> None:
        import sys
        import threading

        # Threads take turns so often that, unguarded, the count goes wrong.
        self.addCleanup(sys.setswitchinterval, sys.getswitchinterval())
        sys.setswitchinterval(1e-6)
        said = refusals.Sparingly()
        written = []

        def knock() -> None:
            for _ in range(2000):
                if said.unwritten("kind") is not None:
                    written.append(1)

        threads = [threading.Thread(target=knock) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        expect(len(written)).to_equal(1)
        with patch.object(refusals.time, "monotonic", return_value=10**9):
            expect(said.unwritten("kind")).to_equal(8 * 2000 - 1)

    def test_no_room_says_how_much_there_is_and_how_much_is_kept(self) -> None:
        body = refusals.no_room_body(66 * 1024 * 1024, 64 * 1024 * 1024)
        expect("66 MB are free" in body["description"]).to_equal(True)
        expect("64 MB" in body["description"]).to_equal(True)
        expect("MB" in refusals.no_room_body(None)["description"]).to_equal(False)
        refusals.said.clear()
        with self.assertLogs("mariner.server.refusals", level="WARNING") as logs:
            refusals.log_no_room(
                3_000_000, "192.168.1.99", 66 * 1024 * 1024, "/var/tmp"
            )
        message = logs.records[0].getMessage()
        for told in ("3000000", "192.168.1.99", "66 MB", "/var/tmp"):
            expect(told in message).to_equal(True)

    def test_what_the_client_said_is_cut(self) -> None:
        for name in ("Host", "Origin", "Referer", "Sec-Fetch-Site", "User-Agent"):
            refusals.said.clear()
            with self.assertLogs("mariner.server.refusals", level="WARNING") as logs:
                refusals.log("Web", "192.168.1.99", "x", {name: "y" * 5000})
            expect(len(logs.records[0].getMessage()) < 700).to_equal(True)

    def test_what_was_cut_still_reads_as_one_quoted_value(self) -> None:
        # Its end mark is not cut away with it, and marks inside it cannot
        # pass for the end: what follows would read as other fields.
        agent = "x', Origin 'http://192.168.1.20" + "y" * 500
        with self.assertLogs("mariner.server.refusals", level="WARNING") as logs:
            refusals.log("Web", "192.168.1.99", "x", {"User-Agent": agent})
        message = logs.records[0].getMessage()
        expect("User-Agent \"x', Origin 'http://192.168.1.20" in message).to_equal(True)
        expect('y", also sent' in message).to_equal(True)

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
