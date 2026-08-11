=====================
Your first experiment
=====================

Run the experiment application itself, before writing any code. ``stimpack`` ships a handful of
example protocols, so this needs no labpack, no rig and no configuration -- a laptop is enough.

Launch it
=========

.. code-block:: console

    stimpack

(The command is installed by ``pip``; ``python -m stimpack.experiment.gui`` is the same thing.)

A startup dialog asks which configuration to use. With no labpack installed there is exactly one
choice, ``default``, already selected -- press **Enter**. Later, this dialog is where your lab's
own configs and rigs appear; the **Data format** dropdown chooses what the data file will be
(HDF5 or NWB), and ``default`` is fine for now.

Present a protocol
==================

The main window opens on the **Main** tab:

1. Set **Protocol** to ``DriftingSquareGrating``. The parameter fields below fill in from the
   protocol's own declarations -- run parameters (how many trials, the idle color between them)
   above, the stimulus's own parameters below.
2. Press **View**.

A stimulus window opens and a grating drifts, once per trial, with gray between trials. The small
flickering square in the corner is the photodiode synchronization signal, part of the standard
render path. **View** presents without recording anything; **Record** writes a data file, and stays
disabled until an experiment file and a subject exist -- its tooltip says which is missing. That
distinction is deliberate: checking a stimulus should not be a file you delete afterwards.

Try setting a parameter to a list -- ``angle: [0, 45, 90]`` -- and pressing View again: the value
now sweeps across trials, and the readout at the bottom shows each trial's draw. That one rule
(a list sweeps) is most of what a parameterized experiment needs.

The full tour of the window -- tabs, presets, ensembles, pause semantics, notes -- is
:doc:`the_gui`.

The other built-ins
===================

The example protocols form a progression, each adding one idea, and all of them run right here:

- ``DriftingSquareGrating``, ``MovingPatch`` -- classic parameterized stimuli; sweep anything.
- ``WanderingSpot`` -- a naturalistic, seeded trajectory; the same seed replays the same path.
- ``ReachTheGoal`` -- closed loop with your keyboard as the tracker, and the trial ends when you
  arrive. Instructions in :doc:`locomotion`.
- ``ChaseTheTower`` -- the goal in motion: chase it down. See :doc:`behavior_ended_trials`.
- ``LinearTrackWithTowers`` -- a full virtual-reality track.

The closed-loop ones are the thing to try before leaving this page. Tracking comes pre-checked
on them (``do_loco``, in the run parameters) -- just press View and drive with the arrow keys in
the KeyTrac window.

What you are looking at
=======================

Behind the window, ``stimpack`` started a **client** (the GUI, running the protocol and owning the
data file) and a **server** (owning the screens), talking over a socket. On a rig they are usually
different machines; here they are one. The example protocols live inside ``stimpack`` purely so
that this page works out of the box -- real protocols live in your lab's own :doc:`labpack
<install_labpack>`, which is the next step.

If instead you want to see how stimuli are made -- driving the stimulus server directly from a
script, no GUI -- that is :doc:`first_stimulus`.
