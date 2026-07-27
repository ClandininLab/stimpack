======================
Your first stimulus
======================

This walks through presenting a stimulus from a Python script, without the GUI and without a rig.
Everything here runs on a laptop.

The scripts shown are in the repository's ``examples/`` directory, and each one runs as-is.

A window, and something in it
=============================

``examples/1-hello_world.py``:

.. code-block:: python

    from stimpack.visual_stim.stim_server import launch_stim_server
    from stimpack.visual_stim.screen import Screen
    from time import sleep

    screen = Screen(fullscreen=False, vsync=True)
    manager = launch_stim_server(screen)
    sleep(2)                                  # give the screen subprocess time to come up

    manager.set_idle_background(0.5)          # mid-grey between stimuli

    for i in range(5):
        manager.load_stim(name='Checkerboard')
        sleep(1.5)                            # pre time
        manager.start_stim()
        sleep(2)                              # stimulus time
        sleep(0.5)                            # tail time
        manager.stop_stim(print_profile=True)

Run it::

    python examples/1-hello_world.py

A window opens and a checkerboard appears five times. On exit, ``print_profile=True`` prints the
frame-time distribution for the epoch, which is the first thing to look at when timing matters.

What just happened
==================

``launch_stim_server`` started a **separate process** that owns the window and its OpenGL context,
and returned a handle to it. Every ``manager.`` call is a message sent to that process over a
socket.

Two consequences follow, and they are worth absorbing early because neither announces itself:

**Calls do not return anything.** ``load_stim`` does not report success, and a call naming a
stimulus that does not exist is accepted, sent, and dropped. The server pushes errors back over the
same connection, which is how they reach the GUI, but a script like the one above will not notice.

**The screen draws on its own clock.** ``start_stim`` tells the screen to begin; the script then
sleeps while the screen renders. The two are not in lockstep. ``stop_stim(print_profile=True)`` is
how you find out what the screen actually did.

Describing a real screen
========================

``Screen(fullscreen=False)`` is fine for a laptop, but on a rig the geometry matters: stimpack
corrects perspective for a subject at a known position relative to a display of known size and
placement. That is what a :class:`~stimpack.visual_stim.screen.SubScreen` describes -- three
physical corners, in metres.

``examples/2-custom_screen_server.py``:

.. code-block:: python

    from stimpack.visual_stim.screen import Screen, SubScreen

    subscreen = SubScreen(pa=(-1, 1, -1),      # lower left corner,  metres
                          pb=( 1, 1, -1),      # lower right corner
                          pc=(-1, 1,  1),      # upper left corner
                          viewport_ll=(-1, -1),
                          viewport_width=2,
                          viewport_height=2)

    screen = Screen(subscreens=[subscreen], display_index=0, fullscreen=True, vsync=True)

The three corners give the display's size, position and orientation relative to the subject, who
sits at the origin looking along **+y**. The viewport says which part of the display device that
rectangle occupies, so several subscreens can share one physical display.

Measuring those corners accurately is the single thing that determines whether the geometry on
screen is correct. See :doc:`under_the_hood` for what is done with them.

.. figure:: /assets/display_coordinates.png
    :width: 500px
    :align: center

    Screen corners, in stimpack's coordinates.

More than one screen
====================

``examples/3-multiple_screens.py`` launches several. Each becomes its own subprocess with its own
GL context, so one display stalling cannot stall another, and a stimulus is drawn once per
subscreen through that subscreen's own perspective matrix.

Stimuli of your own
===================

A stimulus is a class with a ``configure`` method that builds geometry and an ``eval_at`` method
that updates it for a given time. Custom stimuli live in a directory containing a ``stimuli.py``,
which is handed to the server after it starts:

.. code-block:: python

    manager = launch_stim_server(screen)
    sleep(2)
    manager.import_stim_module('./example_custom_module/')

    # ShowImage is defined in that directory's stimuli.py
    manager.load_stim(name='ShowImage', image_path='./assets/cactus.png',
                      vertical_extent=30, horizontal_extent=30)

(The equivalent at launch time is ``launch_stim_server(screen,
other_stim_module_paths=[...])``, which is what a labpack's config drives.)

``examples/4-custom_stimuli.py`` and ``examples/example_custom_module/`` are a working pair. See
:class:`stimpack.visual_stim.base.BaseProgram` for what a stimulus must implement, and
:mod:`stimpack.visual_stim.shapes` for the geometry primitives to build it from.

In a real experiment, custom stimuli live in a labpack rather than in a directory beside the
script, and are named in a config file -- see :doc:`install_labpack`.

Where to go next
================

* :doc:`overview` -- how the client, server and screens fit together
* :doc:`install_labpack` -- setting up a lab's own protocols, configs and rig geometry
* :doc:`modules_and_targets` -- addressing the visual, locomotion and voltage-out modules
* :doc:`under_the_hood` -- perspective correction, and what ``paintGL`` is responsible for
