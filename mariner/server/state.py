"""What Mariner keeps from one start to the next, and nobody else reads.

The key that signs sessions, the password's hash, the settings changed
from the page. All in one folder of the account Mariner runs under,
closed to every other: what is there says who may drive the printer.
"""

import logging
import os
import secrets
import stat
import tempfile
from pathlib import Path
from typing import List, Optional

from mariner import config

logger: logging.Logger = logging.getLogger(__name__)

SESSION_KEY_BYTES = 32

# Where to keep things when the folder asked for cannot be used: in the
# home of the account, which stays from one start to the next.
_FALLBACKS: List[str] = config.STATE_FALLBACKS

_directory: Optional[Path] = None
# Whether the folder in use is not the one that holds what was kept: the
# one asked for is there and cannot be used, or nothing better than a
# folder that goes at the next restart was found.
_makeshift = False
# The key of sessions, while it could not be written.
_unkept_key: Optional[bytes] = None

# What is answered when something could not be written here.
NOT_WRITTEN = {
    "code": "state_not_written",
    "title": "Not Kept",
    "description": "Mariner could not keep this: the folder it keeps its "
    "password and settings in cannot be written. The drive may be full or "
    "read-only. Nothing was changed.",
}


def forget() -> None:
    """Look for the folder again at the next use. For tests."""
    global _directory, _makeshift, _unkept_key
    _directory = None
    _makeshift = False
    _unkept_key = None


def is_makeshift() -> bool:
    """Whether what was kept may be out of reach.

    Then "no password is kept" does not mean that none was ever set, and
    must not open the door: see ``mariner.server.auth``.
    """
    if _directory is not None:
        # Looked at each time: given to another account while Mariner
        # runs, by a restore say, it is out of reach from then on.
        return _makeshift or not _still_usable(_directory)
    # Not yet looked for, and not made for the sake of asking: the one
    # asked for is there and cannot be used.
    wanted = os.path.expanduser(config.get_state_directory())
    if os.path.lexists(wanted):
        return not _usable(wanted)
    # Nor is there anywhere to make one that lasts.
    return not any(_can_be_made(one) for one in [wanted] + _FALLBACKS)


def _can_be_made(wanted: str) -> bool:
    """Whether a folder could be made at *wanted*, without making it."""
    return config.state_directory_can_be_made(wanted)


def _still_usable(folder: Path) -> bool:
    """Whether the folder in use is still there and this account's.

    Nothing is made, nor put right: made again after it went, it would
    be empty, and say that no password was ever chosen. Whether it can
    be written is not asked: on a drive gone read-only the password is
    still read, and the page must go on showing and stopping a print;
    what cannot be kept is said when keeping it is asked for.
    """
    try:
        status = os.lstat(folder)
    except OSError:
        return False
    return (
        stat.S_ISDIR(status.st_mode)
        and status.st_uid == os.geteuid()
        and os.access(folder, os.R_OK | os.X_OK)
    )


def _usable(wanted: str) -> bool:
    """Whether *wanted* is, or can be made, a folder of this account alone."""
    wanted = os.path.expanduser(wanted)
    if os.path.realpath(wanted) != os.path.abspath(wanted):
        # Reached through a link: it could lead to where another account
        # reads or writes.
        return False
    try:
        os.makedirs(wanted, mode=0o700, exist_ok=True)
        status = os.lstat(wanted)
        if not stat.S_ISDIR(status.st_mode) or status.st_uid != os.geteuid():
            return False
        if stat.S_IMODE(status.st_mode) != 0o700:
            os.chmod(wanted, 0o700)
    except OSError:
        return False
    return os.access(wanted, os.R_OK | os.W_OK | os.X_OK)


def directory() -> Path:
    """The folder things are kept in, made if need be.

    The one the configuration names; failing that one in the home of the
    account; failing that one that lasts until the computer restarts, so
    that Mariner starts all the same.
    """
    global _directory, _makeshift
    if _directory is not None:
        # Even gone: another is not taken in its place while Mariner
        # runs (see ``is_makeshift``).
        return _directory
    wanted = config.get_state_directory()
    # Looked at before anything is made: was something kept there?
    was_there = os.path.lexists(os.path.expanduser(wanted))
    if _usable(wanted):
        _directory = Path(os.path.expanduser(wanted))
        _makeshift = False
        return _directory
    for fallback in _FALLBACKS:
        if _usable(fallback):
            _directory = Path(os.path.expanduser(fallback))
            _makeshift = was_there
            logger.warning(
                "Not keeping settings in %r; using %r%s",
                wanted,
                str(_directory),
                (
                    ". What was kept there cannot be read: Mariner's page "
                    "stays shut until that folder belongs to the account "
                    "Mariner runs under and can be written"
                    if was_there
                    else ""
                ),
            )
            return _directory
    _directory = Path(tempfile.mkdtemp(prefix="mariner-state-"))
    _makeshift = True
    logger.warning(
        "Not keeping settings in %r; using %r, which does not outlast a "
        "restart of the computer. Mariner's page stays shut until it has "
        "a folder to keep its password in",
        wanted,
        str(_directory),
    )
    return _directory


def _checked(name: str) -> str:
    if not name or name in (".", "..") or "/" in name or "\x00" in name:
        raise ValueError(f"not the name of something kept: {name!r}")
    return name


def _path(name: str) -> Path:
    return directory() / _checked(name)


def _existing() -> Optional[Path]:
    """The folder to look in, if there is one: none is made for looking.

    The one that is found is the one in use from then on, as if
    something had been kept in it: at a start where everything is
    already kept, nothing is written for a long time, and what holds
    while Mariner runs (see ``is_makeshift``) must hold all the same.
    """
    global _directory, _makeshift
    if _directory is not None:
        return _directory
    wanted = os.path.expanduser(config.get_state_directory())
    found: Optional[Path] = None
    if os.path.lexists(wanted):
        # The one asked for, or nothing: if it cannot be used, what it
        # holds is out of reach, and no other is looked in for it.
        found = Path(wanted) if _usable(wanted) else None
    elif _can_be_made(wanted):
        # It will be made at the first thing kept, and read from then
        # on: nothing is read elsewhere until then, to be lost sight of.
        return None
    else:
        for fallback in _FALLBACKS:
            fallback = os.path.expanduser(fallback)
            if os.path.isdir(fallback) and _usable(fallback):
                found = Path(fallback)
                logger.warning(
                    "Not keeping settings in %r; using %r", wanted, str(found)
                )
                break
    if found is not None:
        _directory, _makeshift = found, False
    return found


def exists(name: str) -> bool:
    """Whether anything is kept under *name*, usable or not."""
    folder = _existing()
    return folder is not None and os.path.lexists(folder / _checked(name))


def read(name: str) -> Optional[bytes]:
    """What is kept under *name*, or None.

    Only a plain file of this account that no other can read or write: one
    left otherwise is not trusted, and reads as nothing. Looking makes no
    folder: only keeping something does.
    """
    folder = _existing()
    if folder is None:
        _checked(name)
        return None
    path = folder / _checked(name)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        if os.path.islink(path):
            logger.warning("%r is a link and is not followed", str(path))
        return None
    try:
        status = os.fstat(descriptor)
        if (
            not stat.S_ISREG(status.st_mode)
            or status.st_uid != os.geteuid()
            or stat.S_IMODE(status.st_mode) & 0o077
        ):
            logger.warning(
                "%r can be read or written by another account and is not used",
                str(path),
            )
            return None
        with os.fdopen(descriptor, "rb", closefd=False) as file:
            return file.read()
    finally:
        os.close(descriptor)


def write(name: str, content: bytes) -> None:
    """Keep *content* under *name*: whole, or not at all.

    Written aside and moved into place, so that a card pulled half-way
    leaves what was there.
    """
    path = _path(name)
    descriptor, scratch = tempfile.mkstemp(dir=path.parent, prefix=".writing-")
    try:
        with os.fdopen(descriptor, "wb") as file:
            os.fchmod(file.fileno(), 0o600)
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(scratch, path)
    except BaseException:
        try:
            os.unlink(scratch)
        except OSError:
            pass
        raise


def remove(name: str) -> None:
    try:
        os.unlink(_path(name))
    except FileNotFoundError:
        pass


def session_key() -> bytes:
    """The key sessions are signed with, the same at every start.

    Made the first time. A page left open then goes on working after
    Mariner restarts, and whoever is signed in stays so.
    """
    if _unkept_key is not None:
        return _unkept_key
    kept = read("session.key")
    if kept is not None and len(kept) == SESSION_KEY_BYTES:
        return kept
    if kept is not None or os.path.lexists(_path("session.key")):
        logger.warning("The key of sessions could not be used; making a new one")
    return new_session_key()


def new_session_key() -> bytes:
    """Make and keep a new key: every session signed with the old ends."""
    global _unkept_key
    key = secrets.token_bytes(SESSION_KEY_BYTES)
    try:
        write("session.key", key)
        _unkept_key = None
    except OSError as error:
        # Sessions then end when Mariner stops, as they used to. The one
        # that is kept, which this one replaces, is not read back.
        logger.warning("The key of sessions could not be kept: %s", error)
        _unkept_key = key
    return key
