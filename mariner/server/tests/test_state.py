import os
import stat
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from pyexpect import expect

from mariner.server import state


class StateDirectoryTest(TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        state.forget()
        self.addCleanup(state.forget)

    def _configured(self, wanted: Path) -> None:
        patcher = patch("mariner.config.get_state_directory", return_value=str(wanted))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_folder_asked_for_is_made_for_this_account_alone(self) -> None:
        wanted = self.root / "state"
        self._configured(wanted)
        expect(state.directory()).to_equal(wanted)
        expect(stat.S_IMODE(os.stat(wanted).st_mode)).to_equal(0o700)

    def test_a_folder_open_to_others_is_closed_to_them(self) -> None:
        # What is kept there says who may drive the printer.
        wanted = self.root / "state"
        wanted.mkdir(mode=0o755)
        os.chmod(wanted, 0o755)
        self._configured(wanted)
        expect(state.directory()).to_equal(wanted)
        expect(stat.S_IMODE(os.stat(wanted).st_mode)).to_equal(0o700)

    def test_a_folder_that_cannot_be_used_does_not_stop_the_start(self) -> None:
        blocked = self.root / "a-file"
        blocked.write_bytes(b"x")
        self._configured(blocked / "state")
        with patch("mariner.server.state._FALLBACKS", [str(self.root / "own")]):
            with self.assertLogs("mariner.server.state", level="WARNING"):
                used = state.directory()
        expect(used).to_equal(self.root / "own")
        expect(stat.S_IMODE(os.stat(used).st_mode)).to_equal(0o700)

    def test_a_folder_reached_through_a_link_is_not_used(self) -> None:
        # It could lead to where another account reads or writes.
        real = self.root / "real"
        real.mkdir()
        link = self.root / "link"
        link.symlink_to(real)
        self._configured(link)
        with patch("mariner.server.state._FALLBACKS", [str(self.root / "own")]):
            with self.assertLogs("mariner.server.state", level="WARNING"):
                used = state.directory()
        expect(used).to_equal(self.root / "own")

    def test_it_is_looked_for_once(self) -> None:
        wanted = self.root / "state"
        self._configured(wanted)
        state.directory()
        with patch("mariner.server.state._usable", side_effect=AssertionError):
            expect(state.directory()).to_equal(wanted)


class KeptSecretTest(TestCase):
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

    def test_the_session_key_is_the_same_from_one_start_to_the_next(self) -> None:
        # A page left open goes on working after Mariner restarts.
        first = state.session_key()
        expect(len(first)).to_equal(32)
        state.forget()
        expect(state.session_key()).to_equal(first)

    def test_the_session_key_can_be_read_by_this_account_alone(self) -> None:
        state.session_key()
        kept = self.root / "s" / "session.key"
        expect(stat.S_IMODE(os.stat(kept).st_mode)).to_equal(0o600)

    def test_a_key_cut_short_is_made_again(self) -> None:
        # By a card pulled as it was written: a short key signs nothing
        # safely.
        state.session_key()
        kept = self.root / "s" / "session.key"
        kept.write_bytes(b"short")
        state.forget()
        with self.assertLogs("mariner.server.state", level="WARNING"):
            again = state.session_key()
        expect(len(again)).to_equal(32)
        expect(kept.read_bytes()).to_equal(again)

    def test_a_key_left_readable_by_others_is_made_again(self) -> None:
        first = state.session_key()
        kept = self.root / "s" / "session.key"
        os.chmod(kept, 0o644)
        state.forget()
        with self.assertLogs("mariner.server.state", level="WARNING"):
            again = state.session_key()
        expect(again == first).to_equal(False)
        expect(stat.S_IMODE(os.stat(kept).st_mode)).to_equal(0o600)

    def test_a_key_that_is_a_link_is_not_followed(self) -> None:
        elsewhere = self.root / "elsewhere"
        elsewhere.write_bytes(b"k" * 32)
        os.chmod(elsewhere, 0o600)
        (self.root / "s").mkdir(mode=0o700)
        (self.root / "s" / "session.key").symlink_to(elsewhere)
        with self.assertLogs("mariner.server.state", level="WARNING"):
            key = state.session_key()
        expect(key == b"k" * 32).to_equal(False)
        expect((self.root / "s" / "session.key").is_symlink()).to_equal(False)
        expect(elsewhere.read_bytes()).to_equal(b"k" * 32)

    def test_writing_replaces_whole_or_not_at_all(self) -> None:
        state.write("note", b"first")
        expect(state.read("note")).to_equal(b"first")
        with patch("os.replace", side_effect=OSError("card pulled")):
            with self.assertRaises(OSError):
                state.write("note", b"second")
        expect(state.read("note")).to_equal(b"first")
        expect(sorted(os.listdir(self.root / "s"))).to_equal(["note"])

    def test_what_is_not_there_reads_as_nothing(self) -> None:
        expect(state.read("absent")).to_equal(None)

    def test_names_stay_inside_the_folder(self) -> None:
        for name in ("../out", "a/b", "", ".", ".."):
            with self.assertRaises(ValueError):
                state.write(name, b"x")
            with self.assertRaises(ValueError):
                state.read(name)

    def test_removing_what_is_not_there_is_fine(self) -> None:
        state.write("note", b"x")
        state.remove("note")
        state.remove("note")
        expect(state.read("note")).to_equal(None)


class DegradedTest(TestCase):
    """What is kept says who may drive the printer: when it cannot be
    reached, that must not read as "nothing was ever set"."""

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        state.forget()
        self.addCleanup(state.forget)

    def _configured(self, wanted: Path) -> None:
        patcher = patch("mariner.config.get_state_directory", return_value=str(wanted))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_folder_asked_for_is_not_a_makeshift(self) -> None:
        self._configured(self.root / "state")
        state.directory()
        expect(state.is_makeshift()).to_equal(False)

    def test_a_folder_of_the_account_s_home_is_not_one_when_none_was_there(
        self,
    ) -> None:
        # Mariner run by hand, outside its service: nothing was kept
        # where the service would keep it.
        blocked = self.root / "a-file"
        blocked.write_bytes(b"x")
        self._configured(blocked / "state")
        with patch("mariner.server.state._FALLBACKS", [str(self.root / "own")]):
            with self.assertLogs("mariner.server.state", level="WARNING"):
                state.directory()
        expect(state.is_makeshift()).to_equal(False)

    def test_another_folder_is_one_when_the_one_asked_for_is_there(self) -> None:
        # There, but not usable: of another account after a restore, or
        # on a drive gone read-only. What it holds was not read.
        wanted = self.root / "state"
        wanted.mkdir()
        self._configured(wanted)
        with patch("mariner.server.state._usable", side_effect=[False, True]):
            with patch("mariner.server.state._FALLBACKS", [str(self.root / "own")]):
                with self.assertLogs("mariner.server.state", level="WARNING"):
                    state.directory()
        expect(state.is_makeshift()).to_equal(True)

    def test_a_folder_that_does_not_outlast_a_restart_is_one(self) -> None:
        blocked = self.root / "a-file"
        blocked.write_bytes(b"x")
        self._configured(blocked / "state")
        with patch("mariner.server.state._FALLBACKS", [str(blocked / "own")]):
            with self.assertLogs("mariner.server.state", level="WARNING"):
                state.directory()
        expect(state.is_makeshift()).to_equal(True)

    def test_looking_makes_no_folder(self) -> None:
        wanted = self.root / "state"
        wanted.mkdir()
        self._configured(wanted)
        made = []
        with patch("mariner.server.state._usable", return_value=False), patch(
            "mariner.server.state._FALLBACKS", [str(self.root / "own")]
        ), patch(
            "tempfile.mkdtemp", side_effect=lambda **k: made.append(1) or "/nowhere"
        ):
            expect(state.read("anything")).to_equal(None)
        expect(made).to_equal([])
        expect((self.root / "own").exists()).to_equal(False)
