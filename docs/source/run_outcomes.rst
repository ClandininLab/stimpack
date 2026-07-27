===========================
Knowing how a run ended
===========================

Every series records how it finished, so a file can be filtered without remembering what happened
at the rig. On the ``series_00n`` group:

==========================  =================================================================
``run_status``              ``completed``, ``stopped``, ``aborted`` or ``error``
``abort_reason``            why, when it was not ``completed``
``num_epochs_completed``    how many epochs actually ran
``run_end_unix_time``       when it stopped
==========================  =================================================================

``stopped`` means someone pressed Stop. ``error`` means the server reported a problem and the
client ended the run. Both are written the same way a completed run is, so a partial series is
still a well-formed series -- it simply says so.

Errors from the server
======================

The link between client and server carries no return values, so a failure on the rig used to be
invisible to the client: the request was accepted and the run carried on. Errors are now pushed
back over the same connection, from the server's root node, from any module, and from the screen
subprocesses, which are two hops away. They are recorded on the client, shown in the GUI, and end
the run with ``run_status='error'``.

Repeated messages are collapsed, so a fault occurring every epoch reports once rather than filling
the log.

A dead connection is treated the same way. If the socket drops mid-run, the client notices at the
next epoch boundary and closes the series as ``aborted`` rather than continuing to send into
nothing.

Stopping a run
--------------

Stop ends the epoch in progress rather than waiting for it. An epoch's pre, stimulus and tail
intervals are :meth:`~stimpack.experiment.protocol.BaseProtocol.sleep` -- a wait that drains the
client's queue as it goes and returns early when asked -- so a run with long epochs stops when the
button is pressed, not when the epoch happens to end.

An error the server reports mid-epoch ends the wait the same way, so an aborting run does not sit
through the rest of a stimulus first.

A protocol that needs an uninterruptible wait can ask for one::

    self.sleep(duration, process_server_requests=False)

and one driven without a client -- the labpack checker does this -- falls back to a plain wait and
says so once.
