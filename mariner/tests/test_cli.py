import io
import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from pyexpect import expect

from mariner import cli, passwords


class CommandLineTest(TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.state = self.root / "state"
        patcher = patch(
            "mariner.config.get_state_directory", return_value=str(self.state)
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        cost = patch.object(passwords, "SCRYPT_N", 2**4)
        cost.start()
        self.addCleanup(cost.stop)
        self.out = io.StringIO()

    def _run(self, *arguments: str, typed: tuple = ()) -> int:
        answers = iter(typed)
        with patch.object(sys, "argv", ["mariner", *arguments]), patch(
            "getpass.getpass", side_effect=lambda prompt="": next(answers)
        ), patch.object(sys, "stdout", self.out), patch.object(sys, "stderr", self.out):
            try:
                cli.main()
            except SystemExit as stopped:
                return int(stopped.code or 0)
        return 0

    def test_with_nothing_asked_it_starts_mariner(self) -> None:
        with patch("mariner.cli._serve") as serve:
            expect(self._run()).to_equal(0)
        serve.assert_called_once_with()

    def test_what_it_does_not_know_is_said_and_nothing_is_started(self) -> None:
        with patch("mariner.cli._serve") as serve:
            expect(self._run("--frobnicate")).to_equal(2)
        serve.assert_not_called()
        expect("reset-password" in self.out.getvalue()).to_equal(True)
        expect("set-password" in self.out.getvalue()).to_equal(True)

    def test_the_commands_do_not_load_the_server(self) -> None:
        # Run by an administrator: loading it makes folders, as that
        # account, where the service would then not use them.
        loaded = set(sys.modules)
        self._run("reset-password")
        self._run("set-password", typed=("long enough!", "long enough!"))
        new = {name for name in set(sys.modules) - loaded}
        expect(
            sorted(name for name in new if name.startswith("mariner.server"))
        ).to_equal([])

    def test_set_password_keeps_the_one_typed_twice(self) -> None:
        # Before the page is ever opened: nobody else gets to choose it.
        expect(
            self._run("set-password", typed=("long enough!", "long enough!"))
        ).to_equal(0)
        kept = self.state / "password"
        record = json.loads(kept.read_bytes())
        expect(passwords.matches(record, "long enough!")).to_equal(True)
        expect(stat.S_IMODE(os.stat(kept).st_mode)).to_equal(0o600)
        expect(stat.S_IMODE(os.stat(self.state).st_mode)).to_equal(0o700)
        expect("long enough!" in self.out.getvalue()).to_equal(False)

    def test_set_password_refuses_two_that_differ(self) -> None:
        expect(
            self._run("set-password", typed=("long enough!", "long enough?"))
        ).to_equal(1)
        expect((self.state / "password").exists()).to_equal(False)

    def test_set_password_says_why_one_is_not_taken(self) -> None:
        expect(self._run("set-password", typed=("short", "short"))).to_equal(1)
        expect("8 characters" in self.out.getvalue()).to_equal(True)

    def test_set_password_replaces_the_one_in_place(self) -> None:
        self._run("set-password", typed=("long enough!", "long enough!"))
        first = json.loads((self.state / "password").read_bytes())
        self._run("set-password", typed=("another one!", "another one!"))
        second = json.loads((self.state / "password").read_bytes())
        expect(passwords.matches(second, "another one!")).to_equal(True)
        # Whoever was signed in under the first no longer is.
        expect(second["generation"] == first["generation"]).to_equal(False)

    def test_the_file_is_given_to_the_account_the_folder_belongs_to(self) -> None:
        # Run with sudo, the file would be root's, and the service would
        # not take it.
        self.state.mkdir(mode=0o700)
        with patch("os.geteuid", return_value=0), patch("os.chown") as chown:
            self._run("set-password", typed=("long enough!", "long enough!"))
        owner = os.stat(self.state)
        chown.assert_called_once_with(
            str(self.state / "password"), owner.st_uid, owner.st_gid
        )

    def test_reset_password_clears_it(self) -> None:
        self._run("set-password", typed=("long enough!", "long enough!"))
        expect(self._run("reset-password")).to_equal(0)
        expect((self.state / "password").exists()).to_equal(False)
        # It says which folder it acted on.
        expect(str(self.state) in self.out.getvalue()).to_equal(True)

    def test_reset_password_says_so_when_there_was_none(self) -> None:
        expect(self._run("reset-password")).to_equal(0)
        expect("no password" in self.out.getvalue().lower()).to_equal(True)

    def test_reset_password_says_so_when_it_may_not(self) -> None:
        self._run("set-password", typed=("long enough!", "long enough!"))
        with patch("os.unlink", side_effect=PermissionError("not yours")):
            expect(self._run("reset-password")).to_equal(1)
        expect("sudo" in self.out.getvalue()).to_equal(True)
