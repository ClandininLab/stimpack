=====================
Modules and targeting
=====================

The server holds a set of modules, and every request names one:

===============  ==============================================================================
``visual``       the screens
``locomotion``   the tracker (FicTrac, KeyTrac, ...)
``voltage_out``  anything driven by an output voltage
``all``          every module; each takes the calls it knows and ignores the rest
``root``         the server itself
===============  ==============================================================================

``voltage_out`` rather than ``daq``
===================================

The module is named for the capability, not the device. Optogenetics, odour delivery, liquid
reward and shock are all a voltage appearing on a channel; which of them a given rig does is a fact
about its wiring, not about stimpack. ``target('daq')`` still works and maps to ``voltage_out``,
warning once per session.

Untargeted calls go to root
===========================

.. warning::

   ``manager.some_function(...)`` with no ``target`` is delivered to the server's **root node**,
   not broadcast. Root has only a handful of functions, so an untargeted call meant for a module
   lands nowhere -- and, because the link is one-way, nothing at the calling end notices.

   This is not hypothetical: it is how a set of protocols stopped delivering optogenetic stimulation
   for months while everything else looked normal. ``stimpack --check-labpack --deep`` reports it.

One protocol, several rigs
==========================

Rigs differ, and a protocol that assumes hardware will fail on the rig that lacks it. The server
tells the client which modules it has when the connection opens, so a protocol can ask::

    if self.has_module('voltage_out') and self.epoch_protocol_parameters['opto_amp'] > 0:
        multicall.target('voltage_out').setup_pulse_wave_stream_out(
            channels_config={'name': 'DAC0', 'high': amp, 'low': 0.0},
            frequency_hz=50, pulse_width_s=0.01)

``has_module()`` returns ``True`` when the server has not advertised anything -- an older stimpack,
say -- so adopting it changes nothing until there is something to report.

A request addressed to a module the server does not have is reported as a **warning**, not an error,
and the run continues. The server cannot tell "this rig has no opto" from "opto was expected here",
and only the protocol knows which it is.

Functions on the root node follow the same rule, with one distinction that matters:

``target('root').some_function()``
    The caller said where they were aiming, and this rig has not registered that function --
    a **warning**, and the run continues. Labs register rig-specific functions on root (a
    projector's LED current, a shutter), and a protocol written for one rig should degrade on
    another rather than refuse to run.

``some_function()``, untargeted
    Root was the default rather than the choice, and nothing was found there. That is an
    **error**, and it aborts the run: the call was meant for something and reached nothing.
    If you meant a module, use ``target('all')`` or name it.

Asking what a rig can do
------------------------

``has_module()`` answers for hardware categories. For the functions a lab registers on its own rig
servers -- a projector's LED current, a shutter, a valve -- use ``has_server_function()``:

.. code-block:: python

    if self.has_server_function('set_dlpc_current'):
        manager.target('root').set_dlpc_current(*self.run_parameters['dlpc_current_start'])

It defaults to the ``root`` target, matching an untargeted call. Pass ``target=`` to ask about a
module instead:

.. code-block:: python

    if self.has_server_function('set_value', target='voltage_out'):
        manager.target('voltage_out').set_value(output_channels='FIO6', value=1)

Both return ``True`` when the answer is not known, so adopting either changes nothing until there
is something real to report. "Unknown" means an older stimpack that advertises nothing, or a target
that cannot enumerate itself -- a module can make itself enumerable by implementing
``get_callable_names()``. All three built-in targets do:

``root``
    the functions registered with ``register_function_on_root``, which is where a lab puts its
    rig-specific ones

``voltage_out``, ``locomotion``
    their public attributes, since they dispatch on exactly those -- so a labpack's own DAQ
    subclass is covered without doing anything

``visual``
    the names each screen registers, taken from ``framework.SCREEN_FUNCTION_NAMES``, plus the
    server's own. The parent process cannot query a screen subprocess, but it does not need to:
    what a screen registers is fixed in stimpack's source.

.. note::

    This is a snapshot taken when the client connects, not a live query -- calls are one-way, so
    there is nothing to ask over. A function registered after a client connected is not in that
    client's snapshot until it reconnects. Register rig-specific functions before ``server.loop()``
    and this never arises.

Skipping the call is optional -- a function the rig does not have is reported as a warning and the
run continues -- but it keeps the log clean and makes the intent explicit.
