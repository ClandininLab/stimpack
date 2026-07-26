==============
Under the Hood
==============

``stimpack``'s functionality is broken into modules.

- ``visual_stim``: generating and displaying visual stimuli
- ``rpc``: communication between processes
- ``experiment``: running experiments -- protocols, data files, the GUI
- ``device``: interfaces for hardware, kept abstract

Where the boundary sits
=======================

``stimpack`` contains no hardware-specific code. ``device.daq`` is abstractions over the RPC link;
``device.locomotion.keytrac`` is a keyboard application standing in for a tracker so that closed
loop can be exercised without one. Drivers for particular parts -- a NI card, a LabJack, a DLPC350
projector -- live in a labpack, alongside the protocols and rig geometry that are equally specific
to one lab. See :doc:`install_labpack`.

The consequence worth knowing is that stimpack loads a labpack's modules **by file path at
runtime**, from the paths named in a config's ``module_paths``. Nothing is imported by package name,
so a labpack may be called whatever a lab likes -- and a path that no longer resolves fails
silently, which is what :doc:`check_labpack` exists to catch.

Rendering
=========

Each screen is a subprocess with its own GL context. A stimulus is drawn once per subscreen through
an off-axis (Kooima) perspective matrix, computed from the physical corners of that subscreen in
metres and the subject's position and heading. The corner square is drawn last, in projector
coordinates, as a photodiode timing signal.

``paintGL`` is what drains the RPC queue, so a screen whose render loop has stopped accepts every
command and does nothing. ``report_frame_count`` asks a screen how many frames it has actually
drawn, which is the way to tell those two states apart from the client.
