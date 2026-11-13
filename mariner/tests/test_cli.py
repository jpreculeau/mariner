import io
import json
import os
import re
import stat
import sys
import tempfile
import time
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from pyexpect import expect

from mariner import cli, passwords, totp


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
        # Never the folder in the home of whoever runs the tests.
        fallbacks = patch("mariner.config.STATE_FALLBACKS", [str(self.root / "own")])
        fallbacks.start()
        self.addCleanup(fallbacks.stop)
        # Whether or not the computer the tests run on has the service.
        service = patch.object(cli, "_runs_under_another_account", return_value=False)
        service.start()
        self.addCleanup(service.stop)
        cost = patch.object(passwords, "SCRYPT_N", 2**4)
        cost.start()
        self.addCleanup(cost.stop)
        self.out = io.StringIO()

    def _run(self, *arguments: str, typed: tuple = (), euid: int = 1000) -> int:
        answers = iter(typed)

        def answer(prompt: str = "") -> str:
            # What is typed may depend on what was shown.
            given = next(answers)
            return given() if callable(given) else given

        # Not as an administrator unless a test says so, whoever runs
        # the tests.
        with patch("os.geteuid", return_value=euid), patch.object(
            sys, "argv", ["mariner", *arguments]
        ), patch("getpass.getpass", side_effect=answer), patch(
            "builtins.input", side_effect=answer
        ), patch.object(
            sys, "stdout", self.out
        ), patch.object(
            sys, "stderr", self.out
        ):
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
        self._run("set-password", typed=("long enough now!", "long enough now!"))
        new = {name for name in set(sys.modules) - loaded}
        expect(
            sorted(name for name in new if name.startswith("mariner.server"))
        ).to_equal([])

    def test_set_password_keeps_the_one_typed_twice(self) -> None:
        # Before the page is ever opened: nobody else gets to choose it.
        expect(
            self._run("set-password", typed=("long enough now!", "long enough now!"))
        ).to_equal(0)
        kept = self.state / "password"
        record = json.loads(kept.read_bytes())
        expect(passwords.matches(record, "long enough now!")).to_equal(True)
        expect(stat.S_IMODE(os.stat(kept).st_mode)).to_equal(0o600)
        expect(stat.S_IMODE(os.stat(self.state).st_mode)).to_equal(0o700)
        expect("long enough now!" in self.out.getvalue()).to_equal(False)

    def test_set_password_refuses_two_that_differ(self) -> None:
        expect(
            self._run("set-password", typed=("long enough now!", "long enough now?"))
        ).to_equal(1)
        expect((self.state / "password").exists()).to_equal(False)

    def test_set_password_says_why_one_is_not_taken(self) -> None:
        expect(self._run("set-password", typed=("short", "short"))).to_equal(1)
        expect("14 characters" in self.out.getvalue()).to_equal(True)

    def test_set_password_replaces_the_one_in_place(self) -> None:
        self._run("set-password", typed=("long enough now!", "long enough now!"))
        first = json.loads((self.state / "password").read_bytes())
        self._run(
            "set-password", typed=("another one, longer!", "another one, longer!")
        )
        second = json.loads((self.state / "password").read_bytes())
        expect(passwords.matches(second, "another one, longer!")).to_equal(True)
        # Whoever was signed in under the first no longer is.
        expect(second["generation"] == first["generation"]).to_equal(False)

    def test_the_file_is_given_to_the_account_the_folder_belongs_to(self) -> None:
        # Run with sudo, the file would be root's, and the service would
        # not take it.
        self.state.mkdir(mode=0o700)
        with patch("os.fchown") as chown:
            self._run(
                "set-password", typed=("long enough now!", "long enough now!"), euid=0
            )
        owner = os.stat(self.state)
        expect(chown.call_args[0][1:]).to_equal((owner.st_uid, owner.st_gid))

    def test_the_file_changes_hands_before_it_is_put_in_place(self) -> None:
        # Changed after, by its name, a link put there meanwhile would
        # hand over whatever it leads to.
        self.state.mkdir(mode=0o700)
        order = []
        real_replace = os.replace
        with patch("os.fchown", side_effect=lambda *a: order.append("owner")), patch(
            "os.chown"
        ) as by_name, patch(
            "os.replace",
            side_effect=lambda a, b: (order.append("placed"), real_replace(a, b)),
        ):
            self._run(
                "set-password", typed=("long enough now!", "long enough now!"), euid=0
            )
        expect(order).to_equal(["owner", "placed"])
        by_name.assert_not_called()

    def test_a_folder_that_is_a_link_is_not_written_into(self) -> None:
        real = self.root / "real"
        real.mkdir()
        self.state.symlink_to(real)
        expect(
            self._run("set-password", typed=("long enough now!", "long enough now!"))
        ).to_equal(1)
        expect(list(real.iterdir())).to_equal([])

    def test_an_administrator_does_not_make_the_folder_of_the_service(self) -> None:
        # Made by root, the service would not use it, and its page would
        # stay shut.
        expect(
            self._run(
                "set-password", typed=("long enough now!", "long enough now!"), euid=0
            )
        ).to_equal(1)
        expect(self.state.exists()).to_equal(False)
        expect("start Mariner once" in self.out.getvalue()).to_equal(True)

    def test_setting_or_clearing_ends_what_was_signed_with_the_old_key(self) -> None:
        # At the next start of Mariner: a copy of the folder made before
        # is then of no use.
        self.state.mkdir(mode=0o700)
        (self.state / "session.key").write_bytes(b"k" * 32)
        self._run("set-password", typed=("long enough now!", "long enough now!"))
        expect((self.state / "session.key").exists()).to_equal(False)
        (self.state / "session.key").write_bytes(b"k" * 32)
        self._run("reset-password")
        expect((self.state / "session.key").exists()).to_equal(False)

    def test_the_commands_do_not_load_the_server_in_a_process_of_their_own(
        self,
    ) -> None:
        import subprocess

        code = "\n".join(
            [
                "import sys",
                "from unittest.mock import patch",
                "from mariner import cli",
                "there = patch('mariner.config.get_state_directory',",
                f"    return_value={str(self.state)!r})",
                "apart = patch('mariner.config.STATE_FALLBACKS',",
                f"    [{str(self.root / 'own')!r}])",
                "asked = patch.object(sys, 'argv', ['mariner', 'reset-password'])",
                "with there, apart, asked:",
                "    try:",
                "        cli.main()",
                "    except SystemExit:",
                "        pass",
                "loaded = any(m.startswith('mariner.server') for m in sys.modules)",
                "print('LOADED' if loaded else 'CLEAN')",
            ]
        )
        done = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=60,
            # Not the home of whoever runs the tests either.
            env={**os.environ, "HOME": str(self.root / "home")},
        )
        expect(done.stdout.strip().splitlines()[-1]).to_equal("CLEAN")

    def _home_folder(self) -> Path:
        own = self.root / "home-state"
        patcher = patch("mariner.config.STATE_FALLBACKS", [str(own)])
        patcher.start()
        self.addCleanup(patcher.stop)
        return own

    def test_set_password_keeps_it_where_mariner_will_read_it(self) -> None:
        # The folder asked for is not there yet and can be made: Mariner
        # will make it and read there, not in the one a run by hand left
        # in the account's home.
        own = self._home_folder()
        own.mkdir(mode=0o700)
        expect(
            self._run("set-password", typed=("long enough now!", "long enough now!"))
        ).to_equal(0)
        expect((self.state / "password").exists()).to_equal(True)
        expect((own / "password").exists()).to_equal(False)

    def test_set_password_does_not_write_through_a_link(self) -> None:
        # Mariner does not use a folder reached by a link: it reads in
        # the account's home, and so the password goes there.
        own = self._home_folder()
        (self.root / "real").mkdir()
        os.symlink(self.root / "real", self.root / "link")
        with patch(
            "mariner.config.get_state_directory",
            return_value=str(self.root / "link" / "state"),
        ):
            expect(
                self._run(
                    "set-password", typed=("long enough now!", "long enough now!")
                )
            ).to_equal(0)
        expect((own / "password").exists()).to_equal(True)
        expect((self.root / "real" / "state").exists()).to_equal(False)

    def test_set_password_does_not_write_into_a_folder_mariner_will_not_use(
        self,
    ) -> None:
        # There, and reached through a link: Mariner refuses it and its
        # page stays shut. Saying "the password was set" would be false.
        (self.root / "real" / "state").mkdir(parents=True, mode=0o700)
        os.symlink(self.root / "real", self.root / "link")
        with patch(
            "mariner.config.get_state_directory",
            return_value=str(self.root / "link" / "state"),
        ):
            status = self._run(
                "set-password", typed=("long enough now!", "long enough now!")
            )
        expect(status).to_equal(1)
        expect("link" in self.out.getvalue()).to_equal(True)
        expect((self.root / "real" / "state" / "password").exists()).to_equal(False)

    def test_they_work_on_the_folder_mariner_fell_back_on(self) -> None:
        # Run by hand under an ordinary account, Mariner keeps its
        # password in that account's home when it cannot make the folder
        # it was told. Clearing it elsewhere would do nothing, and say
        # that all is well.
        own = self._home_folder()
        blocked = self.root / "a-file"
        blocked.write_bytes(b"x")
        with patch(
            "mariner.config.get_state_directory", return_value=str(blocked / "state")
        ):
            expect(
                self._run(
                    "set-password", typed=("long enough now!", "long enough now!")
                )
            ).to_equal(0)
            expect((own / "password").exists()).to_equal(True)
            expect(self._run("reset-password")).to_equal(0)
            expect((own / "password").exists()).to_equal(False)
        expect(str(own) in self.out.getvalue()).to_equal(True)

    def test_reset_password_finds_it_in_the_other_folder(self) -> None:
        own = self._home_folder()
        own.mkdir(mode=0o700)
        (own / "password").write_bytes(b"{}")
        self.state.mkdir(mode=0o700)
        expect(self._run("reset-password")).to_equal(0)
        expect((own / "password").exists()).to_equal(False)

    def test_reset_password_says_where_it_looked(self) -> None:
        own = self._home_folder()
        expect(self._run("reset-password")).to_equal(0)
        said = self.out.getvalue()
        expect(str(self.state) in said and str(own) in said).to_equal(True)

    def test_reset_password_clears_it(self) -> None:
        self._run("set-password", typed=("long enough now!", "long enough now!"))
        expect(self._run("reset-password")).to_equal(0)
        expect((self.state / "password").exists()).to_equal(False)
        # It says which folder it acted on.
        expect(str(self.state) in self.out.getvalue()).to_equal(True)

    def test_reset_password_says_so_when_there_was_none(self) -> None:
        expect(self._run("reset-password")).to_equal(0)
        expect("no password" in self.out.getvalue().lower()).to_equal(True)

    def test_reset_password_says_so_when_it_may_not(self) -> None:
        self._run("set-password", typed=("long enough now!", "long enough now!"))
        with patch("os.unlink", side_effect=PermissionError("not yours")):
            expect(self._run("reset-password")).to_equal(1)
        expect("sudo" in self.out.getvalue()).to_equal(True)

    def test_reset_password_does_not_say_none_was_set_when_it_cannot_look(
        self,
    ) -> None:
        # The folder of the service, which this account may not enter.
        self._run("set-password", typed=("long enough now!", "long enough now!"))
        kept = passwords.kept_path(str(self.state))
        real = os.lstat

        def lstat(path: object, *more: object, **named: object) -> os.stat_result:
            if str(path) == kept:
                raise PermissionError("not yours")
            return real(path, *more, **named)  # type: ignore

        self.out = io.StringIO()
        with patch("os.lstat", side_effect=lstat):
            expect(self._run("reset-password")).to_equal(1)
        said = self.out.getvalue()
        expect("sudo" in said).to_equal(True)
        expect("no password" in said.lower()).to_equal(False)
        expect(os.path.exists(kept)).to_equal(True)

    def test_set_password_makes_no_folder_of_its_own_beside_the_service(
        self,
    ) -> None:
        # Mariner runs under its own account, and has not started yet:
        # a password kept in this account's home would never be read.
        with patch.object(cli, "_runs_under_another_account", return_value=True):
            status = self._run(
                "set-password", typed=("long enough now!", "long enough now!")
            )
        expect(status).to_equal(1)
        expect("sudo" in self.out.getvalue()).to_equal(True)
        expect((self.root / "own").exists()).to_equal(False)
        expect(self.state.exists()).to_equal(False)

    def test_set_password_left_at_the_prompt_changes_nothing_and_says_so(
        self,
    ) -> None:
        self.state.mkdir(mode=0o700)
        for left in (EOFError(), KeyboardInterrupt()):
            self.out = io.StringIO()
            with patch.object(cli, "_folder_to_write", return_value=str(self.state)):
                with patch("mariner.cli.getpass.getpass", side_effect=left):
                    status = self._run_plain("set-password")
            expect(status).to_equal(1)
            expect("Nothing was changed" in self.out.getvalue()).to_equal(True)
        expect((self.state / "password").exists()).to_equal(False)

    def _run_plain(self, *arguments: str) -> int:
        with patch("os.geteuid", return_value=1000), patch.object(
            sys, "argv", ["mariner", *arguments]
        ), patch.object(sys, "stdout", self.out), patch.object(sys, "stderr", self.out):
            try:
                cli.main()
            except SystemExit as stopped:
                return int(stopped.code or 0)
        return 0

    # -- the one-time code ---------------------------------------------------

    def _shown_secret(self) -> str:
        found = re.search(r"secret=([A-Z2-7]+)&", self.out.getvalue())
        assert found is not None
        return found.group(1)

    def _code_of_the_moment(self) -> str:
        return totp.code_at(self._shown_secret(), time.time()) or ""

    def test_set_code_shows_the_key_and_keeps_it_once_a_code_is_typed(self) -> None:
        # For who sets Mariner up from a terminal, before any page is open.
        expect(self._run("set-code", typed=(self._code_of_the_moment,))).to_equal(0)
        secret = self._shown_secret()
        expect(totp.grouped(secret) in self.out.getvalue()).to_equal(True)
        kept = self.state / totp.KEPT_AS
        record = json.loads(kept.read_bytes())
        expect(record["secret"]).to_equal(secret)
        # The code that was typed has served.
        expect(isinstance(record["last"], int)).to_equal(True)
        expect(stat.S_IMODE(os.stat(kept).st_mode)).to_equal(0o600)

    def test_set_code_keeps_nothing_without_a_right_code(self) -> None:
        expect(self._run("set-code", typed=("000000", "111111", "222222"))).to_equal(1)
        expect((self.state / totp.KEPT_AS).exists()).to_equal(False)
        expect("Nothing was changed" in self.out.getvalue()).to_equal(True)

    def test_set_code_takes_a_second_try(self) -> None:
        expect(
            self._run("set-code", typed=("000000", self._code_of_the_moment))
        ).to_equal(0)
        expect((self.state / totp.KEPT_AS).exists()).to_equal(True)

    def test_set_code_left_at_the_prompt_changes_nothing(self) -> None:
        def leave() -> str:
            raise EOFError

        expect(self._run("set-code", typed=(leave,))).to_equal(1)
        expect((self.state / totp.KEPT_AS).exists()).to_equal(False)

    def test_reset_code_does_away_with_it(self) -> None:
        self._run("set-code", typed=(self._code_of_the_moment,))
        expect(self._run("reset-code")).to_equal(0)
        expect((self.state / totp.KEPT_AS).exists()).to_equal(False)
        expect("Internet" in self.out.getvalue()).to_equal(True)

    def test_reset_code_says_so_when_it_may_not_look(self) -> None:
        # Run without sudo: not "there was none", which would leave its
        # owner believing the code gone.
        with patch("os.lstat", side_effect=PermissionError("no")):
            expect(self._run("reset-code")).to_equal(1)
        expect("sudo" in self.out.getvalue()).to_equal(True)
        expect("no one-time code" in self.out.getvalue().lower()).to_equal(False)

    def test_set_code_shows_no_key_where_it_could_not_keep_it(self) -> None:
        # Else the phone is left with an account that opens nothing.
        self._run("set-password", typed=("long enough now!", "long enough now!"))
        os.chmod(self.state, 0o500)
        self.addCleanup(os.chmod, self.state, 0o700)
        if os.access(self.state, os.W_OK):
            self.skipTest("run by an account nothing is closed to")
        expect(self._run("set-code", typed=("000000",))).to_equal(1)
        expect("secret=" in self.out.getvalue()).to_equal(False)
        expect("sudo" in self.out.getvalue()).to_equal(True)

    def test_reset_code_says_so_when_there_was_none(self) -> None:
        expect(self._run("reset-code")).to_equal(0)
        expect("no one-time code" in self.out.getvalue().lower()).to_equal(True)

    def test_the_commands_for_the_code_are_named_in_the_usage(self) -> None:
        self._run("--frobnicate")
        expect("set-code" in self.out.getvalue()).to_equal(True)
        expect("reset-code" in self.out.getvalue()).to_equal(True)
