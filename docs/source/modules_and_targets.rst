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
