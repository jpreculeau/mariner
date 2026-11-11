from pathlib import Path

from pyexpect import expect
from pyfakefs.fake_filesystem import FakeFilesystem
from pyfakefs.fake_filesystem_unittest import TestCase

from mariner.config import _get_config
from mariner.server.files import (
    replacing,
    resolve_in_files_directory,
    safe_filename,
)


class SafeFilenameTest(TestCase):
    def test_keeps_an_ordinary_name(self) -> None:
        expect(safe_filename("model.ctb")).to_equal("model.ctb")

    def test_keeps_spaces_parentheses_and_non_ascii(self) -> None:
        for name in ("ma pièce (v2).ctb", "模型.ctb", "model_6(1).ctb"):
            expect(safe_filename(name)).to_equal(name)

    def test_strips_surrounding_whitespace(self) -> None:
        expect(safe_filename("  model.ctb ")).to_equal("model.ctb")

    def test_rejects_empty_and_dot_names(self) -> None:
        for name in ("", "   ", ".", "..", None):
            expect(safe_filename(name)).to_equal(None)

    def test_rejects_path_separators(self) -> None:
        for name in ("a/b.ctb", "..\\b.ctb", "/etc/passwd.ctb"):
            expect(safe_filename(name)).to_equal(None)

    def test_rejects_control_characters(self) -> None:
        for name in (
            "a\r\nG0 Z-50.ctb",
            "a\nb.ctb",
            "a\x00.ctb",
            "a\tb.ctb",
            "a\x7f.ctb",
        ):
            expect(safe_filename(name)).to_equal(None)

    def test_rejects_the_quote_used_to_delimit_printer_filenames(self) -> None:
        expect(safe_filename("john's model.ctb")).to_equal(None)


class ResolveInFilesDirectoryTest(TestCase):
    fs: FakeFilesystem

    def setUp(self) -> None:
        _get_config.cache_clear()
        self.setUpPyfakefs(additional_skip_names=["importlib.metadata"])
        self.fs.create_file("/mnt/usb_share/sub/model.ctb", contents=b"x")
        self.fs.create_file("/etc/passwd", contents=b"x")

    def test_resolves_a_file_inside_the_directory(self) -> None:
        expect(resolve_in_files_directory("sub/model.ctb")).to_equal(
            Path("/mnt/usb_share/sub/model.ctb")
        )

    def test_resolves_the_directory_itself(self) -> None:
        for relative in ("", "."):
            expect(resolve_in_files_directory(relative)).to_equal(
                Path("/mnt/usb_share")
            )

    def test_refuses_to_climb_out(self) -> None:
        for relative in ("../etc/passwd", "sub/../../etc/passwd", "/etc/passwd"):
            expect(resolve_in_files_directory(relative)).to_equal(None)

    def test_refuses_a_sibling_sharing_the_same_prefix(self) -> None:
        self.fs.create_file("/mnt/usb_share_backup/model.ctb", contents=b"x")
        expect(resolve_in_files_directory("../usb_share_backup/model.ctb")).to_equal(
            None
        )

    def test_refuses_a_nul_byte(self) -> None:
        expect(resolve_in_files_directory("a\x00b")).to_equal(None)


class ReplacingTest(TestCase):
    fs: FakeFilesystem

    def setUp(self) -> None:
        self.setUpPyfakefs(additional_skip_names=["importlib.metadata"])
        self.fs.create_file("/data/model.ctb", contents=b"old")

    def test_moves_the_new_contents_into_place(self) -> None:
        with replacing(Path("/data/model.ctb")) as scratch:
            scratch.write_bytes(b"new")
        expect(Path("/data/model.ctb").read_bytes()).to_equal(b"new")
        expect(sorted(p.name for p in Path("/data").iterdir())).to_equal(["model.ctb"])

    def test_keeps_the_old_file_when_writing_fails(self) -> None:
        with self.assertRaises(OSError):
            with replacing(Path("/data/model.ctb")) as scratch:
                scratch.write_bytes(b"partial")
                raise OSError("disk full")
        expect(Path("/data/model.ctb").read_bytes()).to_equal(b"old")
        expect(sorted(p.name for p in Path("/data").iterdir())).to_equal(["model.ctb"])
