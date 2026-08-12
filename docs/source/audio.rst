=============================
Audio: driving a sound card
=============================

The ``audio`` module is the server's channel to a sound card. It renders a waveform when a trial is
loaded and plays it when the trial starts, so a protocol presents a sound the same way it presents a
stimulus on the screens -- one descriptor, one target, one trial.

It is for a sound card. If what you need is a voltage on a wire that happens to be audio-frequency,
that is :doc:`voltage_out`, and its onset is sample-clocked against your acquisition hardware in a
way a sound card's is not -- see `What the timing is worth`_ before choosing.

.. note::

   PyAudio is an optional dependency: ``pip install stimpack[audio]``, plus PortAudio system-side
   (``brew install portaudio``, or ``apt install portaudio19-dev``). Without it the module simply
   is not built, and audio calls are reported as warnings the way any missing hardware is. The
   local server's startup output says *why* there is no audio (package missing, PortAudio unable
   to start, or no output device), and ``stimpack --check-labpack`` flags a config whose rig sets
   ``audio_available: True`` on a machine that cannot build the module.

Sounds are classes
==================

A sound is a :class:`~stimpack.audio.sounds.BaseSound` subclass that generates float samples in
[-1, 1] for a given sample rate. Stimpack ships four:

=================  ==========================================================================
``SineSong``       a constant-frequency tone -- *Drosophila* sine song, or any pure tone
``PulseSong``      a train of Gaussian-windowed cosine pulses -- *Drosophila* pulse song
``WhiteNoise``     Gaussian noise, seeded by default so a trial is reproducible
``Silence``        nothing, for the requested duration
=================  ==========================================================================

They resolve by name, exactly as visual stimuli do, so a ``labpack`` adds its own by subclassing --
no registration step::

    # labpack/audio/sounds.py
    import numpy as np
    from stimpack.audio.sounds import BaseSound

    class FrequencySweep(BaseSound):
        def __init__(self, duration=1.0, f_start=100.0, f_end=900.0, volume=0.5):
            self.duration, self.f_start, self.f_end, self.volume = duration, f_start, f_end, volume

        def generate(self, sample_rate):
            t = np.linspace(0, self.duration, round(self.duration * sample_rate), endpoint=False)
            rate = (self.f_end - self.f_start) / self.duration
            phase = 2 * np.pi * (self.f_start * t + 0.5 * rate * t ** 2)
            return self.volume * np.sin(phase)

Point the config at the directory holding it, and the client imports it on the server at connect
time::

    module_paths:
      audio_stim: audio          # a directory containing sounds.py

Parameters are plain numbers, not trajectories, because the whole waveform is generated once at
load time. That is deliberate: the audio callback runs on a real-time thread and must not compute
anything (see `Why nothing blocks`_).

Playing one from a protocol
===========================

A stimulus descriptor may name the module that should render it. ``target: 'audio'`` sends it to the
sound card; a descriptor with no ``target`` goes to the screens, which is what every descriptor
meant before targets existed::

    def get_trial_parameters(self):
        super().get_trial_parameters()

        self.trial_stim_parameters = {'name': 'PulseSong',
                                      'target': 'audio',
                                      'duration': self.trial_protocol_parameters['stim_time'],
                                      'freq': self.trial_protocol_parameters['freq'],
                                      'volume': 0.5}

That is the whole integration. ``load_stimuli`` routes the descriptor, and the trial loop already
starts and stops every module together with ``target('all').start_stim()`` -- so nothing about
``start_stimuli`` needs overriding, and there is no separate audio protocol class.

A list gives one trial several stimuli, and they may name different modules::

    self.trial_stim_parameters = [
        {'name': 'MovingPatch', 'width': 10, 'height': 30, ...},
        {'name': 'PulseSong', 'target': 'audio', 'freq': 225.0, ...},
    ]

Both are loaded in one batch and started in one message, so they share a trial without either
knowing about the other. Both sets of parameters are saved on the trial, under ``stim0_`` and
``stim1_`` prefixes, in HDF5 and NWB alike -- including ``target``, so the file records where each
stimulus went.

Several descriptors aimed at ``audio`` are **mixed**, by summing: a short cue over a long carrier
does what it looks like it does. Layered sounds of different lengths are padded to the longest.

Event sounds: cues outside the trial lifecycle
==============================================

``play_event_sound(name=..., ...)`` renders a sound and plays it *now*, mixed over whatever else
is playing, and -- the point -- it survives ``stop_stim``. Trial stimuli cannot do this: a cue
fired by server-side logic in the same tracker update as ``end_trial`` would be silenced
milliseconds later by the ``stop_stim`` that trial teardown broadcasts. The built-in
``ChaseTheTower`` protocol is the worked example: its state-dependent control function rings a
chime the moment the subject catches the tower, by calling the audio module directly in the server
process::

    audio = server.modules.get('audio')
    if audio is not None and hasattr(audio, 'play_event_sound'):
        audio.play_event_sound(name='SineSong', duration=0.15, freq=880.0, volume=0.5)

Guard on presence, as here: a rig without a sound card has no audio module, and your condition
should do its real work (ending the trial, updating state) regardless.

Two honesty notes. Event sounds are not written to the trial log -- they are not stimulus
descriptors, and the condition that fired one leaves its own record (``trial_end_reason``, the
subject state). And an event reaches the speaker a tracker update plus an audio buffer after the
condition fired, ~10 ms of soft latency: right for feedback a subject hears, wrong for a
timestamped reward marker, which belongs on :doc:`voltage_out`.

Sources: continuous sounds with live gains
==========================================

A descriptor carrying a ``source_id`` becomes a **source**: a mono sound, usually looping, whose
per-channel gains can be retargeted while it plays -- how a sound follows the run's geometry::

    {'name': 'SineSong', 'target': 'audio', 'source_id': 'tower', 'loop': True,
     'gains': 0.0, 'duration': 1.0, 'freq': 220.0, 'volume': 1.0}

Sources share the trial lifecycle (they start with ``start_stim`` and die with ``stop_stim`` --
a looping sound must not outlive its trial), and the descriptor is saved with the trial like any
stimulus. The gains are driven from server-side logic, which is the code that already knows the
geometry; the built-in ``ChaseTheTower`` is the worked example, its control function making the
tower hum louder as the subject closes in. (Its ``hum_freq`` protocol parameter shows the safe
way to expose a source in the GUI: the frequency is client-side only, and 0 removes the
descriptor entirely, so hum and no-hum trials can sweep like any other parameter.) ::

    audio = server.modules.get('audio')
    if audio is not None and getattr(audio, 'has_source', lambda _: False)('tower'):
        audio.set_source_gains('tower', min(1.0, REF_DISTANCE / max(distance, 1e-6)))

Guard with ``has_source``, not just the module's presence: between trials the source is gone while
tracker updates keep coming. Gains ramp linearly across one buffer block (~6 ms at the defaults),
so a retarget never clicks; a scalar addresses every channel alike (a distance rolloff on a mono
rig), and a list gives one gain per channel. On a stereo device
:func:`stimpack.audio.util.constant_power_gains` turns a bearing into a left/right pair at
constant loudness -- level-only panning, so it places the sound *ordinally* (left-of, right-of,
sweeping smoothly) rather than at calibrated angles, and a source behind the subject renders at
the nearest side. Two practical notes: a looping sine needs a whole number of periods in its
rendered duration or the loop seam clicks (220 Hz over 1.0 s is seamless; 220.5 Hz is not), and
the gain trajectory is not separately logged because it is a pure function of the subject-state
history, which is saved with the series (see :doc:`locomotion`).

Why a sound is a stimulus, and a voltage is not
===============================================

Descriptors are for *presentations*: things stimpack renders end to end, where the parameters
fully determine what the animal experiences. Pixels and pressure waves qualify -- the descriptor
closes the loop from numbers to experience inside stimpack -- which is why visual and audio
stimuli share ``trial_stim_parameters``, the saved record of what was presented.

A :doc:`voltage_out` call is different in kind, not in importance. Stimpack's part ends at "5 V
on DAC0", and the same waveform is opto light through one wire and a reward through another: what
the animal experiences is a fact about the rig's wiring that only the ``labpack`` knows, and the
DAQ's vocabulary (``output_step``, ``setup_pulse_wave_stream_out``, channel names) is
deliberately the lab's, not stimpack's. So DAQ calls stay imperative -- made from
``load_stimuli``, parameters recorded as protocol parameters -- rather than descriptor-routed.

The routing itself does not enforce that line. ``target`` is popped and forwarded, and any module
implementing ``load_stim`` / ``start_stim`` / ``stop_stim`` can be named by a descriptor: a
``labpack`` that wants declarative, broadcast-synchronized voltage output can implement those
verbs on its own DAQ subclass and write ``{'name': ..., 'target': 'voltage_out'}`` today. The
door is open; it is the lab's to walk through, because only the lab can say what its waveform
names mean.

One reservation to know about: ``target`` is a routing key, so no stimulus -- visual, audio or
otherwise -- can take a parameter named ``target``; it is removed from the descriptor before the
stimulus sees its parameters.

Built-in protocols
==================

Three ship, in ``example_protocol.py``, and they appear in the GUI's dropdown with the visual ones:

``SineSong``, ``PulseSong``
    the courtship songs, sweeping frequency (and inter-pulse interval) across trials.

``AudiovisualPairing``
    a pulse song and a moving patch in one trial, which is what the mixed list above looks like in
    practice.

``examples/5-audio_stimulus.py`` plays the songs standalone, with no server or protocol, and writes
them to ``.wav`` files if PyAudio is not installed.

Wiring it up
============

The rig server script (:doc:`labpack_server`) passes the manager class::

    from stimpack.audio import PyAudioManager

    server = BaseServer(visual_stim_kwargs=visual_stim_kwargs,
                        audio_class=PyAudioManager,
                        audio_kwargs={'sample_rate': 48000, 'device_index': 3})
    server.loop()

``audio_class`` must subclass :class:`~stimpack.audio.managers.AudioManager`. Leave it ``None`` and
the module does not exist, so that rig's audio calls are warnings and the run continues -- what lets
one protocol serve rigs with and without a speaker.

Two arguments are worth setting explicitly on a rig:

``sample_rate``
    Sounds are generated against it. If it is not the device's own rate the OS resamples, silently,
    and the module warns once per run saying so. Set it to the card's native rate.

``device_index``
    The PortAudio output device. The default follows the system default, which moves when somebody
    plugs in a monitor.

``frames_per_buffer`` (default 256, i.e. 5.8 ms at 44.1 kHz) trades timing precision against
underrun safety. If a run reports underruns, raise it; underruns mean samples were dropped and the
waveform the animal heard is not the one that was loaded, so they abort the run.

Developing without a sound card
===============================

:class:`~stimpack.audio.managers.NullAudioManager` renders and times everything and plays nothing --
what ``keytrac`` is for locomotion. Pass it as ``audio_class`` and an audio protocol runs identically
off the rig, which is also how the test suite exercises this module without making noise.

The default local server (the one the GUI starts when no ``labpack`` names its own) builds a
``PyAudioManager`` when the machine can actually play -- PyAudio installed, PortAudio able to start,
an output device present -- at the device's own sample rate. When it cannot, there is no audio module
rather than a silent stand-in: an audio protocol on a machine with no speaker should say so, not run
to completion looking like it worked.

What the timing is worth
========================

Read this before aligning a sound to neural data.

A sound card's onset is known only to within its output buffer -- 5-20 ms typically, and not constant
between runs. Stimpack records what it can:

**The DAC time.** PortAudio reports when the block containing the first sample reaches the output.
Far better than the time the request was handled, and available per trial.

**A per-trial log.** With a save directory set, the module writes ``audio_log.txt`` next to the
data: requested time, DAC onset, realised duration, underruns, and which sounds played. The client
sets this up automatically at the start of a run.

**Nothing else.** There is no audio equivalent of the photodiode corner square in stimpack today.
For alignment you can defend in a paper, record a copy of the audio -- a click on a second channel
at sample 0, or a TTL on ``voltage_out`` batched into the same multicall -- on the same acquisition
system as the neural data, and align to *that*. The log tells you what the software believed; only a
recording tells you what happened.

One more thing the log is for: :class:`~stimpack.audio.sounds.PulseSong` quantises its length to a
whole number of pulse cycles, so a 1.0 s request yields 0.9986 s. Ask
:meth:`~stimpack.audio.sounds.BaseSound.duration_at` for the realised length rather than trusting
``duration``.

Why nothing blocks
==================

Worth knowing if you write your own manager, and the one thing the port from the ``multistim``
project had to change.

``BaseServer`` runs with ``threaded=False``: a module's handlers execute inline on the socket accept
loop. A handler that waited for a sound to finish would stop the server routing anything for that
long -- no ``stop_stim``, no ``end_trial``, no error reporting, and the visual ``stop_stim`` batched
into the same multicall arriving a sound-length late. So ``start_stim`` returns immediately and the
device pulls from a pre-rendered buffer on its own thread.

That thread is why sounds are generated at load time and why the callback allocates nothing but the
block it hands over. If you add a manager of your own, keep both properties.

A note on ``volume``
====================

Full scale is not free: at ``volume=1.0`` a sound that touches 1.0 exactly sits on the edge of the
int16 range. Stimpack clips rather than wrapping, which is audible as nothing at all -- but the
implementation this was ported from computed ``floor(x * 2**15)`` and wrapped, putting a full-scale
inverted spike at the centre of every pulse of pulse song at its default volume. If you need to
regenerate a stimulus as an older recording actually heard it, ``legacy_int16=True`` on the manager
reproduces that exactly. Otherwise leave it alone, and prefer a volume with headroom.
