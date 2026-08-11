==================
Writing a module
==================

A new capability is a new module, not a change to stimpack. The three that ship -- ``visual``,
``locomotion``, ``voltage_out`` -- are ordinary Python objects held in a dictionary on the server
and reached by name, and yours is added the same way. This page is the contract.

If what you want is a new *stimulus*, or a new *tracker*, you do not need a module: stimuli are
loaded from a ``labpack``'s ``module_paths.visual_stim`` and trackers subclass ``LocoManager``. A module
is for a capability that is none of the existing three -- a sound card, a treadmill brake, a
temperature controller.

The contract
============

One method is required::

    class OdorManager:
        def handle_request_list(self, request_list):
            for request in request_list:
                if request['name'] in dir(self):
                    getattr(self, request['name'])(*request.get('args', []),
                                                   **request.get('kwargs', {}))

Requests arrive in batches, because a protocol builds a multicall and sends it in one round trip.
Everything else is optional, and each option buys something specific:

``get_callable_names()``
    The names this module answers to. The server sends them to the client when the connection
    opens, which is what makes ``has_server_function()`` able to answer. Implement it if you can
    enumerate your surface; **decline to implement it if you cannot**. The visual module forwards
    to screen subprocesses and so does not know its own surface, and it declines rather than
    answering wrongly -- callers are then told the answer is unknown, which is honest, instead of
    being told "no" about a function that exists.

``start()`` / ``close()``
    Called when the server starts and shuts down. Acquire and release the hardware here rather
    than in ``__init__``, so that constructing the server does not claim a device.

``on_connection_close()``
    Called when a client disconnects. Use it to stop anything that should not outlive the session
    -- a running waveform, an open valve.

``set_save_directory(path)``
    Called with the current experiment's directory if your module writes its own files alongside
    the data file, as a tracker does with its position log.

``error_reporter``
    Set on your module by the server. Call ``self.error_reporter('error', message)`` and the
    message reaches the client, is shown in the GUI, and aborts the run; ``'warning'`` reports
    without aborting. An exception you let escape ``handle_request_list`` is caught and reported
    for you, but a *silent* failure is not, so report the ones you can detect.

Registering it
==============

Modules are held in ``BaseServer.modules``, keyed by the name protocols will target. Subclass the
server in your ``labpack``'s rig script and add yours::

    from stimpack.experiment import server

    class OdorServer(server.BaseServer):
        def __init__(self, odor_kwargs={}, **kwargs):
            super().__init__(**kwargs)
            self.modules['odor'] = OdorManager(**odor_kwargs)
            self.modules['odor'].error_reporter = self.report_to_client

Assign ``error_reporter`` yourself: the base class wires it for the modules it built, and yours
arrives after that has run. From a protocol the module is then addressed like any other::

    multicall.target('odor').open_valve(channel=2, duration=0.5)

Three conventions worth following
=================================

**Advertise, so protocols can adapt.** A rig without your hardware should degrade rather than
fail. With ``get_callable_names()`` implemented, a protocol can ask before it calls::

    if self.has_server_function('open_valve', target='odor'):
        multicall.target('odor').open_valve(channel=2, duration=0.5)

A request to a module the server does not have is a warning, not an error, and the run continues --
the server cannot tell "this rig has no odor delivery" from "odor was expected here", and only
the protocol knows which it is.

**Ship a software stand-in.** ``keytrac`` is a keyboard that produces the same subject state a real
tracker would, which is what lets closed-loop protocols be written and tested on a laptop. The
equivalent for your module -- a class that accepts every call and does nothing but log -- means
protocols using it can be developed away from the rig, and means the module has something to be
tested against in CI.

**Name it for what it does: a *Server* serves sockets, a *Manager* owns hardware.** Stimpack's own
modules follow this line. ``VisualStimServer`` is named for a real serving role -- every screen is
a subprocess it talks to over a socket, and it runs standalone as the stim server -- while
``LocoClosedLoopManager`` (and the ``OdorManager`` above) own a device or process on the server's
behalf and serve nothing. Most new modules are managers, and owning *more* hardware does not change
that: a manager driving four output streams is still a manager. The name changes only when the
thing starts serving sockets, as it would if each device someday needed its own subprocess.

What you do not have to build
=============================

The batching, the socket, the routing by target, the error path back to the client, the ``labpack``
loading mechanism, the trial structure and the data file are all the framework's, and apply to your
module unchanged the moment it is registered. What you write is the object that talks to your
hardware.

.. note::

   Calls are one-way. ``handle_request_list`` returns nothing to the caller, so a module cannot be
   *queried* -- there is no ``get_temperature()`` that returns a temperature. To get information
   back, push it with ``error_reporter`` (as ``report_frame_count`` does) or write it to a file the
   analysis reads. See :doc:`modules_and_targets`.
