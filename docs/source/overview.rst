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

The **client** runs the protocol: it decides what each epoch contains and writes the data file. The
**server** owns the hardware, and usually runs on the rig machine while the client runs wherever the
experimenter is sitting. Each **screen** is its own subprocess with its own GL context, so one
display stalling cannot stall another.

They talk over a small JSON protocol. Calls are addressed to a module::

    manager.target('visual').load_stim(name='MovingPatch', width=10, height=30)
    manager.target('voltage_out').output_step(output_channels='DAC0', pre_time=0, step_time=1)

Two things follow from that design and are worth knowing early.

**Calls are one-way.** A request that names something the server does not have is accepted, sent,
and dropped -- there is no return value to notice its absence. The server pushes errors back over
the same link so they reach the GUI and abort the run, and :doc:`check_labpack` finds the rest
before an experiment rather than during one.

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
