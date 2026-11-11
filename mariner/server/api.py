import logging
import os
import subprocess
import threading
import traceback
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, NoReturn, Optional, Tuple, Union

from flask import (
    Blueprint,
    Response,
    abort,
    jsonify,
    make_response,
    request,
)
from pyre_extensions import none_throws

from mariner import config
from mariner.exceptions import MarinerException
from mariner.file_formats import SlicedModelFile
from mariner.file_formats.utils import get_file_extension, get_supported_extensions
from mariner.printer import PrinterState, is_safe_for_printer
from mariner.server.files import (
    is_scratch_file,
    modification_time,
    replacing,
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
from mariner.server.utils import read_cached_preview, read_cached_sliced_model_file


logger: logging.Logger = logging.getLogger(__name__)

api = Blueprint("api", __name__, url_prefix="/api")

# Monotonic Z-derived layer estimate. Only updated when Z is near an integer
# multiple of layer_height (exposure phase). During retract the Z reading is
# meaningless for layer estimation, so we hold the last known value.
_last_z_layer: Optional[int] = None
_last_z_total_bytes: Optional[int] = None
# Requests are served by several threads, and each poll updates the estimate.
_progress_lock = threading.Lock()


def reset_progress_tracking() -> None:
    """Clear progress tracking state (e.g. between tests)."""
    global _last_z_layer, _last_z_total_bytes
    with _progress_lock:
        _last_z_layer = None
        _last_z_total_bytes = None


def _layer_from_z_position(
    z_pos_mm: Optional[float],
    layer_height_mm: float,
    layer_count: int,
    total_bytes: int,
) -> Optional[int]:
    """Derive current exposed layer from Z. Returns None if Z not in exposure phase.

    MSLA printers retract Z between layers (lift → tilt → descend), so a poll
    can catch Z mid-retract where Z is not near n*layer_height. In that case
    we can't infer the layer and the caller should fall back to the last
    known value.
    """
    with _progress_lock:
        return _layer_from_z_position_locked(
            z_pos_mm, layer_height_mm, layer_count, total_bytes
        )


def _layer_from_z_position_locked(
    z_pos_mm: Optional[float],
    layer_height_mm: float,
    layer_count: int,
    total_bytes: int,
) -> Optional[int]:
    global _last_z_layer, _last_z_total_bytes

    if _last_z_total_bytes != total_bytes:
        _last_z_layer = None
        _last_z_total_bytes = total_bytes

    if z_pos_mm is None or z_pos_mm <= 0 or layer_height_mm <= 0:
        return _last_z_layer

    layer_float = z_pos_mm / layer_height_mm
    nearest = round(layer_float)
    tolerance = 0.1
    if abs(layer_float - nearest) > tolerance:
        return _last_z_layer
    # Z above the last layer is a retract lift, not an exposure position.
    if nearest > layer_count:
        return _last_z_layer

    layer = max(1, min(layer_count, nearest))
    if _last_z_layer is None or layer > _last_z_layer:
        _last_z_layer = layer
    return _last_z_layer


def _layer_from_byte_offset(current_byte: int, end_byte_offsets: List[int]) -> int:
    """Fallback layer lookup: find first layer whose end-byte covers current_byte."""
    if current_byte <= 0 or not end_byte_offsets:
        return 1
    for i, end_byte in enumerate(end_byte_offsets):
        if current_byte <= end_byte:
            return i + 1
    return len(end_byte_offsets)


def _resolve_or_400(relative: Optional[str]) -> Path:
    """The path *relative* names inside the files directory, or a 400."""
    if relative is None:
        abort(400)
    path = resolve_in_files_directory(relative)
    if path is None:
        abort(400)
    return path


@api.errorhandler(MarinerException)
def handle_mariner_exception(exception: MarinerException) -> Tuple[Response, int]:
    tb = traceback.TracebackException.from_exception(exception)
    return (
        jsonify(
            {
                "title": exception.get_title(),
                "description": exception.get_description(),
                "traceback": "".join(tb.format()),
            }
        ),
        500,
    )


def _read_selected_file(selected_file: str) -> Optional[SlicedModelFile]:
    """The parsed file the printer says it is printing, or None if unusable."""
    if not selected_file:
        return None
    path = resolve_in_files_directory(selected_file)
    if path is None or not os.path.isfile(path):
        return None
    try:
        return read_cached_sliced_model_file(path)
    except Exception:
        logger.warning(
            "Could not read %s, which is being printed", selected_file, exc_info=True
        )
        return None


def _abort_file_in_use(error: FileInUse) -> NoReturn:
    """Answer 409: the file cannot change now, and say what to do about it.

    ``code`` tells clients the two cases apart: ``file_in_use`` when the
    printer is reading the file, ``printer_not_answering`` when it could not
    be asked. In the second case the client can read the status again (GET
    /api/print_status asks the printer anew) and retry.
    """
    name = error.path.name
    if error.printer_is_silent:
        body = {
            "code": "printer_not_answering",
            "title": "Printer Not Answering",
            "description": f"The printer did not say whether {name} is being "
            "printed, so it was left untouched. Check that the printer is on "
            "and connected, then try again, or store the file under another "
            "name.",
        }
    else:
        body = {
            "code": "file_in_use",
            "title": "File In Use",
            "description": f"{name} is in use by the print in progress. Wait "
            "for the print to finish or cancel it first, or store the file "
            "under another name.",
        }
    abort(make_response(jsonify(body), 409))


@api.route("/print_status", methods=["GET"])
def print_status() -> Union[str, Response]:
    print_status, selected_file = read_status()
    if print_status.state == PrinterState.CLOSED:
        # A printer that stopped answering may come back on another print.
        reset_progress_tracking()

    sliced_model_file: Optional[SlicedModelFile] = None
    if print_status.state not in (PrinterState.IDLE, PrinterState.CLOSED):
        sliced_model_file = _read_selected_file(selected_file)

    if (
        print_status.state == PrinterState.IDLE
        or print_status.state == PrinterState.CLOSED
    ):
        progress = 0.0
        print_details = {}
    elif sliced_model_file is None:
        # A print is running from a file that cannot be read here: started
        # from the printer's own screen, removed since, or in a format
        # variant this build does not parse. The bytes the printer has
        # consumed still say how far along it is.
        total_bytes = print_status.total_bytes or 0
        progress = (
            100.0 * (print_status.current_byte or 0) / total_bytes
            if total_bytes
            else 0.0
        )
        print_details = {}
    else:
        current_byte = print_status.current_byte or 0
        layer_count = none_throws(sliced_model_file.layer_count)
        layer_height_mm = sliced_model_file.layer_height_mm

        # Z-derived layer is the ground-truth physical layer. ChiTu D: byte
        # position runs ahead of actual exposure (firmware reads/buffers
        # layers before exposing them), so Z is preferred; byte offset is
        # only a fallback for the pre-exposure ramp where Z isn't usable.
        z_layer: Optional[int] = None
        if print_status.state in (PrinterState.PRINTING, PrinterState.PAUSED):
            z_layer = _layer_from_z_position(
                print_status.z_pos_mm,
                layer_height_mm,
                layer_count,
                print_status.total_bytes or 0,
            )

        if z_layer is not None:
            current_layer = z_layer
        else:
            current_layer = _layer_from_byte_offset(
                current_byte, sliced_model_file.end_byte_offset_by_layer
            )

        progress = 100.0 * (current_layer - 1) / layer_count

        print_details = {
            "current_layer": current_layer,
            "layer_count": sliced_model_file.layer_count,
            "print_time_secs": sliced_model_file.print_time_secs,
            "time_left_secs": round(
                sliced_model_file.print_time_secs * (100.0 - progress) / 100.0
            ),
        }

        logger.debug(
            "print_status debug: state=%s file=%r D=(%s/%s) "
            "z=%s z_layer=%s progress=%.3f layer=%s/%s",
            print_status.state.name,
            selected_file,
            current_byte,
            print_status.total_bytes,
            print_status.z_pos_mm,
            z_layer,
            progress,
            current_layer,
            layer_count,
        )

    return jsonify(
        {
            "state": print_status.state.value,
            "selected_file": selected_file,
            "progress": progress,
            **print_details,
        }
    )


def _is_macos_metadata(path: str) -> bool:
    with open(path, "rb") as file:
        return b"Mac OS X" in file.read(32)


@api.route("/list_files", methods=["GET"])
def list_files() -> Union[str, Response]:
    path = _resolve_or_400(request.args.get("path", "."))
    files_directory_resolved = config.get_files_directory().resolve()
    if not os.path.isdir(path):
        abort(404)
    with os.scandir(path) as dir_entries:
        files = []
        directories = []
        for dir_entry in sorted(dir_entries, key=modification_time, reverse=True):
            if is_scratch_file(dir_entry.name):
                # An upload still on its way in; it appears under its real
                # name once complete.
                continue
            if dir_entry.is_dir():
                directories.append({"dirname": dir_entry.name})
            else:
                # Anything that is not a directory is listed as a file, a
                # dangling symbolic link included: it is reported as
                # unprintable instead of as a folder that cannot be opened.
                sliced_model_file: Optional[SlicedModelFile] = None
                if get_file_extension(dir_entry.name) in get_supported_extensions():
                    # A file with a supported extension can still fail to
                    # parse: truncated, corrupted in transfer, or a format
                    # variant this build does not understand. That must not
                    # take down the whole listing, so it is reported as a
                    # file that cannot be printed.
                    try:
                        if dir_entry.name.startswith("._"):
                            if not _is_macos_metadata(dir_entry.path):
                                sliced_model_file = read_cached_sliced_model_file(
                                    path / dir_entry.name
                                )
                        else:
                            sliced_model_file = read_cached_sliced_model_file(
                                path / dir_entry.name
                            )
                    except Exception:
                        logger.warning(
                            "Could not read %s; listing it as unprintable",
                            dir_entry.name,
                            exc_info=True,
                        )
                        sliced_model_file = None

                file_data: Dict[str, Any] = {
                    "filename": dir_entry.name,
                    "path": str(
                        (path / dir_entry.name).relative_to(files_directory_resolved)
                    ),
                }

                if sliced_model_file:
                    file_data = {
                        "print_time_secs": sliced_model_file.print_time_secs,
                        "can_be_printed": True,
                        **file_data,
                    }
                else:
                    file_data = {
                        "can_be_printed": False,
                        **file_data,
                    }

                files.append(file_data)
        return jsonify(
            {
                "directories": directories,
                "files": files,
            }
        )


@api.route("/file_details", methods=["GET"])
def file_details() -> Union[str, Response]:
    filename = request.args.get("filename")
    path = _resolve_or_400(filename)
    if not os.path.isfile(path):
        abort(400)
    sliced_model_file = read_cached_sliced_model_file(path)
    return jsonify(
        {
            "filename": sliced_model_file.filename,
            "path": filename,
            "bed_size_mm": list(sliced_model_file.bed_size_mm),
            "height_mm": round(sliced_model_file.height_mm, 4),
            "layer_count": sliced_model_file.layer_count,
            "layer_height_mm": round(sliced_model_file.layer_height_mm, 4),
            "resolution": list(sliced_model_file.resolution),
            "print_time_secs": sliced_model_file.print_time_secs,
        }
    )


@api.route("/upload_file", methods=["POST"])
def upload_file() -> Union[str, Response]:
    file = request.files.get("file")
    if file is None or file.filename == "":
        abort(400)
    file_filename: str = none_throws(file.filename)
    if get_file_extension(file_filename) not in get_supported_extensions():
        abort(400)
    filename = safe_filename(file_filename)
    if filename is None:
        abort(400)

    parent = _resolve_or_400(request.args.get("path", "."))
    if not os.path.isdir(parent):
        abort(400)

    destination = parent / filename
    if os.path.isdir(destination):
        # A folder already has that name; a file cannot take its place.
        abort(400)
    try:
        # Checked first so a refusal comes before the upload is stored, and
        # again by the guard at the moment the file is moved into place, in
        # case the print started while it was being received.
        with unless_in_use(destination):
            pass
        with replacing(destination, guard=unless_in_use) as scratch:
            file.save(str(scratch))
    except FileInUse as error:
        _abort_file_in_use(error)
    os.sync()
    return jsonify({"success": True})


@api.route("/delete_file", methods=["POST"])
def delete_file() -> Union[str, Response]:
    filename = request.args.get("filename")
    path = _resolve_or_400(filename)
    # we use os.path.isfile instead of Path.is_file here because pyfakefs doesn't
    # seem to properly mock Path.is_file as of pyfakefs 4.4.0
    if not os.path.isfile(path):
        abort(400)
    try:
        with unless_in_use(path):
            os.remove(path)
    except FileInUse as error:
        _abort_file_in_use(error)
    return jsonify({"success": True})


@api.route("/create_directory", methods=["POST"])
def create_directory() -> Union[str, Response]:
    safe_name = safe_filename(request.args.get("name", type=str))
    if safe_name is None:
        abort(400)

    parent = _resolve_or_400(request.args.get("path", "."))
    if not os.path.isdir(parent):
        abort(400)
    new_path = parent / safe_name

    try:
        os.mkdir(new_path)
    except FileExistsError:
        abort(400)
    return jsonify({"success": True})


@api.route("/file_preview", methods=["GET"])
def file_preview() -> Response:
    filename = request.args.get("filename")
    path = _resolve_or_400(filename)
    if not os.path.isfile(path):
        abort(400)

    preview_bytes = read_cached_preview(path)

    response = make_response(preview_bytes)
    response.headers.set("Content-Type", "image/png")
    response.headers.set(
        "Content-Disposition", "attachment", filename=f"{filename}.png"
    )

    return response


class PrinterCommand(Enum):
    START_PRINT = "start_print"
    PAUSE_PRINT = "pause_print"
    RESUME_PRINT = "resume_print"
    CANCEL_PRINT = "cancel_print"
    REBOOT = "reboot"


def _printable_file_or_abort(filename: Optional[str]) -> str:
    """The path to give the printer for *filename*, or an error response.

    The path ends up verbatim in the command lines sent over serial, so the
    request is refused unless the name is free of control characters and
    points at an existing file of a supported format inside the files
    directory. What is returned is that file's path relative to the files
    directory, which is how the printer knows it, whatever form the client
    used (``./a.ctb``, ``sub/../a.ctb`` or an absolute path).
    """
    if filename is None or not is_safe_for_printer(filename):
        abort(400)
    path = _resolve_or_400(filename)
    if not os.path.isfile(path):
        abort(404)
    if get_file_extension(path.name) not in get_supported_extensions():
        abort(400)
    relative = path.relative_to(config.get_files_directory().resolve()).as_posix()
    if not is_safe_for_printer(relative):
        # Possible only through a symbolic link whose target has such a name.
        abort(400)
    return relative


@api.route("/printer/command/<command>", methods=["POST"])
def printer_command(command: str) -> Union[str, Response]:
    try:
        printer_command = PrinterCommand(command)
    except ValueError:
        abort(404)

    if printer_command == PrinterCommand.START_PRINT:
        start_print(_printable_file_or_abort(request.args.get("filename")))
        return jsonify({"success": True})

    with printer_session() as printer:
        if printer_command == PrinterCommand.PAUSE_PRINT:
            printer.pause_printing()
        elif printer_command == PrinterCommand.RESUME_PRINT:
            printer.resume_printing()
        elif printer_command == PrinterCommand.CANCEL_PRINT:
            printer.stop_printing()
        elif printer_command == PrinterCommand.REBOOT:
            printer.reboot()
        return jsonify({"success": True})


@api.route("/host/shutdown", methods=["POST"])
def host_shutdown() -> Union[str, Response]:
    logger.warning("Host shutdown requested via API")
    subprocess.Popen(["shutdown", "-h", "now"])
    return jsonify({"success": True})


@api.route("/host/reboot", methods=["POST"])
def host_reboot() -> Union[str, Response]:
    logger.warning("Host reboot requested via API")
    subprocess.Popen(["reboot"])
    return jsonify({"success": True})
