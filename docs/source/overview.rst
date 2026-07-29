========
Overview
========

``stimpack`` presents stimuli to an animal and records what it did, with the timing precise enough
that the two can be lined up afterwards.

An experiment runs as several processes:

.. code-block:: text

    ExperimentGUI ── BaseClient ──socket── BaseServer ──┬── visual      ── screen subprocess (GL)
                                                        ├── locomotion  ── tracker subprocess
                                                        └── voltage_out ── DAQ

The **client** runs the protocol: it decides what each trial contains and writes the data file. The
**server** owns the hardware, and usually runs on the rig machine while the client runs wherever the
experimenter is sitting. Each **screen** is its own subprocess with its own GL context, so one
display stalling cannot stall another.

They talk over a small JSON protocol. Calls are addressed to a module::

    manager.target('visual').load_stim(name='MovingPatch', width=10, height=30)
    manager.target('voltage_out').output_step(output_channels='DAC0', pre_time=0, step_time=1)

Trials and series
=================

A **trial** is one stimulus presentation. A **series** is a run of them under one protocol, and is
what the Record button produces: one series, numbered, with its parameters and outcome recorded
alongside.

You *run* a protocol; each recorded run is a series. A View run is a run with no series -- trials
are presented, nothing is written, and no series number is used. That is the whole of the
difference between the two words, and why ``run_parameters`` (``num_trials``, ``idle_color``) is
not called ``series_parameters``: those settings govern a View run too, which never becomes a
series.

Two kinds of parameter go into a run, and which one a setting belongs to decides who reads it:

**Run parameters** are read by stimpack itself and are fixed for the whole run -- ``num_trials``
drives the loop, ``do_loco`` starts the tracker, ``randomize_order`` shapes the sequence.
``num_trials`` and ``idle_color`` are required; the rest have defaults.

**Protocol parameters** are the stimulus, and stimpack never reads one by name. It only sequences
them and hands the protocol one value per trial. Give one a list of more than one value and it
sweeps across trials -- ``angle: [0, 45, 90]`` presents three angles in turn -- which is the one
place that rule applies. A run parameter given a list is just a list.

So a new setting is a run parameter if stimpack has to understand it, and a protocol parameter if
only your protocol does.

Before 0.3 stimpack called these an *epoch* and an *epoch run*. Its NWB files never did -- NWB
calls a presentation a trial -- so the same thing had two names depending on where you looked.
Code written for the old names still works: ``get_epoch_parameters``, ``num_epochs`` and the rest
are accepted, each warning once and naming its replacement. ``stimpack --check-labpack`` lists the
ones a labpack still uses, and :doc:`labpack_configs` covers reading data files written either way.

Two things follow from that design and are worth knowing early.

**Calls are one-way.** There is no return value to branch on, and attribute access alone never
fails -- a mistyped name still produces a callable. The failure is not silent, though: the server
pushes messages back over the same link. What can only be a mistake (an untargeted call finding
nothing on the root node, a name a module does not define) is reported as an **error** and aborts
the run; what legitimately differs between rigs (a module this server has no hardware for, a
rig-specific function on root) is a **warning**, so one protocol can run across rigs. Broadcasts --
``target('all')`` -- are the deliberate exception: every module receives them and acts only on the
names it defines, so an unknown name there stays quiet. Use ``has_server_function()`` to check
before calling; see :doc:`modules_and_targets`. :doc:`check_labpack` finds the rest before an
experiment rather than during one.

**An untargeted call goes to the server's root node**, not to every module. ``manager.load_stim(...)``
without a ``target`` will not reach the screens.

What is lab-specific -- protocols, stimuli, rig geometry, device drivers -- lives outside stimpack,
in a *labpack* that stimpack loads at runtime. See :doc:`install_labpack`.

.. toctree::
    :maxdepth: 1

    check_labpack
    modules_and_targets
    run_outcomes
    behaviour_ended_trials
