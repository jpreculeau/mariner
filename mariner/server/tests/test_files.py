import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import patch

from pyexpect import expect
from pyfakefs.fake_filesystem import FakeFilesystem
from pyfakefs.fake_filesystem_unittest import TestCase

from mariner.config import _get_config
from mariner.server.files import (
    NotPrintable,
    holds_a_transfer_in_progress,
    is_directory,
    is_hidden_entry,
    is_regular_file,
    is_scratch_file,
    move_aside,
    printable_relative_path,
    remove_entry,
    remove_stale_scratch_files,
    replacing,
    resolve_entry_in_files_directory,
    resolve_in_files_directory,
    safe_filename,
    scratch_path_beside,
    stays_in_files_directory,
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

    def test_rejects_characters_that_end_a_line_for_some_readers(self) -> None:
        # Not line breaks to the printer, but a log viewer may take them
        # for one: NEL, another C1 control, LINE and PARAGRAPH SEPARATOR.
        for character in ("\x85", "\x9b", "\u2028", "\u2029"):
            expect(safe_filename(f"a{character}b.ctb")).to_equal(None)

    def test_rejects_a_line_break_at_either_end_instead_of_trimming_it(self) -> None:
        # Trimming would accept the name while the caller's copy, and the
        # request path, still carry the line break.
        for name in (
            "\nmodel.ctb",
            "model.ctb\r\n",
            "\x85model.ctb",
            "model.ctb\u2028",
        ):
            expect(safe_filename(name)).to_equal(None)
        expect(safe_filename("  model.ctb ")).to_equal("model.ctb")

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
        # FAT ignores case: these would be the very same entries.
        expect(safe_filename(".UPLOAD-0123456789ABCDEF.PART")).to_equal(None)
        expect(safe_filename(".Sdcp_Uploads")).to_equal(None)

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
            ".SDCP_UPLOADS/abcd.part",
            "sub/.Upload-0123ABCD.Part",
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


class RealFilesystemHiddenEntryTest(TestCase):
    """A hidden entry reached under another name, as FAT aliases allow."""

    def test_refuses_another_name_for_a_hidden_entry(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            scratch = Path(directory) / ".upload-0123456789abcdef.part"
            scratch.write_bytes(b"half an upload")
            # Stands for the short alias FAT gives the same entry.
            os.link(scratch, Path(directory) / "UPLOAD~1.PAR")
            (Path(directory) / "model.ctb").write_bytes(b"x")
            with patch(
                "mariner.server.files.config.get_files_directory",
                return_value=Path(directory),
            ):
                expect(resolve_in_files_directory("UPLOAD~1.PAR")).to_equal(None)
                expect(resolve_entry_in_files_directory("UPLOAD~1.PAR")).to_equal(None)
                expect(resolve_in_files_directory("model.ctb")).to_equal(
                    Path(directory).resolve() / "model.ctb"
                )

    def test_refuses_text_that_is_no_path_while_a_transfer_is_beside_it(
        self,
    ) -> None:
        # With a hidden entry in the folder, every name is compared with it
        # on disk. Text that cannot be a path must be refused, not raise.
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / ".sdcp_uploads").mkdir()
            (Path(directory) / "sub").mkdir()
            (Path(directory) / "sub" / ".upload-0123456789abcdef.part").write_bytes(
                b"half an upload"
            )
            with patch(
                "mariner.server.files.config.get_files_directory",
                return_value=Path(directory),
            ):
                for text in ("a\x00b.ctb", "\ud800.ctb", "sub/a\x00b", "sub/\ud800"):
                    expect(resolve_entry_in_files_directory(text)).to_equal(None)
                    expect(resolve_in_files_directory(text)).to_equal(None)

    def test_a_hidden_entry_that_cannot_be_read_does_not_hide_the_others(
        self,
    ) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # Listed first, and leads nowhere: a transfer that just ended.
            os.symlink(root / "gone", root / ".upload-0000000000000000.part")
            scratch = root / ".upload-ffffffffffffffff.part"
            scratch.write_bytes(b"half an upload")
            os.link(scratch, root / "UPLOAD~1.PAR")
            with patch(
                "mariner.server.files.config.get_files_directory", return_value=root
            ):
                expect(resolve_in_files_directory("UPLOAD~1.PAR")).to_equal(None)

    def test_remove_entry_leaves_a_hidden_entry_alone(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scratch = root / ".upload-0123456789abcdef.part"
            scratch.write_bytes(b"half an upload")
            os.link(scratch, root / "UPLOAD~1.PAR")
            (root / "model.ctb").write_bytes(b"x")

            # As if the transfer had begun after the name was checked.
            with self.assertRaises(FileNotFoundError):
                remove_entry(root / "UPLOAD~1.PAR")
            expect((root / "UPLOAD~1.PAR").exists()).to_equal(True)

            remove_entry(root / "model.ctb")
            expect((root / "model.ctb").exists()).to_equal(False)

    def test_move_aside_leaves_a_hidden_folder_alone(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".sdcp_uploads").mkdir()
            (root / ".sdcp_uploads" / "abcd.part").write_bytes(b"half an upload")
            # Another name for the same folder, as a FAT alias is.
            os.symlink(root / ".sdcp_uploads", root / "SDCP_U~1")
            (root / "batch").mkdir()

            with self.assertRaises(FileNotFoundError):
                move_aside(root / "SDCP_U~1")
            expect((root / ".sdcp_uploads" / "abcd.part").exists()).to_equal(True)

            aside = move_aside(root / "batch")
            expect((root / "batch").exists()).to_equal(False)
            expect(aside.is_dir()).to_equal(True)
            expect(is_scratch_file(aside.name)).to_equal(True)

    def test_a_link_that_leads_back_to_itself_is_refused(self) -> None:
        # Before Python 3.13, resolving one raises RuntimeError.
        root = Path("/mnt/usb_share")
        with patch("mariner.server.files.config.get_files_directory") as directory:
            directory.return_value.resolve.return_value = root
            with patch.object(Path, "resolve", side_effect=RuntimeError("loop")):
                expect(resolve_in_files_directory("loop.ctb")).to_equal(None)
                expect(stays_in_files_directory(root / "loop.ctb")).to_equal(False)

    def test_an_entry_that_cannot_be_asked_is_neither_folder_nor_file(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            os.symlink("loop.ctb", Path(directory) / "loop.ctb")
            (Path(directory) / "sub").mkdir()
            (Path(directory) / "model.ctb").write_bytes(b"x")
            with os.scandir(directory) as entries:
                found = {entry.name: entry for entry in entries}
            expect(is_directory(found["loop.ctb"])).to_equal(False)
            expect(is_regular_file(found["loop.ctb"])).to_equal(False)
            expect(is_directory(found["sub"])).to_equal(True)
            expect(is_regular_file(found["sub"])).to_equal(False)
            expect(is_regular_file(found["model.ctb"])).to_equal(True)


class RealFilesystemLinksTest(TestCase):
    """Where a directory entry leads, links followed, on a real filesystem."""

    def test_stays_in_files_directory(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as outside:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (Path(outside) / "secret.ctb").write_bytes(b"x")
                (root / "model.ctb").write_bytes(b"x")
                (root / ".sdcp_uploads").mkdir()
                (root / ".upload-0123456789abcdef.part").write_bytes(b"x")
                os.symlink(Path(outside) / "secret.ctb", root / "way-out.ctb")
                os.symlink(outside, root / "way-out")
                os.symlink(root / ".sdcp_uploads", root / "to-transfers")
                os.symlink(
                    root / ".upload-0123456789abcdef.part", root / "to-upload.ctb"
                )
                os.symlink(root / "model.ctb", root / "alias.ctb")
                os.symlink(root / "gone.ctb", root / "dangling.ctb")
                with patch(
                    "mariner.server.files.config.get_files_directory",
                    return_value=root,
                ):
                    for name in ("model.ctb", "alias.ctb", "dangling.ctb"):
                        expect(stays_in_files_directory(root / name)).to_equal(True)
                    for name in (
                        "way-out.ctb",
                        "way-out",
                        "to-transfers",
                        "to-upload.ctb",
                    ):
                        expect(stays_in_files_directory(root / name)).to_equal(False)


class TransferInProgressTest(TestCase):
    fs: FakeFilesystem

    def setUp(self) -> None:
        _get_config.cache_clear()
        self.setUpPyfakefs(additional_skip_names=["importlib.metadata"])
        self.fs.create_file("/mnt/usb_share/batch/part.ctb", contents=b"x")

    def test_a_folder_of_finished_files_holds_no_transfer(self) -> None:
        expect(holds_a_transfer_in_progress(Path("/mnt/usb_share/batch"))).to_equal(
            False
        )

    def test_a_scratch_file_at_any_depth_is_a_transfer(self) -> None:
        self.fs.create_file(
            "/mnt/usb_share/batch/deep/.UPLOAD-0123456789abcdef.part", contents=b"x"
        )
        expect(holds_a_transfer_in_progress(Path("/mnt/usb_share/batch"))).to_equal(
            True
        )

    def test_a_folder_named_like_a_scratch_file_is_not_a_transfer(self) -> None:
        self.fs.create_dir("/mnt/usb_share/batch/.upload-0123456789abcdef.part")
        expect(holds_a_transfer_in_progress(Path("/mnt/usb_share/batch"))).to_equal(
            False
        )

    def test_a_folder_that_cannot_be_read_is_taken_to_hold_one(self) -> None:
        # Not knowing is no ground for removing it.
        def walk_into_a_locked_folder(top: Any, onerror: Any = None) -> Any:
            # What the walk does with a folder it may not list.
            if onerror is not None:
                onerror(PermissionError("denied"))
            return iter(())

        with patch("mariner.server.files.walk", walk_into_a_locked_folder):
            expect(holds_a_transfer_in_progress(Path("/mnt/usb_share/batch"))).to_equal(
                True
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

    def test_refuses_a_link_to_a_file_the_printer_could_not_be_told_about(
        self,
    ) -> None:
        # The link has a fine name; the file it leads to, which is the one
        # the printer would be given, does not.
        self.fs.create_file("/mnt/usb_share/it's.ctb", contents=b"x")
        self.fs.create_symlink("/mnt/usb_share/link.ctb", "/mnt/usb_share/it's.ctb")
        with self.assertRaises(NotPrintable) as raised:
            printable_relative_path("link.ctb")
        expect(raised.exception.reason).to_equal(NotPrintable.UNSAFE)

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
        expect(is_hidden_entry(".Upload-0123456789ABCDEF.Part")).to_equal(True)
        expect(is_hidden_entry(".SDCP_UPLOADS")).to_equal(True)
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
