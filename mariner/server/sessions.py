"""Sessions kept in a signed cookie, read whatever else sends one.

Cookies go by the name of the host, not by its port: another program on
the same computer (the page of a camera, of a network filter) can set a
cookie under the name Mariner uses. The browser then sends both, and
which comes first is not Mariner's to choose. Taking the first, as is
usual, would let that other program sign everyone out for as long as its
cookie lasts, and keep the page from acting at all.

So every cookie of that name is tried. One Mariner did not sign is never
taken: making one takes the key. Of those it signed, one that is signed
in comes first: anyone is given a signed cookie by asking for a token,
and that one, set by another program, must not come before the reader's
own.
"""

from typing import Any, Callable, Dict, Iterator, Mapping, Optional

from flask import Flask, Request
from flask.sessions import SecureCookieSession, SecureCookieSessionInterface
from itsdangerous import BadSignature

COOKIE_NAME = "mariner_session"
# What is tried of a request's cookies: more than a browser sends under
# every path and form of the name there is. Each costs a signature.
_MOST_TRIED = 32
# Longer than this is not one of Mariner's.
_LONGEST = 4096

# Whether what a session holds is signed in: set by mariner.server.auth.
preferred: Optional[Callable[[Mapping[str, Any]], bool]] = None


def _values(cookie_header: str, name: str) -> Iterator[str]:
    found = 0
    for pair in cookie_header.split(";"):
        key, separator, value = pair.strip().partition("=")
        if not separator or key.strip() != name:
            continue
        found += 1
        if found > _MOST_TRIED:
            return
        value = value.strip().strip('"')
        if len(value) <= _LONGEST:
            yield value


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
    first: Optional[Dict[str, Any]] = None
    for value in _values(cookie_header, application.config["SESSION_COOKIE_NAME"]):
        try:
            held = serializer.loads(value, max_age=lifetime)
        except BadSignature:
            continue
        if not isinstance(held, dict):
            continue
        if preferred is None or preferred(held):
            return held
        if first is None:
            first = held
    return first or {}


class Sessions(SecureCookieSessionInterface):
    def open_session(
        self, app: Flask, request: Request
    ) -> Optional[SecureCookieSession]:
        if self.get_signing_serializer(app) is None:
            return None
        return self.session_class(read(app, request.headers.get("Cookie", "")))
