"""Who a request comes from, as far as its headers tell.

Mariner does not ask who is asking: anything on the local network can use
it. That makes two kinds of request from *outside* the network dangerous,
both sent by a browser on the network at the bidding of a page from
anywhere on the web.

A request from another site
    The page has the browser fetch an address of Mariner's: an image
    address is enough for the routes that act on a GET, a form or a
    WebSocket for the others. Browsers say what site a request comes from
    (``Sec-Fetch-Site``, and ``Origin`` before that existed), which is
    checked here. Programs that are not browsers, slicers among them, send
    neither and are let through.

A request under a foreign name
    The site has its own name answer with the address of the printer, so
    that the browser takes the site's pages and Mariner for one site and
    lets the first read and drive the second. The browser then asks for
    that name, which is what gives it away: a printer is reached by its
    address or by a name of the local network.
"""

import ipaddress
import re
import socket
from dataclasses import dataclass
from typing import Mapping, Optional, Tuple
from urllib.parse import urlsplit

from mariner import config


@dataclass(frozen=True)
class Refusal:
    """Why a request is not served, in words a client can show."""

    code: str
    title: str
    description: str

    def body(self) -> dict:
        return {
            "code": self.code,
            "title": self.title,
            "description": self.description,
        }


_OTHER_SITE = Refusal(
    "cross_site_request",
    "Request From Another Site",
    "This request comes from a page that is not Mariner's and was not served.",
)

_FOREIGN_NAME = Refusal(
    "host_not_allowed",
    "Name Not Allowed",
    "Mariner answers to its address and to names of the local network. To "
    "reach it under another name, add that name to allowed_hosts under "
    "[http] in its configuration.",
)

# Names that only resolve within a local network.
_LOCAL_SUFFIXES = (".local", ".lan", ".home", ".home.arpa", ".internal", ".localdomain")
_NAME = re.compile(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*")
_DEFAULT_PORTS = {"http": "80", "https": "443"}


def _name_and_port(host: str) -> Optional[Tuple[str, str]]:
    """The two parts of a ``Host`` header, lower case; None if it is not one."""
    host = host.strip().lower()
    if host.startswith("["):
        address, bracket, rest = host[1:].partition("]")
        if not bracket or (rest and not rest.startswith(":")):
            return None
        name, port = address, rest[1:]
    else:
        name, _, port = host.partition(":")
    if port and not port.isdigit():
        return None
    return name, port


def _is_address(name: str) -> bool:
    try:
        ipaddress.ip_address(name)
    except ValueError:
        return False
    return True


def _is_allowed_name(name: str) -> bool:
    allowed = [entry.strip().lower().rstrip(".") for entry in _allowed_hosts()]
    if "*" in allowed:
        return True
    if _is_address(name):
        return True
    name = name.rstrip(".")
    if not _NAME.fullmatch(name):
        return False
    return (
        "." not in name
        or name.endswith(_LOCAL_SUFFIXES)
        or name == socket.gethostname().lower().rstrip(".")
        or name in allowed
    )


def _allowed_hosts() -> list:
    return config.get_http_allowed_hosts()


def _same_origin(origin: str, host: str) -> bool:
    """Whether the page at *origin* is served under the name *host*."""
    parts = urlsplit(origin.strip().lower())
    if parts.scheme not in _DEFAULT_PORTS or not parts.netloc:
        return False
    page, asked = _name_and_port(parts.netloc), _name_and_port(host)
    if page is None or asked is None:
        return False
    default = _DEFAULT_PORTS[parts.scheme]
    return page[0] == asked[0] and (page[1] or default) == (asked[1] or default)


def host_refusal(headers: Mapping[str, str]) -> Optional[Refusal]:
    """Why the name a request asks for is not one Mariner answers to."""
    host = headers.get("Host")
    if host is None:
        # Only a program written for the purpose leaves it out.
        return None
    parts = _name_and_port(host)
    if parts is None or not _is_allowed_name(parts[0]):
        return _FOREIGN_NAME
    return None


def site_refusal(headers: Mapping[str, str]) -> Optional[Refusal]:
    """Why a request is taken to come from a page of another site."""
    site = headers.get("Sec-Fetch-Site")
    if site is not None:
        # "none" is an address typed, or a bookmark.
        if site.strip().lower() in ("same-origin", "none"):
            return None
        return _OTHER_SITE
    origin = headers.get("Origin")
    if origin is not None and not _same_origin(origin, headers.get("Host", "")):
        return _OTHER_SITE
    return None


def refusal_for(headers: Mapping[str, str]) -> Optional[Refusal]:
    """Why a request that acts or tells is not served; None if it is."""
    return host_refusal(headers) or site_refusal(headers)
