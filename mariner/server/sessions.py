"""Sessions kept in a signed cookie, read whatever else sends one.

Cookies go by the name of the host, not by its port: another program on
the same computer (the page of a camera, of a network filter) can set a
cookie under the name Mariner uses. The browser then sends both, and
which comes first is not Mariner's to choose. Taking the first, as is
usual, would let that other program sign everyone out for as long as its
cookie lasts, and keep the page from acting at all.

So every cookie of that name is tried, and the first that Mariner signed
is the session. One it did not sign is never taken: making one takes the
key.
"""

from typing import Any, Dict, Iterator, Optional

from flask import Flask, Request
from flask.sessions import SecureCookieSession, SecureCookieSessionInterface
from itsdangerous import BadSignature

COOKIE_NAME = "mariner_session"
# What is tried of a request's cookies: nobody has this many by chance.
_MOST_TRIED = 8


def _values(cookie_header: str, name: str) -> Iterator[str]:
    found = 0
    for pair in cookie_header.split(";"):
        key, separator, value = pair.strip().partition("=")
        if not separator or key.strip() != name:
            continue
        found += 1
        if found > _MOST_TRIED:
            return
        yield value.strip().strip('"')


def read(application: Flask, cookie_header: str) -> Dict[str, Any]:
    """What the session of a request holds, from its ``Cookie`` header.

    Empty when it carries none that Mariner signed. Usable before there
    is a request to speak of: by the web server, as headers come in.
    """
    interface = application.session_interface
    if not isinstance(interface, SecureCookieSessionInterface):
        return {}
    serializer = interface.get_signing_serializer(application)
    if serializer is None:
        return {}
    lifetime = int(application.permanent_session_lifetime.total_seconds())
    for value in _values(cookie_header, application.config["SESSION_COOKIE_NAME"]):
        try:
            held = serializer.loads(value, max_age=lifetime)
        except BadSignature:
            continue
        if isinstance(held, dict):
            return held
    return {}


class Sessions(SecureCookieSessionInterface):
    def open_session(
        self, app: Flask, request: Request
    ) -> Optional[SecureCookieSession]:
        if self.get_signing_serializer(app) is None:
            return None
        return self.session_class(read(app, request.headers.get("Cookie", "")))
