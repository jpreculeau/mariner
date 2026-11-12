import logging
import os
import subprocess
import threading
import urllib.parse
from enum import Enum
from functools import partial
from pathlib import Path
from typing import (
    Any,
    Callable,
    ContextManager,
    Dict,
    List,
    NoReturn,
    Optional,
    Tuple,
    TypeVar,
    Union,
)

from flask import (
    Blueprint,
    Response,
    abort,
    jsonify,
    make_response,
    request,
)
from flask_wtf.csrf import generate_csrf
from pyre_extensions import none_throws

from mariner import config
from mariner.exceptions import (
    MarinerException,
    PrintAlreadyRunning,
    PrintJustStarted,
)
from mariner.file_formats import SlicedModelFile
from mariner.file_formats.reading import MalformedFile
from mariner.file_formats.utils import (
    UnsupportedFileFormat,
    get_file_extension,
    get_supported_extensions,
)
from mariner.printer import PrinterState
from mariner.server.files import (
    NotPrintable,
    is_directory,
    MAX_FOLDER_DEPTH,
    folder_depth,
    is_hidden_entry,
    is_macos_companion,
    modification_time,
    remove_entry,
    replacing,
    resolve_entry_in_files_directory,
    resolve_in_files_directory,
    safe_filename,
    stays_in_files_directory,
)
from mariner.server.printer_access import (
    FileInUse,
    Usage,
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
    # Where it happened goes to the logs, not to whoever asks.
    logger.warning("Printer error while serving %r", request.path, exc_info=exception)
    return (
        jsonify(
            {
                "code": "printer_error",
                "title": exception.get_title(),
                "description": exception.get_description(),
            }
        ),
        500,
    )


_T = TypeVar("_T")


def _read_or_refuse(read: Callable[[Path], _T], path: Path) -> _T:
    """What *read* makes of the file at *path*, for a request about it.

    A file can be listed and still not be readable: cut short by a transfer
    that failed, damaged, or made by a slicer version Mariner does not
    know. The client is told so in words it can show, and told apart from
    a read that failed for another reason.
    """
    try:
        return read(path)
    except FileNotFoundError:
        # Removed since the request checked that it was there.
        abort(404)
    except UnsupportedFileFormat:
        abort(400)
    except MalformedFile:
        # Reported, with the reason, when the file was read.
        body = {
            "code": "file_unreadable",
            "title": "File Cannot Be Read",
            "description": f"{path.name} cannot be read: it is incomplete, "
            "damaged, or of a kind Mariner does not know. Transfer it again "
            "from the slicer.",
        }
        abort(make_response(jsonify(body), 422))
    except Exception:
        # The drive or the memory, say: nothing that sending the file again
        # would cure.
        logger.warning("Could not read %r", path.name, exc_info=True)
        body = {
            "code": "file_read_failed",
            "title": "File Could Not Be Read",
            "description": f"Mariner failed to read {path.name}. Try again; "
            "if it keeps failing, the logs say why.",
        }
        abort(make_response(jsonify(body), 500))


def _read_selected_file(selected_file: str) -> Optional[SlicedModelFile]:
    """The parsed file the printer says it is printing, or None if unusable."""
    if not selected_file:
        return None
    path = resolve_in_files_directory(selected_file)
    if path is None or not os.path.isfile(path):
        return None
    try:
        return read_cached_sliced_model_file(path)
    except MalformedFile:
        return None
    except Exception:
        logger.warning(
            "Could not read %r, which is being printed", selected_file, exc_info=True
        )
        return None


# What to tell the user for each reason a file cannot change, keyed by
# FileInUse.usage. ``code`` lets a client tell the cases apart; the sentence
# is completed with what can be done about it, which depends on the
# operation (see _abort_file_in_use).
_IN_USE_ANSWERS: Dict[Usage, Tuple[str, str, str]] = {
    Usage.PRINTING: (
        "file_in_use",
        "File In Use",
        "{name} is in use by the print in progress. Wait for the print to "
        "finish or cancel it first",
    ),
    Usage.JUST_STARTED: (
        "print_just_started",
        "Print Just Started",
        "{name} is in use by a print that was started a moment ago. It stays "
        "protected for half a minute, even if that print was cancelled. Try "
        "again then",
    ),
    Usage.UNIDENTIFIED_PRINT: (
        "print_file_unknown",
        "Print In Progress",
        "A print is in progress and the printer did not say from which file, "
        "so {name} was left untouched. Wait for the print to finish or cancel "
        "it first",
    ),
    Usage.PRINTER_UNCLEAR: (
        "printer_answer_unclear",
        "Printer Answer Unclear",
        "Mariner could not get a clear answer from the printer, so there is "
        "no telling whether {name} is being printed, and it was left "
        "untouched. Try again in a moment",
    ),
    Usage.PRINTER_UNREACHABLE: (
        "printer_not_answering",
        "Printer Not Answering",
        "The printer did not answer, so there is no telling whether {name} "
        "is being printed, and it was left untouched. Check that the printer "
        "is on and connected, then try again",
    ),
}


def _abort_file_in_use(error: FileInUse, *, replacing_it: bool) -> NoReturn:
    """Answer 409: the file cannot change now, and say what to do about it.

    *replacing_it* is True for an upload, which has one more way out than a
    deletion: storing the file under another name.

    ``can_be_overridden`` tells the client whether repeating the request
    with ``ignore_unreachable_printer=1`` can go through, which is only the
    case when the printer is positively silent.
    """
    code, title, sentence = _IN_USE_ANSWERS[error.usage]
    description = sentence.format(name=error.path.name)
    description += ", or store the file under another name." if replacing_it else "."
    body = {
        "code": code,
        "title": title,
        "description": description,
        "can_be_overridden": error.usage is Usage.PRINTER_UNREACHABLE,
    }
    abort(make_response(jsonify(body), 409))


def _guard_for_this_request() -> Callable[[Path], ContextManager[None]]:
    """The in-use guard, relaxed if the user vouched that the printer is off.

    A client sends ``ignore_unreachable_printer=1`` after the user was told
    the printer does not answer and confirmed that it is switched off. The
    file is still refused if the printer does answer and is printing it.
    """
    return partial(unless_in_use, even_if_unreachable=_printer_declared_off())


def _printer_declared_off() -> bool:
    return request.args.get("ignore_unreachable_printer") == "1"


def _refuse_early_if_in_use(destination: Path) -> None:
    """Raise FileInUse before anything is written, when that is already known.

    A refusal then costs nothing. A silent printer the user vouched for is
    not refused here: the guard asks it again at the moment the file is
    moved into place, which is the answer that counts. The silence
    remembered from the request that was refused spares asking here; if
    nothing recent is remembered, this check asks too, and such a request
    waits for the printer twice.
    """
    try:
        with unless_in_use(destination):
            pass
    except FileInUse as error:
        if error.usage is Usage.PRINTER_UNREACHABLE and _printer_declared_off():
            return
        raise


@api.route("/csrf_token", methods=["GET"])
def csrf_token() -> Response:
    """Give the page a token for its requests, as the page itself carries.

    For a page whose own went stale while it was open: Mariner restarted,
    or the browser's session ended. Another site's page cannot read the
    answer.
    """
    return jsonify({"csrf_token": generate_csrf()})


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
            if is_hidden_entry(dir_entry.name):
                # Something on its way in or out, or the SDCP transfer
                # folder. See files.is_hidden_entry.
                continue
            if is_directory(dir_entry):
                directories.append({"dirname": dir_entry.name})
            else:
                # Anything that is not a directory is listed as a file, a
                # dangling symbolic link included: it is reported as
                # unprintable instead of as a folder that cannot be opened.
                sliced_model_file: Optional[SlicedModelFile] = None
                # A link leading out of the files directory is listed, so
                # that it can be removed, but what it leads to is not read.
                # (A link to a transfer in progress is listed too. Deleting
                # it removes the link at most, never the transfer, and a
                # link beside the transfer is refused outright. Another
                # name for a transfer, where the filesystem has such
                # names, is listed and opened here like any file.)
                # Only a link can lead elsewhere, and only links are
                # checked: the check looks through the whole folder.
                leads_elsewhere = (
                    dir_entry.is_symlink()
                    and not stays_in_files_directory(path / dir_entry.name)
                )
                if (
                    get_file_extension(dir_entry.name) in get_supported_extensions()
                    and not leads_elsewhere
                ):
                    # A file with a supported extension can still fail to
                    # parse: truncated, corrupted in transfer, or a format
                    # variant this build does not understand. That must not
                    # take down the whole listing, so it is reported as a
                    # file that cannot be printed.
                    try:
                        if not is_macos_companion(dir_entry.path):
                            sliced_model_file = read_cached_sliced_model_file(
                                path / dir_entry.name
                            )
                    except MalformedFile:
                        # Reported, with the reason, when it was read.
                        sliced_model_file = None
                    except Exception:
                        logger.warning(
                            "Could not read %r; listing it as unprintable",
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
    sliced_model_file = _read_or_refuse(read_cached_sliced_model_file, path)
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
    # The name as it will be stored, then its extension: the same order as
    # the other interfaces, so that all three agree on a name with spaces
    # around it.
    filename = safe_filename(none_throws(file.filename))
    if filename is None:
        abort(400)
    if get_file_extension(filename) not in get_supported_extensions():
        abort(400)

    folder = request.args.get("path", ".")
    if not os.path.isdir(_resolve_or_400(folder)):
        abort(400)

    # The entry of that name in the folder, whatever it is at present.
    destination = resolve_entry_in_files_directory(os.path.join(folder, filename))
    if destination is None:
        abort(400)
    if os.path.isdir(destination):
        # A folder already has that name; a file cannot take its place.
        abort(400)
    try:
        # Checked again by the guard at the moment the file is moved into
        # place, in case a print started while it was being written to disk.
        _refuse_early_if_in_use(destination)
        with replacing(destination, guard=_guard_for_this_request()) as scratch:
            file.save(str(scratch))
    except FileInUse as error:
        _abort_file_in_use(error, replacing_it=True)
    except FileNotFoundError:
        # The folder was removed while the file was being written.
        abort(404)
    except OSError as error:
        # No room left on the drive, most often.
        logger.warning("Could not store %r: %s", filename, error)
        body = {
            "code": "upload_not_stored",
            "title": "File Not Stored",
            "description": f"{filename} could not be stored. Check that the "
            "drive has room for it.",
        }
        abort(make_response(jsonify(body), 500))
    os.sync()
    return jsonify({"success": True})


@api.route("/delete_file", methods=["POST"])
def delete_file() -> Union[str, Response]:
    filename = request.args.get("filename")
    # The entry itself, not what it leads to: deleting a symbolic link
    # removes the link, whether or not its target still exists.
    path = resolve_entry_in_files_directory(filename) if filename else None
    if path is None:
        abort(400)
    if not (os.path.isfile(path) or os.path.islink(path)):
        abort(400)
    try:
        with _guard_for_this_request()(path):
            remove_entry(path)
    except FileInUse as error:
        _abort_file_in_use(error, replacing_it=False)
    except FileNotFoundError:
        # Someone else removed it in the meantime.
        abort(404)
    return jsonify({"success": True})


def _refuse_folder(code: str, title: str, description: str) -> NoReturn:
    """Answer 400 to a folder that cannot be made, saying why."""
    body = {"code": code, "title": title, "description": description}
    abort(make_response(jsonify(body), 400))


@api.route("/create_directory", methods=["POST"])
def create_directory() -> Union[str, Response]:
    safe_name = safe_filename(request.args.get("name", type=str))
    if safe_name is None:
        _refuse_folder(
            "name_not_allowed",
            "Name Not Allowed",
            "A folder cannot have this name. Leave out slashes and names "
            "made of dots only, and do not make it too long.",
        )

    parent = _resolve_or_400(request.args.get("path", "."))
    if not os.path.isdir(parent):
        abort(400)
    new_path = parent / safe_name
    if folder_depth(new_path) > MAX_FOLDER_DEPTH:
        _refuse_folder(
            "folder_too_deep",
            "Too Many Folders Deep",
            f"Folders can be {MAX_FOLDER_DEPTH} deep at most. Make this one "
            "higher up.",
        )

    try:
        os.mkdir(new_path)
    except FileExistsError:
        _refuse_folder(
            "folder_exists",
            "Name Already Taken",
            "A folder or a file of this name is already there. Give the "
            "folder another name.",
        )
    except OSError as error:
        # A path longer than the system takes, a drive that is full.
        logger.warning("Could not make the folder %r: %s", safe_name, error)
        _refuse_folder(
            "folder_not_created",
            "Folder Not Made",
            "The folder could not be made: its name may be too long, or "
            "the drive full. Mariner's log says more.",
        )
    return jsonify({"success": True})


def _shown_as(name: str) -> str:
    """A ``Content-Disposition`` header for what is shown, named *name*.

    Shown where it was asked for, and named for whoever saves it. Not sent
    as a file to save: a download starts or not as the file exists or not,
    and a page of another site that has the browser ask could tell which.

    A header carries plain characters only. The name is given in full in
    the form made for any script, and in plain characters, with the others
    replaced, for clients that only know the older form.
    """
    plain = "".join(
        character if " " <= character < "\x7f" and character not in '"\\' else "_"
        for character in name
    )
    encoded = urllib.parse.quote(name, safe="")
    return f"inline; filename=\"{plain}\"; filename*=UTF-8''{encoded}"


@api.route("/file_preview", methods=["GET"])
def file_preview() -> Response:
    filename = request.args.get("filename")
    path = _resolve_or_400(filename)
    if not os.path.isfile(path):
        abort(400)

    preview_bytes = _read_or_refuse(read_cached_preview, path)

    response = make_response(preview_bytes)
    response.headers.set("Content-Type", "image/png")
    response.headers.set("Content-Disposition", _shown_as(f"{path.name}.png"))

    return response


class PrinterCommand(Enum):
    START_PRINT = "start_print"
    PAUSE_PRINT = "pause_print"
    RESUME_PRINT = "resume_print"
    CANCEL_PRINT = "cancel_print"
    REBOOT = "reboot"


@api.route("/printer/command/<command>", methods=["POST"])
def printer_command(command: str) -> Union[str, Response]:
    try:
        printer_command = PrinterCommand(command)
    except ValueError:
        abort(404)

    if printer_command == PrinterCommand.START_PRINT:
        filename = request.args.get("filename")
        if filename is None:
            abort(400)
        try:
            start_print(filename)
        except NotPrintable as error:
            abort(404 if error.reason == NotPrintable.MISSING else 400)
        except PrintAlreadyRunning as error:
            just_started = isinstance(error, PrintJustStarted)
            body = {
                "code": "print_just_started" if just_started else "print_in_progress",
                "title": error.get_title(),
                "description": error.get_description(),
            }
            abort(make_response(jsonify(body), 409))
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


_HOST_COMMAND_TIMEOUT_SECS = 15


def _run_host_command(command: List[str]) -> None:
    """Run a command that stops or restarts the host; 503 if it is refused.

    The command returns at once when it is accepted. It is refused when the
    account Mariner runs under has no right to it, which the answer must
    say: started and forgotten, a refusal looked like a host that would
    not go down.
    """
    try:
        done = subprocess.run(
            command, capture_output=True, timeout=_HOST_COMMAND_TIMEOUT_SECS
        )
        failure = None if done.returncode == 0 else done.stderr[:500]
    except (OSError, subprocess.TimeoutExpired) as error:
        failure = error
    if failure is None:
        return
    logger.warning("Host command %r was not carried out: %r", command, failure)
    body = {
        "code": "host_command_refused",
        "title": "Command Refused",
        "description": "The computer Mariner runs on did not accept the "
        "command. Mariner may not have the right to stop or restart it.",
    }
    abort(make_response(jsonify(body), 503))


@api.route("/host/shutdown", methods=["POST"])
def host_shutdown() -> Union[str, Response]:
    logger.warning("Host shutdown requested via API")
    _run_host_command(["shutdown", "-h", "now"])
    return jsonify({"success": True})


@api.route("/host/reboot", methods=["POST"])
def host_reboot() -> Union[str, Response]:
    logger.warning("Host reboot requested via API")
    _run_host_command(["reboot"])
    return jsonify({"success": True})
