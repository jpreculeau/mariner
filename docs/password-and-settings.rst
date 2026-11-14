Password and Settings
=====================

Mariner asks for a password before it shows its page or does anything the
page does: listing, sending and deleting files, starting, pausing and
cancelling a print, shutting the computer down, changing settings.

Choosing the password
---------------------

The first time the page is opened, it asks for a password to be chosen: type
it twice, at least 14 characters: a few words make a good one, and nothing
is asked of what it is made of (the handful everybody tries first are
refused). A shorter one chosen with an earlier version still opens the page;
the next one chosen has to be longer. It is chosen from the local network
or with ``sudo mariner set-password``, never from the Internet (see
:doc:`internet`). Whoever opens the page first
chooses it, so do it right after installing Mariner, before the printer is
left on the network.

To leave nobody the chance, choose it from a terminal on the computer
Mariner runs on, before opening the page at all:

.. code-block:: console

   $ sudo mariner set-password
   New password for Mariner:
   Again:
   The password was set (in /var/lib/mariner).
   Every browser that was signed in has to sign in again.

The same command replaces a password at any time, and signs every browser
out. Where Mariner is not installed as a service but run by hand under your
own account, run it as that account (``mariner set-password``, without
``sudo``), so that it works on the folder that account uses.

The password is not kept as it is typed, but as a *hash* from which it cannot
be read back, not even by Mariner. It can be replaced, never recovered.

The one-time code
-----------------

From the Internet, the password is not enough: Mariner also asks for a
*one-time code*, six digits that an application of your phone gives and
that change every half minute. On the local network the password alone
signs in. See :doc:`internet` for what else changes from outside.

To set it up, either:

- in the page, from the local network: **Settings**, **One-time code**,
  **Set up a one-time code**. The page shows a key. In the application
  (Aegis, FreeOTP, Google Authenticator or any other that speaks TOTP),
  add an account and type the key, or open the link on the phone itself;
  then type the code the application gives, to check that it took the key
  in;
- or from a terminal on the computer Mariner runs on:

  .. code-block:: console

     $ sudo mariner set-code

  which shows the same key and asks for the same first code.

**Replace the phone**, in the same part of the settings, asks for the
password and sets the code up on another phone; the old phone's codes stop
working once the new phone's first code is given. To do away with the code:
**Remove the one-time code** (it asks for the password too), or
``sudo mariner reset-code``. Without a code, nobody signs in from the
Internet. Replaced or removed, a code signs out whoever had signed in from
the Internet with it, for good: the browser of a phone that was lost does
not come back when the next code is set up.

The code depends on the time: the computer's clock and the phone's must be
right, within half a minute or so. A computer that reaches the Internet
sets its clock by itself; one that has just started without it may refuse
right codes until it has.

A lost phone locks nobody out at home: sign in from the local network, or
use the terminal, and set the code up on the new phone.

Recent sign-ins
---------------

**Settings**, **Recent sign-ins** lists the latest things that happened at
the door (up to fifty wrong passwords and closings, and up to fifty of
all the rest): sign-ins, wrong passwords, a right password sent with a wrong code, the
password or the one-time code being changed, sign-in being closed to the
Internet. Wrong passwords sent one after the other from one place are one
line, with how many; they are kept apart from the rest, so that a crowd of
them does not push out the sign-in you are looking for. Each with when, and
where from: the local network or the Internet, and the address. Above the
list, and in a message when you sign in, Mariner says how many wrong
passwords were sent between your last two visits (not counting your own
slips just before signing in), and, apart, how many times the right password
came with a wrong code. If that was not you (a code mistyped, or one used a
second time: a code works once, and the next comes within half a minute), it
means somebody else knows the password. What was typed is never kept.

A few wrong passwords from the Internet are the lot of anything reachable
from there. Many of them, or one from the local network that is not yours,
are worth a look: see :doc:`internet`.

Signing in and out
------------------

Once signed in, a browser stays so for a month from its last visit, through
restarts of Mariner and of the computer. *Settings → Sign out* ends that
browser's session for good: its cookie is of no use afterwards, even copied.
Changing the password (*Settings → Password*) asks for the
current one and signs every other browser out: do that if a browser you do
not trust was ever signed in.

After three wrong passwords the next attempt has to wait: one second, then
two, four, and so on up to thirty. The count starts again at the first right
one. The count is kept for each computer (by its address), so that someone
else's wrong passwords do not keep you waiting. Only a few computers have a
count of their own at a time; past that the rest share one. Where
Mariner is made to listen over IPv6, the computers of one network share a
count: a computer has as many such addresses as it likes.

What the password does not cover
--------------------------------

Slicers send files and start prints over the network, and none of them can
give a password. Their two interfaces are therefore **not** behind it:

- UVtools, on the port Mariner listens on in the clear (``/uvtools/...``,
  port 5000 unless set otherwise under ``[http]``);
- SDCP, which ChiTuBox speaks, on UDP port 3000 and TCP port 3030.

Anyone on your network can use them while they are on, and what goes
through them is not encrypted (the page itself is: see :doc:`https`). Switch off the ones
you do not use, under *Settings → Slicers* (Mariner then has to be
restarted, which the page offers to do), or in ``config.toml``:

.. code-block:: toml

   [uvtools]
   enabled = false

   [sdcp]
   enabled = false

See :ref:`Network Printing` for what each interface is for.

Other programs on the same computer
-----------------------------------

A browser tells sites apart by their name, not by their port: the cookie
that says you are signed in to Mariner is also sent to the page of any other
program served from the same computer (a camera's page, a network filter).
So that such a program cannot use it, signing in also gives Mariner's page a
key that the browser keeps for that page alone and that goes with each of
its requests; the cookie without the key opens nothing, except the picture
of a file. In a browser set to keep nothing, the key lasts as long as the
tab: reloading the page asks for the password again.

A password that is lost
-----------------------

It cannot be read back: it is cleared, and a new one chosen at the next
visit. Clearing it takes someone who has the computer in hand, in either of
two ways.

From a terminal on the computer Mariner runs on (over SSH, for instance):

.. code-block:: console

   $ sudo mariner reset-password
   The password was cleared (in /var/lib/mariner).
   Until a new one is chosen, whoever opens Mariner's page first chooses it.
   To choose it here instead, run: mariner set-password

Until a new one is chosen, whoever opens the page first chooses it. To
choose it yourself in the same breath, run ``sudo mariner set-password``
instead: it replaces the password whether or not the old one is known.

Without a terminal: switch the computer off, put its card in another
computer, and make an empty file named ``reset-password`` (or
``reset-password.txt``) on the card's first drive, the small one that shows
up under any system (``bootfs``). Put the card back and start the computer:
Mariner clears the password. Installed as a service it may not write to that
drive, so it leaves the file there and remembers having obeyed it: the file
is passed over from then on, until it is written again. Remove it when the
card is next in a computer.

Either way every browser is signed out.

Settings
--------

*Settings*, in the menu, holds what can be changed without opening a
terminal:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Setting
     - What it does
   * - Name shown for the printer
     - Shown on the dashboard. Empty, the name in ``config.toml``
       (``display_name`` under ``[printer]``) is used.
   * - UVtools
     - Serves the addresses UVtools sends files and commands to. Takes
       effect when Mariner is started again.
   * - ChiTuBox (SDCP)
     - Answers ChiTuBox's discovery and takes its files and commands. Takes
       effect when Mariner is started again.
   * - Do not ask when the printer does not answer
     - Replacing or deleting a file while the printer is silent normally
       asks whether it is switched off, because a silent printer cannot say
       whether it is printing that file. With this on, Mariner goes ahead
       as if you had answered yes. A file that a printer which *does*
       answer is printing stays protected.

What is changed here comes before what ``config.toml`` says. Everything else
is set in ``config.toml`` only.

Where Mariner is installed as a service, *Restart Mariner* stops it and the
service starts it again; a print under way goes on, a file being sent is
lost. Run by hand or in a container, restart it the way it was started.

Where this is kept
------------------

In the *state directory*, ``/var/lib/mariner`` unless ``directory`` under
``[state]`` in ``config.toml`` names another. It belongs to the account
Mariner runs under and no other account can read it. It holds:

- ``password``: the password's hash;
- ``session.key``: the key that signs the cookie of who is signed in. Remove
  it and restart Mariner to sign everyone out;
- ``signed-out.json``: the sessions that were signed out of, until they
  would have ended by themselves;
- ``settings.json``: the settings changed from the page. Remove it to go
  back to ``config.toml`` alone;
- ``one-time-code``: the secret of the one-time code, with the last code
  that served and the count of wrong ones. Whoever reads it can make the
  codes: it is as secret as the password is;
- ``sign-ins``: the journal of sign-ins and attempts;
- ``sdcp_history.json``: the prints shown to ChiTuBox as past tasks.

Keep this directory when you move an installation; in Docker it is a volume.

A copy of this directory is a way in: with ``session.key`` a session can be
made without knowing the password. Keep backups and images of the card where
you would keep the password. If a copy may have got out, change the password
(from the page or with ``mariner set-password``): Mariner then makes a new
key and every session made with the old one is refused.

If Mariner cannot use this directory, or the password kept in it (they
belong to another account, after a copy made as ``root`` or a Docker mount;
the directory was moved away; or, when Mariner starts, the drive is
read-only), it does not fall back on "no password yet": its page says that
it cannot open and lets nobody in, and the slicers' interfaces stay off,
until the directory is put right and Mariner restarted. The log names the
directory. A drive that goes read-only while Mariner runs does not shut the
page — a print can still be watched and stopped — but nothing more can be
kept: saving a setting or changing the password says so. For instance:

.. code-block:: console

   $ sudo chown -R mariner:mariner /var/lib/mariner
   $ sudo chmod 700 /var/lib/mariner
   $ sudo systemctl restart mariner3d

The service may write under ``/var/lib/mariner`` and ``/var/cache/mariner``
and reads the homes of users without writing to them. It cannot gain rights
it was not started with (``NoNewPrivileges``): shutting the computer down
from the page works through the rights given to Mariner's account, not
through a ``sudo`` wrapper. If you set
``files_directory``, ``spool_directory`` or the state directory under
``/home``, allow it with a drop-in (``sudo systemctl edit mariner3d``):

.. code-block:: ini

   [Service]
   ReadWritePaths=/home/me/prints

From a script
-------------

A script signs in like the page does, and keeps the cookie it is given:

.. code-block:: console

   $ curl -s --cacert mariner.pem -c jar https://printer.local:5443/api/csrf_token
   {"csrf_token":"IjM4..."}
   $ curl -s --cacert mariner.pem -b jar -c jar -H 'X-CSRFToken: IjM4...' \
         -H 'Content-Type: application/json' \
         -d '{"password":"correct horse battery"}' \
         https://printer.local:5443/api/auth/login
   {"csrf_token":"ImE1...","page_key":"u3Jk...","success":true}
   $ curl -s --cacert mariner.pem -b jar -H 'X-Mariner-Key: u3Jk...' \
         https://printer.local:5443/api/print_status

``mariner.pem`` is Mariner's certificate, copied as :doc:`https` says.
The answer to signing in carries the key to send with every request from
then on (``X-Mariner-Key``), and the token to send with those that change
something (``X-CSRFToken``). Without both the cookie and the key the page's
addresses answer ``401`` with the code ``login_required``, or
``password_not_set`` when no password has been chosen yet. Other answers a
script should expect: ``429`` ``too_many_attempts`` after wrong passwords,
with the seconds to wait in ``Retry-After``; ``503`` ``state_unavailable``
while Mariner cannot use its state directory; ``500`` ``state_not_written``
when a password or a setting could not be kept there.
