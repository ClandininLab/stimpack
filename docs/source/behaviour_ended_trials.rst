==============================================
Trials that end when the animal does something
==============================================

Most protocols set a stimulus duration and every trial lasts that long. Some experiments need the
opposite: the trial ends when the animal fixates long enough, reaches a virtual goal, makes a
choice, or stops walking. This page is about how stimpack supports that, and about the one thing
it changes in your data.

Why it has to work this way
===========================

The obvious approach -- have the protocol watch the animal and stop when it likes -- cannot work,
for two reasons that are worth stating plainly because they are not obvious from the outside:

**The client never sees subject state.** Position updates from a tracker go to the server, which
fans them out to its own modules (``target('all').set_subject_state``). Nothing sends them to the
client, where the protocol runs.

**The client could not ask, either.** Requests are one-way and carry no reply
(:doc:`overview`), so there is no "where is the animal?" call to make. This is not an oversight
that could be patched around in a protocol; it is what the transport is.

So the condition has to be evaluated on the server, next to the data, and the server has to tell
the client. That is what :meth:`~stimpack.experiment.server.BaseServer.end_epoch` does.

Where your condition runs
=========================

A labpack supplies a **server-side closed-loop function**, which stimpack calls on every subject
state update -- that is, at whatever rate the tracker reports, not once per frame or once per
epoch. It is defined on the protocol class and loaded onto the server when the run starts:

.. code-block:: python

    class GoalDirected(BaseProtocol):
        def __init__(self, cfg):
            super().__init__(cfg)
            self.use_server_side_state_dependent_control = True   # load it onto the server

        @staticmethod
        def server_side_state_dependent_control(server, subject_state, state_update):
            # runs ON THE SERVER, on every tracker update
            x = state_update.get('x', subject_state.get('x', 0))
            if x > 0.5:
                server.end_epoch(reason='reached_goal')
            return state_update

The function's usual job is to modify the state update -- that is the closed-loop part -- and it
must return one. Ending the epoch is an extra thing it may do along the way.

.. important::

    Mind which of the two arguments you test.

    ``state_update``
        what the tracker has just reported -- only the keys that changed.

    ``subject_state``
        the accumulated state **as it was before this update**. The function runs *before* the
        update is applied, so reading a value here gives you the previous one.

    A condition written against ``subject_state`` alone therefore fires one update late, and if
    the animal crosses your threshold and the run ends on that same update, it never fires at
    all. Read the update first and fall back to the accumulated state, as above.

It runs in the server process, so it can only use what is there: the ``server`` object, the
accumulated ``subject_state``, and whatever the labpack imports. It cannot see the protocol
object, which lives on the client.

What happens next
=================

``end_epoch()`` sends the client a request to cut short the epoch in progress. The client's
current wait -- the pre, stimulus or tail interval, which are interruptible
(:doc:`run_outcomes`) -- returns immediately, and the epoch ends as if its timer had elapsed.

**The run continues.** The next epoch starts normally. To stop the whole run instead, report an
error, which aborts it and records why.

Ending an epoch is not instantaneous: the request travels over the socket and is acted on when the
client next polls, every couple of milliseconds. That is well inside a frame, but it is not a
hardware trigger. If your experiment needs the *stimulus* to change within a frame of the animal's
behaviour, do that on the server too, in the same function, by driving the stimulus directly --
``end_epoch`` is for ending the trial, not for closing a fast visual loop.

What this does to your data
===========================

Once trials end on behaviour, the protocol's ``stim_time`` describes what you asked for, not what
happened. Analysis that assumes every trial is the same length will be quietly wrong.

stimpack therefore records, per epoch:

``epoch_duration``
    how long it actually lasted, in seconds (HDF5). The NWB trials table carries start and stop
    times, so the duration is there by construction.

``ended_early``
    ``True`` if it was cut short, ``False`` if it ran its full length.

``epoch_end_reason``
    the string passed to ``end_epoch``, present only when it ended early.

Set a meaningful ``reason``. It costs nothing and it is the difference between "this trial was
1.4 s" and "this trial was 1.4 s because the animal reached the goal", which is usually the thing
you want to condition the analysis on.

Late requests
=============

A criterion met just as an epoch was ending would, naively, arrive during the *next* epoch and cut
that one short too -- a truncated trial with nothing in the data to explain it.

To prevent that, the client tells the server which epoch it is running, the server stamps each
request with it, and the client ignores a request for an epoch that has already ended. Between
epochs the server has nothing to end and ``end_epoch()`` does nothing at all.

This is handled for you. It matters only if you are writing something that calls ``end_epoch``
from outside the closed-loop function, where you may be further from the epoch boundary than you
think.

A worked example
================

Ending a trial once the animal has held its heading within 10 degrees for half a second:

.. code-block:: python

    class Fixation(BaseProtocol):
        def __init__(self, cfg):
            super().__init__(cfg)
            self.use_server_side_state_dependent_control = True

        @staticmethod
        def server_side_state_dependent_control(server, subject_state, state_update):
            # state persists on the server between updates; keep the counter there
            held = getattr(server, '_fixation_held_since', None)
            theta = state_update.get('theta', subject_state.get('theta', 0))
            on_target = abs(theta) < 10

            if not on_target:
                server._fixation_held_since = None
            elif held is None:
                server._fixation_held_since = time.time()
            elif time.time() - held > 0.5:
                server._fixation_held_since = None
                server.end_epoch(reason='fixated')

            return state_update

Note where the timer lives. The function is called fresh each update and keeps nothing of its own,
so per-trial state goes on the ``server`` object -- and wants clearing when the criterion is met,
or the next trial inherits it.

.. warning::

    Name any state you park on the server with a **leading underscore**, as above.

    The server turns unknown attributes into remote calls, so ``getattr(server, 'held_since',
    None)`` does not return ``None`` when the attribute is missing -- it returns a callable stub,
    which is truthy, and your condition silently never fires. Underscore-prefixed names are
    excluded from that mechanism and behave like ordinary attributes.

.. note::

    Because this runs per tracker update, keep it cheap. Anything slow here delays the state
    update reaching the screens, which is the closed-loop path the animal is actually in.
