Installation (Stimpack)
==========


1. Make a new python virtualenvironment
^^^^^^^^^^^^^^^^^^^

In the terminal, type:
    >>> python3 -m venv .stimpack

This will create a new virtual environment in the current directory. You can activate it by typing:
    >>> source .stimpack/bin/activate

2. ``pip`` install stimpack 
^^^^^^^^^^^^^^^^^^^

In your virtualenvironment, install stimpack via ``pip``:
    >>> python3 -m pip install stimpack


3. Confirm installation 
^^^^^^^^^^^^^^^^^^^^^^^

In the ``.stimpack`` virtual environment, type:
    >>> stimpack


This should result in a window opening, that looks like this:

.. image:: /assets/labpack_query.png
    :width: 200px
    :align: center
    :alt: Stimpack window

If you see this window, you have successfully installed stimpack. 
Press `Enter` (red). You should now see a window that looks like this:

.. image:: /assets/stimpack_gui.png
    :width: 500px
    :align: center
    :alt: Stimpack window

Installation issues
^^^^^^^^^^^^^^^^^^^^^^^
**X11 vs. wayland**

Stimpack needs an X11 window system to run properly. Newer versions of Ubuntu default to Wayland. To run stimpack on Ubuntu, log in using an X11 session instead of the default Wayland

**Qt dependency issues**

If you run into errors on Ubuntu relating to your Qt installation, you can try to install some Qt libraries to see if that helps. See these resources:

https://askubuntu.com/questions/1485442/issue-with-installing-pyqt6-on-ubuntu-22-04

