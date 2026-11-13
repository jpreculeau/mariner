"""``mariner``: start Mariner, or set or clear its password.

The two commands about the password are for whoever has the computer in
hand. They work on the folder the service keeps its password in, without
loading the server.
"""

import getpass
import json
import os
import pwd
import stat
import sys
import tempfile
from typing import List, Optional

from mariner import config, passwords

_USAGE = """usage: mariner                  start Mariner
       mariner set-password     choose Mariner's password, typed here
       mariner reset-password   clear a password that is lost: the next
                                visit to Mariner's page chooses one"""


def _serve() -> None:
    from mariner.server import main as serve

    serve()


def _folders() -> List[str]:
    """The folders Mariner may keep its password in, the first first.

    The one the configuration names, then the one it falls back on in
    the home of its account when it cannot make that one: where it is
    run by hand rather than as a service.
    """
    return [
        os.path.expanduser(one)
        for one in [config.get_state_directory()] + config.STATE_FALLBACKS
    ]


def _reset_password() -> int:
    folders = _folders()
    try:
        holding = [one for one in folders if _holds_a_password(one)]
    except PermissionError:
        print("This account may not look into the folder Mariner keeps things in.")
        print("Run this command with sudo.")
        return 1
    if not holding:
        print(f"No password was set (looked in {' and '.join(folders)}).")
        print("Open Mariner's page to choose one, or run: mariner set-password")
        print(
            "If Mariner runs under another account than this one, run this "
            "command as that account."
        )
        return 0
    directory = holding[0]
    try:
        os.unlink(passwords.kept_path(directory))
    except OSError as error:
        print(f"The password could not be cleared ({error}).")
        print("Run this command with sudo.")
        return 1
    _end_sessions(directory)
    print(f"The password was cleared (in {directory}).")
    print(
        "Until a new one is chosen, whoever opens Mariner's page first "
        "chooses it. To choose it here instead, run: mariner set-password"
    )
    return 0


def _holds_a_password(folder: str) -> bool:
    try:
        os.lstat(passwords.kept_path(folder))
    except PermissionError:
        raise
    except OSError:
        return False
    return True


_SERVICE_ACCOUNT = "mariner"


def _runs_under_another_account() -> bool:
    """Whether Mariner is installed as a service of its own account."""
    try:
        return pwd.getpwnam(_SERVICE_ACCOUNT).pw_uid != os.geteuid()
    except KeyError:
        return False


def _folder_to_write() -> Optional[str]:
    """The folder Mariner keeps things in, made if this account may."""
    folders = _folders()
    wanted, others = folders[0], folders[1:]
    if os.path.lexists(wanted):
        if os.path.realpath(wanted) != os.path.abspath(wanted):
            # Mariner does not use it, for where a link could lead, and
            # looks in no other while it is there.
            print(f"{wanted} is reached through a link, which Mariner does not")
            print("follow: its page stays shut. Name the folder itself under")
            print("[state] in the configuration.")
            return None
        return wanted
    # As Mariner chooses: the folder it was told when it can be made,
    # else the first of the others that is there or can be.
    may_make = os.geteuid() != 0 and not _runs_under_another_account()
    if config.state_directory_can_be_made(wanted):
        # Made by root, or in a home the service does not read, it would
        # be of no use to the service.
        return _made(wanted) if may_make else None
    for one in others:
        if os.path.lexists(one):
            return one
    if not may_make:
        return None
    for one in others:
        made = _made(one)
        if made is not None:
            return made
    return None


def _made(folder: str) -> Optional[str]:
    try:
        os.makedirs(folder, mode=0o700, exist_ok=True)
    except OSError:
        return None
    return folder


def _set_password() -> int:
    directory = _folder_to_write()
    if directory is None and os.path.lexists(_folders()[0]):
        print("Nothing was changed.")
        return 1
    if directory is None:
        print(f"There is no {_folders()[0]} yet: start Mariner once first, then")
        print("run this command again with sudo. If Mariner runs by hand under")
        print("an account of yours, run this command as that account.")
        return 1
    try:
        first = getpass.getpass("New password for Mariner: ")
        second = getpass.getpass("Again: ")
    except (EOFError, KeyboardInterrupt):
        # Left at the prompt.
        print()
        print("Nothing was changed.")
        return 1
    if first != second:
        print("The two are not the same. Nothing was changed.")
        return 1
    try:
        record = passwords.record_for(first)
    except passwords.PasswordNotAllowed as error:
        print(f"{error.description} Nothing was changed.")
        return 1
    as_root = os.geteuid() == 0
    try:
        # The folder itself, not what a link of its name leads to.
        owner = os.lstat(directory)
        if not stat.S_ISDIR(owner.st_mode):
            print(f"{directory} is not a folder. Nothing was changed.")
            return 1
        descriptor, scratch = tempfile.mkstemp(dir=directory, prefix=".writing-")
        try:
            with os.fdopen(descriptor, "wb") as file:
                os.fchmod(file.fileno(), 0o600)
                if as_root:
                    # To the account the folder belongs to, which is the
                    # service's: it does not take a file that is root's.
                    # Before the file is put in place, and by the open
                    # file, not by its name: a link put under that name
                    # meanwhile would hand over whatever it leads to.
                    os.fchown(file.fileno(), owner.st_uid, owner.st_gid)
                file.write(json.dumps(record).encode("ascii"))
                file.flush()
                os.fsync(file.fileno())
            os.replace(scratch, passwords.kept_path(directory))
        except BaseException:
            try:
                os.unlink(scratch)
            except OSError:
                pass
            raise
    except OSError as error:
        print(f"The password could not be kept in {directory} ({error}).")
        print("Run this command with sudo.")
        return 1
    _end_sessions(directory)
    print(f"The password was set (in {directory}).")
    print("Every browser that was signed in has to sign in again.")
    return 0


def _end_sessions(directory: str) -> None:
    """Have Mariner make a new key for sessions at its next start.

    What was signed with the old one, or could be forged from a copy of
    the folder, is then of no use. Sessions end at once all the same:
    they go with the password.
    """
    try:
        os.unlink(os.path.join(directory, "session.key"))
    except OSError:
        pass


def main() -> None:
    arguments = sys.argv[1:]
    if not arguments:
        _serve()
        return
    if arguments == ["reset-password"]:
        sys.exit(_reset_password())
    if arguments == ["set-password"]:
        sys.exit(_set_password())
    print(_USAGE, file=sys.stderr)
    sys.exit(2)
