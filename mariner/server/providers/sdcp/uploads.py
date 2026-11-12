"""Chunked file upload handling for the SDCP HTTP server.

SDCP clients send a file as a sequence of ~1MB multipart POSTs that all share
a ``Uuid`` and carry an ``Offset``. Chunks are appended to a scratch file in
``.sdcp_uploads/``, on the same filesystem as the destination, so the final
move is a rename.
"""

import hashlib
import logging
import os
import re
import secrets
import stat
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, Callable, ContextManager, Dict, Optional, Tuple

from mariner import config
from mariner.file_formats.utils import get_file_extension, get_supported_extensions
from mariner.server.files import (
    SDCP_SCRATCH_DIRNAME,
    resolve_entry_in_files_directory,
    safe_filename,
)
from mariner.server.printer_access import FileInUse, unless_in_use
from mariner.server.providers.sdcp import constants

logger: logging.Logger = logging.getLogger(__name__)


@dataclass
class ChunkResult:
    ok: bool
    error: Optional[int] = None
    completed: bool = False
    filename: str = ""
    md5_failed: bool = False
    format_failed: bool = False


_UPLOAD_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_MD5 = re.compile(r"[0-9a-fA-F]{32}")

# A transfer that has received nothing for this long is given up on: the
# client is gone. Chunks are about 1 MB, seconds apart on the slowest link.
IDLE_TRANSFER_SECS = 300.0

# A transfer belongs to the client that sent its first chunk, known by its
# address, and goes by the id that client chose.
_SessionKey = Tuple[str, str]


@dataclass
class _Session:
    filename: str
    total_size: int
    expected_md5: str
    verify: bool
    scratch_path: Path
    handle: BinaryIO
    offset: int = 0
    last_chunk_at: float = field(default_factory=time.monotonic)
    # hashlib's hash objects have no public type to name here.
    hasher: Any = field(default_factory=hashlib.md5)

    def close(self) -> None:
        """Close the scratch file of a transfer that is being given up."""
        try:
            self.handle.close()
        except OSError:
            pass

    def finish(self) -> None:
        """Close the scratch file of a transfer that has received everything.

        The end of the last chunk is only written out here. Raises OSError
        if it cannot be, for want of room say: the file is then short of
        what was received, and must not be taken for the whole of it.
        """
        self.handle.close()


class UploadManager:
    """Assembles chunked uploads into files in Mariner's files directory."""

    _lock: threading.Lock

    def __init__(
        self,
        unless_in_use: Callable[[Path], ContextManager[None]] = unless_in_use,
    ) -> None:
        """
        *unless_in_use* decides whether a file may be replaced while a print
        is running (see ``printer_access``). It talks to the printer, which
        can take seconds, so it is never called with ``self._lock`` held:
        the SDCP event loop takes that lock itself.
        """
        self._lock = threading.Lock()
        self._sessions: Dict[_SessionKey, _Session] = {}
        self._unless_in_use = unless_in_use

    def is_transferring(self) -> bool:
        self.drop_idle_transfers()
        with self._lock:
            return bool(self._sessions)

    def drop_idle_transfers(self) -> None:
        """Give up on transfers whose client stopped sending.

        Called on every chunk and status request, and by the service at
        regular intervals, so that it happens with no client around too.
        """
        with self._lock:
            now = time.monotonic()
            for key, session in list(self._sessions.items()):
                if now - session.last_chunk_at >= IDLE_TRANSFER_SECS:
                    logger.warning(
                        "SDCP: giving up on the unfinished transfer of %s",
                        session.filename,
                    )
                    self._discard(key, session)
        self._cleanup_scratch_dir()

    def _scratch_dir(self) -> Path:
        # Kept inside the files directory so finalize() is a rename rather
        # than a cross-filesystem copy of a potentially huge file.
        path = config.get_files_directory() / SDCP_SCRATCH_DIRNAME
        try:
            os.mkdir(path)
        except FileExistsError:
            pass
        if not stat.S_ISDIR(os.lstat(path).st_mode):
            # A link, which would lead the transfers elsewhere, or a file.
            raise NotADirectoryError(path)
        return path

    def handle_chunk(
        self,
        *,
        upload_uuid: str,
        filename: str,
        offset: int,
        total_size: int,
        expected_md5: str,
        verify: bool,
        data: bytes,
        client: str = "",
    ) -> ChunkResult:
        """Store one chunk, and move the file into place if it was the last.

        *client* is the address the chunk came from. Two clients may well
        choose the same id, "default" when they send none, and must not
        feed each other's transfer.
        """
        self.drop_idle_transfers()
        try:
            return self._handle_chunk(
                key=(client, upload_uuid),
                filename=filename,
                offset=offset,
                total_size=total_size,
                expected_md5=expected_md5,
                verify=verify,
                data=data,
            )
        finally:
            # However the chunk went, no empty scratch folder stays behind.
            self._cleanup_scratch_dir()

    def _handle_chunk(
        self,
        *,
        key: _SessionKey,
        filename: str,
        offset: int,
        total_size: int,
        expected_md5: str,
        verify: bool,
        data: bytes,
    ) -> ChunkResult:
        upload_uuid = key[1]
        if offset < 0 or total_size < 0:
            return ChunkResult(ok=False, error=constants.UploadError.OFFSET_ERROR)

        # The id is client input, used as a key and written to the log. Only
        # a short token of letters, digits, "-" and "_" is accepted: clients
        # send a UUID, and the service passes "default" when they send none.
        if not _UPLOAD_ID.fullmatch(upload_uuid):
            logger.warning("SDCP: refusing malformed upload id %r", upload_uuid)
            return ChunkResult(ok=False, error=constants.UploadError.UNKNOWN)

        # Client input too, compared with the file's own MD5 and written to
        # the log.
        if expected_md5 and not _MD5.fullmatch(expected_md5):
            logger.warning("SDCP: refusing malformed MD5 %r", expected_md5)
            return ChunkResult(ok=False, error=constants.UploadError.UNKNOWN)

        safe_name = safe_filename(filename)
        if safe_name is None:
            logger.warning("SDCP: refusing unsafe upload filename %r", filename)
            return ChunkResult(
                ok=False,
                error=constants.UploadError.UNKNOWN,
                format_failed=True,
            )

        if get_file_extension(safe_name) not in get_supported_extensions():
            return ChunkResult(
                ok=False,
                error=constants.UploadError.UNKNOWN,
                format_failed=True,
            )

        # Refused before any byte is stored, so the client learns at once
        # instead of after sending the whole file. Checked again when the
        # file is moved into place.
        if offset == 0:
            destination = resolve_entry_in_files_directory(safe_name)
            try:
                if destination is not None:
                    with self._unless_in_use(destination):
                        pass
            except FileInUse as error:
                logger.warning(
                    "SDCP: not replacing %s: %s", safe_name, error.usage.value
                )
                self._abandon(key)
                return ChunkResult(
                    ok=False, error=constants.UploadError.FILE_OPEN_FAILED
                )

        with self._lock:
            session = self._sessions.get(key)

            if session is None and offset != 0:
                # A chunk from the middle of a transfer that is not under
                # way: abandoned, terminated, or never begun. Nothing is
                # kept for it.
                return ChunkResult(
                    ok=False, error=constants.UploadError.OFFSET_MISMATCH
                )

            # Offset 0 always (re)starts a transfer, so a client retrying from
            # the beginning discards whatever was buffered before.
            if session is None or offset == 0:
                if session is not None:
                    self._discard(key, session)
                try:
                    # Its own random name, not the client's id: a transfer
                    # that reuses an id must not reopen the file of one that
                    # is still being moved into place.
                    scratch = self._scratch_dir() / f"{secrets.token_hex(8)}.part"
                    handle = open(scratch, "wb")
                except OSError as exc:
                    logger.warning("SDCP: cannot open scratch file: %s", exc)
                    return ChunkResult(
                        ok=False, error=constants.UploadError.FILE_OPEN_FAILED
                    )
                session = _Session(
                    filename=safe_name,
                    total_size=total_size,
                    expected_md5=(expected_md5 or "").lower(),
                    verify=verify,
                    scratch_path=scratch,
                    handle=handle,
                )
                self._sessions[key] = session
                logger.info(
                    "SDCP: upload starting: %s uuid=%s total_size=%d "
                    "check=%s declared_md5=%s",
                    safe_name,
                    upload_uuid,
                    total_size,
                    verify,
                    expected_md5 or "<none>",
                )

            # A chunk continues the transfer it names in full: same file,
            # same size, next offset. Anything else is another transfer
            # that happens to use the same id, and gets nothing in. (The
            # declared MD5 is left out of this: nothing says that clients
            # repeat it with every chunk. Two transfers alike in all of
            # the above, from one address, cannot be told apart.)
            if (
                offset != session.offset
                or safe_name != session.filename
                or total_size != session.total_size
            ):
                return ChunkResult(
                    ok=False, error=constants.UploadError.OFFSET_MISMATCH
                )
            session.last_chunk_at = time.monotonic()

            # Clients may pad the final packet. TotalSize is authoritative, so
            # anything past it is dropped: writing it produces a file longer
            # than the original, which breaks formats that store a checksum in
            # their trailing bytes (encrypted CTB seeks back from the end).
            if session.total_size:
                remaining = session.total_size - session.offset
                if remaining <= 0:
                    data = b""
                elif len(data) > remaining:
                    data = data[:remaining]

            try:
                session.handle.write(data)
            except OSError as exc:
                logger.warning("SDCP: write failed: %s", exc)
                self._discard(key, session)
                return ChunkResult(
                    ok=False, error=constants.UploadError.FILE_OPEN_FAILED
                )

            session.hasher.update(data)
            session.offset += len(data)

            if not (session.total_size and session.offset >= session.total_size):
                return ChunkResult(ok=True)

            # Complete, if all of it made it to the disk.
            try:
                session.finish()
            except OSError as exc:
                logger.warning("SDCP: write failed: %s", exc)
                self._discard(key, session)
                return ChunkResult(
                    ok=False, error=constants.UploadError.FILE_OPEN_FAILED
                )

            # The session leaves the table here, under the lock; the rest
            # happens outside it because it talks to the printer.
            self._sessions.pop(key, None)

        return self._finalize(session)

    def _abandon(self, key: _SessionKey) -> None:
        """Drop whatever was received so far for *key*, if anything."""
        with self._lock:
            session = self._sessions.get(key)
            if session is not None:
                self._discard(key, session)

    def _finalize(self, session: _Session) -> ChunkResult:
        """Verify a completed transfer and move it into the files directory.

        Called without ``self._lock``, because the move waits for the
        printer. *session* is already out of the table and owns a scratch
        file no other transfer can be given, so nothing else touches it;
        ``_cleanup_scratch_dir`` only ever removes the directory once empty.

        Whatever was received is removed unless it was moved into place.
        """
        moved = False
        try:
            result = self._verify_and_move(session)
            moved = result.completed
            return result
        finally:
            # Also when the move fails in a way nobody foresaw: the session
            # is out of the table, so nothing else would ever remove it.
            if not moved:
                self._unlink(session.scratch_path)

    def _verify_and_move(self, session: _Session) -> ChunkResult:
        computed = session.hasher.hexdigest()
        logger.info(
            "SDCP: upload finished: %s bytes=%d declared_total=%d check=%s "
            "declared_md5=%s computed_md5=%s",
            session.filename,
            session.offset,
            session.total_size,
            session.verify,
            session.expected_md5 or "<none>",
            computed,
        )

        if session.verify and session.expected_md5:
            if computed != session.expected_md5:
                logger.warning(
                    "SDCP: MD5 mismatch for %s (expected %s, got %s)",
                    session.filename,
                    session.expected_md5,
                    computed,
                )
                return ChunkResult(
                    ok=False,
                    error=constants.UploadError.UNKNOWN,
                    md5_failed=True,
                    filename=session.filename,
                )

        # The entry of that name, not what it leads to: a file stored onto a
        # symbolic link takes the place of the link.
        destination = resolve_entry_in_files_directory(session.filename)
        if destination is None:
            return ChunkResult(
                ok=False,
                error=constants.UploadError.UNKNOWN,
                format_failed=True,
            )

        try:
            # The guard holds off print starts for the move, so a print
            # cannot start on this file between the check and the
            # replacement.
            with self._unless_in_use(destination):
                os.replace(session.scratch_path, destination)
        except FileInUse as error:
            logger.warning(
                "SDCP: not replacing %s: %s", session.filename, error.usage.value
            )
            return ChunkResult(ok=False, error=constants.UploadError.FILE_OPEN_FAILED)
        except OSError as exc:
            logger.warning("SDCP: could not move upload into place: %s", exc)
            return ChunkResult(ok=False, error=constants.UploadError.FILE_OPEN_FAILED)

        self._sync()
        logger.info("SDCP: received %s (%d bytes)", session.filename, session.offset)
        return ChunkResult(ok=True, completed=True, filename=session.filename)

    def terminate(self, upload_uuid: str, client: str = "") -> int:
        """Handle Cmd 255, returning the matching ack code.

        Ends the transfer *client* began under that id, and no one else's.
        """
        key = (client, upload_uuid)
        with self._lock:
            session = self._sessions.get(key)
            if session is not None:
                self._discard(key, session)
        self._cleanup_scratch_dir()
        if session is None:
            return int(constants.FileTransferAck.NOT_TRANSFER)
        return int(constants.FileTransferAck.SUCCESS)

    def _discard(self, key: _SessionKey, session: _Session) -> None:
        session.close()
        self._sessions.pop(key, None)
        self._unlink(session.scratch_path)

    @staticmethod
    def _unlink(path: Path) -> None:
        try:
            os.remove(path)
        except OSError:
            pass

    def _cleanup_scratch_dir(self) -> None:
        """Remove the scratch directory once no transfer needs it.

        Only an empty directory is removed, so the file of a transfer that
        is being moved into place, outside the lock, is never taken away.
        """
        with self._lock:
            if self._sessions:
                return
            try:
                os.rmdir(config.get_files_directory() / SDCP_SCRATCH_DIRNAME)
            except OSError:
                pass

    @staticmethod
    def _sync() -> None:
        # The printer reads the same files over USB mass storage, so flush
        # before telling the client the transfer succeeded.
        sync = getattr(os, "sync", None)
        if sync is not None:
            try:
                sync()
            except OSError:
                pass
