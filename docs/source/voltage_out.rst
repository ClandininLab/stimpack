==============================
Voltage output: driving a DAQ
==============================

The ``voltage_out`` module is the server's channel to a DAQ -- anything that turns a request into a
voltage on a wire. Optogenetic LEDs, odor valves, reward pumps, shock grids and the TTL line that
starts a two-photon acquisition are, from stimpack's side, the same act: a voltage appears on a
channel. What the voltage *means* is a fact about your rig's wiring, which is why the module is
named for the capability rather than the device (:doc:`modules_and_targets`).

What stimpack ships, and what your ``labpack`` defines
======================================================

Stimpack ships ``stimpack.daq.DAQ``, and it is deliberately close to empty:

**The module plumbing.** ``handle_request_list`` dispatches each request to the public method of
the same name, so any public method of your subclass is callable from a protocol with
``target('voltage_out')`` -- no registration step. An exception in a handler is caught, reported
back to the client and aborts the run; so is a name your driver does not define, except in a
``target('all')`` broadcast, which every module receives and quietly skips the names it lacks.
``get_callable_names()`` enumerates those methods, so ``has_server_function(...,
target='voltage_out')`` answers for your driver without you doing anything.

**A ``send_trigger()`` stub** that only prints a warning. This is the one DAQ method stimpack's own
machinery calls (see the trigger section below), and the one your driver must override.

Everything else is your ``labpack``'s vocabulary. ``output_step``, ``setup_pulse_wave_stream_out``,
``set_value``, ``stream_with_timing`` -- the names in the template and in real labpacks -- are
conventions shared between a lab's driver and that lab's protocols, not an interface stimpack
defines or checks. There is no base implementation to inherit and no required signature: a driver
that does not define ``output_step`` does not have it, and channels, amplitudes and timing are
keyword arguments your protocols and your driver agree on between themselves.

Wiring it up
============

The driver runs on the server, next to the hardware. The rig server script
(:doc:`labpack_server`) passes it as ``daq_class``::

    from labpack.daq import MyRigDAQ

    server = BaseServer(visual_stim_kwargs=visual_stim_kwargs,
                        daq_class=MyRigDAQ,
                        daq_kwargs={'dev': '440017544', 'trigger_channel': 'FIO4'})
    server.loop()

``daq_class`` must subclass ``stimpack.daq.DAQ``; the instance becomes the server's
``voltage_out`` module. Leave it ``None`` and the module does not exist: that rig's
``voltage_out`` calls are reported as warnings and the run continues, which is what lets one
protocol serve rigs with and without the hardware.

A minimal driver
================

Distilled from the template's drivers, with the vendor API left out::

    # labpack/daq.py
    import threading, time
    from stimpack import daq

    class MyRigDAQ(daq.DAQ):
        def __init__(self, dev=None, trigger_channel='FIO4'):
            super().__init__()
            self.trigger_channel = trigger_channel
            self.hw = vendor_api.open(dev)

        def output_step(self, output_channel='DAC0', pre_time=0.0,
                        step_time=1.0, step_hi=5.0, step_lo=0.0):
            def run():
                time.sleep(pre_time)
                self.hw.write(output_channel, step_hi)
                time.sleep(step_time)
                self.hw.write(output_channel, step_lo)
            threading.Thread(target=run, daemon=True).start()

        def send_trigger(self, trigger_channel=None, trigger_duration=0.05):
            self.output_step(output_channel=trigger_channel or self.trigger_channel,
                             step_time=trigger_duration, step_hi=5.0)

        def close(self):
            self.hw.close()

Two details are load-bearing. The timed output runs on a **background thread**: the server handles
requests in one loop, so a handler that slept out the step duration would stall every module --
screens included -- until it finished. And ``close()`` releases the hardware: the server broadcasts
``close`` to every module at shutdown.

Calling it from a protocol
==========================

Address the module like any other, and batch its calls with the trial's stimuli so everything
arrives in one round trip::

    def load_stimuli(self, manager, multicall=None):
        if multicall is None:
            multicall = MyMultiCall(manager)

        if self.has_module('voltage_out') and self.trial_protocol_parameters['opto_amp'] > 0:
            multicall.target('voltage_out').setup_pulse_wave_stream_out(
                channels_config=[{'name': 'DAC0',
                                  'high': self.trial_protocol_parameters['opto_amp'],
                                  'low': 0.0}],
                frequency_hz=50, pulse_width_s=0.01)
            multicall.target('voltage_out').stream_with_timing(pre_time=1.0, stim_time=4.0)

        super().load_stimuli(manager, multicall)   # adds the visual stimuli, then sends the batch

The method names and keyword arguments are one lab's, talking to that lab's LabJack driver; yours
will be whatever your driver defines. So is the timing convention -- here, a driver-side thread
that waits ``pre_time`` and then runs the waveform against the trial. The ``has_module`` guard is
what lets the same protocol run on a rig without the hardware. Calls are one-way: nothing comes
back, and a mistyped method name is reported as an error and aborts the run.

Acquisition triggers at run and trial start
===========================================

The one DAQ call stimpack makes on its own is ``send_trigger()``, to start acquisition hardware --
a microscope, cameras -- in a known temporal relationship to the stimulus. Two protocol attributes
say when:

``trigger_on_epoch_run`` (default ``True``)
    fire once as the run starts.

``trigger_on_epoch`` (default ``False``)
    fire again as each trial starts.

Both fire on the *client*, through a trigger device named in the rig config::

    rig_config:
      my_rig:
        trigger: NIUSB6210(dev='Dev5', trigger_channel='ctr0')  # DAQ on the client machine
        # trigger: DAQonServer()                                # DAQ on the server machine

The value is a Python expression evaluated in your ``labpack``'s ``daq`` module (the
``module_paths.daq`` file in the config). A device attached to the client machine is driven
directly. ``DAQonServer`` is the shipped proxy for the usual case where the hardware is on the
server: its ``send_trigger`` and ``output_step`` forward to ``target('voltage_out')`` over the
socket, so the trigger fires on the server's driver. Both accept an optional ``multicall``: pass
one and the call is queued in that batch instead of sent immediately (and the multicall is
returned, for chaining), so a trigger can land in the same wire message as ``start_stim``. It
forwards only those two names; labs that want to reach the rest of their driver through the same
object subclass it to forward more. With no ``trigger`` key, no trigger is sent.

Full drivers
============

``labpack-template`` ships complete, working drivers to copy, one vendor per file in
``template_labpack/daq/``: NI-DAQ drivers (``NIUSB6001``, ``NIUSB6210``, via ``nidaqmx``) in
``ni.py``, a LabJack T-series driver (via ``ljm``) with waveform stream-out in ``labjack.py``,
and a ``DAQonServer`` subclass that forwards the streaming methods in ``on_server.py``;
``server/example_server.py`` shows where ``daq_class`` goes.
