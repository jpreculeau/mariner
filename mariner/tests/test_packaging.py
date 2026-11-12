import configparser
import pathlib
from unittest import TestCase

from pyexpect import expect

ROOT = pathlib.Path(__file__).parent.parent.parent
UNITS = [
    ROOT / "dist" / "debian" / "mariner3d.service",
    ROOT / "dist" / "rpm" / "mariner3d.service",
]


def _service(unit: pathlib.Path) -> configparser.SectionProxy:
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str  # type: ignore[assignment,method-assign]
    parser.read(unit)
    return parser["Service"]


class ServiceUnitTest(TestCase):
    def test_both_packages_ship_the_same_service(self) -> None:
        expect(UNITS[0].read_text()).to_equal(UNITS[1].read_text())

    def test_it_is_given_folders_of_its_own_to_keep_things_in(self) -> None:
        # The account has no home. Without them the key of sessions and
        # the password would not outlast a restart of the computer, and
        # the cache would be back in /tmp.
        service = _service(UNITS[0])
        expect(service["StateDirectory"]).to_equal("mariner")
        expect(service["StateDirectoryMode"]).to_equal("0700")
        expect(service["CacheDirectory"]).to_equal("mariner")
        expect(service["CacheDirectoryMode"]).to_equal("0700")

    def test_it_is_started_again_when_it_stops(self) -> None:
        # Also how it is restarted from the page, after a change of
        # settings: it stops, and is started again.
        service = _service(UNITS[0])
        expect(service["Restart"]).to_equal("always")

    def test_what_it_writes_to_the_log_has_a_ceiling(self) -> None:
        # Any device of the network can have lines written.
        service = _service(UNITS[0])
        expect(service["LogRateLimitIntervalSec"]).to_equal("30s")
        expect(int(service["LogRateLimitBurst"]) <= 1000).to_equal(True)

    def test_it_is_kept_from_what_it_has_no_use_for(self) -> None:
        service = _service(UNITS[0])
        for setting in (
            "NoNewPrivileges",
            "PrivateTmp",
            "ProtectKernelTunables",
            "ProtectKernelModules",
            "ProtectControlGroups",
            "RestrictSUIDSGID",
            "LockPersonality",
            "RestrictRealtime",
        ):
            expect(service[setting]).to_equal("true")
        expect(service["ProtectSystem"]).to_equal("full")
        expect(service["ProtectHome"]).to_equal("read-only")

    def test_it_can_still_reach_the_printer_and_the_network(self) -> None:
        # Nothing here may hide devices or close the network: the serial
        # port and the slicers' ports are what it is for.
        service = _service(UNITS[0])
        for setting in ("PrivateDevices", "PrivateNetwork", "DevicePolicy"):
            expect(setting in service).to_equal(False)
        expect(service["User"]).to_equal("mariner")


class WorkflowsTest(TestCase):
    def test_every_action_is_named_by_its_commit(self) -> None:
        # A tag can be moved to other code by whoever holds the action's
        # repository; a commit cannot. The workflows build what is
        # installed on printers, and hold the keys that publish it.
        import re

        found = 0
        for workflow in sorted((ROOT / ".github" / "workflows").glob("*.y*ml")):
            for line in workflow.read_text().splitlines():
                used = re.search(r"\buses:\s*(\S+)", line)
                if not used or used.group(1).startswith("./"):
                    continue
                found += 1
                expect(
                    bool(re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", used.group(1)))
                ).to_equal(True)
                # The version it stands for, for whoever reads or updates it.
                expect(bool(re.search(r"#\s*v\d", line))).to_equal(True)
        expect(found > 10).to_equal(True)
