import json
import os
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from pyexpect import expect

from mariner import config
from mariner.server import app as application, auth, settings, state


class _WithState(TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        state.forget()
        self.addCleanup(state.forget)
        patcher = patch(
            "mariner.config.get_state_directory", return_value=str(self.root / "s")
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        config._get_config.cache_clear()
        no_file = patch("mariner.config._get_config", return_value={})
        no_file.start()
        self.addCleanup(no_file.stop)
        self.addCleanup(lambda: setattr(config, "overrides", {}))
        config.overrides.clear()


class SettingsTest(_WithState):
    def test_nothing_is_changed_until_something_is(self) -> None:
        expect(settings.current()).to_equal(
            {
                "printer_display_name": None,
                "uvtools_enabled": True,
                "sdcp_enabled": True,
                "assume_printer_off": False,
            }
        )
        # And nothing is made on the drive by looking.
        expect((self.root / "s").exists()).to_equal(False)

    def test_what_the_configuration_file_says_is_what_is_shown(self) -> None:
        with patch(
            "mariner.config._get_config",
            return_value={
                "printer": {"display_name": "Saturn"},
                "uvtools": {"enabled": False},
            },
        ):
            shown = settings.current()
        expect(shown["printer_display_name"]).to_equal("Saturn")
        expect(shown["uvtools_enabled"]).to_equal(False)
        expect(shown["sdcp_enabled"]).to_equal(True)

    def test_what_is_set_from_the_page_comes_before_the_file(self) -> None:
        with patch(
            "mariner.config._get_config",
            return_value={"printer": {"display_name": "Saturn"}},
        ):
            settings.change({"printer_display_name": "Workshop", "sdcp_enabled": False})
            expect(config.get_printer_display_name()).to_equal("Workshop")
            expect(config.get_sdcp_enabled()).to_equal(False)
            expect(config.get_uvtools_enabled()).to_equal(True)

    def test_it_outlasts_a_restart(self) -> None:
        settings.change({"assume_printer_off": True, "uvtools_enabled": False})
        config.overrides.clear()
        state.forget()
        settings.apply()
        expect(config.get_uvtools_enabled()).to_equal(False)
        expect(settings.current()["assume_printer_off"]).to_equal(True)

    def test_a_setting_is_never_seen_gone_while_they_are_read(self) -> None:
        # By another request, served at the same time.
        import threading

        settings.change({"assume_printer_off": True})
        seen_off = []
        stop = threading.Event()

        def watch() -> None:
            while not stop.is_set():
                if not config.get_assume_printer_off():
                    seen_off.append(1)

        watcher = threading.Thread(target=watch)
        watcher.start()
        for _ in range(300):
            settings.current()
        stop.set()
        watcher.join()
        expect(seen_off).to_equal([])

    def test_only_what_is_sent_is_changed(self) -> None:
        settings.change({"printer_display_name": "Workshop"})
        settings.change({"sdcp_enabled": False})
        expect(settings.current()["printer_display_name"]).to_equal("Workshop")
        expect(settings.current()["sdcp_enabled"]).to_equal(False)

    def test_an_empty_name_goes_back_to_the_file_s(self) -> None:
        with patch(
            "mariner.config._get_config",
            return_value={"printer": {"display_name": "Saturn"}},
        ):
            settings.change({"printer_display_name": "Workshop"})
            settings.change({"printer_display_name": "  "})
            expect(config.get_printer_display_name()).to_equal("Saturn")

    def test_a_name_is_trimmed(self) -> None:
        settings.change({"printer_display_name": "  Workshop  "})
        expect(config.get_printer_display_name()).to_equal("Workshop")

    def test_what_is_not_a_setting_or_not_of_its_kind_is_refused_whole(self) -> None:
        for wrong in (
            {"uvtools_enabled": "false"},
            {"uvtools_enabled": 0},
            {"sdcp_enabled": None},
            {"assume_printer_off": "yes"},
            {"printer_display_name": 5},
            {"printer_display_name": "a" * 65},
            {"printer_display_name": "two\nlines"},
            {"printer_display_name": "Saturn", "unknown": True},
            {"files_directory": "/etc"},
            {},
        ):
            with self.assertRaises(settings.NotASetting):
                settings.change(wrong)
        expect(settings.current()["printer_display_name"]).to_equal(None)
        expect(state.read("settings.json")).to_equal(None)

    def test_a_file_that_cannot_be_read_changes_nothing(self) -> None:
        for broken in (b"", b"{", b"[1]", b'{"uvtools_enabled": "no"}'):
            state.write("settings.json", broken)
            config.overrides.clear()
            with self.assertLogs("mariner.server.settings", level="WARNING"):
                settings.apply()
            expect(config.get_assume_printer_off()).to_equal(False)

    def test_slicers_are_off_when_what_was_set_cannot_be_read(self) -> None:
        # They may have been switched off there: on by default, they
        # would come back on by a file changing hands.
        import os

        settings.change({"printer_display_name": "Workshop"})
        os.chmod(self.root / "s" / "settings.json", 0o644)
        with self.assertLogs("mariner.server", level="WARNING"):
            settings.apply()
        expect(config.get_uvtools_enabled()).to_equal(False)
        expect(config.get_sdcp_enabled()).to_equal(False)

    def test_slicers_are_off_when_what_was_set_is_damaged(self) -> None:
        for broken in (b"{", b"[1]", b""):
            state.write("settings.json", broken)
            with self.assertLogs("mariner.server.settings", level="WARNING"):
                settings.apply()
            expect(config.get_uvtools_enabled()).to_equal(False)
            expect(config.get_sdcp_enabled()).to_equal(False)

    def test_slicers_are_off_when_nothing_kept_can_be_reached(self) -> None:
        with patch.object(state, "is_makeshift", return_value=True):
            with self.assertLogs("mariner.server.settings", level="WARNING"):
                settings.apply()
        expect(config.get_uvtools_enabled()).to_equal(False)
        expect(config.get_sdcp_enabled()).to_equal(False)

    def test_what_it_holds_that_is_good_is_kept_when_some_is_not(self) -> None:
        state.write(
            "settings.json",
            json.dumps({"sdcp_enabled": False, "uvtools_enabled": "no"}).encode(),
        )
        with self.assertLogs("mariner.server.settings", level="WARNING"):
            settings.apply()
        expect(config.get_sdcp_enabled()).to_equal(False)
        expect(config.get_uvtools_enabled()).to_equal(True)


class SettingsApiTest(_WithState):
    def setUp(self) -> None:
        super().setUp()
        self.application = application.app
        patcher = patch.dict(self.application.config, {"WTF_CSRF_ENABLED": False})
        patcher.start()
        self.addCleanup(patcher.stop)
        signed_in = patch("mariner.server.auth.let_in", return_value=True)
        signed_in.start()
        self.addCleanup(signed_in.stop)
        self.client = self.application.test_client()
        settings.note_what_runs()

    def test_they_are_shown_with_what_runs(self) -> None:
        body = self.client.get("/api/settings").get_json()
        expect(body["settings"]["uvtools_enabled"]).to_equal(True)
        expect(body["restart_needed"]).to_equal(False)

    def test_a_change_is_kept_and_shown(self) -> None:
        response = self.client.post(
            "/api/settings", json={"printer_display_name": "Workshop"}
        )
        expect(response.status_code).to_equal(200)
        expect(response.get_json()["settings"]["printer_display_name"]).to_equal(
            "Workshop"
        )
        # The name is read at each page: no restart.
        expect(response.get_json()["restart_needed"]).to_equal(False)

    def test_a_change_that_cannot_be_kept_is_said_as_such(self) -> None:
        with patch.object(
            state, "write", side_effect=OSError(28, "No space left")
        ), self.assertLogs("mariner.server.settings", level="ERROR"):
            response = self.client.post("/api/settings", json={"sdcp_enabled": False})
        expect(response.status_code).to_equal(500)
        expect(response.get_json()["code"]).to_equal("state_not_written")
        expect(settings.current()["sdcp_enabled"]).to_equal(True)

    def test_switching_a_slicer_s_interface_asks_for_a_restart(self) -> None:
        # Its addresses and ports are opened at start.
        response = self.client.post("/api/settings", json={"sdcp_enabled": False})
        expect(response.get_json()["restart_needed"]).to_equal(True)
        expect(self.client.get("/api/settings").get_json()["restart_needed"]).to_equal(
            True
        )
        # Put back as it runs, none is needed.
        response = self.client.post("/api/settings", json={"sdcp_enabled": True})
        expect(response.get_json()["restart_needed"]).to_equal(False)

    def test_a_change_that_is_not_one_is_refused_with_the_reason(self) -> None:
        response = self.client.post("/api/settings", json={"uvtools_enabled": "no"})
        expect(response.status_code).to_equal(400)
        expect(response.get_json()["code"]).to_equal("setting_not_valid")
        for body in ([], "x", None):
            response = self.client.post("/api/settings", json=body)
            expect(response.status_code).to_equal(400)

    def test_they_are_not_shown_nor_changed_without_signing_in(self) -> None:
        patch.stopall()
        self.addCleanup(patch.stopall)
        patcher = patch(
            "mariner.config.get_state_directory", return_value=str(self.root / "s")
        )
        patcher.start()
        with patch.dict(self.application.config, {"WTF_CSRF_ENABLED": False}):
            auth.forget_attempts()
            client = self.application.test_client()
            expect(client.get("/api/settings").status_code).to_equal(401)
            response = client.post("/api/settings", json={"sdcp_enabled": False})
            expect(response.status_code).to_equal(401)


class AssumePrinterOffTest(_WithState):
    def test_the_printer_is_taken_for_off_without_asking_when_set(self) -> None:
        from mariner.server import api

        with application.app.test_request_context("/api/delete_file?filename=a"):
            expect(api._printer_declared_off()).to_equal(False)
            settings.change({"assume_printer_off": True})
            expect(api._printer_declared_off()).to_equal(True)


class RestartTest(_WithState):
    def setUp(self) -> None:
        super().setUp()
        patcher = patch.dict(application.app.config, {"WTF_CSRF_ENABLED": False})
        patcher.start()
        self.addCleanup(patcher.stop)
        signed_in = patch("mariner.server.auth.let_in", return_value=True)
        signed_in.start()
        self.addCleanup(signed_in.stop)
        self.client = application.app.test_client()

    def test_stopping_asks_the_process_to_end(self) -> None:
        import signal

        with patch("threading.Timer") as timer, patch("os.kill") as kill:
            settings._stop_soon()
            timer.call_args[0][1]()
        timer.return_value.start.assert_called_once_with()
        kill.assert_called_once_with(os.getpid(), signal.SIGTERM)

    def test_under_a_service_it_stops_to_be_started_again(self) -> None:
        with patch.dict("os.environ", {"INVOCATION_ID": "abc"}), patch.object(
            settings, "_stop_soon"
        ) as stop:
            response = self.client.post("/api/restart")
        expect(response.status_code).to_equal(200)
        stop.assert_called_once_with()

    def test_run_by_hand_it_does_not_stop_with_nothing_to_start_it_again(
        self,
    ) -> None:
        with patch.dict("os.environ", {}, clear=True), patch.object(
            settings, "_stop_soon"
        ) as stop:
            response = self.client.post("/api/restart")
        expect(response.status_code).to_equal(409)
        expect(response.get_json()["code"]).to_equal("restart_not_available")
        stop.assert_not_called()

    def test_the_page_is_told_whether_it_can(self) -> None:
        with patch.dict("os.environ", {"INVOCATION_ID": "abc"}):
            expect(self.client.get("/api/settings").get_json()["can_restart"]).to_equal(
                True
            )
        with patch.dict("os.environ", {}, clear=True):
            expect(self.client.get("/api/settings").get_json()["can_restart"]).to_equal(
                False
            )
