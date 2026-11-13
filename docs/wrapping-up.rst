Wrapping up
-----------

Reboot the Pi and you should be all set. Again these are rough
instructions for now :)

You can check that the ``mariner3d`` service is running with:

.. code-block:: shell-session

   $ sudo systemctl status mariner3d

If it is, you should be able to access it by opening
``https://<pi ip address>:5443/`` on your browser (``http://<pi ip
address>:5000/`` leads there too). The browser warns about the certificate
the first time: see :doc:`https`.
