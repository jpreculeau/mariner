"""UVTools network print provider.

Exposes endpoints compatible with UVTools' remote printer feature.
UVTools sends raw binary file bodies (not multipart) and substitutes
``{0}`` in configured URL paths with the filename.  It only inspects
the HTTP status code, so successful responses return 200 with a short
JSON body.

Recommended UVTools configuration for Mariner
----------------------------------------------
Host : <Mariner IP>
Port : 5050  (or whatever ``mariner.conf`` sets)
Extensions : ctb;cbddlp;fdg;photon

=============  ======  =======================
Operation      Method  Request path
=============  ======  =======================
UploadFile     POST    uvtools/upload/{0}
PrintFile      GET     uvtools/print/{0}
DeleteFile     GET     uvtools/delete/{0}
PausePrint     GET     uvtools/pause
ResumePrint    GET     uvtools/resume
StopPrint      GET     uvtools/stop
GetFiles       GET     uvtools/files
PrintStatus    GET     uvtools/status
PrinterInfo    GET     uvtools/info
=============  ======  =======================
"""

import logging
import os
from typing import Union

from flask import Blueprint, Response, abort, jsonify, request

from mariner import config
from mariner.file_formats.utils import get_file_extension, get_supported_extensions
from mariner.printer import PrinterState
from mariner.server.providers.base import NetworkPrintProvider
from mariner.server.files import (
    NotPrintable,
    modification_time,
    printable_relative_path,
    replacing,
    resolve_entry_in_files_directory,
    resolve_in_files_directory,
    safe_filename,
)
from mariner.server.printer_access import (
    FileInUse,
    printer_session,
    read_status,
    start_print,
    unless_in_use,
)
from mariner.server.utils import read_cached_sliced_model_file

logger: logging.Logger = logging.getLogger(__name__)


class UVToolsProvider(NetworkPrintProvider):
    @property
    def name(self) -> str:
        return "uvtools"

    def register_routes(self, blueprint: Blueprint) -> None:
        blueprint.add_url_rule(
            "/upload/<filename>",
            endpoint="upload_file",
            view_func=self._upload_file,
            methods=["POST", "PUT"],
        )
        blueprint.add_url_rule(
            "/print/<filename>",
            endpoint="print_file",
            view_func=self._print_file,
            methods=["GET", "POST"],
        )
        blueprint.add_url_rule(
            "/delete/<filename>",
            endpoint="delete_file",
            view_func=self._delete_file,
            methods=["GET", "POST"],
        )
        blueprint.add_url_rule(
            "/pause",
            endpoint="pause_print",
            view_func=self._pause_print,
            methods=["GET", "POST"],
        )
        blueprint.add_url_rule(
            "/pause/<filename>",
            endpoint="pause_print_with_file",
            view_func=self._pause_print,
            methods=["GET", "POST"],
        )
        blueprint.add_url_rule(
            "/resume",
            endpoint="resume_print",
            view_func=self._resume_print,
            methods=["GET", "POST"],
        )
        blueprint.add_url_rule(
            "/resume/<filename>",
            endpoint="resume_print_with_file",
            view_func=self._resume_print,
            methods=["GET", "POST"],
        )
        blueprint.add_url_rule(
            "/stop",
            endpoint="stop_print",
            view_func=self._stop_print,
            methods=["GET", "POST"],
        )
        blueprint.add_url_rule(
            "/stop/<filename>",
            endpoint="stop_print_with_file",
            view_func=self._stop_print,
            methods=["GET", "POST"],
        )
        blueprint.add_url_rule(
            "/files",
            endpoint="get_files",
            view_func=self._get_files,
            methods=["GET"],
        )
        blueprint.add_url_rule(
            "/status",
            endpoint="print_status",
            view_func=self._print_status,
            methods=["GET"],
        )
        blueprint.add_url_rule(
            "/info",
            endpoint="printer_info",
            view_func=self._printer_info,
            methods=["GET"],
        )

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _upload_file(self, filename: str) -> Union[str, Response]:
        """Accept a raw-binary file upload.

        UVTools streams the file bytes directly in the request body
        (no multipart, no form fields).  The filename comes from the
        URL path.
        """
        safe_name = safe_filename(filename)
        if safe_name is None:
            logger.warning("UVTools: refusing unsafe filename %r", filename)
            abort(400)

        ext = get_file_extension(safe_name)
        if ext not in get_supported_extensions():
            abort(400)

        dest = resolve_in_files_directory(safe_name)
        if dest is None:
            abort(400)

        data = request.get_data()
        if not data:
            abort(400)
        if os.path.isdir(dest):
            # A folder already has that name; a file cannot take its place.
            abort(400)
        try:
            # Checked first so a refusal comes before anything is written,
            # and again by the guard as the file is moved into place.
            with unless_in_use(dest):
                pass
            with replacing(dest, guard=unless_in_use) as scratch:
                scratch.write_bytes(data)
        except FileNotFoundError:
            # The folder was removed while the file was being written.
            abort(404)
        except FileInUse as error:
            logger.warning(
                "UVTools: not replacing %s: %s", safe_name, error.usage.value
            )
            abort(409)
        try:
            os.sync()
        except AttributeError:
            pass

        logger.info("UVTools upload: %s (%d bytes)", safe_name, len(data))
        return jsonify({"success": True, "filename": safe_name})

    def _print_file(self, filename: str) -> Union[str, Response]:
        try:
            relative = printable_relative_path(filename)
        except NotPrintable as error:
            logger.warning("UVTools: not printing %r: %s", filename, error.reason)
            abort(404 if error.reason == NotPrintable.MISSING else 400)

        start_print(relative)

        logger.info("UVTools print: %s", relative)
        return jsonify({"success": True})

    def _delete_file(self, filename: str) -> Union[str, Response]:
        # Not safe_filename: that decides which names may be stored. A file
        # that is already there must stay deletable whatever its name, as
        # long as it is an entry of the files directory itself.
        path = None
        if "/" not in filename and "\\" not in filename:
            path = resolve_entry_in_files_directory(filename)
        if path is None:
            logger.warning("UVTools: refusing unsafe filename %r", filename)
            abort(400)

        if not (os.path.isfile(path) or os.path.islink(path)):
            abort(404)
        try:
            with unless_in_use(path):
                os.remove(path)
        except FileNotFoundError:
            # Someone else removed it in the meantime.
            abort(404)
        except FileInUse as error:
            logger.warning("UVTools: not deleting %r: %s", filename, error.usage.value)
            abort(409)
        logger.info("UVTools delete: %r", filename)
        return jsonify({"success": True})

    def _pause_print(self, filename: str = "") -> Union[str, Response]:
        with printer_session() as printer:
            printer.pause_printing()
        logger.info("UVTools pause")
        return jsonify({"success": True})

    def _resume_print(self, filename: str = "") -> Union[str, Response]:
        with printer_session() as printer:
            printer.resume_printing()
        logger.info("UVTools resume")
        return jsonify({"success": True})

    def _stop_print(self, filename: str = "") -> Union[str, Response]:
        with printer_session() as printer:
            printer.stop_printing()
        logger.info("UVTools stop")
        return jsonify({"success": True})

    def _get_files(self) -> Union[str, Response]:
        files_dir = config.get_files_directory()
        supported = get_supported_extensions()
        file_list = []

        with os.scandir(files_dir) as entries:
            for entry in sorted(entries, key=modification_time, reverse=True):
                if entry.is_file() and get_file_extension(entry.name) in supported:
                    file_list.append(entry.name)

        return jsonify({"files": file_list})

    def _print_status(self) -> Union[str, Response]:
        status, selected_file = read_status()
        if status.state == PrinterState.CLOSED:
            return jsonify({"state": PrinterState.CLOSED.value})

        result = {
            "state": status.state.value,
            "selected_file": selected_file,
        }

        if (
            status.state not in (PrinterState.IDLE, PrinterState.CLOSED)
            and selected_file
        ):
            try:
                path = resolve_in_files_directory(selected_file)
                if path is None:
                    raise FileNotFoundError(selected_file)
                sliced = read_cached_sliced_model_file(path)
                layer_count = sliced.layer_count or 0
                progress = 0.0
                if (
                    status.current_byte
                    and status.total_bytes
                    and status.total_bytes > 0
                ):
                    progress = 100.0 * status.current_byte / status.total_bytes
                result.update(
                    {
                        "progress": round(progress, 2),
                        "layer_count": layer_count,
                        "print_time_secs": sliced.print_time_secs,
                    }
                )
            except Exception:
                pass

        return jsonify(result)

    def _printer_info(self) -> Union[str, Response]:
        info = {
            "name": config.get_printer_display_name() or "Mariner",
            "extensions": list(get_supported_extensions()),
        }

        try:
            with printer_session() as printer:
                info["firmware"] = printer.get_firmware_version()
        except Exception:
            pass

        return jsonify(info)
