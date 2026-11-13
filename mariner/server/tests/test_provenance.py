"""Where a request comes from: the local network, or the Internet."""

from unittest import TestCase
from unittest.mock import patch

from pyexpect import expect

from mariner import config
from mariner.server import provenance


class LocalOrNotTest(TestCase):
    def test_the_addresses_of_a_home_network_are_local(self) -> None:
        for address in (
            "127.0.0.1",
            "192.168.1.20",
            "10.0.0.7",
            "172.16.5.4",
            "172.31.255.254",
            "169.254.10.10",
            "::1",
            "fe80::1",
            "fe80::1%eth0",
            "fd12:3456:789a::1",
            # The same computer, written the other way.
            "::ffff:192.168.1.20",
        ):
            expect((address, provenance.is_local(address))).to_equal((address, True))

    def test_the_rest_is_the_internet(self) -> None:
        for address in (
            "203.0.113.5",
            "8.8.8.8",
            "172.32.0.1",
            "100.128.0.1",
            # Shared by a provider among its customers: a neighbour's, as
            # much as a VPN's. Local only where the owner says so.
            "100.64.0.3",
            "2001:db8::1",
            "::ffff:203.0.113.5",
        ):
            expect((address, provenance.is_local(address))).to_equal((address, False))

    def test_what_is_no_address_is_not_taken_for_local(self) -> None:
        # In doubt, the stricter rules.
        for address in (None, "", "unix", "192.168.1", "192.168.1.20, 10.0.0.1"):
            expect(provenance.is_local(address)).to_equal(False)

    def test_networks_can_be_added_to_the_local_ones(self) -> None:
        with patch.object(
            config, "get_local_networks", return_value=["203.0.113.0/24"]
        ):
            expect(provenance.is_local("203.0.113.5")).to_equal(True)
            expect(provenance.is_local("203.0.114.5")).to_equal(False)

    def test_a_local_address_can_be_said_not_to_be(self) -> None:
        # A router that passes connections on under its own address:
        # everything from the Internet would look local.
        with patch.object(config, "get_not_local", return_value=["192.168.1.1"]):
            expect(provenance.is_local("192.168.1.1")).to_equal(False)
            expect(provenance.is_local("192.168.1.2")).to_equal(True)

    def test_an_address_of_this_computer_s_own_network_is_local(self) -> None:
        # Over IPv6 the computers of a home have addresses of the Internet,
        # all of them under the one prefix the provider gave.
        with patch.object(
            provenance, "_own_ipv6", return_value=["2a01:e0a:12:3400::50"]
        ):
            expect(provenance.is_local("2a01:e0a:12:3400:abcd::7")).to_equal(True)
            expect(provenance.is_local("2a01:e0a:12:3401::7")).to_equal(False)

    def test_which_can_still_be_said_not_to_be(self) -> None:
        with patch.object(
            provenance, "_own_ipv6", return_value=["2a01:e0a:12:3400::50"]
        ), patch.object(config, "get_not_local", return_value=["2a01:e0a:12:3400::1"]):
            expect(provenance.is_local("2a01:e0a:12:3400::1")).to_equal(False)

    def test_a_setting_that_is_no_network_changes_nothing(self) -> None:
        with patch.object(
            config, "get_local_networks", return_value=["everything", "0.0.0.0/0x"]
        ):
            expect(provenance.is_local("203.0.113.5")).to_equal(False)
            expect(provenance.is_local("192.168.1.2")).to_equal(True)


class RefusalTest(TestCase):
    def test_slicers_are_answered_on_the_local_network_alone(self) -> None:
        # They give no password, and never will.
        refused = provenance.refusal("/uvtools/files", "203.0.113.5")
        assert refused is not None
        expect(refused["code"]).to_equal("local_network_only")
        expect(provenance.refusal("/uvtools/files", "192.168.1.20")).to_equal(None)

    def test_the_computer_is_stopped_from_the_local_network_alone(self) -> None:
        for path in ("/api/host/shutdown", "/api/host/reboot"):
            refused = provenance.refusal(path, "203.0.113.5")
            assert refused is not None
            expect(refused["code"]).to_equal("local_network_only")
            expect(provenance.refusal(path, "10.0.0.7")).to_equal(None)

    def test_unless_the_owner_allows_it(self) -> None:
        with patch.object(config, "get_host_commands_from_internet", return_value=True):
            expect(provenance.refusal("/api/host/reboot", "203.0.113.5")).to_equal(None)
            # Never the slicers.
            expect(
                provenance.refusal("/uvtools/files", "203.0.113.5") is None
            ).to_equal(False)

    def test_the_page_itself_is_answered_from_anywhere(self) -> None:
        for path in ("/", "/api/print_status", "/api/auth/login", "/files"):
            expect(provenance.refusal(path, "203.0.113.5")).to_equal(None)
