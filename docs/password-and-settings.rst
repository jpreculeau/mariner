Password and Settings
=====================

Mariner asks for a password before it shows its page or does anything the
page does: listing, sending and deleting files, starting, pausing and
cancelling a print, shutting the computer down, changing settings.

Choosing the password
---------------------

The first time the page is opened, it asks for a password to be chosen: type
it twice, at least 8 characters. Whoever opens the page first chooses it, so
do it right after installing Mariner, before the printer is left on the
network.

The password is not kept as it is typed, but as a *hash* from which it cannot
be read back, not even by Mariner. It can be replaced, never recovered.

Signing in and out
------------------

Once signed in, a browser stays so for a month from its last visit, through
restarts of Mariner and of the computer. *Settings → Sign out* ends it at
once. Changing the password (*Settings → Password*) asks for the current one
and signs every other browser out.

After three wrong passwords the next attempt has to wait: one second, then
two, four, and so on up to thirty. The count starts again at the first right
one.

What the password does not cover
--------------------------------

Slicers send files and start prints over the network, and none of them can
give a password. Their two interfaces are therefore **not** behind it:

- UVtools, on the port of the web page (``/uvtools/...``);
- SDCP, which ChiTuBox speaks, on UDP port 3000 and TCP port 3030.

Anyone on your network can use them while they are on. Switch off the ones
you do not use, under *Settings → Slicers* (Mariner then has to be
restarted, which the page offers to do), or in ``config.toml``:

.. code-block:: toml

   [uvtools]
   enabled = false

   [sdcp]
   enabled = false

See :ref:`Network Printing` for what each interface is for.

A password that is lost
-----------------------

It cannot be read back: it is cleared, and a new one chosen at the next
visit. Clearing it takes someone who has the computer in hand, in either of
two ways.

From a terminal on the computer Mariner runs on (over SSH, for instance):

.. code-block:: console

   $ sudo mariner reset-password
   The password was cleared. Open Mariner's page to choose a new one: until
   then, whoever opens it first can.

Without a terminal: switch the computer off, put its card in another
computer, and make an empty file named ``reset-password`` (or
``reset-password.txt``) on the card's first drive, the small one that shows
up under any system (``bootfs``). Put the card back and start the computer:
Mariner clears the password and removes the file. If it is not allowed to
remove it, it remembers having obeyed it and passes it over from then on,
until the file is written again.

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
- ``settings.json``: the settings changed from the page. Remove it to go
  back to ``config.toml`` alone;
- ``sdcp_history.json``: the prints shown to ChiTuBox as past tasks.

Keep this directory when you move an installation; in Docker it is a volume.

From a script
-------------

A script signs in like the page does, and keeps the cookie it is given:

.. code-block:: console

   $ curl -s -c jar http://printer.local:5050/api/csrf_token
   {"csrf_token":"IjM4..."}
   $ curl -s -b jar -c jar -H 'X-CSRFToken: IjM4...' \
         -H 'Content-Type: application/json' \
         -d '{"password":"correct horse battery"}' \
         http://printer.local:5050/api/auth/login
   {"csrf_token":"ImE1...","success":true}
   $ curl -s -b jar http://printer.local:5050/api/print_status

The answer to signing in carries the token to send from then on. Without a
session the page's addresses answer ``401`` with the code ``login_required``,
or ``password_not_set`` when no password has been chosen yet.
