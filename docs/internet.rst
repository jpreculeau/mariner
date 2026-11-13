Local network and Internet
==========================

Mariner is made for the network of a home or a workshop. Should it be
reached from the Internet all the same (a port of the router forwarded to
it), part of what it does stays for the local network alone.

.. warning::

   This page says what is in place today. It is not yet enough to forward
   a port to Mariner: what a page open to the Internet needs besides (a
   second proof at sign-in, limits on what strangers can make it do) is
   not there yet. Until it is, reach Mariner from outside through a VPN.

What is kept for the local network
----------------------------------

- **What serves slicers**: the UVtools addresses (``/uvtools/…``), SDCP
  (its port, and the answer to a slicer looking for printers). Slicers give
  no password; from the Internet they would be open to anyone.
- **Stopping or restarting the computer** (``/api/host/shutdown`` and
  ``/api/host/reboot``), even signed in. ``host_commands = true`` under
  ``[internet]`` allows it.

From an address that is not local these are answered ``403`` with the code
``local_network_only``, a file before any of it is taken in, and the log
says who was refused. The page itself, and everything else it does once
signed in, is answered as on the local network.

Signing in from the Internet
----------------------------

- **The password is not chosen from there.** On a Mariner that has none
  yet, a visitor from the Internet is refused (``local_network_only``):
  choose it from the local network, or with ``sudo mariner set-password``.
- **A one-time code is asked besides the password.** Six digits that an
  application of the phone gives and that change every half minute (any
  application that speaks TOTP: Aegis, FreeOTP, Google Authenticator…). A
  password that was guessed, or read somewhere, opens nothing without the
  phone. Until a code is set up, nobody signs in from the Internet
  (``403`` ``code_not_set``). It is set up, and done away with, from the
  local network alone, by who is signed in, in the page's settings
  ("One-time code"): the page gives a key to type into the application,
  or a link that opens it on the phone, then asks for a first code to
  check that the phone took it in. A code serves once. Sent to
  ``/api/auth/login`` as ``code``, beside ``password``; which of the two
  was wrong is not told.
- **Signed in at home is not signed in outside.** On the local network the
  password is enough; a session opened that way is asked to sign in again,
  with the code, once it comes from the Internet (a phone that leaves the
  house, a cookie that was copied). One opened with the code holds
  everywhere.
- **The page does not offer what would be refused**: seen from the
  Internet, its power menu says that the computer is stopped and restarted
  from the local network alone.
- **Wrong passwords from the Internet are counted together**, whatever
  addresses they come from. Past 20 within the hour, signing in from the
  Internet is closed until the oldest is an hour old (``429``
  ``sign_in_closed``, and a line in the log). Who is already signed in
  stays so, and signing in from the local network goes on as before: a
  stranger can keep you from signing in from outside for a while, never at
  home.

What is local
-------------

- this computer itself (``127.0.0.1``, ``::1``);
- the private ranges: ``10.x.x.x``, ``172.16.x.x`` to ``172.31.x.x``,
  ``192.168.x.x``, ``169.254.x.x``; over IPv6 ``fe80::…`` and ``fd…``;
- ``100.64.x.x`` to ``100.127.x.x``, which VPNs of the Tailscale kind give;
- over IPv6, the network this computer has its own address in (its first
  64 bits): there every computer of a home has an address of the Internet.

An address that cannot be read is not local.

.. code-block:: toml

   [internet]
   # Taken for local besides the above.
   local_networks = ["203.0.113.0/24"]
   # Not local, whatever they look like.
   not_local = ["192.168.1.1"]
   # Stopping and restarting the computer from anywhere, once signed in.
   host_commands = false

An entry that is neither an address nor a network is passed over, and the
log says so at start.

When the Internet looks local
-----------------------------

Two set-ups make every visitor look like a local one, and ``not_local`` is
there for them:

- **A router that passes connections on under its own address.** Most keep
  the visitor's address; some replace it with their own (``192.168.1.1``,
  say). To know: forward the port, visit from a phone on mobile data, and
  read Mariner's log (``journalctl -u mariner3d``) for the address a
  refusal names, for instance after asking for ``/uvtools/files``. If
  that is the router's, set ``not_local = ["192.168.1.1"]``: slicers on the
  local network go on working, they do not come through the router.
- **A tunnel or a relay on this very computer** (cloudflared, a reverse
  proxy): everything arrives from ``127.0.0.1``. Set
  ``not_local = ["127.0.0.1"]``.
