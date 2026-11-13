HTTPS
=====

Mariner serves its page over HTTPS: what goes between your browser and
Mariner — the password to begin with — cannot be read by whoever shares the
network. It does so by itself, with nothing to install or set up.

Where the page is
-----------------

The page is at ``https://<address of the Pi>:5443/``. The address without
``https`` (``http://<address of the Pi>:5000/``) still works: it sends the
browser on to the HTTPS one.

Nothing of the page's own is answered in the clear any more: not its
addresses (they answer ``403`` with the code ``https_required``), not a
session. Only slicers are: UVtools and ChiTuBox speak nothing else, so they
go on using the addresses given in :doc:`network-printing`.

The warning of the browser
--------------------------

The first time, the browser warns that the connection "is not private" or
that the certificate "is not trusted". This is expected: Mariner makes its
own certificate when it first starts, and no authority vouches for a printer
on a home network. The connection is encrypted all the same. Choose
*Advanced*, then *Continue* (the words differ from one browser to another);
the browser remembers, on that address.

What the warning means is that the browser cannot tell *this* printer from
a computer that would pretend to be it. To have it check, and never warn
again, give it Mariner's certificate to trust:

1. Copy the certificate off the Pi. It holds nothing secret:

   .. code-block:: console

      $ sudo cat /var/lib/mariner/https-certificate.pem > mariner.pem

2. Add ``mariner.pem`` to the certificates your computer or phone trusts
   ("install a certificate" in the settings of the system or of the
   browser), for identifying web sites.
3. Open the page under a name or an address the certificate lists: the name
   of the Pi (``printer.local`` if it is called ``printer``) or the address
   it had when the certificate was made.

The certificate lists the short name of the computer (``printer`` and
``printer.local`` for a computer called ``printer.home.lan``) and its
addresses. A name with a character other than letters, digits and hyphens
is left out, and the certificate then lists the addresses alone. In Docker
the name and address are the container's, which nothing outside reaches it
by: the browser warns every time unless you give Mariner a certificate of
your own (below), made for the name of the host.

The certificate lasts thirteen months, the longest browsers accept, and
Mariner makes a new one in its last month, at a restart: the warning then
comes back once, and a certificate that was trusted has to be trusted
again. If the name or the address of the Pi changes, delete
``/var/lib/mariner/https-certificate.pem`` and ``https-key.pem`` and restart
Mariner to have one made for the new name.

Signing in again
----------------

A browser that was signed in before Mariner had HTTPS has to sign in again,
once: what it was given then went in the clear, and is no longer accepted.

A certificate of your own
-------------------------

If you have a certificate for the name the printer is reached by (from your
own authority, or from a public one), name it and its key in
``/etc/mariner/config.toml`` and restart Mariner:

.. code-block:: toml

   [https]
   certificate = "/etc/mariner/printer.pem"
   key = "/etc/mariner/printer.key"

Both files must be readable by the account Mariner runs under (``mariner``),
the key by nobody else, and the key must not be kept under a password:
nobody is there to type it when Mariner starts. The certificate file holds the certificate followed
by those of the authorities between it and the root, if any. If the pair
cannot be used, Mariner says so in its log and serves the page with a
certificate of its own rather than in the clear.

Another port, or no HTTPS
-------------------------

.. code-block:: toml

   [https]
   # The port of the page over HTTPS. 443 if nothing else on the Pi uses it.
   port = 5443
   # Set to false to have Mariner serve its page in the clear only.
   enabled = true

Switch HTTPS off only where something else encrypts the connection: a relay
(nginx, Caddy) in front of Mariner on the same computer, with Mariner
listening on ``127.0.0.1`` alone (``host`` under ``[http]``). In the clear,
the password and everything else can be read and replayed by any device of
the network.

Mariner also serves its page in the clear, and says so in its log at start,
when it cannot have a certificate: the ``openssl`` command is not installed
(``sudo apt install openssl``), or both ports are set to the same number.
A port that is not one (not a whole number from 1 to 65535) is passed over
for 5443, which the log says too.

If another program already uses one of the two ports, Mariner does not
start at all, slicers' interfaces included: its log names the port
(``journalctl -u mariner3d``). Give Mariner another one under ``[http]`` or
``[https]``.

Where Mariner cannot use its state directory (see
:doc:`password-and-settings`), the certificate is kept with what else it
falls back on, and made again at each start if that is a temporary folder.

The wrong address
-----------------

``http://`` with the port of HTTPS (5443) is answered by a line saying that
the port speaks HTTPS. ``https://`` with the port in the clear (5000) is
hung up on: the browser says that the connection failed.

From a script
-------------

.. code-block:: console

   $ curl --cacert mariner.pem https://printer.local:5443/api/csrf_token

``--cacert`` has ``curl`` check that it is talking to this printer, with the
certificate copied as above; ``-k`` skips the check. See
:doc:`password-and-settings` for signing in.
