"""Tests never read or write the home of whoever runs them.

Mariner run by hand keeps its password and the key of its sessions in
a folder of the account's home: the tests would read them, and those of
the commands would clear them.
"""

import atexit
import shutil
import tempfile

from mariner import config

_apart = tempfile.mkdtemp(prefix="mariner-tests-")
atexit.register(shutil.rmtree, _apart, ignore_errors=True)
# In place: the list is shared with ``mariner.server.state``.
config.STATE_FALLBACKS[:] = [_apart + "/state"]
