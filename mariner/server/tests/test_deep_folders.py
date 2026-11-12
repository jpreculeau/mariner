"""Folders nested deeper than any honest use: nothing may fail on them."""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pyexpect import expect

from mariner.server import files
from mariner.server.files import (
    MAX_FOLDER_DEPTH,
    folder_depth,
    holds_a_transfer_in_progress,
    printable_files,
    remove_stale_scratch_files,
    walk,
)

# Deeper than Python lets a function call itself.
DEPTH = sys.getrecursionlimit() + 200


class DeepFoldersTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(self._remove, self.root)
        (self.root / "a.ctb").write_bytes(b"x")
        # Built and entered one level at a time: a path of this many levels
        # is longer than the system takes in one piece.
        here = os.open(self.root, os.O_RDONLY)
        try:
            for _ in range(DEPTH):
                os.mkdir("d", dir_fd=here)
                below = os.open("d", os.O_RDONLY, dir_fd=here)
                os.close(here)
                here = below
        finally:
            os.close(here)
        (self.root / "z").mkdir()
        (self.root / "z" / "b.ctb").write_bytes(b"x")
        (self.root / "z" / ".upload-0123456789abcdef.part").write_bytes(b"x")
        patcher = patch("mariner.config.get_files_directory", return_value=self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def _remove(root: Path) -> None:
        # From the bottom up, by renaming the chain short first.
        while (root / "d" / "d").is_dir():
            os.rename(root / "d" / "d", root / "moved")
            os.rmdir(root / "d")
            os.rename(root / "moved", root / "d")
        shutil.rmtree(root)

    def test_the_start_up_cleaning_goes_through(self) -> None:
        expect(remove_stale_scratch_files()).to_equal(1)
        expect(os.listdir(self.root / "z")).to_equal(["b.ctb"])

    def test_the_start_up_reading_goes_through(self) -> None:
        found = sorted(path.name for path in printable_files())
        expect(found).to_equal(["a.ctb", "b.ctb"])

    def test_looking_for_transfers_goes_through(self) -> None:
        expect(holds_a_transfer_in_progress(self.root / "z")).to_equal(True)
        # Not knowing what lies below is no ground for calling it free.
        expect(holds_a_transfer_in_progress(self.root / "d")).to_equal(True)

    def test_a_walk_stops_going_down_well_before_trouble(self) -> None:
        deepest = max(
            len(Path(folder).relative_to(self.root).parts)
            for folder, _, _ in walk(self.root)
        )
        expect(deepest).to_equal(files.MAX_WALK_DEPTH)


class WalkTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        (self.root / "sub" / "below").mkdir(parents=True)
        (self.root / "a.ctb").write_bytes(b"x")
        (self.root / "sub" / "b.ctb").write_bytes(b"x")
        (self.root / "sub" / "below" / "c.ctb").write_bytes(b"x")

    def test_gives_every_folder_with_its_folders_and_files(self) -> None:
        os.symlink(self.root / "sub", self.root / "link")
        seen = {
            str(Path(folder).relative_to(self.root)): (sorted(folders), sorted(names))
            for folder, folders, names in walk(self.root)
        }
        expect(seen).to_equal(
            {
                # A link to a folder is named among the folders, as os.walk
                # does, and not entered.
                ".": (["link", "sub"], ["a.ctb"]),
                "sub": (["below"], ["b.ctb"]),
                "sub/below": ([], ["c.ctb"]),
            }
        )

    def test_folders_taken_out_of_the_list_are_not_entered(self) -> None:
        visited = []
        for folder, folders, _ in walk(self.root):
            visited.append(Path(folder).name)
            folders[:] = [name for name in folders if name != "below"]
        expect(sorted(visited)).to_equal(sorted([self.root.name, "sub"]))

    def test_a_folder_that_cannot_be_read_is_reported_and_passed(self) -> None:
        (self.root / "other").mkdir()
        real_scandir = os.scandir
        # Each of the two in turn: whichever comes first, the other is
        # still gone through.
        for failing, passing in (("sub", "other"), ("other", "sub")):
            errors: list = []

            def scandir(path: object, failing: str = failing) -> object:
                if str(path).endswith(failing):
                    raise OSError(5, "Input/output error")
                return real_scandir(path)  # type: ignore[call-overload]

            with patch("os.scandir", side_effect=scandir):
                visited = [Path(f).name for f, _, _ in walk(self.root, errors.append)]
            expect(passing in visited).to_equal(True)
            expect(failing in visited).to_equal(False)
            expect(len(errors)).to_equal(1)

    def test_folder_depth(self) -> None:
        with patch("mariner.config.get_files_directory", return_value=self.root):
            expect(folder_depth(self.root)).to_equal(0)
            expect(folder_depth(self.root / "sub")).to_equal(1)
            expect(folder_depth(self.root / "sub" / "below")).to_equal(2)
        expect(MAX_FOLDER_DEPTH).to_equal(16)
