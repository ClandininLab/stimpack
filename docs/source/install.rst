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

On Windows the interpreter is usually ``py`` rather than ``python3``, and activation lives under
``Scripts``:

.. code-block:: console

    py -m venv .stimpack
    .stimpack\Scripts\activate

2. ``pip`` install stimpack 
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

In your virtual environment, install stimpack via ``pip`` (Python 3.10 or newer):

.. code-block:: console

    python3 -m pip install stimpack

**Audio is an optional extra.** Rigs that play sound install it as
``pip install "stimpack[audio]"``; everything else works without it, and audio calls on a rig
without it report warnings rather than playing. It needs PortAudio system-side -- see
`Installation issues`_ below before installing it on macOS.

**Installing from a checkout** (how rig machines usually run, so data files can record the git
revision that produced them):

.. code-block:: console

    git clone https://github.com/ClandininLab/stimpack.git
    cd stimpack
    python3 -m pip install -e ".[audio]"

The quotes keep shells like zsh from interpreting the brackets; extras combine, so developers
typically want ``-e ".[audio,test]"``. Leave ``[audio]`` off entirely for a silent rig.


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

**Audio: PyAudio needs PortAudio**

The ``[audio]`` extra installs PyAudio, which builds against the PortAudio library when no
prebuilt wheel matches your Python. The telltale failure is
``fatal error: 'portaudio.h' file not found``. Install PortAudio first:

.. code-block:: console

    brew install portaudio          # macOS
    sudo apt install portaudio19-dev   # Debian / Ubuntu

On Apple Silicon, Homebrew lives in ``/opt/homebrew`` and the compiler may not look there; point
it explicitly:

.. code-block:: console

    CFLAGS="-I$(brew --prefix)/include" LDFLAGS="-L$(brew --prefix)/lib" pip install "stimpack[audio]"

If you just want the rest of stimpack working now, install without the extra -- audio is optional
by design and can be added later.

**Windows**

Three things to know, none of them stimpack-specific:

- **PyAudio** ships prebuilt wheels for Windows on the Python versions it supports; if ``pip``
  starts *compiling* instead (a wall of C compiler output), your Python is newer than the wheels
  and the path of least resistance is a Python version that has them, rather than assembling a
  PortAudio build environment.
- **Remote Desktop has no real OpenGL.** An RDP session hands programs a software renderer far
  older than the OpenGL 3.3 stimpack's screens need, so screens that work at the machine fail
  over RDP. Administer rigs over a screen-sharing tool that mirrors the local session (VNC and
  the like), or launch stimpack from the console session.
- **The firewall will ask.** The server binds loopback by default, which needs no permission;
  a rig serving a remote client binds a real interface, and Windows Defender prompts to allow
  Python through on first launch -- decline it and the client's connection quietly times out.

**Qt dependency issues**

If you run into errors on Ubuntu relating to your Qt installation, you can try to install some Qt libraries to see if that helps. See these resources:

https://askubuntu.com/questions/1485442/issue-with-installing-pyqt6-on-ubuntu-22-04

