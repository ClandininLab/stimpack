====================================
Locomotion: closing the loop
====================================

The ``locomotion`` module owns a movement tracker. It reads positions from the tracker and forwards
them to the server as **subject state**, which every module follows -- so the visual scene turns as
the animal turns, at whatever rate the tracker reports, without a round trip through the client.
The tracker itself is hardware, so the driver lives in your ``labpack``; stimpack ships the base
classes and one tracker that needs no hardware at all.

Try it with no hardware
=======================

The GUI's built-in local server already runs **KeyTrac**, a keyboard standing in for a tracker.
From :doc:`first_experiment`'s setup: select a closed-loop protocol -- ``ReachTheGoal`` and its
siblings arrive with ``do_loco`` already checked; on other protocols, tick it -- and press
**View**. A small KeyTrac window opens alongside the stimulus; with it focused, the arrow
keys walk the subject through the scene (rotation and translation), and ``y``/``h``, ``u``/``j``
carry the remaining axes. This is the whole closed-loop path -- tracker to subject state to
re-rendered scene -- with your keyboard as the animal, which is also how closed-loop protocols are
developed and tested before they meet a rig.

``do_loco`` appears in the run parameters only when the rig config says
``loco_available: True``, which is the default; a rig with no tracker sets it ``False`` and the
checkbox disappears rather than offering a thing that cannot work.

What a protocol does, and what it gets for free
===============================================

:meth:`~stimpack.experiment.protocol.BaseProtocol.start_stimuli` already makes every locomotion
call an ordinary trial needs, gated on two parameters:

``do_loco`` (run parameter)
    Tracking is on for this run. At each trial's start the subject position is re-zeroed to the
    tracker's current reading (``set_pos_0``), so trials start from a common origin however far
    the animal wandered between them.

``loco_pos_closed_loop`` (trial/protocol parameter)
    The scene follows the animal within the trial: ``loop_start_closed_loop`` at stimulus onset,
    ``loop_stop_closed_loop`` at its end. Without it, tracking is recorded but the stimulus plays
    open loop.

When a run is **recorded** and closed loop is on, the position history for each trial is saved
alongside the data file, one file per trial, so the animal's trajectory arrives with the stimulus
parameters that produced it. Two different modules do the writing, for two different records: each
**screen** logs the subject state it rendered from (``save_pos_history_to_file`` is a screen
function -- the history of what the animal *saw*), and the locomotion manager can log the raw
tracker lines (``write_log`` on ``set_pos_0`` -- what the tracker *said*).

A protocol that needs more than this -- ending a trial when the animal reaches a goal, holding a
stimulus against fixation -- supplies a server-side control function, which runs on every tracker
update with the full subject state. That is its own page: :doc:`behavior_ended_trials`.

Wiring a real tracker
=====================

A tracker driver is a :class:`~stimpack.locomotion.LocoClosedLoopManager`
subclass in your ``labpack``, passed to the rig server:

.. code-block:: python

    from your_labpack.device.locomotion.loco_managers.fictrac_managers import FtClosedLoopManager

    server = BaseServer(visual_stim_kwargs=visual_stim_kwargs,
                        loco_class=FtClosedLoopManager,
                        loco_kwargs={'host': '127.0.0.1', 'port': 33334,
                                     'ft_bin':    '/path/to/fictrac',
                                     'ft_config': '/path/to/config.txt'},
                        daq_class=..., daq_kwargs=...)
    server.loop()

The instance becomes the server's ``locomotion`` module. Leave ``loco_class=None`` and the module
does not exist: ``locomotion`` calls on that rig are reported as warnings and the run continues,
which is what lets one protocol serve rigs with and without tracking.

**FicTrac** [#fictrac]_, the spherical-treadmill tracker most of our rigs use, ships in the
``labpack`` template as a worked example:
``template_labpack/device/locomotion/loco_managers/fictrac_managers.py``. It launches the FicTrac
binary, reads its output stream, and maps the columns FicTrac reports into subject state. Copy and
adapt it -- the column indices and socket settings at the top of that file are the parts a
different FicTrac configuration changes. It is in the template rather than in stimpack
deliberately: stimpack contains no hardware-specific code, and a tracker binary's output format is
exactly that.

A tracker stimpack has never heard of needs only the base-class contract: read your device,
convert each reading to a position update, and hand it to
``update_pos``/``set_subject_state`` -- the base class carries the socket loop, the request
dispatch and the raw tracker log. :doc:`writing_a_module` covers the general shape; the KeyTrac
manager (``stimpack/locomotion/keytrac/managers.py``) is the smallest real
example.

Where the data goes
===================

Every position update fans out to **all modules** as subject state -- the visual module re-renders
from the new position, and any module of yours sees the same update. State keys beyond position
(anything your tracker or protocol adds) travel the same way, which is what server-side control
functions read. The flow, end to end::

    tracker -> LocoClosedLoopManager -> server.set_subject_state -> every module
                                                 |
                                                 v
                              server-side control function (optional)

Two properties follow, both worth knowing before designing an experiment around them. The client
never sees any of this -- requests are one-way, so a protocol cannot ask where the animal is
(:doc:`overview`), and conditions on position must run server-side. And the scene follows at
*tracker* rate, not frame rate: a 200 Hz tracker updates subject state 200 times a second, and each
frame renders from the latest state at draw time.

.. [#fictrac] Moore et al. (2014), *FicTrac: a visual method for tracking spherical motion and
   generating fictive animal paths*, J. Neurosci. Methods.
