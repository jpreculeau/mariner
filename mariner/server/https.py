"""What is answered in the clear once the page is served over HTTPS.

Mariner goes on listening in the clear: slicers speak nothing else, and
an address typed without ``https://`` must lead somewhere. But nothing
of the page's own is answered there: the page is sent on to HTTPS, and
its addresses (the password, the session, commands to the printer) are
refused, so that none of it goes where whoever shares the network can
read it.
"""

from typing import Dict, Optional

from mariner.server import origin

# Where slicers send and fetch: see mariner.server.providers.
_IN_THE_CLEAR = ("/uvtools/",)
_USUAL_PORT = 443


def address(host: str, port: int) -> Optional[str]:
    """Where Mariner's page is over HTTPS, for who reached it at *host*.

    None when *host*, the ``Host`` header of a request, is not one.
    """
    parts = origin.name_and_port(host)
    if parts is None or not parts[0]:
        return None
    name = parts[0]
    if ":" in name:
        name = f"[{name}]"
    return f"https://{name}" + ("" if port == _USUAL_PORT else f":{port}")


def is_for_the_page(path: str) -> bool:
    """Whether *path* is one of the page's own, not a slicer's."""
    return not path.startswith(_IN_THE_CLEAR)


def refusal(host: str, port: int) -> Dict[str, str]:
    """What is answered to a request for the page's own in the clear."""
    where = address(host, port)
    body = {
        "code": "https_required",
        "title": "HTTPS Required",
        "description": "Mariner's page is served over HTTPS, and answers "
        "nothing of its own in the clear"
        + (f": use {where} instead." if where else "."),
    }
    if where:
        # For a page left open in the clear, to go there by itself.
        body["address"] = where
    return body
