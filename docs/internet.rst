Local network and Internet
==========================

Mariner is made for the network of a home or a workshop. Should it be
reached from the Internet all the same (a port of the router forwarded to
it), part of what it does stays for the local network alone.

.. warning::

   Being reachable from the Internet is new in this version, and has been
   tried on few installations. A VPN stays the safer way to reach Mariner
   from outside. If you forward a port all the same:

   - forward **the HTTPS port alone** (5443 on the computer). Never the
     port in the clear (5000), nor the one of SDCP (3030): they are for
     the local network;
   - set up the one-time code first, from the local network (see below);
   - read `When the Internet looks local`_: on some routers, and behind
     some providers, strangers look like computers of the house;
   - keep the computer's clock right (it is, on a computer that reaches
     the Internet): the one-time code depends on it.

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
  stays so, and signing in from the local network goes on as before, with
  counts of its own: a stranger can keep you from signing in from outside
  for a while, never at home. These counts are forgotten when Mariner
  restarts.
- **A right password with a wrong code is counted apart, and kept.** It
  means somebody has the password and is guessing at the code. The
  stranger is told what a wrong password is told; the journal of sign-ins
  says it as it is. After ten of them with no sign-in between, signing in
  from the Internet is closed (``403`` ``code_locked``) until somebody
  signs in from the local network. Then change the password.

Its name and its certificate
----------------------------

.. code-block:: toml

   [internet]
   public_name = "printer.example.org"
   public_port = 443

   [https]
   certificate = "/etc/letsencrypt/live/printer.example.org/fullchain.pem"
   key = "/etc/letsencrypt/live/printer.example.org/privkey.pem"

- ``public_name`` is the name Mariner has on the Internet. Mariner answers
  to it without it being listed under ``allowed_hosts``.
- ``public_port`` is the port the router listens on, where it is not the
  one it passes on to (443 outside, 5443 on the computer, say). Asked for
  in the clear under its public name, the page is sent on to that port.
- The certificate of a public name comes from an authority (Let's Encrypt
  and the like) and is renewed every other month or so by a program of its
  own. Mariner looks at the two files every few seconds and takes a renewed
  certificate without being restarted: pages that are open stay open. A
  pair that cannot be used (half written, a key that is not the
  certificate's) is said in the log once, and the one in use is kept.
  Mariner's account must be able to read both files.

Under load
----------

Mariner cannot keep strangers from leaning on its door. It keeps them from
shutting you out at home, and from bringing it down:

- of the 64 connections it takes at once, the Internet holds 24 at most,
  and one address 8: the local network always finds room;
- one address opens 30 new connections in ten seconds at most, the whole
  Internet 150: each one over HTTPS costs the computer some work;
- a connection from the Internet that asks nothing within ten seconds is
  closed, as is one that takes longer than that to say what it asks for;
  one that was answered is closed after thirty seconds with nothing more
  asked;
- over IPv6, where whoever has one address has billions, a network counts
  as one address;
- whoever is sent a very large answer and reads none of it for a minute is
  taken for gone, from wherever it is: it no longer holds what serves the
  others. (Nothing Mariner serves today is that large.)

Connections turned away are counted in the log, a line a minute at most.
None of this applies to addresses of the local network, bar the last.

A small computer still has its limits: a flood wide enough fills the line
itself, and then nothing answers from outside until it stops. Home is not
touched, nor is a print under way: the printer reads its file by itself.

What is local
-------------

- this computer itself (``127.0.0.1``, ``::1``);
- the private ranges: ``10.x.x.x``, ``172.16.x.x`` to ``172.31.x.x``,
  ``192.168.x.x``, ``169.254.x.x``; over IPv6 ``fe80::…`` and ``fd…``;
- over IPv6, the network this computer has its own address in (its first
  64 bits): there every computer of a home has an address of the Internet.
  Where that network is shared with strangers (a hosting company, a hall
  of residence), list it under ``not_local``.

An address that cannot be read is not local.

**Not** ``100.64.x.x`` to ``100.127.x.x``. VPNs of the Tailscale kind give
such addresses, but so do providers that share one public address among
their customers, and those customers would be at home here. If you reach
Mariner through such a VPN and want it treated as the local network, say
so: ``local_networks = ["100.64.0.0/10"]``. Left as it is, the VPN is
treated as the Internet: the one-time code is asked, which does no harm.

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

Three set-ups make visitors look like local ones, and ``not_local`` is
there for them. To know whether yours is one: forward the port, open the
page from a phone **on mobile data, not on the house's Wi-Fi**, and look.
If the page asks for the one-time code (or says that none is set up), all
is well. If it asks for the password alone, the phone was taken for a
computer of the house: sign in from the local network, open **Settings**,
**Recent sign-ins**, and read the address the phone's attempt came from.

- **A router that passes connections on under its own address.** Most keep
  the visitor's address; some replace it with their own (``192.168.1.1``,
  say). Set ``not_local = ["192.168.1.1"]``: slicers on the local network
  go on working, they do not come through the router.
- **A router whose own outside address is private**: behind a provider that
  shares addresses, or behind a second router. Its outside address (shown
  in the router's own pages as "WAN" or "Internet" address) then begins
  with ``10.``, ``172.16.`` to ``172.31.``, ``192.168.`` or ``100.64.`` to
  ``100.127.``, and other customers of the provider, or the computers of
  the network in between, arrive with such addresses. List that network
  under ``not_local`` (``not_local = ["10.0.0.0/8"]``, say), unless it is
  the very range your own computers use.
- **A tunnel or a relay on this very computer** (cloudflared, a reverse
  proxy): everything arrives from ``127.0.0.1``. Set
  ``not_local = ["127.0.0.1"]``.
