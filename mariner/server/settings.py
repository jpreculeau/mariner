"""The settings that can be changed from Mariner's page.

A few, of those in the configuration file: the ones somebody is likely to
want without opening a terminal. They are kept in the folder Mariner
keeps for itself and come before what the file says, which Mariner's
account often cannot write.
"""

import json
import logging
import os
import signal
import threading
from typing import Any, Dict, Mapping

from flask import Blueprint, Response, jsonify, make_response, request

from mariner import config
from mariner.printer import has_control_character
from mariner.server import state

logger: logging.Logger = logging.getLogger(__name__)

_KEPT_AS = "settings.json"
_LONGEST_NAME = 64
_SWITCHES = ("uvtools_enabled", "sdcp_enabled", "assume_printer_off")
# Read when Mariner starts: changed, they wait for the next start.
_READ_AT_START = ("uvtools_enabled", "sdcp_enabled")


_change_lock = threading.Lock()


class NotASetting(ValueError):
    pass


def _checked(given: Mapping[str, Any]) -> Dict[str, Any]:
    """*given* as it is kept; NotASetting if any of it cannot be."""
    kept: Dict[str, Any] = {}
    for name, value in given.items():
        if name in _SWITCHES:
            if not isinstance(value, bool):
                raise NotASetting(f"{name} is switched with true or false")
            kept[name] = value
        elif name == "printer_display_name":
            if not isinstance(value, str):
                raise NotASetting("the name of the printer is text")
            name_given = value.strip()
            if len(name_given) > _LONGEST_NAME:
                raise NotASetting(
                    f"the name of the printer has at most {_LONGEST_NAME} characters"
                )
            if has_control_character(name_given):
                raise NotASetting("the name of the printer is on one line")
            # Empty: back to what the configuration file says.
            kept[name] = name_given or None
        else:
            raise NotASetting(f"{name} is not a setting that is changed here")
    return kept


def _kept() -> Dict[str, Any]:
    """What was changed from the page, as far as it can be read."""
    off = {"uvtools_enabled": False, "sdcp_enabled": False}
    raw = None if state.is_makeshift() else state.read(_KEPT_AS)
    if raw is None:
        if state.is_makeshift() or state.exists(_KEPT_AS):
            # Something was set that cannot be read. The slicers'
            # interfaces may have been switched off there: on by default,
            # they would come back on by a folder changing hands.
            logger.warning(
                "The settings changed from the page cannot be read: the "
                "slicers' interfaces stay off"
            )
            return dict(off)
        return {}
    try:
        held = json.loads(raw)
        if not isinstance(held, dict):
            raise ValueError("not an object")
    except ValueError as error:
        # As above: damaged, it may have held the slicers switched off.
        logger.warning(
            "The settings changed from the page cannot be read (%s): the "
            "slicers' interfaces stay off",
            error,
        )
        return dict(off)
    good: Dict[str, Any] = {}
    for name, value in held.items():
        try:
            if value is None and name == "printer_display_name":
                continue
            good.update(_checked({name: value}))
        except NotASetting as error:
            logger.warning("A setting changed from the page is passed over: %s", error)
    return good


def apply() -> None:
    """Have the configuration answer with what was changed from the page."""
    # Put in place in one go: emptied first, a request served meanwhile
    # would find a setting gone.
    config.overrides = {
        name: value for name, value in _kept().items() if value is not None
    }


def current() -> Dict[str, Any]:
    """The settings as they stand: the page's changes over the file."""
    apply()
    return {
        "printer_display_name": config.get_printer_display_name(),
        "uvtools_enabled": config.get_uvtools_enabled(),
        "sdcp_enabled": config.get_sdcp_enabled(),
        "assume_printer_off": config.get_assume_printer_off(),
    }


def change(given: Any) -> Dict[str, Any]:
    """Keep the changes in *given*, all of them or none."""
    if not isinstance(given, dict) or not given:
        raise NotASetting("send the settings to change in a JSON object")
    changes = _checked(given)
    # One at a time: of two changes made at once, neither is lost.
    with _change_lock:
        held = {**_kept(), **changes}
        held = {name: value for name, value in held.items() if value is not None}
        state.write(_KEPT_AS, json.dumps(held, sort_keys=True).encode("utf-8"))
        return current()


# What Mariner was started with, of the settings read at start.
_running: Dict[str, Any] = {}


def note_what_runs() -> None:
    now = current()
    _running.clear()
    _running.update({name: now[name] for name in _READ_AT_START})


def _restart_needed() -> bool:
    now = current()
    return any(now[name] != _running.get(name, now[name]) for name in _READ_AT_START)


def _can_restart() -> bool:
    """Whether something starts Mariner again when it stops.

    A service does (systemd names each run). Run by hand, or in a
    container whose policy is not known from inside, Mariner would stop
    and stay stopped.
    """
    return bool(os.environ.get("INVOCATION_ID"))


def _stop_soon() -> None:
    """Stop once the answer has left; the service starts Mariner again."""

    def stop() -> None:
        logger.warning("Stopping, to be started again: asked from the page")
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Timer(0.5, stop).start()


settings_api = Blueprint("settings", __name__, url_prefix="/api")


def _shown() -> Response:
    return jsonify(
        {
            "settings": current(),
            "restart_needed": _restart_needed(),
            "can_restart": _can_restart(),
        }
    )


@settings_api.route("/settings", methods=["GET"])
def show() -> Response:
    return _shown()


@settings_api.route("/settings", methods=["POST"])
def save() -> Response:
    try:
        change(request.get_json(silent=True))
    except NotASetting as error:
        body = {
            "code": "setting_not_valid",
            "title": "Setting Not Taken",
            "description": f"Nothing was changed: {error}.",
        }
        return make_response(jsonify(body), 400)
    except OSError as error:
        logger.error("Could not write to the state directory: %s", error)
        return make_response(jsonify(state.NOT_WRITTEN), 500)
    logger.warning("Settings were changed from %s", request.remote_addr)
    return _shown()


@settings_api.route("/restart", methods=["POST"])
def restart() -> Response:
    if not _can_restart():
        body = {
            "code": "restart_not_available",
            "title": "Restart By Hand",
            "description": "Mariner is not run as a service here, so nothing "
            "would start it again: restart it the way it was started.",
        }
        return make_response(jsonify(body), 409)
    _stop_soon()
    return jsonify({"success": True})
