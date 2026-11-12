"""Who a request comes from, as far as its headers tell.

Mariner does not ask who is asking: anything on the local network can use
it. That makes two kinds of request from *outside* the network dangerous,
both sent by a browser on the network at the bidding of a page from
anywhere on the web.

A request from another site
    The page has the browser fetch an address of Mariner's: an image
    address or a link is enough for the routes that act on a GET, a form
    or a WebSocket for the others. Browsers say what site a request comes
    from, but not always. ``Sec-Fetch-Site`` is only sent to addresses
    reached over HTTPS or on the machine itself, which Mariner's is not;
    ``Origin`` is sent with a form posted, a WebSocket and a request a
    script reads the answer of, and not with a link followed or a picture
    loaded. Both are checked
    here when they are there. Programs that are not browsers, slicers
    among them, send neither and are let through.

A browser on the routes made for slicers
    That leaves the GET a browser sends without a word of the site. On
    the routes made for slicers, which act on a GET, a browser is turned
    away as such: it gives itself a name no page can change, and Mariner's
    own page never asks for those routes. So is what says other things
    that only browsers and players of sound and video say. That is a list
    of the programs known to follow a page's links, not a proof there are
    no others. The web API acts on POST only,
    for which ``Origin`` is there.

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
from typing import List, Mapping, Optional, Tuple
from urllib.parse import urlsplit

from mariner import config
from mariner.server import refusals


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

_NOT_A_SLICER = Refusal(
    "browser_not_served",
    "Not For Browsers",
    "These addresses are for slicers, and are not served to a web browser "
    "or to a program that says what browsers say. A script must give "
    "itself a name of its own (User-Agent) and leave out the headers "
    "Accept-Language, Range, Icy-MetaData, Purpose and Sec-Purpose.",
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
_LABEL = r"[a-z0-9_]([a-z0-9_-]*[a-z0-9_])?"
_NAME = re.compile(rf"{_LABEL}(\.{_LABEL})*")
_DEFAULT_PORTS = {"http": "80", "https": "443"}
_SCHEME = re.compile(r"[a-z][a-z0-9+.-]*")


def name_and_port(host: str) -> Optional[Tuple[str, str]]:
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


def _is_a_name(name: str) -> bool:
    """Whether *name* is written as a machine is named: an address, or words."""
    return _is_address(name) or _NAME.fullmatch(name) is not None


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


def _site(address: str) -> Optional[Tuple[str, str, str]]:
    """The scheme, name and port a page address stands for, if it is one."""
    try:
        parts = urlsplit(address.strip().lower())
    except ValueError:
        # Brackets that hold no address, say.
        return None
    if parts.scheme not in _DEFAULT_PORTS or not parts.netloc:
        return None
    name = name_and_port(parts.netloc)
    if name is None or not _is_a_name(name[0].rstrip(".")):
        return None
    return parts.scheme, name[0].rstrip("."), name[1] or _DEFAULT_PORTS[parts.scheme]


def _is_own_page(address: str, host: str) -> bool:
    """Whether the page at *address* is one of Mariner's.

    Served under the name and port the request asks for; or at an address
    listed whole in ``allowed_origins``, for a relay in front of Mariner
    that asks it under another name or port than the browser used. A name
    in ``allowed_hosts`` may be asked for and is not thereby a friend:
    under the same name, another port is another program's page. A request
    that names no port is taken to be on the usual one for the page's
    scheme, as it is behind a relay that passes the name on as it came.
    """
    page = _site(address)
    if page is None:
        return False
    if any(page == _site(listed) for listed in config.get_http_allowed_origins()):
        return True
    asked = name_and_port(host)
    if asked is None:
        return False
    return page[1] == asked[0].rstrip(".") and page[2] == (
        asked[1] or _DEFAULT_PORTS[page[0]]
    )


def _is_a_program_s(origin: str) -> bool:
    """Whether an ``Origin`` is of a kind no page on the web can give.

    A slicer built as a desktop application can give one of its own, such
    as ``app://name``. A page on the web gives ``http``, ``https`` or,
    when it hides where it is from, ``null``. A page that belongs to an
    extension installed in the browser gives the extension's own, and is
    served: whoever installed it gave it that reach.
    """
    scheme, separator, _ = origin.strip().lower().partition("://")
    return (
        bool(separator)
        and _SCHEME.fullmatch(scheme) is not None
        and scheme not in _DEFAULT_PORTS
    )


def is_browser(headers: Mapping[str, str]) -> bool:
    """Whether a request says it comes from a web browser.

    By the name every browser has given itself since the first ones. A
    page cannot change it on a link, a picture or a form.
    """
    agent = headers.get("User-Agent", "").lstrip().lower()
    return agent.startswith(("mozilla/", "opera/"))


def browser_refusal(headers: Mapping[str, str]) -> Optional[Refusal]:
    """Why a request to a route made for slicers is not served.

    To a browser, or to another program that loads the addresses a page
    gives it. This catches the ones known, not every one there could be:
    what keeps the rest out is that Mariner is asked who is asking, once
    it does that.
    """
    if is_browser(headers):
        return _NOT_A_SLICER
    said = {name.lower() for name in headers.keys()}
    return _NOT_A_SLICER if said & refusals.NOT_SAID_BY_SLICERS else None


def host_refusal(headers: Mapping[str, str]) -> Optional[Refusal]:
    """Why the name a request asks for is not one Mariner answers to."""
    host = headers.get("Host")
    if host is None:
        # Only a program written for the purpose leaves it out.
        return None
    parts = name_and_port(host)
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
    host = headers.get("Host", "")
    origin = headers.get("Origin")
    if origin is not None:
        if _is_own_page(origin, host) or _is_a_program_s(origin):
            return None
        return _OTHER_SITE
    # Neither: a program, or a browser following a link or loading a
    # picture over plain HTTP. The second often says which page asked.
    referer = headers.get("Referer")
    if referer is not None and not _is_own_page(referer, host):
        return _OTHER_SITE
    return None


# What acts on the printer or the files, or tells about them.
GUARDED_PREFIXES = ("/api/", "/uvtools/")
# What is made for slicers, and acts on a GET.
SLICER_PREFIXES = ("/uvtools/",)

# Sent with Mariner's answers that are data: not for other sites to load,
# and what their type says whatever their contents look like.
ANSWER_HEADERS = {
    "Cross-Origin-Resource-Policy": "same-origin",
    "X-Content-Type-Options": "nosniff",
}


def request_refusal(path: str, headers: Mapping[str, str]) -> Optional[Refusal]:
    """Why the web server does not serve a request for *path*; None if it does.

    A foreign name is refused wherever the application answers (the
    page's own scripts and styles, which tell nothing, are served before
    it); a request from another site only where it would act or tell, so
    that a link to Mariner on another page still opens it; a browser on
    the routes made for slicers.
    """
    refusal = host_refusal(headers)
    if refusal is None and path.startswith(GUARDED_PREFIXES):
        refusal = site_refusal(headers)
    if refusal is None and path.startswith(SLICER_PREFIXES):
        refusal = browser_refusal(headers)
    return refusal


def unusable_entries() -> List[str]:
    """What the configuration lists that can match nothing, in words.

    For the log at start: such an entry looks like one that was applied.
    Judged by what does the matching, so that the two cannot disagree.
    """
    found = []
    for host in config.get_http_allowed_hosts():
        name = host.strip().lower().rstrip(".")
        if name.startswith("[") and name.endswith("]"):
            name = name[1:-1]
        if name == "*" or _is_a_name(name):
            continue
        found.append(
            f"[http] allowed_hosts entry {host!r} can match nothing: a name "
            'is given alone, without scheme or port, "*" stands only by '
            "itself, and a name with accents is written as browsers send it "
            '("xn--...")'
        )
    for address in config.get_http_allowed_origins():
        if _site(address) is None:
            found.append(
                f"[http] allowed_origins entry {address!r} can match nothing: "
                'one address is given whole, as "https://printer.example.org"'
            )
    return found


def body_refusal(path: str, headers: Mapping[str, str]) -> Optional[Refusal]:
    """Why the web server does not take in the body of a request for *path*.

    As ``request_refusal``, but another site is turned away wherever it
    sends: a body is stored before anyone looks at where it was going.
    """
    return request_refusal(path, headers) or site_refusal(headers)


def refusal_for(headers: Mapping[str, str]) -> Optional[Refusal]:
    """Why a request that acts or tells is not served; None if it is."""
    return host_refusal(headers) or site_refusal(headers)
