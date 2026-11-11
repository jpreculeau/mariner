import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from unittest.mock import patch

from pyexpect import expect
from pyfakefs.fake_filesystem import FakeFilesystem
from pyfakefs.fake_filesystem_unittest import TestCase

from mariner.config import _get_config
from mariner.server.files import (
    NotPrintable,
    is_hidden_entry,
    is_scratch_file,
    printable_relative_path,
    remove_stale_scratch_files,
    replacing,
    resolve_entry_in_files_directory,
    resolve_in_files_directory,
    safe_filename,
    scratch_path_beside,
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

    def test_rejects_characters_the_fat_filesystem_cannot_store(self) -> None:
        for character in ':*?"<>|':
            expect(safe_filename(f"a{character}b.ctb")).to_equal(None)

    def test_rejects_text_that_is_not_valid_unicode(self) -> None:
        # A JSON client can send a lone surrogate, which no file can be
        # named after.
        expect(safe_filename("\ud800.ctb")).to_equal(None)

    def test_rejects_names_reserved_for_transfers_in_progress(self) -> None:
        # Listings hide them, so an entry created under one would vanish.
        expect(safe_filename(".upload-0123456789abcdef.part")).to_equal(None)
        expect(safe_filename(".sdcp_uploads")).to_equal(None)

    def test_rejects_a_trailing_dot_which_fat_would_drop(self) -> None:
        expect(safe_filename("model.ctb.")).to_equal(None)

    def test_rejects_a_name_longer_than_a_directory_entry(self) -> None:
        expect(safe_filename("a" * 251 + ".ctb")).to_equal("a" * 251 + ".ctb")
        expect(safe_filename("a" * 252 + ".ctb")).to_equal(None)
        # The limit is in bytes: these 90 characters take 270.
        expect(safe_filename("模" * 90 + ".ctb")).to_equal(None)


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

    def test_refuses_to_go_through_a_hidden_entry(self) -> None:
        # Transfers in progress live there. No client request may reach them.
        self.fs.create_file("/mnt/usb_share/.sdcp_uploads/abcd.part", contents=b"x")
        self.fs.create_file("/mnt/usb_share/sub/.upload-0123abcd.part", contents=b"x")
        for relative in (
            ".sdcp_uploads",
            ".sdcp_uploads/abcd.part",
            "sub/.upload-0123abcd.part",
            "sub/../.sdcp_uploads",
        ):
            expect(resolve_in_files_directory(relative)).to_equal(None)


class ResolveEntryInFilesDirectoryTest(TestCase):
    fs: FakeFilesystem

    def setUp(self) -> None:
        _get_config.cache_clear()
        self.setUpPyfakefs(additional_skip_names=["importlib.metadata"])
        self.fs.create_file("/mnt/usb_share/sub/model.ctb", contents=b"x")
        self.fs.create_file("/mnt/outside.ctb", contents=b"x")
        self.fs.create_symlink(
            "/mnt/usb_share/link.ctb", "/mnt/usb_share/sub/model.ctb"
        )
        self.fs.create_symlink("/mnt/usb_share/dangling.ctb", "/mnt/usb_share/gone")
        self.fs.create_symlink("/mnt/usb_share/way_out", "/mnt")

    def test_gives_the_entry_and_not_what_it_points_to(self) -> None:
        expect(resolve_entry_in_files_directory("sub/model.ctb")).to_equal(
            Path("/mnt/usb_share/sub/model.ctb")
        )
        expect(resolve_entry_in_files_directory("link.ctb")).to_equal(
            Path("/mnt/usb_share/link.ctb")
        )
        expect(resolve_entry_in_files_directory("dangling.ctb")).to_equal(
            Path("/mnt/usb_share/dangling.ctb")
        )

    def test_resolves_the_folder_holding_the_entry(self) -> None:
        expect(resolve_entry_in_files_directory("sub/../sub/model.ctb")).to_equal(
            Path("/mnt/usb_share/sub/model.ctb")
        )

    def test_refuses_to_leave_the_files_directory(self) -> None:
        for relative in ("../outside.ctb", "/mnt/outside.ctb", "way_out/outside.ctb"):
            expect(resolve_entry_in_files_directory(relative)).to_equal(None)

    def test_refuses_what_does_not_name_an_entry(self) -> None:
        for relative in ("", ".", "..", "sub/..", "sub/."):
            expect(resolve_entry_in_files_directory(relative)).to_equal(None)

    def test_refuses_hidden_entries(self) -> None:
        self.fs.create_file("/mnt/usb_share/.sdcp_uploads/abcd.part", contents=b"x")
        for relative in (".sdcp_uploads", ".sdcp_uploads/abcd.part"):
            expect(resolve_entry_in_files_directory(relative)).to_equal(None)


class RealFilesystemResolveTest(TestCase):
    """On a real filesystem, which is where such text is actually refused."""

    def test_refuses_text_the_filesystem_cannot_take_as_a_path(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            with patch(
                "mariner.server.files.config.get_files_directory",
                return_value=Path(directory),
            ):
                # A lone surrogate, as a JSON client can send.
                expect(resolve_in_files_directory("\ud800.ctb")).to_equal(None)
                expect(resolve_in_files_directory("fine.ctb")).to_equal(
                    Path(directory).resolve() / "fine.ctb"
                )


class PrintableRelativePathTest(TestCase):
    fs: FakeFilesystem

    def setUp(self) -> None:
        _get_config.cache_clear()
        self.setUpPyfakefs(additional_skip_names=["importlib.metadata"])
        self.fs.create_file("/mnt/usb_share/model.ctb", contents=b"x")
        self.fs.create_file("/mnt/usb_share/sub/part.ctb", contents=b"x")
        self.fs.create_file("/mnt/usb_share/notes.txt", contents=b"x")
        self.fs.create_file("/mnt/elsewhere.ctb", contents=b"x")

    def _reason(self, name: str) -> str:
        with self.assertRaises(NotPrintable) as raised:
            printable_relative_path(name)
        return raised.exception.reason

    def test_gives_the_path_relative_to_the_files_directory(self) -> None:
        for given, expected in (
            ("model.ctb", "model.ctb"),
            ("sub/part.ctb", "sub/part.ctb"),
            ("./model.ctb", "model.ctb"),
            ("sub/../model.ctb", "model.ctb"),
            ("sub//part.ctb", "sub/part.ctb"),
            ("/mnt/usb_share/sub/part.ctb", "sub/part.ctb"),
        ):
            expect(printable_relative_path(given)).to_equal(expected)

    def test_refuses_what_could_not_be_sent_to_the_printer(self) -> None:
        for name in ("", "a\r\nG28.ctb", "it's.ctb", "\ud800.ctb", "a\x00.ctb"):
            expect(self._reason(name)).to_equal(NotPrintable.UNSAFE)

    def test_refuses_a_file_outside_the_files_directory(self) -> None:
        for name in ("../elsewhere.ctb", "/mnt/elsewhere.ctb"):
            expect(self._reason(name)).to_equal(NotPrintable.UNSAFE)

    def test_refuses_a_missing_file_and_a_folder(self) -> None:
        for name in ("missing.ctb", "sub"):
            expect(self._reason(name)).to_equal(NotPrintable.MISSING)

    def test_refuses_an_unsupported_format(self) -> None:
        expect(self._reason("notes.txt")).to_equal(NotPrintable.UNSUPPORTED)


class ReplacingTest(TestCase):
    fs: FakeFilesystem

    def setUp(self) -> None:
        self.setUpPyfakefs(additional_skip_names=["importlib.metadata"])
        self.fs.create_file("/data/model.ctb", contents=b"old")

    def _names(self) -> list:
        return sorted(os.listdir("/data"))

    def test_moves_the_new_contents_into_place(self) -> None:
        with replacing(Path("/data/model.ctb")) as scratch:
            scratch.write_bytes(b"new")
        expect(Path("/data/model.ctb").read_bytes()).to_equal(b"new")
        expect(self._names()).to_equal(["model.ctb"])

    def test_the_old_file_is_intact_until_the_block_ends(self) -> None:
        with replacing(Path("/data/model.ctb")) as scratch:
            scratch.write_bytes(b"new")
            expect(Path("/data/model.ctb").read_bytes()).to_equal(b"old")
            expect(is_scratch_file(scratch.name)).to_equal(True)

    def test_keeps_the_old_file_when_writing_fails(self) -> None:
        with self.assertRaises(OSError):
            with replacing(Path("/data/model.ctb")) as scratch:
                scratch.write_bytes(b"partial")
                raise OSError("disk full")
        expect(Path("/data/model.ctb").read_bytes()).to_equal(b"old")
        expect(self._names()).to_equal(["model.ctb"])

    def test_two_uploads_of_the_same_name_do_not_share_a_scratch_file(self) -> None:
        destination = Path("/data/model.ctb")
        with replacing(destination) as first:
            first.write_bytes(b"AAAA")
            with replacing(destination) as second:
                second.write_bytes(b"BBBB")
                expect(first).not_to_equal(second)
                expect(first.read_bytes()).to_equal(b"AAAA")
            expect(destination.read_bytes()).to_equal(b"BBBB")
        # The last one to finish wins, whole.
        expect(destination.read_bytes()).to_equal(b"AAAA")
        expect(self._names()).to_equal(["model.ctb"])

    def test_a_long_name_still_has_room_for_its_scratch_file(self) -> None:
        name = "a" * 251 + ".ctb"
        with replacing(Path("/data") / name) as scratch:
            expect(len(scratch.name) < len(name)).to_equal(True)
            scratch.write_bytes(b"new")
        expect((Path("/data") / name).read_bytes()).to_equal(b"new")

    def test_the_guard_wraps_the_final_move(self) -> None:
        events = []

        @contextmanager
        def guard(path: Path) -> Iterator[None]:
            events.append(("enter", path, Path("/data/model.ctb").read_bytes()))
            yield
            events.append(("exit", path, Path("/data/model.ctb").read_bytes()))

        with replacing(Path("/data/model.ctb"), guard=guard) as scratch:
            scratch.write_bytes(b"new")
            expect(events).to_equal([])
        expect(events).to_equal(
            [
                ("enter", Path("/data/model.ctb"), b"old"),
                ("exit", Path("/data/model.ctb"), b"new"),
            ]
        )

    def test_a_guard_that_refuses_keeps_the_old_file(self) -> None:
        @contextmanager
        def guard(path: Path) -> Iterator[None]:
            raise PermissionError("in use")
            yield

        with self.assertRaises(PermissionError):
            with replacing(Path("/data/model.ctb"), guard=guard) as scratch:
                scratch.write_bytes(b"new")
        expect(Path("/data/model.ctb").read_bytes()).to_equal(b"old")
        expect(self._names()).to_equal(["model.ctb"])


class RealFilesystemReplacingTest(TestCase):
    """Overlapping writers, on a real filesystem with real threads."""

    def test_overlapping_uploads_never_mix_their_contents(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "model.ctb"
            barrier = threading.Barrier(2)
            errors = []

            def upload(byte: bytes) -> None:
                try:
                    with replacing(destination) as scratch:
                        with open(scratch, "wb") as file:
                            barrier.wait(timeout=5)
                            for _ in range(200):
                                file.write(byte * 4096)
                except Exception as error:  # pragma: no cover - a failure
                    errors.append(error)

            threads = [
                threading.Thread(target=upload, args=(byte,)) for byte in (b"A", b"B")
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            expect(errors).to_equal([])
            contents = destination.read_bytes()
            expect(len(contents)).to_equal(200 * 4096)
            expect(len(set(contents))).to_equal(1)
            expect(os.listdir(directory)).to_equal(["model.ctb"])


class ScratchFilesTest(TestCase):
    fs: FakeFilesystem

    def setUp(self) -> None:
        _get_config.cache_clear()
        self.setUpPyfakefs(additional_skip_names=["importlib.metadata"])
        self.fs.create_file("/mnt/usb_share/model.ctb", contents=b"x")

    def test_is_hidden_entry(self) -> None:
        expect(is_hidden_entry(".upload-0123456789abcdef.part")).to_equal(True)
        expect(is_hidden_entry(".sdcp_uploads")).to_equal(True)
        for name in ("model.ctb", ".hidden", "sdcp_uploads"):
            expect(is_hidden_entry(name)).to_equal(False)

    def test_is_scratch_file(self) -> None:
        expect(is_scratch_file(".upload-0123456789abcdef.part")).to_equal(True)
        for name in ("model.ctb", ".upload-notes.txt", "model.part", ".hidden"):
            expect(is_scratch_file(name)).to_equal(False)

    def test_scratch_path_beside(self) -> None:
        first = scratch_path_beside(Path("/mnt/usb_share/sub/model.ctb"))
        second = scratch_path_beside(Path("/mnt/usb_share/sub/model.ctb"))
        expect(first.parent).to_equal(Path("/mnt/usb_share/sub"))
        expect(is_scratch_file(first.name)).to_equal(True)
        expect(first).not_to_equal(second)

    def test_remove_stale_scratch_files(self) -> None:
        self.fs.create_file("/mnt/usb_share/.upload-aaaa.part", contents=b"x")
        self.fs.create_file("/mnt/usb_share/sub/.upload-bbbb.part", contents=b"x")
        self.fs.create_file("/mnt/usb_share/sub/keep.ctb", contents=b"x")
        # A folder that was being deleted, and an unfinished SDCP transfer.
        self.fs.create_file("/mnt/usb_share/.upload-cccc.part/old.ctb", contents=b"x")
        self.fs.create_file("/mnt/usb_share/.sdcp_uploads/dddd.part", contents=b"x")

        expect(remove_stale_scratch_files()).to_equal(4)

        expect(sorted(os.listdir("/mnt/usb_share"))).to_equal(["model.ctb", "sub"])
        expect(os.listdir("/mnt/usb_share/sub")).to_equal(["keep.ctb"])

    def test_remove_stale_scratch_files_without_a_files_directory(self) -> None:
        self.fs.remove_object("/mnt/usb_share/model.ctb")
        self.fs.remove_object("/mnt/usb_share")
        expect(remove_stale_scratch_files()).to_equal(0)
