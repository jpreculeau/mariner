from unittest import TestCase
from unittest.mock import patch

from flask import Flask
from flask_wtf.csrf import CSRFProtect
from pyexpect import expect

from mariner.server import providers


class ProviderSwitchTest(TestCase):
    def _registered(self) -> list:
        app = Flask(__name__)
        providers.register_providers(app, CSRFProtect(app))
        return sorted(app.blueprints)

    def test_uvtools_is_served_unless_switched_off(self) -> None:
        expect(self._registered()).to_equal(["provider_uvtools"])
        with patch("mariner.config.get_uvtools_enabled", return_value=False):
            expect(self._registered()).to_equal([])

    def test_its_addresses_stay_its_own_when_it_is_off(self) -> None:
        # They answer 404 then, not the page of the web interface.
        with patch("mariner.config.get_uvtools_enabled", return_value=False):
            expect(providers.get_provider_prefixes()).to_equal(["uvtools"])

    def test_a_provider_switched_off_is_not_started(self) -> None:
        with patch("mariner.config.get_uvtools_enabled", return_value=False), patch(
            "mariner.config.get_sdcp_enabled", return_value=False
        ), patch.object(providers.UVToolsProvider, "start") as uvtools, patch.object(
            providers.SDCPProvider, "start"
        ) as sdcp:
            providers.start_providers()
        uvtools.assert_not_called()
        sdcp.assert_not_called()
