==============
Under the Hood
==============

``stimpack``'s functionality is broken into modules.

- ``visual_stim``: generating and displaying visual stimuli
- ``rpc``: communication between processes
- ``experiment``: running experiments -- protocols, data files, the GUI
- ``device``: interfaces for hardware, kept abstract

.. toctree::
    :maxdepth: 1

    subframes

Where the boundary sits
=======================

``stimpack`` contains no hardware-specific code. ``device.daq`` is abstractions over the RPC link;
``device.locomotion.keytrac`` is a keyboard application standing in for a tracker so that closed
loop can be exercised without one. Drivers for particular parts -- a NI card, a LabJack, a DLPC350
projector -- live in a ``labpack``, alongside the protocols and rig geometry that are equally specific
to one lab. See :doc:`install_labpack`.

The consequence worth knowing is that stimpack loads a ``labpack``'s modules **by file path at
runtime**, from the paths named in a config's ``module_paths``. Nothing is imported by package name,
so a ``labpack`` may be called whatever a lab likes -- and a path that no longer resolves fails
silently, which is what :doc:`check_labpack` exists to catch.

Rendering
=========

Each screen is a subprocess with its own GL context. There are **two rendering paths**, chosen by
the type of the screen, and a rig may mix them -- one screen of each, in the same process.

.. figure:: /images/client_server_framework.png
    :width: 90%
    :align: center
    :alt: Client, RPC, server, and per-screen internals

    One client, one server, N screen subprocesses. Inside each screen, ``framework.py``'s render
    loop evaluates the stimulus at each frame's draw time (``stimuli.py``), which draws through
    the GL layer (``base.py``).

**Flat screens: one off-axis frustum per subscreen.** A ``Screen`` is described by its subscreens'
physical corners in meters -- ``pa`` lower-left, ``pb`` lower-right, ``pc`` upper-left -- and each
stimulus is drawn once per subscreen through a generalized (off-axis) perspective matrix computed
from those corners and the subject's position and heading. This is Kooima's construction, and it is
what makes an object subtend the angle it should from where the animal actually sits, on a screen
that is neither square to the animal nor equidistant from it. Nothing is resampled: the stimulus is
rasterized straight into the window.

**Curved screens: a cube map, then one warp.** A flat frustum cannot describe a bowl, so a
``CurvedScreen`` renders in two passes. The scene is drawn into the faces of a cube map from the
subject's position, and then the screen's mesh is drawn **once**, in projector coordinates, with
each fragment sampling the cube along its own interpolated direction. The mesh comes from
``build_screen_mesh(surface, projector)`` and carries, per vertex, both where that point of the
screen lands in the projector's image and which direction it lies in from the animal -- which is the
whole of the warp.

.. figure:: /images/pipeline.png
    :align: center
    :alt: A rig schematic with photodiode, the warped frame with its corner square, the subject's view of the checkerboard, and a photodiode trace with two dropped frames

    The visual path, end to end. (a) The rig: a projector lights a bowl-shaped screen around the
    subject, and a photodiode watches the corner of the thrown frame. (b) The frame sent to the
    projector, rendered once into a cube map centered on the subject and warped by the bowl's
    geometry, with the synchronization square in that corner. (c) The subject's visual field over
    the same cube map: the checkerboard's patches subtend 10 degrees in the subject's own angular
    coordinates. (d) Frame delivery at the photodiode: nominal inversions every 8.3 ms
    (120.5 Hz), and two dropped frames, one held bright and one held dark, each a level held for
    16.6--16.7 ms.

The cost structures are different, and it is worth knowing which you are paying:

.. list-table::
   :header-rows: 1
   :widths: 22 39 39

   * -
     - flat
     - curved
   * - draws per frame
     - stimuli x subscreens
     - stimuli x cube faces, plus one warp
   * - screen tessellation
     - not applicable
     - free -- one draw call at any density
   * - what it costs to add screen detail
     - another frustum, so another full pass
     - nothing
   * - resampling
     - none
     - one intermediate, sized by ``cube_resolution``

So the curved path deliberately trades an intermediate for a cost that does not multiply: the screen
may have 200 triangles or 20,000 for the same price, where giving each facet its own frustum would
multiply scene complexity by screen complexity. Measured on a 7.7 cm bowl at 1536-pixel faces, the
warp pass is about 0.28 ms of an 8.33 ms frame, and a hundredfold increase in mesh density moves it
by under a tenth of a millisecond. The scene draws dominate, which is why the renderer draws only
the faces the mesh actually samples -- and why ``cube_orientation`` reduces that count further by
turning the cube to suit the screen, which it does by default (see
``docs/design/cube-orientation.md``).

The corner square is drawn last on either path, in projector coordinates, as a photodiode timing
signal: it inverts on every rendered frame -- under :doc:`subframe multiplexing <subframes>`, on
every subframe -- so a photodiode over it produces a square wave at half the frame rate, and a
dropped frame appears as one level held for two frame intervals. Digitized by the acquisition
system on the same clock as the neural recording, frame delivery is measured *after* the whole
graphics stack, so stimulus onsets and dropped frames are recoverable from the acquisition data
alone. Panel (d) of the pipeline figure above shows exactly this: nominal inversions at the
frame rate, and a dropped frame of each phase, each a level held for two frame intervals.

``paintGL`` is what drains the RPC queue, so a screen whose render loop has stopped accepts every
command and does nothing. ``report_frame_count`` asks a screen how many frames it has actually
drawn, which is the way to tell those two states apart from the client.

A frame can carry more than one timepoint. With a projector that reads a frame's color channels as
successive patterns, ``stimpack`` draws up to three timepoints per frame and masks each into one
channel -- a 120 Hz video link driving a 360 Hz monochrome display. The renderer's half is here; the
projector's half is a ``labpack``'s. See :doc:`subframes`.
