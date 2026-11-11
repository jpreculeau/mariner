import hashlib
import json
import os
import pathlib
import re
import shutil
from contextlib import contextmanager
from typing import Any, Iterator, List, cast
from unittest import IsolatedAsyncioTestCase
from unittest.mock import Mock, patch

from aiohttp.client_exceptions import ClientConnectionResetError
from pyexpect import expect
from pyfakefs.fake_filesystem import FakeFilesystem
from pyfakefs.fake_filesystem_unittest import TestCase

from mariner import config
from mariner.config import _get_config
from mariner.exceptions import UnexpectedPrinterResponse
from mariner.printer import ChiTuPrinter, PrinterState, PrintStatus
from mariner.server.providers.sdcp import constants, identity, messages
from mariner.server.providers.sdcp.bridge import PrinterBridge, strip_storage_prefix
from mariner.server.providers.sdcp.service import SDCPService
from mariner.server import printer_access
from mariner.server.printer_access import FileInUse
from mariner.server.providers.sdcp.uploads import UploadManager


def _never_in_use(path: pathlib.Path) -> bool:
    return False


@contextmanager
def _no_guard(path: pathlib.Path) -> Iterator[None]:
    yield


class StripStoragePrefixTest(TestCase):
    def test_strips_local_prefix(self) -> None:
        expect(strip_storage_prefix("/local/foo.ctb")).to_equal("foo.ctb")

    def test_strips_usb_prefix(self) -> None:
        expect(strip_storage_prefix("/usb/nested/foo.ctb")).to_equal("nested/foo.ctb")

    def test_leaves_bare_name_alone(self) -> None:
        expect(strip_storage_prefix("foo.ctb")).to_equal("foo.ctb")

    def test_strips_leading_slash(self) -> None:
        expect(strip_storage_prefix("/foo.ctb")).to_equal("foo.ctb")

    def test_handles_empty(self) -> None:
        expect(strip_storage_prefix("")).to_equal("")


class MessageEnvelopeTest(TestCase):
    def setUp(self) -> None:
        _get_config.cache_clear()
        identity._machine_seed.cache_clear()

    def test_response_envelope_shape(self) -> None:
        message = messages.response(constants.Cmd.START_PRINT, {"Ack": 0}, "req-1")
        expect(message["Topic"]).to_equal(
            f"sdcp/response/{identity.get_mainboard_id()}"
        )
        expect(message["Data"]["Cmd"]).to_equal(128)
        expect(message["Data"]["Data"]).to_equal({"Ack": 0})
        expect(message["Data"]["RequestID"]).to_equal("req-1")
        expect(message["Data"]["MainboardID"]).to_equal(identity.get_mainboard_id())

    def test_status_envelope_has_no_id_field(self) -> None:
        message = messages.status({"CurrentStatus": [0]})
        expect("Id" in message).to_equal(False)
        expect(message["Topic"]).to_equal(f"sdcp/status/{identity.get_mainboard_id()}")
        expect(message["Status"]).to_equal({"CurrentStatus": [0]})

    def test_attributes_envelope_has_no_id_field(self) -> None:
        message = messages.attributes({"Name": "Mariner"})
        expect("Id" in message).to_equal(False)
        expect(message["Topic"]).to_equal(
            f"sdcp/attributes/{identity.get_mainboard_id()}"
        )

    def test_error_envelope_nests_under_data(self) -> None:
        message = messages.error(int(constants.ErrorCode.MD5_FAILED))
        expect(message["Data"]["Data"]["ErrorCode"]).to_equal(1)
        expect(message["Topic"]).to_equal(f"sdcp/error/{identity.get_mainboard_id()}")

    def test_discovery_response_shape(self) -> None:
        message = messages.discovery_response(
            name="My Printer",
            machine_name="Mars 3",
            brand_name="CBD",
            mainboard_ip="192.168.1.5",
            firmware_version="V1.0.0",
            protocol_version="V3.0.0",
        )
        expect(message["Data"]["Name"]).to_equal("My Printer")
        expect(message["Data"]["MainboardIP"]).to_equal("192.168.1.5")
        expect(message["Data"]["ProtocolVersion"]).to_equal("V3.0.0")
        expect(message["Data"]["MainboardID"]).to_equal(identity.get_mainboard_id())
        # Discovery replies must be a single UDP datagram of valid JSON.
        expect(json.loads(json.dumps(message))).to_equal(message)

    def test_discovery_omits_internal_machine_name_by_default(self) -> None:
        message = messages.discovery_response(
            name="My Printer",
            machine_name="ELEGOO Mars 3",
            brand_name="ELEGOO",
            mainboard_ip="192.168.1.5",
            firmware_version="V1.0.0",
            protocol_version="V3.0.0",
        )
        expect("InternalMachineName" in message["Data"]).to_equal(False)

    def test_discovery_includes_internal_machine_name_when_set(self) -> None:
        message = messages.discovery_response(
            name="My Printer",
            machine_name="ELEGOO Mars 3",
            brand_name="ELEGOO",
            mainboard_ip="192.168.1.5",
            firmware_version="V1.0.0",
            protocol_version="V3.0.0",
            internal_machine_name="Mars 3",
        )
        expect(message["Data"]["InternalMachineName"]).to_equal("Mars 3")
        expect(message["Data"]["BrandName"]).to_equal("ELEGOO")

    def test_client_picture_key_resolves_on_both_lookup_paths(self) -> None:
        """ChituManager derives its image key two different ways.

        Discovery uses BrandName + (InternalMachineName or MachineName);
        attributes uses (InternalMachineName or MachineName) alone. Both must
        normalise to the same key or the printer falls back to a generic
        picture.
        """

        def normalise(value: str) -> str:
            return re.sub(r"\s*", "", value).lower()

        brand = "ELEGOO"
        machine_name = "ELEGOO Mars 3"
        internal = "Mars 3"

        discovery_key = normalise(brand + internal)
        # Attributes deliberately carry no InternalMachineName.
        attributes_key = normalise(machine_name)

        expect(discovery_key).to_equal("elegoomars3")
        expect(attributes_key).to_equal("elegoomars3")

    def test_upload_success_payload(self) -> None:
        expect(messages.upload_success()).to_equal(
            {
                "code": "000000",
                "messages": None,
                "data": {},
                "success": True,
            }
        )

    def test_upload_failure_payload(self) -> None:
        payload = messages.upload_failure(constants.UploadError.OFFSET_MISMATCH)
        expect(payload["success"]).to_equal(False)
        expect(payload["code"]).to_equal("111111")
        expect(payload["messages"][0]["message"]).to_equal(-2)


class SDCPBridgeTest(TestCase):
    ctb_file_contents: bytes
    fs: FakeFilesystem
    printer_mock: Any
    printer_patcher: Any

    def setUp(self) -> None:
        path = (
            pathlib.Path(__file__).parent.parent.parent.parent.absolute()
            / "file_formats"
            / "tests"
            / "stairs.ctb"
        )
        with open(path, "rb") as f:
            self.ctb_file_contents = f.read()

        _get_config.cache_clear()
        self.setUpPyfakefs(additional_skip_names=["importlib.metadata"])
        self.fs.create_file(
            "/mnt/usb_share/foobar.ctb", contents=self.ctb_file_contents
        )

        self.printer_mock = Mock(spec=ChiTuPrinter)
        printer_access.forget_status()
        self.printer_patcher = patch("mariner.server.printer_access.ChiTuPrinter")
        constructor = self.printer_patcher.start()
        constructor.return_value = self.printer_mock
        self.printer_mock.__enter__ = Mock(return_value=self.printer_mock)
        self.printer_mock.__exit__ = Mock(return_value=None)
        # An idle printer with nothing selected, unless a test says otherwise.
        self.printer_mock.get_print_status.return_value = PrintStatus(
            state=PrinterState.IDLE, counters_seen=True
        )
        self.printer_mock.get_selected_file.return_value = ""

        self.bridge = PrinterBridge()

    def tearDown(self) -> None:
        self.printer_patcher.stop()

    def test_status_while_idle(self) -> None:
        self.printer_mock.get_selected_file.return_value = ""
        self.printer_mock.get_print_status.return_value = PrintStatus(
            state=PrinterState.IDLE, counters_seen=True
        )
        status = self.bridge.snapshot_status()
        expect(status["CurrentStatus"]).to_equal([int(constants.MachineStatus.IDLE)])
        expect(status["PrintInfo"]["Status"]).to_equal(int(constants.PrintStatus.IDLE))

    def test_status_while_printing_reports_layers(self) -> None:
        self.printer_mock.get_selected_file.return_value = "foobar.ctb"
        self.printer_mock.get_print_status.return_value = PrintStatus(
            state=PrinterState.PRINTING,
            current_byte=256537,
            total_bytes=832745,
        )
        status = self.bridge.snapshot_status()
        expect(status["CurrentStatus"]).to_equal(
            [int(constants.MachineStatus.PRINTING)]
        )
        expect(status["PrintInfo"]["Status"]).to_equal(
            int(constants.PrintStatus.EXPOSURING)
        )
        expect(status["PrintInfo"]["TotalLayer"]).to_equal(400)
        expect(status["PrintInfo"]["CurrentLayer"]).to_equal(130)
        expect(status["PrintInfo"]["Filename"]).to_equal("foobar.ctb")
        expect(status["PrintInfo"]["TotalTicks"]).to_equal(5621 * 1000)

    def test_status_while_paused(self) -> None:
        self.printer_mock.get_selected_file.return_value = "foobar.ctb"
        self.printer_mock.get_print_status.return_value = PrintStatus(
            state=PrinterState.PAUSED,
            current_byte=256537,
            total_bytes=832745,
        )
        status = self.bridge.snapshot_status()
        expect(status["PrintInfo"]["Status"]).to_equal(
            int(constants.PrintStatus.PAUSED)
        )

    def test_status_reports_file_transfer(self) -> None:
        self.printer_mock.get_selected_file.return_value = ""
        self.printer_mock.get_print_status.return_value = PrintStatus(
            state=PrinterState.IDLE, counters_seen=True
        )
        status = self.bridge.snapshot_status(transferring=True)
        expect(status["CurrentStatus"]).to_equal(
            [int(constants.MachineStatus.FILE_TRANSFERRING)]
        )

    def test_attributes_advertise_supported_types(self) -> None:
        self.printer_mock.get_selected_file.return_value = ""
        self.printer_mock.get_print_status.return_value = PrintStatus(
            state=PrinterState.IDLE, counters_seen=True
        )
        attributes = self.bridge.snapshot_attributes()
        expect("CTB" in attributes["SupportFileType"]).to_equal(True)
        expect(attributes["ProtocolVersion"]).to_equal("V3.0.0")
        expect(attributes["MainboardID"]).to_equal(identity.get_mainboard_id())
        expect("FILE_TRANSFER" in attributes["Capabilities"]).to_equal(True)
        expect("PRINT_CONTROL" in attributes["Capabilities"]).to_equal(True)

    def test_absent_hardware_is_omitted_not_reported_broken(self) -> None:
        # SDCP's 0 means "disconnected", which clients show as a fault, so
        # hardware a Mars 3 does not have must be left out entirely rather
        # than reported as 0.
        devices = self.bridge.snapshot_attributes()["DevicesStatus"]
        expect("XMotorStatus" in devices).to_equal(False)
        expect("RotateMotorStatus" in devices).to_equal(False)

    def test_devices_present_on_every_printer_report_healthy(self) -> None:
        devices = self.bridge.snapshot_attributes()["DevicesStatus"]
        expect(devices["ZMotorStatus"]).to_equal(1)
        expect(devices["LCDStatus"]).to_equal(1)
        expect(devices["TempSensorStatusOfUVLED"]).to_equal(1)
        expect(devices["RelaseFilmState"]).to_equal(1)
        expect(devices["SgStatus"]).to_equal(1)

    def test_optional_hardware_is_reported_when_configured(self) -> None:
        with patch.object(config, "get_sdcp_optional_devices", lambda: ["x_motor"]):
            devices = self.bridge.snapshot_attributes()["DevicesStatus"]
        expect(devices["XMotorStatus"]).to_equal(1)
        # Only what was configured; the rotary axis stays omitted.
        expect("RotateMotorStatus" in devices).to_equal(False)

    def test_both_optional_devices_can_be_enabled(self) -> None:
        with patch.object(
            config,
            "get_sdcp_optional_devices",
            lambda: ["x_motor", "rotate_motor"],
        ):
            devices = self.bridge.snapshot_attributes()["DevicesStatus"]
        expect(devices["XMotorStatus"]).to_equal(1)
        expect(devices["RotateMotorStatus"]).to_equal(1)

    def test_firmware_version_is_read_from_the_printer(self) -> None:
        self.printer_mock.get_firmware_version.return_value = "V4.5.0_1.0_e13_LCDE1"
        attributes = self.bridge.snapshot_attributes()
        expect(attributes["FirmwareVersion"]).to_equal("V4.5.0_1.0_e13_LCDE1")

    def test_firmware_version_is_read_only_once(self) -> None:
        self.printer_mock.get_firmware_version.return_value = "V4.5.0"
        self.bridge.firmware_version()
        self.bridge.firmware_version()
        self.bridge.firmware_version()
        # Serial is contended, and the version cannot change while running.
        expect(self.printer_mock.get_firmware_version.call_count).to_equal(1)

    def test_configured_firmware_version_wins(self) -> None:
        self.printer_mock.get_firmware_version.return_value = "V4.5.0"
        with patch.object(config, "get_sdcp_firmware_version", lambda: "V9.9.9"):
            expect(self.bridge.firmware_version()).to_equal("V9.9.9")
        self.printer_mock.get_firmware_version.assert_not_called()

    def test_firmware_version_falls_back_when_printer_is_unreachable(self) -> None:
        self.printer_mock.get_firmware_version.side_effect = UnexpectedPrinterResponse(
            "garbage"
        )
        expect(self.bridge.firmware_version()).to_equal("V1.0.0")

    def test_geometry_skips_an_unreadable_file(self) -> None:
        # A corrupt upload must not leave the printer advertising 0x0 when a
        # readable file is also present.
        self.fs.create_file("/mnt/usb_share/corrupt.ctb", contents="garbage")
        os.utime("/mnt/usb_share/corrupt.ctb", (2_000_000_000, 2_000_000_000))

        attributes = self.bridge.snapshot_attributes()
        expect(attributes["Resolution"]).to_equal("1440x2560")
        expect(attributes["XYZsize"]).to_equal("68.04x120.96x150")

    def test_geometry_falls_back_when_nothing_is_readable(self) -> None:
        os.remove("/mnt/usb_share/foobar.ctb")
        self.fs.create_file("/mnt/usb_share/corrupt.ctb", contents="garbage")

        attributes = self.bridge.snapshot_attributes()
        expect(attributes["Resolution"]).to_equal("0x0")
        expect(attributes["XYZsize"]).to_equal("0x0x0")

    def test_configured_geometry_wins_over_derivation(self) -> None:
        with patch.object(config, "get_sdcp_resolution", lambda: "4098x2560"):
            with patch.object(config, "get_sdcp_xyz_size", lambda: "143.43x89.6x175"):
                attributes = self.bridge.snapshot_attributes()
        expect(attributes["Resolution"]).to_equal("4098x2560")
        expect(attributes["XYZsize"]).to_equal("143.43x89.6x175")

    def test_attributes_never_carry_internal_machine_name(self) -> None:
        # ChituManager's attributes lookup omits BrandName, so MachineName
        # alone has to be the full key; an InternalMachineName here would
        # shadow it and break the picture match.
        attributes = self.bridge.snapshot_attributes()
        expect("InternalMachineName" in attributes).to_equal(False)

    def test_attributes_derive_geometry_from_sliced_file(self) -> None:
        attributes = self.bridge.snapshot_attributes()
        expect(attributes["Resolution"]).to_equal("1440x2560")
        expect(attributes["XYZsize"]).to_equal("68.04x120.96x150")

    def test_start_print_dispatches_to_printer(self) -> None:
        ack = self.bridge.start_print("/local/foobar.ctb")
        expect(ack).to_equal(int(constants.PrintCtrlAck.OK))
        self.printer_mock.start_printing.assert_called_once_with("foobar.ctb")

    def test_uploaded_name_can_be_printed_verbatim(self) -> None:
        """Upload then print, under the name the client actually sends.

        Reproduces the reported failure: the upload stored a rewritten name
        while Cmd 128 asked for the original, so the print was rejected as
        NOT_FOUND even though the file was sitting in the directory.
        """
        name = "a-precise-chimney_6(1).stl_1_0.050_2.500_2026_09_07.ctb"
        manager = UploadManager(is_in_use=_never_in_use, unless_in_use=_no_guard)
        result = manager.handle_chunk(
            upload_uuid="abc",
            filename=name,
            offset=0,
            total_size=len(self.ctb_file_contents),
            expected_md5="",
            verify=False,
            data=self.ctb_file_contents,
        )
        expect(result.completed).to_equal(True)

        ack = self.bridge.start_print(f"/local/{name}")
        expect(ack).to_equal(int(constants.PrintCtrlAck.OK))
        self.printer_mock.start_printing.assert_called_once_with(name)

    def test_start_print_missing_file(self) -> None:
        ack = self.bridge.start_print("/local/nope.ctb")
        expect(ack).to_equal(int(constants.PrintCtrlAck.NOT_FOUND))
        self.printer_mock.start_printing.assert_not_called()

    def test_start_print_rejects_path_traversal(self) -> None:
        ack = self.bridge.start_print("/local/../../etc/passwd")
        expect(ack).to_equal(int(constants.PrintCtrlAck.NOT_FOUND))
        self.printer_mock.start_printing.assert_not_called()

    def test_pause_resume_stop(self) -> None:
        expect(self.bridge.pause_print()).to_equal(int(constants.PrintCtrlAck.OK))
        self.printer_mock.pause_printing.assert_called_once()

        expect(self.bridge.resume_print()).to_equal(int(constants.PrintCtrlAck.OK))
        self.printer_mock.resume_printing.assert_called_once()

        expect(self.bridge.stop_print()).to_equal(int(constants.PrintCtrlAck.OK))
        self.printer_mock.stop_printing.assert_called_once()

    def test_list_files(self) -> None:
        self.fs.create_dir("/mnt/usb_share/nested")
        self.fs.create_file("/mnt/usb_share/notes.txt", contents="ignored")

        entries = self.bridge.list_files("/local/")
        names = {entry["name"]: entry for entry in entries}

        expect("/local/foobar.ctb" in names).to_equal(True)
        expect(names["/local/foobar.ctb"]["type"]).to_equal(1)
        expect("/local/nested" in names).to_equal(True)
        expect(names["/local/nested"]["type"]).to_equal(0)
        # Unprintable files are filtered out by the mainboard per the spec.
        expect("/local/notes.txt" in names).to_equal(False)

    def test_list_files_rejects_escape(self) -> None:
        expect(self.bridge.list_files("/local/../../etc")).to_equal([])

    def test_delete_files(self) -> None:
        failures = self.bridge.delete(["/local/foobar.ctb"], [])
        expect(failures).to_equal([])
        expect(pathlib.Path("/mnt/usb_share/foobar.ctb").exists()).to_equal(False)

    def test_delete_reports_failures(self) -> None:
        failures = self.bridge.delete(["/local/missing.ctb"], [])
        expect(failures).to_equal(["/local/missing.ctb"])

    def test_delete_refuses_the_file_being_printed(self) -> None:
        self.printer_mock.get_selected_file.return_value = "foobar.ctb"
        self.printer_mock.get_print_status.return_value = PrintStatus(
            state=PrinterState.PRINTING, current_byte=10, total_bytes=100
        )
        failures = self.bridge.delete(["/local/foobar.ctb"], [])
        expect(failures).to_equal(["/local/foobar.ctb"])
        expect(pathlib.Path("/mnt/usb_share/foobar.ctb").exists()).to_equal(True)

    def test_delete_refuses_a_folder_holding_the_file_being_printed(self) -> None:
        self.fs.create_file("/mnt/usb_share/batch/part.ctb", contents=b"x")
        self.printer_mock.get_selected_file.return_value = "batch/part.ctb"
        self.printer_mock.get_print_status.return_value = PrintStatus(
            state=PrinterState.PAUSED, current_byte=10, total_bytes=100
        )
        failures = self.bridge.delete([], ["/local/batch"])
        expect(failures).to_equal(["/local/batch"])
        expect(pathlib.Path("/mnt/usb_share/batch/part.ctb").exists()).to_equal(True)

    def test_delete_is_refused_when_the_printer_is_silent(self) -> None:
        self.printer_mock.get_print_status.return_value = PrintStatus(
            state=PrinterState.CLOSED
        )
        failures = self.bridge.delete(["/local/foobar.ctb"], [])
        expect(failures).to_equal(["/local/foobar.ctb"])
        expect(pathlib.Path("/mnt/usb_share/foobar.ctb").exists()).to_equal(True)

    def test_delete_folders(self) -> None:
        self.fs.create_file("/mnt/usb_share/batch/a.ctb", contents=b"x")
        self.fs.create_file("/mnt/usb_share/batch/deep/b.ctb", contents=b"x")
        failures = self.bridge.delete([], ["/local/batch"])
        expect(failures).to_equal([])
        # Gone, and nothing left of the name it was moved aside under.
        expect(sorted(os.listdir("/mnt/usb_share"))).to_equal(["foobar.ctb"])

    def test_delete_does_not_hold_the_printer_while_a_folder_is_removed(self) -> None:
        self.fs.create_file("/mnt/usb_share/batch/a.ctb", contents=b"x")
        held = []
        real_rmtree = shutil.rmtree

        def rmtree(path: Any, *args: Any, **kwargs: Any) -> None:
            held.append(printer_access._printer_lock._is_owned())
            real_rmtree(path, *args, **kwargs)

        with patch("mariner.server.providers.sdcp.bridge.shutil.rmtree", rmtree):
            self.bridge.delete([], ["/local/batch"])
        expect(held).to_equal([False])

    def test_delete_asks_the_printer_once_for_a_whole_batch(self) -> None:
        self.fs.create_file("/mnt/usb_share/a.ctb", contents=b"x")
        self.fs.create_file("/mnt/usb_share/b.ctb", contents=b"x")
        self.printer_mock.get_selected_file.return_value = ""
        self.printer_mock.get_print_status.return_value = PrintStatus(
            state=PrinterState.IDLE, counters_seen=True
        )
        failures = self.bridge.delete(["/local/a.ctb", "/local/b.ctb"], [])
        expect(failures).to_equal([])
        expect(self.printer_mock.get_print_status.call_count).to_equal(1)

    def test_delete_does_not_walk_a_string_character_by_character(self) -> None:
        # A client sending "FolderList": "a" must not delete the folder "a".
        self.fs.create_dir("/mnt/usb_share/a")
        failures = self.bridge.delete([], "ab")
        expect(failures).to_equal(["ab"])
        expect(pathlib.Path("/mnt/usb_share/a").is_dir()).to_equal(True)

    def test_delete_reports_entries_that_are_not_paths(self) -> None:
        failures = self.bridge.delete([42, None, {"a": 1}], [["x"]])
        expect(failures).to_equal([42, None, {"a": 1}, ["x"]])
        expect(pathlib.Path("/mnt/usb_share/foobar.ctb").exists()).to_equal(True)

    def test_delete_refuses_to_remove_root(self) -> None:
        failures = self.bridge.delete([], ["/local/"])
        expect(failures).to_equal(["/local/"])
        expect(pathlib.Path("/mnt/usb_share").is_dir()).to_equal(True)


class UploadManagerTest(TestCase):
    fs: FakeFilesystem

    def setUp(self) -> None:
        _get_config.cache_clear()
        self.setUpPyfakefs(additional_skip_names=["importlib.metadata"])
        self.fs.create_dir("/mnt/usb_share")
        self.manager = UploadManager(is_in_use=_never_in_use, unless_in_use=_no_guard)

    def _upload(
        self,
        data: bytes,
        *,
        filename: str = "model.ctb",
        chunk_size: int = 1024,
        verify: bool = True,
        md5: str = "",
        upload_uuid: str = "abc",
    ) -> Any:
        digest = md5 or hashlib.md5(data).hexdigest()
        result = None
        for offset in range(0, len(data), chunk_size):
            end = offset + chunk_size
            result = self.manager.handle_chunk(
                upload_uuid=upload_uuid,
                filename=filename,
                offset=offset,
                total_size=len(data),
                expected_md5=digest,
                verify=verify,
                data=data[offset:end],
            )
            if not result.ok:
                return result
        return result

    def _chunk(self, manager: Any, offset: int, data: bytes, total: int) -> Any:
        return manager.handle_chunk(
            upload_uuid="abc",
            filename="model.ctb",
            offset=offset,
            total_size=total,
            expected_md5="",
            verify=False,
            data=data,
        )

    def test_upload_refuses_to_replace_the_file_being_printed(self) -> None:
        self.fs.create_file("/mnt/usb_share/model.ctb", contents=b"printing")
        manager = UploadManager(
            is_in_use=lambda path: path.name == "model.ctb", unless_in_use=_no_guard
        )
        result = self._chunk(manager, 0, b"new!", 8)
        expect(result.ok).to_equal(False)
        expect(result.error).to_equal(constants.UploadError.FILE_OPEN_FAILED)
        with open("/mnt/usb_share/model.ctb", "rb") as file:
            expect(file.read()).to_equal(b"printing")
        # Refused before anything was stored.
        expect(manager.is_transferring()).to_equal(False)
        expect(os.path.exists("/mnt/usb_share/.sdcp_uploads")).to_equal(False)

    def test_upload_refuses_when_the_print_starts_during_the_transfer(self) -> None:
        self.fs.create_file("/mnt/usb_share/model.ctb", contents=b"printing")

        @contextmanager
        def print_started_meanwhile(path: pathlib.Path) -> Iterator[None]:
            raise FileInUse(path, printer_access.Usage.PRINTING)
            yield

        manager = UploadManager(
            is_in_use=_never_in_use, unless_in_use=print_started_meanwhile
        )
        expect(self._chunk(manager, 0, b"new!", 8).ok).to_equal(True)
        result = self._chunk(manager, 4, b"new!", 8)
        expect(result.ok).to_equal(False)
        expect(result.error).to_equal(constants.UploadError.FILE_OPEN_FAILED)
        with open("/mnt/usb_share/model.ctb", "rb") as file:
            expect(file.read()).to_equal(b"printing")
        expect(manager.is_transferring()).to_equal(False)

    def test_restarting_a_transfer_onto_a_printing_file_drops_what_was_sent(
        self,
    ) -> None:
        printing = {"now": False}
        manager = UploadManager(
            is_in_use=lambda path: printing["now"], unless_in_use=_no_guard
        )
        expect(self._chunk(manager, 0, b"new!", 8).ok).to_equal(True)
        printing["now"] = True
        expect(self._chunk(manager, 0, b"new!", 8).ok).to_equal(False)
        expect(manager.is_transferring()).to_equal(False)

    def test_a_transfer_reusing_an_id_cannot_touch_one_being_moved_into_place(
        self,
    ) -> None:
        # While the first transfer waits for the printer before its final
        # move, a second one arrives under the same id (clients that send
        # none all share "default"). Each must end up whole, under its name.
        manager: Any = None
        interleaved = []

        @contextmanager
        def guard(path: pathlib.Path) -> Iterator[None]:
            if not interleaved:
                interleaved.append(True)
                started = manager.handle_chunk(
                    upload_uuid="default",
                    filename="second.ctb",
                    offset=0,
                    total_size=8,
                    expected_md5="",
                    verify=False,
                    data=b"BBBB",
                )
                expect(started.ok).to_equal(True)
            yield

        manager = UploadManager(is_in_use=_never_in_use, unless_in_use=guard)
        first = manager.handle_chunk(
            upload_uuid="default",
            filename="first.ctb",
            offset=0,
            total_size=4,
            expected_md5="",
            verify=False,
            data=b"AAAA",
        )
        expect(first.completed).to_equal(True)
        second = manager.handle_chunk(
            upload_uuid="default",
            filename="second.ctb",
            offset=4,
            total_size=8,
            expected_md5="",
            verify=False,
            data=b"BBBB",
        )
        expect(second.completed).to_equal(True)

        with open("/mnt/usb_share/first.ctb", "rb") as file:
            expect(file.read()).to_equal(b"AAAA")
        with open("/mnt/usb_share/second.ctb", "rb") as file:
            expect(file.read()).to_equal(b"BBBBBBBB")
        expect(os.path.exists("/mnt/usb_share/.sdcp_uploads")).to_equal(False)

    def test_one_transfer_finishing_leaves_another_being_moved_alone(self) -> None:
        # A small transfer completes, and cleans up, while a big one is still
        # waiting for the printer before its final move.
        manager: Any = None
        interleaved = []

        @contextmanager
        def guard(path: pathlib.Path) -> Iterator[None]:
            if path.name == "big.ctb" and not interleaved:
                interleaved.append(True)
                small = manager.handle_chunk(
                    upload_uuid="small",
                    filename="small.ctb",
                    offset=0,
                    total_size=4,
                    expected_md5="",
                    verify=False,
                    data=b"tiny",
                )
                expect(small.completed).to_equal(True)
            yield

        manager = UploadManager(is_in_use=_never_in_use, unless_in_use=guard)
        big = manager.handle_chunk(
            upload_uuid="big",
            filename="big.ctb",
            offset=0,
            total_size=4,
            expected_md5="",
            verify=False,
            data=b"HUGE",
        )
        expect(big.completed).to_equal(True)
        with open("/mnt/usb_share/big.ctb", "rb") as file:
            expect(file.read()).to_equal(b"HUGE")
        with open("/mnt/usb_share/small.ctb", "rb") as file:
            expect(file.read()).to_equal(b"tiny")

    def test_by_default_the_manager_asks_the_printer(self) -> None:
        # The wiring used in production: no stand-ins for the in-use checks.
        self.fs.create_file("/mnt/usb_share/model.ctb", contents=b"printing")
        printer_access.forget_status()
        printer_mock = Mock(spec=ChiTuPrinter)
        printer_mock.__enter__ = Mock(return_value=printer_mock)
        printer_mock.__exit__ = Mock(return_value=None)
        printer_mock.get_print_status.return_value = PrintStatus(
            state=PrinterState.PRINTING,
            current_byte=10,
            total_bytes=100,
            counters_seen=True,
        )
        printer_mock.get_selected_file.return_value = "model.ctb"
        with patch(
            "mariner.server.printer_access.ChiTuPrinter", return_value=printer_mock
        ):
            result = self._chunk(UploadManager(), 0, b"new!", 4)
            other = UploadManager().handle_chunk(
                upload_uuid="abc",
                filename="other.ctb",
                offset=0,
                total_size=4,
                expected_md5="",
                verify=False,
                data=b"new!",
            )
        printer_access.forget_status()

        expect(result.ok).to_equal(False)
        expect(result.error).to_equal(constants.UploadError.FILE_OPEN_FAILED)
        with open("/mnt/usb_share/model.ctb", "rb") as file:
            expect(file.read()).to_equal(b"printing")
        expect(other.completed).to_equal(True)

    def test_the_printer_is_never_queried_with_the_upload_lock_held(self) -> None:
        # The SDCP event loop calls is_transferring(), which takes that lock.
        # A serial conversation can take seconds; holding the lock across it
        # would freeze every connected client.
        manager: Any = None
        observed = []

        def is_in_use(path: pathlib.Path) -> bool:
            observed.append(manager._lock.locked())
            return False

        @contextmanager
        def unless_in_use(path: pathlib.Path) -> Iterator[None]:
            observed.append(manager._lock.locked())
            yield

        manager = UploadManager(is_in_use=is_in_use, unless_in_use=unless_in_use)
        expect(self._chunk(manager, 0, b"new!", 8).ok).to_equal(True)
        expect(self._chunk(manager, 4, b"new!", 8).completed).to_equal(True)
        expect(observed).to_equal([False, False])

    def test_upload_id_cannot_name_a_path(self) -> None:
        self.fs.create_dir("/mnt/outside")
        for upload_uuid in (
            "../../outside/escaped",
            "/mnt/outside/absolute",
            "a/b",
            "..",
            "",
            "x" * 65,
        ):
            result = self._upload(b"x" * 64, upload_uuid=upload_uuid)
            expect(result.ok).to_equal(False)
        expect(os.listdir("/mnt/outside")).to_equal([])
        expect(os.path.exists("/mnt/usb_share/model.ctb")).to_equal(False)

    def test_upload_id_accepts_the_shapes_clients_send(self) -> None:
        for upload_uuid in (
            "default",
            "3f2b8c1e-9d4a-4f6b-8a1c-2e5d7f9b0a13",
            "3f2b8c1e9d4a4f6b8a1c2e5d7f9b0a13",
        ):
            result = self._upload(b"x" * 64, upload_uuid=upload_uuid)
            expect(result.completed).to_equal(True)

    def test_single_chunk_upload(self) -> None:
        payload = b"x" * 512
        result = self._upload(payload)
        expect(result.ok).to_equal(True)
        expect(result.completed).to_equal(True)
        expect(result.filename).to_equal("model.ctb")
        expect(pathlib.Path("/mnt/usb_share/model.ctb").read_bytes()).to_equal(payload)

    def test_multi_chunk_upload_is_reassembled_in_order(self) -> None:
        payload = bytes(range(256)) * 40
        result = self._upload(payload, chunk_size=1024)
        expect(result.ok).to_equal(True)
        expect(result.completed).to_equal(True)
        expect(pathlib.Path("/mnt/usb_share/model.ctb").read_bytes()).to_equal(payload)

    def test_transferring_flag_tracks_active_upload(self) -> None:
        expect(self.manager.is_transferring()).to_equal(False)
        self.manager.handle_chunk(
            upload_uuid="abc",
            filename="model.ctb",
            offset=0,
            total_size=2048,
            expected_md5="",
            verify=False,
            data=b"y" * 1024,
        )
        expect(self.manager.is_transferring()).to_equal(True)
        self.manager.handle_chunk(
            upload_uuid="abc",
            filename="model.ctb",
            offset=1024,
            total_size=2048,
            expected_md5="",
            verify=False,
            data=b"y" * 1024,
        )
        expect(self.manager.is_transferring()).to_equal(False)

    def test_padding_past_total_size_is_dropped(self) -> None:
        # ChiTuBox pads the final packet. Writing the padding makes the file
        # longer than the original, which breaks encrypted CTB parsing since
        # its checksum is read by seeking back from the end.
        payload = b"real-ctb-payload" * 8
        result = self.manager.handle_chunk(
            upload_uuid="abc",
            filename="model.ctb",
            offset=0,
            total_size=len(payload),
            expected_md5="",
            verify=False,
            data=payload + b"\x00\x01\x02\x03",
        )
        expect(result.ok).to_equal(True)
        expect(result.completed).to_equal(True)
        landed = pathlib.Path("/mnt/usb_share/model.ctb").read_bytes()
        expect(len(landed)).to_equal(len(payload))
        expect(landed).to_equal(payload)

    def test_padding_on_the_last_of_several_chunks_is_dropped(self) -> None:
        payload = bytes(range(256)) * 8
        half = len(payload) // 2
        self.manager.handle_chunk(
            upload_uuid="abc",
            filename="model.ctb",
            offset=0,
            total_size=len(payload),
            expected_md5="",
            verify=False,
            data=payload[:half],
        )
        result = self.manager.handle_chunk(
            upload_uuid="abc",
            filename="model.ctb",
            offset=half,
            total_size=len(payload),
            expected_md5="",
            verify=False,
            data=payload[half:] + b"\xde\xad\xbe\xef",
        )
        expect(result.completed).to_equal(True)
        expect(pathlib.Path("/mnt/usb_share/model.ctb").read_bytes()).to_equal(payload)

    def test_md5_is_checked_against_the_unpadded_file(self) -> None:
        payload = b"exactly-this-content" * 4
        digest = hashlib.md5(payload).hexdigest()
        result = self.manager.handle_chunk(
            upload_uuid="abc",
            filename="model.ctb",
            offset=0,
            total_size=len(payload),
            expected_md5=digest,
            verify=True,
            data=payload + b"\x00\x00\x00\x00",
        )
        expect(result.ok).to_equal(True)
        expect(result.md5_failed).to_equal(False)

    def test_offset_mismatch_is_rejected(self) -> None:
        self.manager.handle_chunk(
            upload_uuid="abc",
            filename="model.ctb",
            offset=0,
            total_size=4096,
            expected_md5="",
            verify=False,
            data=b"z" * 1024,
        )
        result = self.manager.handle_chunk(
            upload_uuid="abc",
            filename="model.ctb",
            offset=9999,
            total_size=4096,
            expected_md5="",
            verify=False,
            data=b"z" * 1024,
        )
        expect(result.ok).to_equal(False)
        expect(result.error).to_equal(int(constants.UploadError.OFFSET_MISMATCH))

    def test_negative_offset_is_rejected(self) -> None:
        result = self.manager.handle_chunk(
            upload_uuid="abc",
            filename="model.ctb",
            offset=-1,
            total_size=10,
            expected_md5="",
            verify=False,
            data=b"z",
        )
        expect(result.ok).to_equal(False)
        expect(result.error).to_equal(int(constants.UploadError.OFFSET_ERROR))

    def test_md5_mismatch_discards_the_file(self) -> None:
        result = self._upload(b"q" * 256, md5="0" * 32)
        expect(result.ok).to_equal(False)
        expect(result.md5_failed).to_equal(True)
        expect(pathlib.Path("/mnt/usb_share/model.ctb").exists()).to_equal(False)

    def test_md5_is_not_checked_when_verification_is_off(self) -> None:
        result = self._upload(b"q" * 256, md5="0" * 32, verify=False)
        expect(result.ok).to_equal(True)
        expect(result.completed).to_equal(True)

    def test_unsupported_extension_is_rejected(self) -> None:
        result = self._upload(b"data", filename="notes.txt")
        expect(result.ok).to_equal(False)
        expect(result.format_failed).to_equal(True)

    def test_filename_with_parentheses_is_preserved(self) -> None:
        # ChiTuBox names files like "model_6(1).stl_....ctb" and then asks to
        # print under that exact name. Rewriting it on upload leaves the print
        # command looking for a file that does not exist.
        name = "a-precise-chimney_6(1).stl_1_0.050_2.500.ctb"
        result = self._upload(b"data" * 64, filename=name)
        expect(result.ok).to_equal(True)
        expect(result.filename).to_equal(name)
        expect((pathlib.Path("/mnt/usb_share") / name).exists()).to_equal(True)

    def test_filename_with_spaces_and_unicode_is_preserved(self) -> None:
        name = "my model éà.ctb"
        result = self._upload(b"data" * 64, filename=name)
        expect(result.ok).to_equal(True)
        expect((pathlib.Path("/mnt/usb_share") / name).exists()).to_equal(True)

    def test_filename_with_a_path_separator_is_rejected(self) -> None:
        result = self._upload(b"data" * 64, filename="../../etc/passwd.ctb")
        expect(result.ok).to_equal(False)
        expect(result.format_failed).to_equal(True)
        expect(pathlib.Path("/mnt/usb_share/passwd.ctb").exists()).to_equal(False)

    def test_filename_with_a_backslash_is_rejected(self) -> None:
        result = self._upload(b"data" * 64, filename="..\\..\\evil.ctb")
        expect(result.ok).to_equal(False)
        expect(result.format_failed).to_equal(True)

    def test_restarting_at_offset_zero_resets_the_transfer(self) -> None:
        self.manager.handle_chunk(
            upload_uuid="abc",
            filename="model.ctb",
            offset=0,
            total_size=4096,
            expected_md5="",
            verify=False,
            data=b"a" * 1024,
        )
        payload = b"b" * 2048
        result = self._upload(payload, chunk_size=2048, verify=True)
        expect(result.ok).to_equal(True)
        expect(pathlib.Path("/mnt/usb_share/model.ctb").read_bytes()).to_equal(payload)

    def test_terminate_without_transfer(self) -> None:
        ack = self.manager.terminate("nope")
        expect(ack).to_equal(int(constants.FileTransferAck.NOT_TRANSFER))

    def test_terminate_active_transfer(self) -> None:
        self.manager.handle_chunk(
            upload_uuid="abc",
            filename="model.ctb",
            offset=0,
            total_size=4096,
            expected_md5="",
            verify=False,
            data=b"a" * 1024,
        )
        ack = self.manager.terminate("abc")
        expect(ack).to_equal(int(constants.FileTransferAck.SUCCESS))
        expect(self.manager.is_transferring()).to_equal(False)
        expect(pathlib.Path("/mnt/usb_share/model.ctb").exists()).to_equal(False)


class _ClosingWebSocket:
    """A socket the peer closed between its ping and our reply."""

    closed: bool = False
    sent: int = 0

    async def send_str(self, text: str) -> None:
        self.sent += 1
        raise ClientConnectionResetError("Cannot write to closing transport")


class _OpenWebSocket:
    closed: bool = False

    def __init__(self) -> None:
        self.sent: List[str] = []

    async def send_str(self, text: str) -> None:
        self.sent.append(text)


class ServiceHeartbeatTest(IsolatedAsyncioTestCase):
    service: SDCPService

    def setUp(self) -> None:
        _get_config.cache_clear()
        # __init__ reads config and may open a history file; the send paths
        # under test need none of that.
        self.service = SDCPService.__new__(SDCPService)
        self.service._clients = set()

    async def test_ping_is_answered_with_pong(self) -> None:
        ws = _OpenWebSocket()
        await self.service._handle_text(cast(Any, ws), "ping")
        expect(ws.sent).to_equal(["pong"])

    async def test_quoted_ping_is_answered_with_pong(self) -> None:
        ws = _OpenWebSocket()
        await self.service._handle_text(cast(Any, ws), '"ping"')
        expect(ws.sent).to_equal(["pong"])

    async def test_pong_to_a_closing_socket_drops_the_client(self) -> None:
        # aiohttp raises from send_str when the peer has gone away. Letting
        # that escape aborts the read loop with an ERROR traceback for what
        # is an ordinary disconnect.
        ws = _ClosingWebSocket()
        self.service._clients.add(cast(Any, ws))
        await self.service._handle_text(cast(Any, ws), "ping")
        expect(ws.sent).to_equal(1)
        expect(len(self.service._clients)).to_equal(0)


class ThumbnailUrlTest(TestCase):
    service: Any
    bridge: Any

    def setUp(self) -> None:
        _get_config.cache_clear()
        identity._machine_seed.cache_clear()
        self.bridge = Mock(spec=PrinterBridge)
        self.service = SDCPService.__new__(SDCPService)
        self.service._bridge = self.bridge

    def test_url_ends_in_png(self) -> None:
        # ChituManager saves the download under the URL's last path segment
        # and re-serves it from a local HTTP server that types files by
        # extension. Without a suffix the image never renders.
        self.bridge.has_preview.return_value = True
        url = self.service._thumbnail_url("abc123", "model.ctb")
        expect(url.endswith("/abc123.png")).to_equal(True)

    def test_last_path_segment_carries_the_task_id_and_suffix(self) -> None:
        self.bridge.has_preview.return_value = True
        url = self.service._thumbnail_url("abc123", "model.ctb")
        expect(url.rsplit("/", 1)[-1]).to_equal("abc123.png")

    def test_handler_strips_the_suffix_the_url_adds(self) -> None:
        self.bridge.has_preview.return_value = True
        segment = self.service._thumbnail_url("abc123", "model.ctb").rsplit("/", 1)[-1]
        expect(segment.rsplit(".", 1)[0]).to_equal("abc123")

    def test_no_url_without_a_filename(self) -> None:
        self.bridge.has_preview.return_value = True
        expect(self.service._thumbnail_url("abc123", "")).to_equal("")

    def test_no_url_when_the_preview_cannot_be_rendered(self) -> None:
        self.bridge.has_preview.return_value = False
        expect(self.service._thumbnail_url("abc123", "model.ctb")).to_equal("")


class HasPreviewTest(TestCase):
    fs: FakeFilesystem
    bridge: PrinterBridge

    def setUp(self) -> None:
        _get_config.cache_clear()
        self.setUpPyfakefs(additional_skip_names=["importlib.metadata"])
        self.fs.create_dir("/mnt/usb_share")
        self.bridge = PrinterBridge()

    def test_false_for_a_missing_file(self) -> None:
        expect(self.bridge.has_preview("nope.ctb")).to_equal(False)

    def test_false_for_an_unsupported_extension(self) -> None:
        self.fs.create_file("/mnt/usb_share/notes.txt", contents="hi")
        expect(self.bridge.has_preview("notes.txt")).to_equal(False)

    def test_false_when_the_file_cannot_be_parsed(self) -> None:
        # A supported extension is not a promise the file parses. Saying yes
        # here would advertise a Thumbnail address that 404s, which shows up
        # in the client as a broken image rather than as no image.
        self.fs.create_file("/mnt/usb_share/corrupt.ctb", contents="not a ctb")
        expect(self.bridge.has_preview("corrupt.ctb")).to_equal(False)
