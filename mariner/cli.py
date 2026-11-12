"""``mariner``: start Mariner, or set or clear its password.

The two commands about the password are for whoever has the computer in
hand. They work on the folder the service keeps its password in, without
loading the server.
"""

import getpass
import json
import os
import sys
import tempfile

from mariner import config, passwords

_USAGE = """usage: mariner                  start Mariner
       mariner set-password     choose Mariner's password, typed here
       mariner reset-password   clear a password that is lost: the next
                                visit to Mariner's page chooses one"""


def _serve() -> None:
    from mariner.server import main as serve

    serve()


def _reset_password() -> int:
    directory = os.path.expanduser(config.get_state_directory())
    try:
        os.unlink(passwords.kept_path(directory))
    except FileNotFoundError:
        print(f"No password was set (in {directory}).")
        print("Open Mariner's page to choose one, or run: mariner set-password")
        return 0
    except OSError as error:
        print(f"The password could not be cleared ({error}).")
        print("Run this command with sudo.")
        return 1
    print(f"The password was cleared (in {directory}).")
    print(
        "Until a new one is chosen, whoever opens Mariner's page first "
        "chooses it. To choose it here instead, run: mariner set-password"
    )
    return 0


def _set_password() -> int:
    directory = os.path.expanduser(config.get_state_directory())
    first = getpass.getpass("New password for Mariner: ")
    second = getpass.getpass("Again: ")
    if first != second:
        print("The two are not the same. Nothing was changed.")
        return 1
    try:
        record = passwords.record_for(first)
    except passwords.PasswordNotAllowed as error:
        print(f"{error.description} Nothing was changed.")
        return 1
    try:
        os.makedirs(directory, mode=0o700, exist_ok=True)
        owner = os.stat(directory)
        descriptor, scratch = tempfile.mkstemp(dir=directory, prefix=".writing-")
        try:
            with os.fdopen(descriptor, "wb") as file:
                os.fchmod(file.fileno(), 0o600)
                file.write(json.dumps(record).encode("ascii"))
                file.flush()
                os.fsync(file.fileno())
            kept = passwords.kept_path(directory)
            os.replace(scratch, kept)
        except BaseException:
            try:
                os.unlink(scratch)
            except OSError:
                pass
            raise
        if os.geteuid() == 0:
            # To the account the folder belongs to, which is the
            # service's: it does not take a file that is root's.
            os.chown(kept, owner.st_uid, owner.st_gid)
    except OSError as error:
        print(f"The password could not be kept in {directory} ({error}).")
        print("Run this command with sudo.")
        return 1
    print(f"The password was set (in {directory}).")
    print("Every browser that was signed in has to sign in again.")
    return 0


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
