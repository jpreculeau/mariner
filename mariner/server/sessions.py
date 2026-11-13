"""Sessions kept in a signed cookie, read whatever else sends one.

Cookies go by the name of the host, not by its port: another program on
the same computer (the page of a camera, of a network filter) can set a
cookie under the name Mariner uses. The browser then sends both, and
which comes first is not Mariner's to choose. Taking the first, as is
usual, would let that other program sign everyone out for as long as its
cookie lasts, and keep the page from acting at all.

So every cookie of that name is tried. One Mariner did not sign is never
taken: making one takes the key. Of those it signed, the one that goes
with the key the page sent comes first, then one that is signed in:
anyone is given a signed cookie by asking for a token, and neither that
one nor the session of another of the reader's browsers, set here by
another program, must come before the reader's own.
"""

from typing import Any, Callable, Dict, Iterator, Mapping, Optional

from flask import Flask, Request
from flask.sessions import SecureCookieSession, SecureCookieSessionInterface
from itsdangerous import BadSignature

COOKIE_NAME = "mariner_session"
# Over HTTPS. Under this prefix a browser takes the cookie only from
# HTTPS, for this host alone and for all of its paths: another program
# of the computer, served in the clear or under another path, can no
# longer set one of this name.
SECURED_COOKIE_NAME = "__Host-" + COOKIE_NAME
# What is tried of a request's cookies: more than a browser sends under
# every path and form of the name there is. Each costs a signature.
_MOST_TRIED = 32
# Longer than this is not one of Mariner's.
_LONGEST = 4096

# How far what a session holds, sent with a key, is let in: the higher
# the better. Set by mariner.server.auth.
rank: Optional[Callable[[Mapping[str, Any], str], int]] = None
# Sent with the session: see mariner.server.auth.
KEY_HEADER = "X-Mariner-Key"


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


def read(application: Flask, cookie_header: str, key: str = "") -> Dict[str, Any]:
    """What the session of a request holds, from its ``Cookie`` header and
    the key sent with it.

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
    best: Optional[Dict[str, Any]] = None
    best_rank = -1
    for value in _values(cookie_header, application.config["SESSION_COOKIE_NAME"]):
        try:
            held = serializer.loads(value, max_age=lifetime)
        except BadSignature:
            continue
        if not isinstance(held, dict):
            continue
        ranked = rank(held, key) if rank is not None else 0
        # The first of the best: the one that goes with the key the page
        # sent, before one that is merely signed in, before the others.
        if ranked > best_rank:
            best, best_rank = held, ranked
    return best or {}


class Sessions(SecureCookieSessionInterface):
    def open_session(
        self, app: Flask, request: Request
    ) -> Optional[SecureCookieSession]:
        if self.get_signing_serializer(app) is None:
            return None
        return self.session_class(
            read(
                app,
                request.headers.get("Cookie", ""),
                request.headers.get(KEY_HEADER, ""),
            )
        )
