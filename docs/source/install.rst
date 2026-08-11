Installation (Stimpack)
=======================


1. Make a new python virtualenvironment
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

In the terminal:

.. code-block:: console

    python3 -m venv .stimpack

This creates a new virtual environment in the current directory. Activate it:

.. code-block:: console

    source .stimpack/bin/activate

2. ``pip`` install stimpack 
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

In your virtual environment, install stimpack via ``pip``:

.. code-block:: console

    python3 -m pip install stimpack


3. Confirm installation 
^^^^^^^^^^^^^^^^^^^^^^^^

In the ``.stimpack`` virtual environment:

.. code-block:: console

    stimpack

A startup dialog opens, which looks like this (shown with a ``labpack`` configured; on a fresh
install the Labpack line reads "none — stimpack's built-in examples" and only the
default config is offered; the **None** button returns to that state at any time):

.. image:: /assets/labpack_query.png
    :width: 320px
    :align: center
    :alt: Stimpack config selection window

If you see this window, stimpack is installed. What to do with it is the next page,
:doc:`first_experiment`.

Installation issues
^^^^^^^^^^^^^^^^^^^^^^^
**X11 vs. Wayland**

Both work. Stimpack detects the session type at startup rather than assuming one: under Wayland it
creates an EGL context and hands it to ModernGL, and under X11 it uses GLX. It reports which it
chose when a screen is launched::

    Display session type: wayland
    QT platform type: default (unset)

(The second line reports the ``QT_QPA_PLATFORM`` override, which is normally unset.)

Pass ``Screen(use_egl=...)`` to override the choice.

(Older versions of stimpack did require X11, and some guides still say so. Since 0.2.0 they do not.)

**Multiple displays**

An X11 session with several X screens per display is supported, as are Windows and macOS. Which
physical display a screen appears on is set by ``display_index``; see
:class:`stimpack.visual_stim.screen.Screen`.

**Qt dependency issues**

If you run into errors on Ubuntu relating to your Qt installation, you can try to install some Qt libraries to see if that helps. See these resources:

https://askubuntu.com/questions/1485442/issue-with-installing-pyqt6-on-ubuntu-22-04

