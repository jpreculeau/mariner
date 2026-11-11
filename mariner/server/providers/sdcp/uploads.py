"""Chunked file upload handling for the SDCP HTTP server.

SDCP clients send a file as a sequence of ~1MB multipart POSTs that all share
a ``Uuid`` and carry an ``Offset``. Chunks are appended to a scratch file next
to the destination so the final move is an atomic same-filesystem rename.
"""

import hashlib
import logging
import os
import re
import secrets
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, Callable, ContextManager, Dict, Optional

from mariner import config
from mariner.file_formats.utils import get_file_extension, get_supported_extensions
from mariner.server.files import (
    SDCP_SCRATCH_DIRNAME,
    resolve_in_files_directory,
    safe_filename,
)
from mariner.server.printer_access import FileInUse, is_in_use, unless_in_use
from mariner.server.providers.sdcp import constants

logger: logging.Logger = logging.getLogger(__name__)

SCRATCH_DIRNAME: str = SDCP_SCRATCH_DIRNAME


@dataclass
class ChunkResult:
    ok: bool
    error: Optional[int] = None
    completed: bool = False
    filename: str = ""
    md5_failed: bool = False
    format_failed: bool = False


_UPLOAD_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


@dataclass
class _Session:
    filename: str
    total_size: int
    expected_md5: str
    verify: bool
    scratch_path: Path
    handle: BinaryIO
    offset: int = 0
    # hashlib's hash objects have no public type to name here.
    hasher: Any = field(default_factory=hashlib.md5)

    def close(self) -> None:
        try:
            self.handle.close()
        except OSError:
            pass


class UploadManager:
    """Assembles chunked uploads into files in Mariner's files directory."""

    _lock: threading.Lock

    def __init__(
        self,
        is_in_use: Callable[[Path], bool] = is_in_use,
        unless_in_use: Callable[[Path], ContextManager[None]] = unless_in_use,
    ) -> None:
        """
        *is_in_use* and *unless_in_use* decide whether a file may be replaced
        while a print is running (see ``printer_access``). They talk to the
        printer, which can take seconds, so they are never called with
        ``self._lock`` held: the SDCP event loop takes that lock itself.
        """
        self._lock = threading.Lock()
        self._sessions: Dict[str, _Session] = {}
        self._is_in_use = is_in_use
        self._unless_in_use = unless_in_use

    def is_transferring(self) -> bool:
        with self._lock:
            return bool(self._sessions)

    def _scratch_dir(self) -> Path:
        # Kept inside the files directory so finalize() is a rename rather
        # than a cross-filesystem copy of a potentially huge file.
        path = config.get_files_directory() / SCRATCH_DIRNAME
        path.mkdir(parents=True, exist_ok=True)
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
    ) -> ChunkResult:
        if offset < 0 or total_size < 0:
            return ChunkResult(ok=False, error=constants.UploadError.OFFSET_ERROR)

        # The id is client input used as a key and written to the log. Clients
        # send a UUID, with or without dashes; nothing else is accepted.
        if not _UPLOAD_ID.fullmatch(upload_uuid):
            logger.warning("SDCP: refusing malformed upload id %r", upload_uuid)
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
        if self._starts_a_transfer(upload_uuid, offset):
            destination = resolve_in_files_directory(safe_name)
            if destination is not None and self._is_in_use(destination):
                logger.warning(
                    "SDCP: refusing to replace %s while it prints", safe_name
                )
                self._abandon(upload_uuid)
                return ChunkResult(
                    ok=False, error=constants.UploadError.FILE_OPEN_FAILED
                )

        with self._lock:
            session = self._sessions.get(upload_uuid)

            # Offset 0 always (re)starts a transfer, so a client retrying from
            # the beginning discards whatever was buffered before.
            if session is None or offset == 0:
                if session is not None:
                    self._discard(upload_uuid, session)
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
                self._sessions[upload_uuid] = session
                logger.info(
                    "SDCP: upload starting: %s uuid=%s total_size=%d "
                    "check=%s declared_md5=%s",
                    safe_name,
                    upload_uuid,
                    total_size,
                    verify,
                    expected_md5 or "<none>",
                )

            if offset != session.offset:
                return ChunkResult(
                    ok=False, error=constants.UploadError.OFFSET_MISMATCH
                )

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
                self._discard(upload_uuid, session)
                return ChunkResult(
                    ok=False, error=constants.UploadError.FILE_OPEN_FAILED
                )

            session.hasher.update(data)
            session.offset += len(data)

            if not (session.total_size and session.offset >= session.total_size):
                return ChunkResult(ok=True)

            # Complete. The session leaves the table here, under the lock;
            # the rest happens outside it because it talks to the printer.
            session.close()
            self._sessions.pop(upload_uuid, None)

        return self._finalize(session)

    def _starts_a_transfer(self, upload_uuid: str, offset: int) -> bool:
        with self._lock:
            return offset == 0 or upload_uuid not in self._sessions

    def _abandon(self, upload_uuid: str) -> None:
        """Drop whatever was received so far under *upload_uuid*, if anything."""
        with self._lock:
            session = self._sessions.get(upload_uuid)
            if session is not None:
                self._discard(upload_uuid, session)
        self._cleanup_scratch_dir()

    def _finalize(self, session: _Session) -> ChunkResult:
        """Verify a completed transfer and move it into the files directory.

        Called without ``self._lock``, because the move waits for the
        printer. *session* is already out of the table and owns a scratch
        file no other transfer can be given, so nothing else touches it;
        ``_cleanup_scratch_dir`` only ever removes the directory once empty.
        """
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
                self._unlink(session.scratch_path)
                return ChunkResult(
                    ok=False,
                    error=constants.UploadError.UNKNOWN,
                    md5_failed=True,
                    filename=session.filename,
                )

        destination = resolve_in_files_directory(session.filename)
        if destination is None:
            self._unlink(session.scratch_path)
            return ChunkResult(
                ok=False,
                error=constants.UploadError.UNKNOWN,
                format_failed=True,
            )

        try:
            # The guard holds the printer for the move, so a print cannot
            # start on this file between the check and the replacement.
            with self._unless_in_use(destination):
                os.replace(session.scratch_path, destination)
        except FileInUse:
            logger.warning(
                "SDCP: refusing to replace %s while it prints", session.filename
            )
            self._unlink(session.scratch_path)
            return ChunkResult(ok=False, error=constants.UploadError.FILE_OPEN_FAILED)
        except OSError as exc:
            logger.warning("SDCP: could not move upload into place: %s", exc)
            self._unlink(session.scratch_path)
            return ChunkResult(ok=False, error=constants.UploadError.FILE_OPEN_FAILED)

        self._sync()
        self._cleanup_scratch_dir()
        logger.info("SDCP: received %s (%d bytes)", session.filename, session.offset)
        return ChunkResult(ok=True, completed=True, filename=session.filename)

    def terminate(self, upload_uuid: str, filename: str = "") -> int:
        """Handle Cmd 255, returning the matching ack code."""
        with self._lock:
            session = self._sessions.get(upload_uuid)
            if session is None:
                return int(constants.FileTransferAck.NOT_TRANSFER)
            self._discard(upload_uuid, session)
        self._cleanup_scratch_dir()
        return int(constants.FileTransferAck.SUCCESS)

    def _discard(self, upload_uuid: str, session: _Session) -> None:
        session.close()
        self._sessions.pop(upload_uuid, None)
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
                os.rmdir(config.get_files_directory() / SCRATCH_DIRNAME)
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
