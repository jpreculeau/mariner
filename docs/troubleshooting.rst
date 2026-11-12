Troubleshooting
===============

Common Issues
-------------

.. rubric:: Slow WiFi

If uploading or accessing mariner is too slow, the following might help:

* If you are powering your Raspberry Pi from a 5V pin on the printer's
  mainboard, try using an external power supply or a buck converter from the
  printer's 12V line. WiFi reception has been reported to be weaker when
  powering the RPi directly from the printer's mainboard.
* `Use an external antenna
  <https://www.briandorey.com/post/raspberry-pi-zero-w-external-antenna-mod>`_.
* Try moving the RPi to outside of the printer case.
* Try moving your RPi closer to your router, `consider using ethernet
  <https://www.raspberrypi-spy.co.uk/2020/05/adding-ethernet-to-a-pi-zero/>`_ or
  a different model such as the RPi 4B, which has onboard ethernet.

.. rubric:: Disk init fail

If your printer is returning an error such as ``//Disk init fail!\r\n``, it
means your Raspberry Pi is not properly configured to use Linux's USB Gadget
mode and your printer is failing to see the virtual disk shared by the RPi.
Please refer to the :ref:`USB Gadget Setup` section of the documentation and
check your setup carefully.

Often, this can be one of these issues:

* **Check for bad USB cables.** Your Micro USB cable should be able to transfer
  data. There are a lot of USB cables out there that don't have the D+/D- data
  lines connected and only have the 5V and GND pins connected. Check that your
  USB cable works with other devices!
* Your ``/etc/rc.local`` isn't setup correctly with the ``modprobe
  g_mass_storage`` line (see `Issue #412
  <https://github.com/mariner3d/mariner/issues/412>`_ for an example).
* Make sure ``dtoverlay=dwc2`` is under the ``[all]`` section of your
  ``/boot/config.txt``.
* Make sure your Raspberry Pi `supports USB OTG
  <https://en.wikipedia.org/wiki/Raspberry_Pi#Specifications>`_.


.. rubric:: Unexpected Printer Response

If you are seeing the "Unexpected Printer Response" while printing from the web
interface (but printing is working fine), then you are running into `Issue #180
<https://github.com/mariner3d/mariner/issues/180>`_, which is being worked on.

This has no performance effect and won't cause issues with your prints. It
should cause nothing but cosmetic issues on the user interface and can safely
be ignored. Just refresh the page if you run into it.

.. rubric:: No such file or directory: /dev/serial0

If you are seeing this on the logs for the ``mariner3d`` service on
``journalctl``, this means your serial port is not setup properly. Please refer
to the :ref:`Setting up the serial port` section of the installation guide.

.. rubric:: Error: File is not existed or empty

If your printer is returning responses such as ``Error: File is not existed or
empty``, make sure to upgrade to the latest version of mariner. This is an old
issue which was fixed on ``v0.2.0``. See `Issue #311
<https://github.com/mariner3d/mariner/issues/311>`_.

.. rubric:: Printer stops during print

If your printer is stopping during the print process, make sure to upgrade to
the latest version of mariner. This is an old issue which was fixed on
``v0.2.0``. See `Issue #311
<https://github.com/mariner3d/mariner/issues/311>`_.

File Names
----------

.. rubric:: An upload is refused with error 400

Mariner stores a file under the name it was given, so that the same name
works for listing, printing and deleting. Spaces, accents, parentheses and
non-Latin characters are all kept; only the whitespace around the name is
removed. Names it cannot use safely are refused instead of being rewritten:

* names containing ``/`` or ``\``;
* names containing a single quote (``'``), which the printer uses to delimit
  the file name in its print command;
* names containing ``: * ? " < > |``, which the FAT filesystem read by the
  printer cannot store;
* names ending with a dot, or longer than 255 bytes;
* names containing control characters such as a line break, or the Unicode
  line and paragraph separators, anywhere including at either end.

Rename the file and upload it again. The same rules apply to folder names and
to files sent from a slicer.

A file stored before these rules existed, or put on the drive by other
means, under a name they do not allow, can still be deleted from the web
interface, from UVtools and from a slicer. It cannot be printed under that
name.

An upload is also refused with error 400 when the file is not in a format
Mariner can print, when a folder already has that name, or when the name is
one Mariner keeps for transfers in progress (``.upload-<random>.part`` and
``.sdcp_uploads``, in upper or lower case).

.. rubric:: Replacing a file

Uploading a file whose name already exists replaces it. The new file is first
written under a temporary name (``.upload-<random>.part``), which the file
list does not show, and moved into place once complete. An interrupted upload
therefore leaves the previous file intact. Files sent from a slicer over SDCP
are assembled the same way, in a ``.sdcp_uploads`` folder that the file lists
do not show either. Anything of the kind left behind by a power cut is
removed the next time Mariner starts.

.. rubric:: A file cannot be replaced or deleted (error 409)

The printer reads its file layer by layer for the whole print. Mariner
therefore changes an existing file only when the printer confirms it is not
reading it, and refuses in five cases, in the web interface, from UVtools
and from a slicer sending over the network alike:

* **The file is being printed** (the print is starting, running or paused).
  The same goes for a folder that contains it, which slicers can delete. This
  holds however the print was started: from Mariner, from a slicer or from
  the printer's own screen. Wait for the print to finish, or cancel it.

* **A print of the file was started through Mariner a moment ago.** For a
  few seconds after being told to print, the printer still reports that it
  is idle, so Mariner protects the file itself for half a minute, or until
  the printer reports the print. Cancelling the print during that time does
  not lift the protection: nothing the printer says then tells a print that
  was stopped from one that is about to begin. Try again half a minute
  later.

* **A print is running from a file Mariner could not identify**, for example
  one started from the printer's own screen under a name Mariner does not
  find. Every existing file is then left alone until that print is over.

* **Mariner could not get a clear answer from the printer.** The printer
  sent something that says nothing about a print, which happens now and
  then on a busy serial line, or the line failed while it was being read,
  or Mariner could not use the serial port at all. Try again in a moment;
  if it lasts, see `Other Issues`_.

* **The printer is not answering at all**: it was asked and nothing came
  back, or its serial device is not there. It is off, or the cable is
  loose. Switch the printer on or check the cable, then try again; opening
  the dashboard asks the printer again.

In all five cases a file can still be stored under a **new name**, since
nothing can be reading a file that does not exist yet.

.. rubric:: Changing a file while the printer is switched off

A printer that is switched off cannot say that it is not printing, so the
last refusal above also applies when the printer is off on purpose. That
refusal, and no other, can be lifted:

* In the **web interface**, Mariner asks *Printer not answering: delete
  anyway?* (or *replace anyway?*). Confirm only if the printer really is
  switched off. A printer that is printing with its cable unplugged looks
  exactly the same to Mariner, and its print would be ruined. The question
  is asked each time.

* A client of the **web API** repeats the request with
  ``ignore_unreachable_printer=1``. Mariner then asks the printer again
  and goes ahead only if it stays silent.

* **UVtools and slicers sending over the network** have no way to confirm,
  so for them the refusal stands. Use the web interface, or store the file
  under a new name.

.. rubric:: What clients receive

The web interface shows the reason in a notification. The web API answers
with status 409 and a JSON body:

* ``code``: ``file_in_use``, ``print_just_started``, ``print_file_unknown``,
  ``printer_answer_unclear`` or ``printer_not_answering``, for the five
  cases above in that order;
* ``title`` and ``description``: the explanation, ready to be shown;
* ``can_be_overridden``: true for ``printer_not_answering`` only.

UVtools receives a 409, and a slicer using SDCP sees its transfer or
deletion fail. A slicer deleting a folder is also turned down when a file is
being uploaded into that folder through another interface at that moment.

.. note::

   This protection is only as good as the serial link. A print started
   through Mariner protects its file at once; one started from the printer's
   own screen is noticed within about a second. Mariner cannot protect a file
   from being changed by other means, such as another computer writing to the
   same storage.

.. rubric:: A transfer from a slicer is refused or disappears

Slicers send a file over the network (SDCP) in pieces. Mariner keeps the
pieces of each transfer apart by the address of the computer that sends them
and by the transfer id the slicer chose:

* a piece that names another file, or another size, than the transfer it
  claims to continue is refused, and so is a piece from the middle of a
  transfer that is not under way;
* a slicer can only end its own transfer;
* a declared MD5 checksum that is not 32 hexadecimal digits is refused;
* a transfer that receives nothing for five minutes is abandoned and what
  was received is removed; send the file again;
* a transfer whose last bytes cannot be stored, for want of room, is refused
  and the previous file is kept; free some space and send the file again.

Two slicers on the **same** computer that send the same file name and size
at the same time, under the same transfer id or both without one, cannot be
told apart: the second one to start takes over, and pieces still arriving
from the first can end up in its file. Slicers that ask for the checksum to be verified
are protected: the file is then refused.

.. rubric:: Mariner answers "Name Not Allowed" (error 403, ``host_not_allowed``)

Mariner answers to its IP address and to names of the kind used on a local
network: a single word such as ``mariner``, the name of the computer it
runs on, or a name ending in ``.local``, ``.lan``, ``.home``,
``.home.arpa``, ``.internal`` or ``.localdomain``. (This is custom, not
law: no ordinary web site can own a single word or a name with one of these
endings today.) If you reach it under
another name, one your router gives (``mariner.fritz.box``), one of a VPN
(Tailscale's ``.ts.net``) or of your own domain, add that name, without a
port, under ``[http]`` in ``/etc/mariner/config.toml`` and restart Mariner:

.. code-block:: toml

   [http]
   allowed_hosts = ["printer.example.org"]

The check is there because nothing in Mariner asks who is using it. Without
it, a web site could point a name of its own at the address of your printer
and have your browser read and drive it. So add a name only if it is one
you, your router or your VPN gave the printer; if you landed on this error
from a link and do not know the name, leave the setting alone.

.. rubric:: A request is refused as coming from another site (error 403, ``cross_site_request``)

For this refusal, the one before and the one after, Mariner's log says who was refused
and what the request said of itself (``journalctl -u mariner3d``), once a
minute at most for the same client and reason.

When a browser says which page a request comes from, Mariner serves only
its own pages' requests. A bookmark, a typed address and a link to Mariner
all work. Slicers and scripts say nothing of a page and are served. A
script that sends an ``Origin`` or ``Referer`` header must send Mariner's
own address in it, or none.

Behind a relay such as nginx, every request of the page is refused, so that
it shows no files and no printer, when the relay asks Mariner under another
name or port than the browser used. Have the relay pass the name on as it
came (``proxy_set_header Host $http_host;``), or give the address the
browser shows, whole, under ``[http]`` in ``/etc/mariner/config.toml``:

.. code-block:: toml

   [http]
   allowed_origins = ["https://printer.example.org"]

A name in ``allowed_hosts`` is one Mariner may be asked for. It does not
make a page served under that name one of Mariner's: on the same computer,
another port is another program.

Mariner can no longer be shown inside another page, a dashboard for
instance: a page able to do that could lay its own buttons over Mariner's.

.. rubric:: A slicer address is refused to a browser or a script (error 403, ``browser_not_served``)

The addresses under ``/uvtools`` are for slicers. They act on a plain
request, which any page can have a browser send by a link or a picture, so
they are not served to a browser, whatever page it comes from, nor to a
program that sends what browsers and media players send.

A script is refused there when it calls itself a browser or sends one of
the headers ``Accept-Language``, ``Range``, ``Icy-MetaData``, ``Purpose``
or ``Sec-Purpose``. PowerShell does the first: give ``Invoke-WebRequest``
and ``Invoke-RestMethod`` a name of your own with ``-UserAgent
"my-script"``. curl, wget and Python's libraries are served as they are,
unless asked to resume a download (``curl -C``, ``curl -r``, ``wget -c``),
which sends ``Range``.

This keeps out the programs known to follow a page's links. It is not a
lock: if the printer's network holds devices or people you do not trust,
switch these addresses off (``[uvtools] enabled = false``).

.. rubric:: An action answers "Page Out Of Date" (error 400, ``token_refused``)

The page was open when Mariner restarted, or the browser ended its
session. The page normally notices, asks Mariner for a new token and sends
its request again without a word. If you do see this message, reload the
page. A script has no page: it asks ``/api/csrf_token`` for a token first,
and sends it in the ``X-CSRFToken`` header with the cookie that came with
it.

.. rubric:: A request is refused as too large (error 413, ``request_too_large``)

Only the addresses files are sent to (``/api/upload_file`` and
``/uvtools/upload/``) take 512 KB or more, or data of no size said
beforehand. Nothing Mariner's page or a slicer sends elsewhere comes near
that size. A script that sends even a small request in pieces
(``Transfer-Encoding: chunked``) to another address is refused too: have it
say the length.

.. rubric:: An upload stops without an answer

Mariner closes a connection on which nothing has moved for a minute to a
minute and a half: there are only so many, and one that hangs keeps others
out. A phone that goes to sleep or changes network in the middle of an
upload loses it; send the file again.

.. rubric:: A file is refused as too large (error 413)

Files can be 2048 MB at most, from the web page and from slicers. To accept
larger ones, set ``max_upload_size_mb`` under ``[http]`` in
``/etc/mariner/config.toml`` and restart Mariner. The answer comes from the
web server itself, as plain text.

.. rubric:: A file is refused for want of room (error 507, ``upload_not_stored``)

While it arrives, a file is kept in ``/var/tmp``, on the drive of the
computer Mariner runs on, which must have room for it: twice its size for a
file sent from the web page, its size for one sent through UVtools, and 64 MB
that Mariner leaves free for the system. Where files are kept on that same
drive, which is not how Mariner is installed, the file itself counts once
more. A file that says how large it is,
as the web page and slicers do, is refused before Mariner takes any of it
in when that room is not there. Room is measured when a file starts to
arrive: of several sent at once, or of one that does not say how large it
is, one may still find the drive full on the way, and its connection is
then closed without an answer. Free some room, or set another place on a drive as
``spool_directory`` under ``[http]``. If that place cannot be used, Mariner
says so in the logs at start and falls back on ``/tmp``; where ``/tmp`` is
held in memory there is little room in it.

The same code with error 500 means the file did arrive and the printer's
drive, where files are stored, had no room for it.

.. rubric:: A folder cannot be made (error 400, ``folder_too_deep``)

Folders can be nested 16 deep. Make the folder higher up.

Folders nested deeper, put on the drive by other means, are left as they
are. Below 64 levels Mariner no longer looks into them: files there are not
read ahead of time at start, and a folder holding such a chain cannot be
deleted from a slicer.

.. rubric:: A file is listed but cannot be printed

Mariner reads each file before the web page offers to print it. A file it
cannot make sense of stays in the list without the print action, so that it
can still be deleted. The usual
cause is a transfer that stopped part of the way: the start of the file is
there, the last layers are not, and the print would stop midway. Send the
file again from the slicer.

The other causes are a file damaged on the drive, and a file made by a
slicer version whose format Mariner does not know yet. The reason is in the
logs, at the end of a line holding ``Could not read``, written when the
file is first read:

.. code-block:: shell-session

   $ sudo journalctl -u mariner3d.service | grep "Could not read .*: "

The line is written once for each version of the file. If it is no longer in
the logs, restart Mariner or send the file again.

The check is the web page's: a print asked for by other means, from a slicer
or the printer's own screen, is started as before.

If a file that prints correctly from the printer's own screen is listed this
way, please report it with that line.

Asked for the details of such a file, the web API answers 422 with the code
``file_unreadable``; so it does for the preview when the picture itself is
missing or damaged.

Printing
--------

.. rubric:: A print cannot be started (error 409)

Mariner does not start a print while the printer reports one that is
starting, running or paused. Wait for it to finish, or cancel it first. The
web API answers 409 with the code ``print_in_progress``.

The same goes for the half minute after a print was started through Mariner,
until the printer reports that print, which also stops a double click from
starting two. There is nothing to cancel then: try again half a minute
later. That also applies when the printer turned the first print down after
selecting its file, since Mariner cannot tell that apart from a print that
is about to begin. The web API answers 409 with the code
``print_just_started``.

In both cases UVtools receives a 409, and a slicer using SDCP is told that
the printer is busy.

.. rubric:: The dashboard shows progress but no layer count

When a print was started from the printer's own screen with a file Mariner
cannot find or cannot read, the dashboard still shows the state and a
progress figure worked out from how much of the file the printer has read.
Layer numbers and the remaining time need the file itself, so they are left
out.

Other Issues
------------

If your issue isn't listed above, check the ``mariner3d`` logs for clues:

.. code-block:: shell-session

   $ sudo journalctl -ub mariner3d.service

Also check the message buffer of the Linux kernel for errors:

.. code-block:: shell-session

   $ sudo dmesg

Carefully read the :ref:`Installation Guide` once again and, if none of that
helps, `file an issue on GitHub
<https://github.com/mariner3d/mariner/issues/new/choose>`_!
