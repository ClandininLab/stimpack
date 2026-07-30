========================
Checking a labpack
========================

.. code-block:: console

    stimpack --check-labpack           # config keys and module paths; imports nothing
    stimpack --check-labpack --deep    # also imports each protocol and checks where its calls go

Returns non-zero if anything is reported as an error, so it can gate a script or CI.

Why
===

A labpack that names something stimpack can no longer find does not crash. The GUI opens, the
protocol list populates, Record works, and the experiment is simply wrong -- custom stimuli never
loaded, or a call routed nowhere. Every failure of this kind seen so far reduces to *a name that no
longer resolves*, and nothing checks names until the moment they are used, which is when an animal
is already on the rig.

Errors and warnings
===================

The distinction is about what happens next, not how serious something sounds:

**error**
    stimpack will not find what the config names, so a run will silently do the wrong thing.

**warning**
    something is absent or ignored, but the consequence is visible, or deliberate for this rig.

A projector covering only part of its screen, a preset directory that does not exist yet, a
protocol needing a driver this machine has no reason to have -- all warnings. A stimulus module
path that resolves nowhere is an error.

What it checks
==============

Tiers 1 and 2 import nothing, which is what lets them run on every GUI launch as well as on demand:

1. config keys stimpack no longer reads
2. every ``module_paths`` entry resolves on disk, and ``visual_stim`` directories look loadable

``--deep`` imports lab code and runs each protocol, so it is opt-in and never part of startup:

3. each protocol module imports, and each protocol constructs and produces an trial
4. every stimulus name an trial asks for resolves, as ``load_stim`` would resolve it
5. every call a protocol makes is addressed somewhere that exists

Tiers 4 and 5 run the protocol rather than reading it. Stimulus names and call sites are often
computed rather than literal, and the key ``name`` means four different things in stimpack's
parameter dictionaries -- stimuli, trajectories, distributions and DAQ channels all use it. Parsing
gets that wrong; running it does not.

At startup
==========

Tiers 1 and 2 run when a config is chosen. Errors raise a dialog; warnings go to the terminal.
Neither blocks: the person at the rig decides whether a finding matters, and a modal refusing to
open the GUI would be worse than the silent failure it replaces.
