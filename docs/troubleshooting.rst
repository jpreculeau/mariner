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
* names containing control characters such as a line break.

Rename the file and upload it again. The same rules apply to folder names and
to files sent from a slicer.

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
reading it, and refuses in four cases, in the web interface, from UVtools
and from a slicer sending over the network alike:

* **The file is being printed** (the print is starting, running or paused).
  The same goes for a folder that contains it, which slicers can delete. This
  holds however the print was started: from Mariner, from a slicer or from
  the printer's own screen. Wait for the print to finish, or cancel it.

* **A print is running from a file Mariner could not identify**, for example
  one started from the printer's own screen under a name Mariner does not
  find. Every existing file is then left alone until that print is over.

* **The printer answered, but not clearly enough.** It is switched on, and
  what it sent says nothing about a print, which happens now and then on a
  busy serial line. Try again in a moment.

* **The printer is not answering at all**: it is off, or the serial cable is
  loose. Switch the printer on or check the cable, then try again; opening
  the dashboard asks the printer again.

In all four cases a file can still be stored under a **new name**, since
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
  ``ignore_unreachable_printer=1``. Mariner then asks the printer once more
  and goes ahead only if nothing at all comes back.

* **UVtools and slicers sending over the network** have no way to confirm,
  so for them the refusal stands. Use the web interface, or store the file
  under a new name.

.. rubric:: What clients receive

The web interface shows the reason in a notification. The web API answers
with status 409 and a JSON body:

* ``code``: ``file_in_use``, ``print_file_unknown``,
  ``printer_answer_unclear`` or ``printer_not_answering``, for the four
  cases above in that order;
* ``title`` and ``description``: the explanation, ready to be shown;
* ``can_be_overridden``: true for ``printer_not_answering`` only.

UVtools receives a 409, and a slicer using SDCP sees its transfer or
deletion fail. A slicer deleting a folder is also turned down while a file
is being uploaded into that folder through another interface.

.. note::

   This protection is only as good as the serial link. A print started
   through Mariner protects its file at once; one started from the printer's
   own screen is noticed within about a second. Mariner cannot protect a file
   from being changed by other means, such as another computer writing to the
   same storage.

Printing
--------

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
