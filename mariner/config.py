from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, MutableMapping, Optional, Sequence

import toml


def __get_config_filename() -> Optional[str]:
    potential_paths: Sequence[Path] = [
        Path("config.toml"),
        Path("~/.mariner/config.toml"),
        Path("/etc/mariner/config.toml"),
    ]
    try:
        path = next(
            path for path in potential_paths if path.exists() and not path.is_dir()
        )
    except StopIteration:
        return None
    return str(path.absolute())


@lru_cache(maxsize=None)
def _get_config() -> MutableMapping[str, object]:
    filename = __get_config_filename()
    if filename is None:
        return {}
    with open(filename, "r") as file:
        toml_string = file.read()
        return toml.loads(toml_string)


def get_files_directory() -> Path:
    config = _get_config()
    return Path(str(config.get("files_directory", "/mnt/usb_share")))


def get_printer_display_name() -> Optional[str]:
    printer_config = _get_config().get("printer")
    if not isinstance(printer_config, dict):
        return None
    display_name = printer_config.get("display_name")
    if display_name is None:
        return None
    return str(display_name)


def get_printer_serial_port() -> str:
    default_port = "/dev/serial0"
    printer_config = _get_config().get("printer")
    if not isinstance(printer_config, dict):
        return default_port
    return str(printer_config.get("serial_port", default_port))


def get_printer_baudrate() -> int:
    default_baudrate = 115200
    printer_config = _get_config().get("printer")
    if not isinstance(printer_config, dict):
        return default_baudrate
    return int(printer_config.get("baudrate", default_baudrate))


def get_log_level() -> str:
    """Global process log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)."""
    level = _get_config().get("log_level", "INFO")
    valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    level_str = str(level).upper()
    if level_str not in valid:
        return "INFO"
    return level_str


def get_http_host() -> str:
    default_host = "0.0.0.0"
    http_config = _get_config().get("http")
    if not isinstance(http_config, dict):
        return default_host
    return str(http_config.get("host", default_host))


def get_http_port() -> int:
    default_port = 5050
    http_config = _get_config().get("http")
    if not isinstance(http_config, dict):
        return default_port
    return int(http_config.get("port", default_port))


def get_http_allowed_hosts() -> List[str]:
    """Names Mariner answers to besides its address and local names.

    ``allowed_hosts`` under ``[http]``: a list of names, or ``"*"`` for any.
    """
    http_config = _get_config().get("http")
    if not isinstance(http_config, dict):
        return []
    hosts = http_config.get("allowed_hosts", [])
    if isinstance(hosts, str):
        return [hosts]
    if not isinstance(hosts, list):
        return []
    return [str(host) for host in hosts]


DEFAULT_MAX_UPLOAD_SIZE_MB = 2048


def get_max_upload_bytes() -> int:
    """The largest file any interface accepts, in bytes.

    Set in megabytes as ``max_upload_size_mb`` under ``[http]``. Anything
    but a whole number above zero is taken for the default.
    """
    megabytes: object = DEFAULT_MAX_UPLOAD_SIZE_MB
    http_config = _get_config().get("http")
    if isinstance(http_config, dict):
        megabytes = http_config.get("max_upload_size_mb", megabytes)
    if isinstance(megabytes, bool) or not isinstance(megabytes, int) or megabytes <= 0:
        megabytes = DEFAULT_MAX_UPLOAD_SIZE_MB
    return megabytes * 1024 * 1024


def get_spool_directory() -> str:
    """Where an upload is kept while it arrives: a place on a drive.

    The web server writes an upload to a temporary file before handing it
    over. In the default place for those, /tmp, it would be held in memory
    on systems where /tmp is, and a file can be larger than the memory of
    the board.
    """
    default_directory = "/var/tmp"
    http_config = _get_config().get("http")
    if not isinstance(http_config, dict):
        return default_directory
    return str(http_config.get("spool_directory", default_directory))


def get_cache_directory() -> str:
    default_directory = "/tmp/mariner/"
    cache_config = _get_config().get("cache")
    if not isinstance(cache_config, dict):
        return default_directory
    return str(cache_config.get("directory", default_directory))


def get_uvtools_enabled() -> bool:
    """Whether the routes UVtools sends files and commands to are served."""
    uvtools_config = _get_config().get("uvtools")
    if not isinstance(uvtools_config, dict):
        return True
    return bool(uvtools_config.get("enabled", True))


def _sdcp_config() -> Dict[str, Any]:
    # Values come back as Any (rather than object) so callers can coerce them
    # with int()/float(), matching how the other config sections narrow.
    sdcp_config = _get_config().get("sdcp")
    if not isinstance(sdcp_config, dict):
        return {}
    return sdcp_config


def get_sdcp_enabled() -> bool:
    return bool(_sdcp_config().get("enabled", True))


def get_sdcp_brand_name() -> str:
    return str(_sdcp_config().get("brand_name", "CBD"))


def get_sdcp_machine_name() -> str:
    configured = _sdcp_config().get("machine_name")
    if configured is not None:
        return str(configured)
    return get_printer_display_name() or "Mariner"


def get_sdcp_firmware_version() -> str:
    """Firmware version to advertise. Empty means read it from the printer."""
    return str(_sdcp_config().get("firmware_version", ""))


def get_sdcp_resolution() -> str:
    """Panel resolution as ``WxH``. Empty means derive it from a sliced file."""
    return str(_sdcp_config().get("resolution", ""))


def get_sdcp_xyz_size() -> str:
    """Build volume as ``XxYxZ`` in mm. Empty means derive it from a file."""
    return str(_sdcp_config().get("xyz_size", ""))


def get_sdcp_mainboard_id() -> Optional[str]:
    mainboard_id = _sdcp_config().get("mainboard_id")
    if mainboard_id is None:
        return None
    return str(mainboard_id)


def get_sdcp_discovery_port() -> int:
    return int(_sdcp_config().get("discovery_port", 3000))


def get_sdcp_server_port() -> int:
    return int(_sdcp_config().get("server_port", 3030))


def get_sdcp_poll_interval_secs() -> float:
    return float(_sdcp_config().get("poll_interval_secs", 3.0))


def get_sdcp_internal_machine_name() -> str:
    """Bare model name, without the brand, for client picture matching.

    ChituManager keys its printer images on a normalised model name. In the
    discovery reply it prefixes BrandName, so sending the bare model here
    (e.g. "Mars 3" alongside brand "ELEGOO") matches without the brand being
    counted twice. Empty means the field is not sent at all.
    """
    return str(_sdcp_config().get("internal_machine_name", ""))


def get_sdcp_optional_devices() -> List[str]:
    """Optional hardware fitted to this machine, e.g. ``x_motor``.

    SDCP's device self-check has no value meaning "not fitted": 0 is
    "disconnected", which clients show as a fault. So hardware not listed
    here is left out of the report entirely rather than reported as 0.
    """
    configured = _sdcp_config().get("optional_devices")
    if not isinstance(configured, list):
        return []
    return [str(device).strip().lower() for device in configured]


def get_sdcp_history_enabled() -> bool:
    return bool(_sdcp_config().get("history_enabled", True))


def get_sdcp_history_limit() -> int:
    return int(_sdcp_config().get("history_limit", 50))


def get_sdcp_history_path() -> Path:
    """Where print task history is persisted.

    Defaults into the cache directory, which is often tmpfs, so history is
    lost on reboot unless this is pointed somewhere durable.
    """
    configured = _sdcp_config().get("history_path")
    if configured:
        return Path(str(configured))
    return Path(get_cache_directory()) / "sdcp_history.json"
