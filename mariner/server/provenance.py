"""Where a request comes from: the local network, or the Internet.

Once a port of the router is forwarded to it, Mariner is spoken to by
anyone. Some of what it does is then kept for the local network:

- slicers (UVtools, SDCP) give no password and never will: what serves
  them is answered on the local network alone;
- stopping or restarting the computer, unless the owner allows it.

What is local: this computer itself, the private ranges of a home or an
office, those a VPN gives, and over IPv6 the network this computer has
an address in. The configuration can add networks, and take addresses
out: a router that passes connections on under its own address, or a
tunnel that ends on this very computer, makes everything look local.
An address that cannot be read is not local: in doubt, the stricter rule.
"""

import ipaddress
import socket
import time
from typing import Dict, List, Optional, Tuple, Union

from mariner import config

_Network = Union[ipaddress.IPv4Network, ipaddress.IPv6Network]
_Address = Union[ipaddress.IPv4Address, ipaddress.IPv6Address]

_LOCAL: Tuple[_Network, ...] = tuple(
    ipaddress.ip_network(network)
    for network in (
        "127.0.0.0/8",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "169.254.0.0/16",
        # Shared address space: what a VPN of the Tailscale kind gives.
        "100.64.0.0/10",
        "::1/128",
        "fe80::/10",
        "fc00::/7",
    )
)

# What serves slicers: see mariner.server.providers.
_FOR_SLICERS = "/uvtools"
_HOST_COMMANDS = "/api/host/"

# A home's prefix changes now and then: asked again after this long.
_OWN_KEPT_SECS = 60.0
_own: Tuple[float, List[str]] = (0.0, [])


def _own_ipv6() -> List[str]:
    """The address of this computer over IPv6, when it has one."""
    global _own
    asked, found = _own
    now = time.monotonic()
    if asked and now - asked < _OWN_KEPT_SECS:
        return found
    found = []
    try:
        # Nothing is sent: asking where it would go from tells the
        # address the network knows this computer by.
        with socket.socket(socket.AF_INET6, socket.SOCK_DGRAM) as probe:
            probe.connect(("2001:db8::1", 9))
            found.append(str(probe.getsockname()[0]))
    except OSError:
        pass
    _own = (now, found)
    return found


def _read(address: object) -> Optional[_Address]:
    if not isinstance(address, str):
        return None
    try:
        # "fe80::1%eth0": the part after "%" names the interface.
        read = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return None
    if isinstance(read, ipaddress.IPv6Address) and read.ipv4_mapped is not None:
        return read.ipv4_mapped
    return read


def shown(address: object) -> str:
    """*address* as it can be shown: itself if it is one, and nothing a
    peer or a header could have put in its place."""
    read = _read(address)
    return "unknown" if read is None else str(read)


def _networks(given: List[str]) -> List[_Network]:
    found = []
    for one in given:
        try:
            found.append(ipaddress.ip_network(one, strict=False))
        except ValueError:
            continue
    return found


def _within(address: _Address, networks: List[_Network]) -> bool:
    return any(
        address.version == network.version and address in network
        for network in networks
    )


def is_local(address: object) -> bool:
    """Whether *address*, where a request came from, is on the local network."""
    read = _read(address)
    if read is None:
        return False
    if _within(read, _networks(config.get_not_local())):
        return False
    if _within(read, list(_LOCAL) + _networks(config.get_local_networks())):
        return True
    if read.version == 6:
        own = _networks([f"{mine.split('%', 1)[0]}/64" for mine in _own_ipv6()])
        return _within(read, own)
    return False


def _body(what: str) -> Dict[str, str]:
    return {
        "code": "local_network_only",
        "title": "Local Network Only",
        "description": f"{what} is answered on the local network alone, "
        "not from the Internet.",
    }


def refusal(path: str, address: object) -> Optional[Dict[str, str]]:
    """What is answered to a request for *path* from *address*, if refused."""
    for_slicers = path == _FOR_SLICERS or path.startswith(_FOR_SLICERS + "/")
    host_command = path.startswith(_HOST_COMMANDS)
    if not (for_slicers or host_command) or is_local(address):
        return None
    if for_slicers:
        return _body("What serves slicers")
    if config.get_host_commands_from_internet():
        return None
    return _body("Stopping or restarting the computer")


def slicer_refusal(address: object) -> Optional[Dict[str, str]]:
    """The same for a service that serves slicers and nothing else."""
    return refusal(_FOR_SLICERS, address)
