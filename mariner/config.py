import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, MutableMapping, Optional, Sequence, Tuple

import ipaddress
import re
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


# What was changed from Mariner's page, which comes before the file: see
# mariner.server.settings, which fills this in.
overrides: Dict[str, Any] = {}


def get_assume_printer_off() -> bool:
    """Whether a printer that does not answer is taken for switched off.

    Changing or deleting a file then goes ahead without the question the
    page otherwise asks. Set from the page only.
    """
    return overrides.get("assume_printer_off") is True


def get_printer_display_name() -> Optional[str]:
    if isinstance(overrides.get("printer_display_name"), str):
        return overrides["printer_display_name"]
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


def _https() -> MutableMapping[str, object]:
    section = _get_config().get("https")
    return section if isinstance(section, dict) else {}


def get_https_enabled() -> bool:
    """Whether Mariner serves its page over HTTPS itself.

    On unless it is plainly switched off: taken for off, something that is
    neither true nor false would put the page in the clear without anyone
    having said so.
    """
    return _https().get("enabled", True) is not False


DEFAULT_HTTPS_PORT = 5443


def _is_a_port(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 < value < 65536


def get_https_port() -> int:
    port = _https().get("port", DEFAULT_HTTPS_PORT)
    return port if _is_a_port(port) else DEFAULT_HTTPS_PORT  # type: ignore


def _own_certificate() -> Optional[Tuple[str, str]]:
    """The certificate and key of the owner's own, when both are named."""
    certificate, key = _https().get("certificate"), _https().get("key")
    if isinstance(certificate, str) and isinstance(key, str):
        return certificate, key
    return None


def get_https_certificate() -> Optional[str]:
    own = _own_certificate()
    return own[0] if own else None


def get_https_key() -> Optional[str]:
    own = _own_certificate()
    return own[1] if own else None


def _internet() -> MutableMapping[str, object]:
    section = _get_config().get("internet")
    return section if isinstance(section, dict) else {}


def _is_a_network(given: object) -> bool:
    if not isinstance(given, str):
        return False
    try:
        ipaddress.ip_network(given, strict=False)
    except ValueError:
        return False
    return True


def _networks(name: str) -> List[str]:
    given = _internet().get(name, [])
    if not isinstance(given, list):
        return []
    return [one for one in given if _is_a_network(one)]


def get_local_networks() -> List[str]:
    """Networks taken for local besides the usual ones.

    ``local_networks`` under ``[internet]``: see mariner.server.provenance.
    """
    return _networks("local_networks")


def get_not_local() -> List[str]:
    """Addresses and networks that are not local, whatever they look like.

    ``not_local`` under ``[internet]``: a router that passes connections
    on under its own address, a tunnel that ends on this computer.
    """
    return _networks("not_local")


def get_host_commands_from_internet() -> bool:
    """Whether the computer can be stopped or restarted from the Internet.

    Only when plainly allowed.
    """
    return _internet().get("host_commands", False) is True


_A_NAME = re.compile(r"(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}")
DEFAULT_PUBLIC_PORT = 443


def get_public_name() -> Optional[str]:
    """The name Mariner is reached under from the Internet, if it has one.

    ``public_name`` under ``[internet]``, as in ``printer.example.org``:
    Mariner answers to it besides its address and local names.
    """
    given = _internet().get("public_name")
    if not isinstance(given, str):
        return None
    name = given.strip().lower().rstrip(".")
    return name if _A_NAME.fullmatch(name) else None


def get_public_port() -> int:
    """The port its page is reached at from the Internet, over HTTPS.

    ``public_port`` under ``[internet]``: the port the router listens on,
    where it is not the one it passes connections on to. 443 unless said.
    """
    given = _internet().get("public_port", DEFAULT_PUBLIC_PORT)
    if isinstance(given, bool) or not isinstance(given, int):
        return DEFAULT_PUBLIC_PORT
    return given if 1 <= given <= 65535 else DEFAULT_PUBLIC_PORT


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


def get_http_allowed_origins() -> List[str]:
    """Addresses at which Mariner's page is served, besides its own.

    ``allowed_origins`` under ``[http]``: whole addresses such as
    ``"https://printer.example.org"``, for a relay in front of Mariner
    that asks it under another name, port or scheme than the browser used.
    """
    http_config = _get_config().get("http")
    if not isinstance(http_config, dict):
        return []
    origins = http_config.get("allowed_origins", [])
    if isinstance(origins, str):
        return [origins]
    if not isinstance(origins, list):
        return []
    return [str(one) for one in origins]


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


def ignored_settings() -> List[str]:
    """What the configuration sets in a way that is passed over, in words.

    For the log at start: a setting quietly taken for its default, or for
    off, looks like one that was applied.
    """
    found = []
    http_config = _get_config().get("http")
    if isinstance(http_config, dict) and "max_upload_size_mb" in http_config:
        megabytes = http_config["max_upload_size_mb"]
        whole = isinstance(megabytes, int) and not isinstance(megabytes, bool)
        if not (whole and megabytes > 0):
            found.append(
                f"[http] max_upload_size_mb = {megabytes!r} is not a whole "
                f"number above zero: {DEFAULT_MAX_UPLOAD_SIZE_MB} is used"
            )
    if "enabled" in _https() and not isinstance(_https()["enabled"], bool):
        found.append(
            f"[https] enabled = {_https()['enabled']!r} is neither true nor "
            "false: HTTPS stays on"
        )
    if "port" in _https() and not _is_a_port(_https()["port"]):
        found.append(
            f"[https] port = {_https()['port']!r} is not a port (a whole "
            f"number from 1 to 65535): {DEFAULT_HTTPS_PORT} is used"
        )
    if ("certificate" in _https() or "key" in _https()) and not _own_certificate():
        found.append(
            "[https] certificate and [https] key go together, each the path "
            "of a file: Mariner makes a certificate of its own instead"
        )
    for name in ("local_networks", "not_local"):
        if name not in _internet():
            continue
        given = _internet()[name]
        if not isinstance(given, list):
            found.append(
                f"[internet] {name} = {given!r} is not a list of networks: "
                "it is passed over"
            )
            continue
        for one in given:
            if not _is_a_network(one):
                found.append(
                    f"[internet] {name}: {one!r} is neither an address nor a "
                    "network (as in 192.168.1.0/24): it is passed over"
                )
    if "public_name" in _internet() and get_public_name() is None:
        found.append(
            f"[internet] public_name = {_internet()['public_name']!r} is not a "
            "name (as in printer.example.org, without https:// or a port): "
            "it is passed over"
        )
    if "public_port" in _internet():
        given = _internet()["public_port"]
        if (
            isinstance(given, bool)
            or not isinstance(given, int)
            or not (1 <= given <= 65535)
        ):
            found.append(
                f"[internet] public_port = {given!r} is not a port: "
                f"{DEFAULT_PUBLIC_PORT} is used"
            )
    if "host_commands" in _internet() and not isinstance(
        _internet()["host_commands"], bool
    ):
        found.append(
            f"[internet] host_commands = {_internet()['host_commands']!r} is "
            "neither true nor false: it is taken for false"
        )
    for section in ("uvtools", "sdcp"):
        section_config = _get_config().get(section)
        if isinstance(section_config, dict) and "enabled" in section_config:
            value = section_config["enabled"]
            if not isinstance(value, bool):
                found.append(
                    f"[{section}] enabled = {value!r} is neither true nor "
                    "false: it is taken for false"
                )
    return found


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


def get_state_directory() -> str:
    """Where Mariner keeps what must outlast a restart, for itself alone.

    The key of sessions, the password's hash, the settings changed from
    the page. ``directory`` under ``[state]``; the default is the folder
    systemd makes for the service.
    """
    default_directory = "/var/lib/mariner"
    state_config = _get_config().get("state")
    if not isinstance(state_config, dict):
        return default_directory
    return str(state_config.get("directory", default_directory))


# Where things are kept when the state directory cannot be made: in the
# home of the account Mariner runs under, as when it is run by hand.
STATE_FALLBACKS: List[str] = ["~/.mariner/state"]


def state_directory_can_be_made(wanted: str) -> bool:
    """Whether Mariner would make and use a folder at *wanted*.

    Nothing is made for asking. Mariner and the commands about the
    password go by this, so that they look in the same folder. One
    reached through a link is not used: it could lead to where another
    account reads or writes.
    """
    above = os.path.abspath(os.path.expanduser(wanted))
    if os.path.realpath(above) != above:
        return False
    while not os.path.lexists(above):
        parent = os.path.dirname(above)
        if parent == above:
            return False
        above = parent
    return os.path.isdir(above) and os.access(above, os.W_OK | os.X_OK)


DEFAULT_CACHE_DIRECTORY = "/var/cache/mariner"


def get_cache_directory() -> str:
    default_directory = DEFAULT_CACHE_DIRECTORY
    cache_config = _get_config().get("cache")
    if not isinstance(cache_config, dict):
        return default_directory
    return str(cache_config.get("directory", default_directory))


def _switch(value: object) -> bool:
    """Whether a setting that switches something on says so.

    Only ``true`` does. Anything else is taken for off: ``"false"`` between
    quotes is text, which would otherwise count as on.
    """
    return value is True


def get_uvtools_enabled() -> bool:
    """Whether the routes UVtools sends files and commands to are served."""
    if isinstance(overrides.get("uvtools_enabled"), bool):
        return overrides["uvtools_enabled"]
    uvtools_config = _get_config().get("uvtools")
    if not isinstance(uvtools_config, dict):
        return True
    return _switch(uvtools_config.get("enabled", True))


def _sdcp_config() -> Dict[str, Any]:
    # Values come back as Any (rather than object) so callers can coerce them
    # with int()/float(), matching how the other config sections narrow.
    sdcp_config = _get_config().get("sdcp")
    if not isinstance(sdcp_config, dict):
        return {}
    return sdcp_config


def get_sdcp_enabled() -> bool:
    if isinstance(overrides.get("sdcp_enabled"), bool):
        return overrides["sdcp_enabled"]
    return _switch(_sdcp_config().get("enabled", True))


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


def get_sdcp_history_path() -> Optional[Path]:
    """Where print task history is kept, when a place is named for it.

    ``history_path`` under ``[sdcp]``. Left out, it is kept with what
    Mariner keeps from one start to the next (see ``[state]``).
    """
    configured = _sdcp_config().get("history_path")
    if configured:
        return Path(str(configured))
    return None
