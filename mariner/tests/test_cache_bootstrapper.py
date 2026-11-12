import os
import pathlib
import tempfile
from typing import Any
from unittest import TestCase
from unittest.mock import call, patch, MagicMock

from pyexpect import expect

from mariner.file_formats.reading import MalformedFile
from mariner.server import CacheBootstrapper


class CacheBootstrapperTest(TestCase):
    @patch("mariner.server.read_cached_sliced_model_file")
    @patch("mariner.server.read_cached_preview")
    def test_ctb_metadata_cache(
        self,
        read_cached_preview_mock: MagicMock,
        read_cached_sliced_model_file_mock: MagicMock,
    ) -> None:
        files_directory = (
            pathlib.Path(__file__).parent.parent.absolute() / "file_formats" / "tests"
        )

        with patch("mariner.config.get_files_directory", return_value=files_directory):
            CacheBootstrapper().run()

        read_cached_sliced_model_file_mock.assert_has_calls(
            [
                call(files_directory / "stairs.fdg"),
                call(files_directory / "pyramid.cbddlp"),
                call(files_directory / "stairs.ctb"),
            ],
            any_order=True,
        )

        read_cached_preview_mock.assert_has_calls(
            [
                call(files_directory / "stairs.fdg"),
                call(files_directory / "pyramid.cbddlp"),
                call(files_directory / "stairs.ctb"),
            ],
            any_order=True,
        )


class CacheBootstrapperRobustnessTest(TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = pathlib.Path(self.directory.name).resolve()
        for name in ("a.ctb", "b.ctb", "sub/c.ctb"):
            (self.root / name).parent.mkdir(exist_ok=True)
            (self.root / name).write_bytes(b"x")
        patcher = patch("mariner.config.get_files_directory", return_value=self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _warmed(self, sliced: MagicMock, preview: MagicMock) -> Any:
        CacheBootstrapper().run()
        return (
            sorted(call.args[0].name for call in sliced.call_args_list),
            sorted(call.args[0].name for call in preview.call_args_list),
        )

    @patch("mariner.server.read_cached_sliced_model_file")
    @patch("mariner.server.read_cached_preview")
    def test_one_unreadable_file_does_not_stop_the_others(
        self, preview: MagicMock, sliced: MagicMock
    ) -> None:
        def unreadable(path: pathlib.Path) -> None:
            if path.name == "a.ctb":
                raise ValueError("truncated")

        sliced.side_effect = unreadable
        with self.assertLogs("mariner.server", "WARNING") as logs:
            read, previewed = self._warmed(sliced, preview)
        expect(read).to_equal(["a.ctb", "b.ctb", "c.ctb"])
        # No preview is attempted for a file that could not be parsed.
        expect(previewed).to_equal(["b.ctb", "c.ctb"])
        expect(len(logs.records)).to_equal(1)
        expect("a.ctb" in logs.records[0].getMessage()).to_equal(True)

    @patch("mariner.server.read_cached_sliced_model_file")
    @patch("mariner.server.read_cached_preview")
    def test_a_malformed_file_does_not_stop_the_others_and_is_not_reported_twice(
        self, preview: MagicMock, sliced: MagicMock
    ) -> None:
        def malformed(path: pathlib.Path) -> None:
            if path.name == "a.ctb":
                raise MalformedFile("cut short")

        sliced.side_effect = malformed
        preview.side_effect = malformed
        (self.root / "a.ctb").write_bytes(b"x")
        # Where the file is read, the reason was logged already.
        with self.assertNoLogs("mariner.server", "WARNING"):
            read, previewed = self._warmed(sliced, preview)
        expect(read).to_equal(["a.ctb", "b.ctb", "c.ctb"])
        expect(previewed).to_equal(["b.ctb", "c.ctb"])

    @patch("mariner.server.read_cached_sliced_model_file")
    @patch("mariner.server.read_cached_preview")
    def test_a_malformed_preview_is_not_reported_twice_either(
        self, preview: MagicMock, sliced: MagicMock
    ) -> None:
        preview.side_effect = MalformedFile("no complete row")
        with self.assertNoLogs("mariner.server", "WARNING"):
            read, previewed = self._warmed(sliced, preview)
        expect(previewed).to_equal(["a.ctb", "b.ctb", "c.ctb"])

    @patch("mariner.server.read_cached_sliced_model_file")
    @patch("mariner.server.read_cached_preview")
    def test_what_is_not_a_file_is_left_alone(
        self, preview: MagicMock, sliced: MagicMock
    ) -> None:
        os.mkfifo(self.root / "pipe.ctb")
        os.mkfifo(self.root / "._pipe.ctb")
        (self.root / "folder.ctb").mkdir()
        read, _ = self._warmed(sliced, preview)
        expect(read).to_equal(["a.ctb", "b.ctb", "c.ctb"])

    @patch("mariner.server.read_cached_sliced_model_file")
    @patch("mariner.server.read_cached_preview")
    def test_an_entry_the_drive_fails_on_does_not_stop_the_others(
        self, preview: MagicMock, sliced: MagicMock
    ) -> None:
        # A damaged directory entry, after the drive was unplugged mid-write.
        real_stat = os.stat

        def failing_stat(path: Any, *args: Any, **kwargs: Any) -> Any:
            if str(path).endswith("a.ctb"):
                raise OSError(5, "Input/output error")
            return real_stat(path, *args, **kwargs)

        with patch("os.stat", side_effect=failing_stat):
            read, _ = self._warmed(sliced, preview)
        expect(read).to_equal(["b.ctb", "c.ctb"])

    @patch("mariner.server.read_cached_sliced_model_file")
    @patch("mariner.server.read_cached_preview")
    def test_companion_files_from_a_mac_are_left_alone(
        self, preview: MagicMock, sliced: MagicMock
    ) -> None:
        # What macOS writes beside a file on a drive that is not its own.
        (self.root / "._a.ctb").write_bytes(
            b"\x00\x05\x16\x07\x00\x02\x00\x00Mac OS X    "
        )
        # Not one of those, whatever its name.
        (self.root / "._d.ctb").write_bytes(b"x")
        read, _ = self._warmed(sliced, preview)
        expect(read).to_equal(["._d.ctb", "a.ctb", "b.ctb", "c.ctb"])

    @patch("mariner.server.read_cached_sliced_model_file")
    @patch("mariner.server.read_cached_preview")
    def test_a_preview_that_cannot_be_rendered_does_not_stop_the_others(
        self, preview: MagicMock, sliced: MagicMock
    ) -> None:
        preview.side_effect = ValueError("no preview")
        with self.assertLogs("mariner.server", "WARNING"):
            read, previewed = self._warmed(sliced, preview)
        expect(read).to_equal(["a.ctb", "b.ctb", "c.ctb"])
        expect(previewed).to_equal(["a.ctb", "b.ctb", "c.ctb"])

    @patch("mariner.server.read_cached_sliced_model_file")
    @patch("mariner.server.read_cached_preview")
    def test_transfers_in_progress_and_links_leading_elsewhere_are_left_alone(
        self, preview: MagicMock, sliced: MagicMock
    ) -> None:
        with tempfile.TemporaryDirectory() as outside:
            (pathlib.Path(outside) / "secret.ctb").write_bytes(b"x")
            (self.root / ".sdcp_uploads").mkdir()
            (self.root / ".sdcp_uploads" / "half.ctb").write_bytes(b"x")
            os.symlink(pathlib.Path(outside) / "secret.ctb", self.root / "out.ctb")
            os.symlink(outside, self.root / "outside")
            read, previewed = self._warmed(sliced, preview)
        expect(read).to_equal(["a.ctb", "b.ctb", "c.ctb"])
        expect(previewed).to_equal(["a.ctb", "b.ctb", "c.ctb"])
