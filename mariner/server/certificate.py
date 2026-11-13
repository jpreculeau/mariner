"""The certificate Mariner's page is served with.

The owner's own when the configuration names one. Otherwise one that
Mariner makes for itself and keeps: no authority vouches for it, so a
browser warns the first time, but what goes between the browser and
Mariner (the password to begin with) is no longer readable by whoever
shares the network.

Made with the ``openssl`` command of the system: nothing of Python's
own makes a certificate, and a library for it is a lot to install on a
small board for something done once.
"""

import ipaddress
import logging
import os
import re
import shutil
import socket
import ssl
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

from mariner import config
from mariner.server import tls

logger: logging.Logger = logging.getLogger(__name__)

CERTIFICATE_AS = "https-certificate.pem"
KEY_AS = "https-key.pem"
# Browsers refuse one that lasts longer than this, even told to trust it.
_LASTS_DAYS = 397
# Made again when it has less than this left.
_RENEWED_BEFORE_DAYS = 30
_A_NAME = re.compile(r"[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?")


def _names() -> List[str]:
    """What the computer is reached as, in the form a certificate lists."""
    found = ["DNS:localhost", "IP:127.0.0.1", "IP:::1"]
    name = socket.gethostname().split(".")[0]
    if _A_NAME.fullmatch(name):
        found += [f"DNS:{name}", f"DNS:{name}.local"]
    for address in _addresses():
        entry = f"IP:{address}"
        if entry not in found:
            found.append(entry)
    return found


def _addresses() -> List[str]:
    """The addresses of this computer on its networks, as far as is told."""
    found: List[str] = []
    for family, towards in (
        (socket.AF_INET, "192.0.2.1"),
        (socket.AF_INET6, "2001:db8::1"),
    ):
        # Nothing is sent: asking where it would go from tells the
        # address the network knows this computer by.
        try:
            with socket.socket(family, socket.SOCK_DGRAM) as probe:
                probe.connect((towards, 9))
                address = ipaddress.ip_address(probe.getsockname()[0])
        except (OSError, ValueError):
            continue
        if not address.is_loopback and not address.is_unspecified:
            found.append(str(address))
    return found


def _usable(certificate: Path, key: Path) -> bool:
    """Whether the pair is there, goes together and lasts a while yet."""
    if not (certificate.is_file() and key.is_file()):
        return False
    try:
        tls.context(str(certificate), str(key))
    except (OSError, ValueError):
        # ssl.SSLError is an OSError.
        return False
    lasting = subprocess.run(
        [
            "openssl",
            "x509",
            "-noout",
            "-checkend",
            str(_RENEWED_BEFORE_DAYS * 86400),
            "-in",
            str(certificate),
        ],
        capture_output=True,
    )
    return lasting.returncode == 0


def self_signed(folder: Path) -> Optional[Tuple[str, str]]:
    """The certificate and key Mariner made for itself in *folder*.

    Made if there is none that can be used; kept otherwise, so that a
    browser told to trust it is not asked again. None when it cannot be
    made.
    """
    if shutil.which("openssl") is None:
        logger.warning(
            "The openssl command is not installed: no certificate can be "
            "made, and Mariner's page is served without HTTPS"
        )
        return None
    certificate, key = folder / CERTIFICATE_AS, folder / KEY_AS
    if _usable(certificate, key):
        return str(certificate), str(key)
    if certificate.exists() or key.exists():
        logger.warning(
            "The certificate in %s cannot be used any longer (it runs out, "
            "or its key is not with it): making a new one. Browsers will "
            "warn about it once more.",
            folder,
        )
    # Made beside, and put in place whole.
    new_certificate, new_key = folder / (CERTIFICATE_AS + ".new"), folder / (
        KEY_AS + ".new"
    )
    previous = os.umask(0o077)
    try:
        made = subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "ec",
                "-pkeyopt",
                "ec_paramgen_curve:prime256v1",
                "-nodes",
                "-keyout",
                str(new_key),
                "-out",
                str(new_certificate),
                "-days",
                str(_LASTS_DAYS),
                "-subj",
                "/CN=Mariner",
                "-addext",
                "subjectAltName=" + ",".join(_names()),
                "-addext",
                "basicConstraints=critical,CA:FALSE",
                "-addext",
                "extendedKeyUsage=serverAuth",
            ],
            capture_output=True,
            text=True,
        )
    except OSError as error:
        logger.warning("No certificate could be made: %s", error)
        return None
    finally:
        os.umask(previous)
    if made.returncode != 0:
        logger.warning("No certificate could be made: %s", made.stderr.strip()[-500:])
        for left in (new_certificate, new_key):
            left.unlink(missing_ok=True)
        return None
    try:
        os.chmod(new_key, 0o600)
        os.replace(new_key, key)
        os.replace(new_certificate, certificate)
    except OSError as error:
        logger.warning("The certificate could not be kept: %s", error)
        return None
    logger.info("Made a certificate for Mariner's page in %s", folder)
    return str(certificate), str(key)


def in_use(folder: Optional[Path] = None) -> Optional[Tuple[str, str]]:
    """The certificate and key to serve the page with, if it is to be.

    None when HTTPS is switched off, or when there is no way to have a
    certificate. One Mariner makes is kept in *folder*: by default with
    what else it keeps.
    """
    if not config.get_https_enabled():
        return None
    own_certificate, own_key = config.get_https_certificate(), config.get_https_key()
    if own_certificate and own_key:
        try:
            tls.context(own_certificate, own_key)
            return own_certificate, own_key
        except (OSError, ValueError) as error:
            under_a_password = isinstance(error, ssl.SSLError) and not isinstance(
                error, FileNotFoundError
            )
            logger.error(
                "The certificate named in the configuration (%s, with its "
                "key %s) cannot be used: %s.%s Mariner serves its page with a "
                "certificate of its own instead",
                own_certificate,
                own_key,
                error,
                (
                    " If the key is kept under a password, it must not be; if not, "
                    "the two files do not go together or are not what they are "
                    "named for."
                    if under_a_password
                    else ""
                ),
            )
    if folder is None:
        from mariner.server import state

        folder = state.directory()
    return self_signed(folder)
