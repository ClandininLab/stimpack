Labpack Server
================

This directory contains files for individual server configurations.
These servers run the stimpack framework in a rig-specific manner.

One script per rig, named by a config's ``rig_config.<rig>.server_options.local_server_path``.
``labpack-template`` ships ``server/example_server.py`` as the thing to copy.

A rig server is where hardware that only one rig has gets connected to stimpack. Two kinds of thing
live here:

**Rig geometry** -- the ``Screen`` and ``SubScreen`` objects describing the physical displays, in
metres, relative to the subject at the origin.

**Rig-specific functions**, registered with ``register_function_on_root(fn, 'name')`` and called
from a protocol as ``manager.target('root').name()``. A projector's LED current, a shutter, a valve.
Protocols should guard these with ``has_server_function()`` so that one protocol still runs on a rig
that does not have the hardware -- see :doc:`modules_and_targets`.

:doc:`subframes` is a worked example of the second kind, and the case where getting it wrong is
quiet: the projector and the renderer each hold half of one decision, and a rig server is where they
are kept in step.
