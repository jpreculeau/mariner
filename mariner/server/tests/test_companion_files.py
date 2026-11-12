import os
import tempfile
from pathlib import Path
from unittest import TestCase

from pyexpect import expect

from mariner import config
from mariner.server.app import app
from mariner.server.files import is_macos_companion


class MacosCompanionTest(TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def _file(self, name: str, contents: bytes) -> Path:
        path = self.root / name
        path.write_bytes(contents)
        return path

    def test_what_macos_writes_beside_a_file_is_one(self) -> None:
        marked = b"\x00\x05\x16\x07\x00\x02\x00\x00Mac OS X        rest"
        expect(is_macos_companion(self._file("._model.ctb", marked))).to_equal(True)
        expect(is_macos_companion(str(self.root / "._model.ctb"))).to_equal(True)

    def test_the_name_alone_does_not_make_one(self) -> None:
        expect(is_macos_companion(self._file("._model.ctb", b"a model"))).to_equal(
            False
        )

    def test_the_contents_alone_do_not_make_one(self) -> None:
        marked = b"\x00\x05\x16\x07\x00\x02\x00\x00Mac OS X        rest"
        expect(is_macos_companion(self._file("model.ctb", marked))).to_equal(False)

    def test_what_cannot_be_opened_is_not_one(self) -> None:
        os.mkdir(self.root / "._folder.ctb")
        expect(is_macos_companion(self.root / "._folder.ctb")).to_equal(False)
        expect(is_macos_companion(self.root / "._gone.ctb")).to_equal(False)


class CacheDirectoryTest(TestCase):
    def test_parsed_files_are_kept_apart_from_what_else_is_stored_there(self) -> None:
        # Emptying what is remembered of files, at each start, must leave
        # the rest alone: the history of prints shown to slicers, for one.
        kept = Path(app.config["CACHE_DIR"])
        expect(kept.parent).to_equal(Path(config.get_cache_directory()))
        expect(kept in config.get_sdcp_history_path().parents).to_equal(False)

    def test_any_number_of_files_can_be_remembered(self) -> None:
        expect(app.config["CACHE_THRESHOLD"]).to_equal(0)
