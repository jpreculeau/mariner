from typing import Dict
from unittest import TestCase
from unittest.mock import patch

from pyexpect import expect

from mariner.server import origin


def _refusal(headers: Dict[str, str], host: str = "192.168.1.20:5050") -> object:
    return origin.refusal_for({"Host": host, **headers})


class CrossSiteTest(TestCase):
    def test_a_request_from_the_page_itself_is_let_through(self) -> None:
        expect(_refusal({"Sec-Fetch-Site": "same-origin"})).to_equal(None)
        expect(_refusal({"Sec-Fetch-Site": " Same-Origin "})).to_equal(None)

    def test_an_address_typed_or_bookmarked_is_let_through(self) -> None:
        expect(_refusal({"Sec-Fetch-Site": "none"})).to_equal(None)

    def test_a_request_from_another_site_is_refused(self) -> None:
        # A page anywhere on the web, open in a browser on the same network,
        # could otherwise start, stop or delete: nothing asks who is asking.
        for site in ("cross-site", "same-site", "CROSS-SITE", "anything-else"):
            refusal = _refusal({"Sec-Fetch-Site": site})
            expect(refusal).not_to_equal(None)
            expect(none_throws(refusal).code).to_equal("cross_site_request")

    def test_a_browser_that_only_says_where_the_page_is_from(self) -> None:
        # Older ones, which give the origin of the page with what it sends.
        expect(_refusal({"Origin": "http://192.168.1.20:5050"})).to_equal(None)
        expect(_refusal({"Origin": "HTTP://192.168.1.20:5050"})).to_equal(None)
        for elsewhere in (
            "http://evil.example",
            "http://192.168.1.20:8080",
            "http://192.168.1.20",
            "null",
            "",
        ):
            refusal = _refusal({"Origin": elsewhere})
            expect(none_throws(refusal).code).to_equal("cross_site_request")

    def test_the_default_port_may_be_left_out_on_either_side(self) -> None:
        expect(
            _refusal({"Origin": "http://mariner.local"}, "mariner.local:80")
        ).to_equal(None)
        expect(
            _refusal({"Origin": "http://mariner.local:80"}, "mariner.local")
        ).to_equal(None)
        expect(
            _refusal({"Origin": "https://mariner.local"}, "mariner.local:443")
        ).to_equal(None)

    def test_what_the_browser_says_of_the_site_counts_before_the_origin(self) -> None:
        # Behind the development server the two differ in port and the
        # request is still the page's own.
        headers = {"Sec-Fetch-Site": "same-origin", "Origin": "http://localhost:3000"}
        expect(_refusal(headers, "localhost:5050")).to_equal(None)

    def test_a_program_that_is_not_a_browser_is_let_through(self) -> None:
        # Slicers and scripts send neither.
        expect(_refusal({})).to_equal(None)


class HostTest(TestCase):
    def test_addresses_and_names_of_a_local_network_are_let_through(self) -> None:
        for host in (
            "192.168.1.20:5050",
            "192.168.1.20",
            "10.0.0.7:5050",
            "[fe80::1]:5050",
            "[::1]",
            "localhost:5050",
            "mariner:5050",
            "mariner.local:5050",
            "MARINER.LOCAL",
            "printer.lan",
            "printer.home.arpa:5050",
            "printer.internal",
            "mariner.local.:5050",
        ):
            expect(_refusal({}, host)).to_equal(None)

    def test_a_name_from_the_wider_web_is_refused(self) -> None:
        # A site can have its own name answer with the address of the
        # printer; the browser then takes its pages and Mariner for one
        # site. The name it asks for gives it away.
        for host in ("evil.example", "evil.example:5050", "local.evil.example", "a.b"):
            refusal = _refusal({"Sec-Fetch-Site": "same-origin"}, host)
            expect(none_throws(refusal).code).to_equal("host_not_allowed")
            expect("allowed_hosts" in none_throws(refusal).description).to_equal(True)

    def test_the_name_of_the_machine_is_let_through(self) -> None:
        with patch.object(origin.socket, "gethostname", return_value="Pi.Example.org"):
            expect(_refusal({}, "pi.example.org:5050")).to_equal(None)

    def test_names_can_be_added(self) -> None:
        with patch.object(
            origin.config,
            "get_http_allowed_hosts",
            return_value=["Printer.Example.org"],
        ):
            expect(_refusal({}, "printer.example.org:5050")).to_equal(None)
            expect(_refusal({}, "other.example.org")).not_to_equal(None)

    def test_any_name_can_be_allowed(self) -> None:
        with patch.object(origin.config, "get_http_allowed_hosts", return_value=["*"]):
            expect(_refusal({}, "evil.example")).to_equal(None)

    def test_no_name_at_all_is_let_through(self) -> None:
        # Only a program written for the purpose leaves it out.
        expect(origin.refusal_for({})).to_equal(None)

    def test_a_name_that_is_not_one_is_refused(self) -> None:
        for host in (
            "evil.example\nX: y",
            "a b",
            "exa mple.local",
            "[::1",
            ":5050",
            "mariner.local:80a",
            "[::1]x",
        ):
            expect(_refusal({}, host)).not_to_equal(None)

    def test_the_name_comes_before_the_site(self) -> None:
        refusal = _refusal({"Sec-Fetch-Site": "cross-site"}, "evil.example")
        expect(none_throws(refusal).code).to_equal("host_not_allowed")


def none_throws(value: object) -> origin.Refusal:
    assert isinstance(value, origin.Refusal)
    return value
