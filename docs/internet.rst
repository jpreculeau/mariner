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
