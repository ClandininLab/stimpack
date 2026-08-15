"""
Audio managers: the interface between a sound card and the server.

A manager renders sounds to samples when a trial is loaded and hands them to the output device when
the trial starts. :class:`PyAudioManager` drives a real card; :class:`NullAudioManager` is the
software stand-in that lets audio protocols be written and tested with no card at all, the way
:mod:`~stimpack.locomotion.keytrac` does for a tracker.

**Nothing here blocks.** ``BaseServer`` runs with ``threaded=False``, so a module's handlers execute
inline on the socket accept loop: a handler that waits for a sound to finish stops the server
routing anything for that long -- no ``stop_stim``, no ``end_trial``, no error reporting, and the
visual ``stop_stim`` batched into the same multicall arriving a sound-length late. The multistim
implementation this is ported from called ``stream.write()`` and did exactly that. Here the device
pulls from a pre-rendered buffer on its own thread and every handler returns immediately.
"""
import os
from time import monotonic, time

import numpy as np

from stimpack.module import BaseManager
from stimpack.audio import util
from stimpack.audio.sounds import BaseSound, make_as_sound


class AudioManager(BaseManager):
    """
    The audio module's base: rendering, mixing, trial logging and the module contract.

    Subclass to add an output device -- override :meth:`_open_device`, :meth:`_close_device` and
    :meth:`_device_playing`. Two subclasses ship, below.
    """
    module_name = 'audio'   # prefix on errors reported to the client

    def __init__(self, sample_rate=44100, channels=1, frames_per_buffer=256,
                 legacy_int16=False, save_directory=None, verbose=False):
        """
        :param sample_rate: samples per second. Sounds are generated against whatever this is, so a
            card that cannot do 44100 changes the waveform, not just its playback.
        :param channels: output channels. A mono sound is spread across all of them.
        :param frames_per_buffer: the device's callback block size. 256 frames at 44100 Hz is 5.8 ms,
            which sets the floor on how precisely a sound can start and on how late ``stop_stim``
            takes effect. Larger is safer against underruns and worse for timing.
        :param legacy_int16: reproduce multistim's overflowing int16 cast. See
            :func:`stimpack.audio.util.to_int16`; leave this off unless matching an old recording.
        """
        super().__init__(verbose=verbose)

        self.sample_rate = sample_rate
        self.channels = channels
        self.frames_per_buffer = frames_per_buffer
        self.legacy_int16 = legacy_int16
        self.save_directory = save_directory

        self.sound_list = []        # the sounds loaded for this trial, mixed into _buffer
        self.started = False

        # Playback state. Only the callback thread advances _cursor, and only the handlers set
        # _playing, so the two never write the same field and no lock is needed on the audio path --
        # which matters, because taking a lock in a real-time callback is how you get an underrun.
        self._buffer = None         # interleaved int16, length n_frames * channels
        self._cursor = 0            # in frames
        self._playing = False

        # Event sounds: one-shot cues that play the moment they are asked for and outlive
        # stop_stim, because their whole use is firing in the same breath as end_trial (a catch
        # chime) -- trial teardown must not silence them. Handlers only APPEND to _pending_events
        # (atomic under the GIL); the device thread alone moves entries to _active_events and
        # advances their cursors, so the two threads never write the same field and the audio
        # path stays lock-free.
        self._pending_events = []   # rendered interleaved int16 arrays, handler-side
        self._active_events = []    # [samples, cursor] pairs, device-thread-side

        # Sources: continuous (usually looping) mono sounds whose per-channel gains change while
        # they play -- a tower humming louder as the subject approaches. Same two-thread contract
        # as events: handlers create source dicts and append them to _pending_sources; the device
        # thread adopts them into _active_sources and alone advances 'cursor' and 'current_gains'.
        # Handlers write only whole-value fields ('target_gains' as a fresh tuple, the 'playing'
        # and 'stopped' flags), so nothing is mutated from two threads and no lock guards the
        # audio path. _sources_by_id is the handler-side index for set_source_gains and stop_stim.
        self._pending_sources = []
        self._active_sources = []
        self._sources_by_id = {}

        # What actually happened, for the log and for reporting. Reset per trial.
        self._requested_at = None   # wall clock when start_stim was handled
        self._onset_dac_time = None # the device's own clock for the first sample, when it can say
        self._underruns = 0

        self.log_file = None

    # # # The module contract # # #

    def load_stim(self, name, hold=False, source_id=None, loop=False, gains=1.0, **kwargs):
        """
        Render a sound and hold it ready. Called with the trial's stimulus descriptor.

        ``hold=True`` layers this sound on the ones already loaded, mixing them by summing, the way
        ``target('visual').load_stim(..., hold=True)`` layers stimuli. ``hold=False`` (the default)
        replaces them.

        A descriptor carrying ``source_id`` becomes a **source** instead of joining the trial mix:
        a mono sound, optionally looping, whose per-channel ``gains`` can be changed while it plays
        (:meth:`set_source_gains`) -- how a sound follows the run's geometry. Sources share the
        trial lifecycle: they start with ``start_stim`` and die with ``stop_stim``, unlike event
        sounds, because a looping sound that outlived its trial would drone forever.

        Rendering happens here rather than at ``start_stim`` on purpose: generating a waveform takes
        milliseconds and would otherwise land inside the trial it is timing.
        """
        # make_as pops 'name' from the dict it is given, so hand it a fresh one. It raises for an
        # unknown name, which BaseManager.handle_request_list catches and reports to the client --
        # the same treatment a mistyped visual stimulus gets.
        sound = make_as_sound({'name': name, **kwargs})
        if not isinstance(sound, BaseSound):
            raise ValueError(f"'{name}' is not a BaseSound subclass")

        if source_id is not None:
            self._load_source(source_id, sound, loop=loop, gains=gains)
            return

        if not hold:
            self.sound_list = []
        self.sound_list.append(sound)

        self._buffer = self._render(self.sound_list)
        self._cursor = 0

    def _load_source(self, source_id, sound, loop, gains):
        waveform = np.asarray(sound.generate(self.sample_rate), dtype=np.float64)
        if waveform.ndim != 1:
            # Per-channel gains ARE the source's channel content; a sound that renders its own
            # channels is describing the same thing twice, in ways that could disagree.
            raise ValueError(f"a gain-controlled source must be mono; "
                             f"'{type(sound).__name__}' rendered {waveform.shape[1]} channels")

        source = {
            'samples': np.clip(waveform, -1.0, 1.0).astype(np.float64),
            'cursor': 0,                                         # device-thread-owned
            'loop': bool(loop),
            'target_gains': self._as_channel_gains(gains),       # handler-replaced, whole tuple
            'current_gains': None,                               # device-side ramp state
            'playing': False,                                    # flipped by start_stim
            'stopped': False,                                    # flipped by stop_stim
        }
        # Reloading an id replaces the source: the old one is flagged off and forgotten here; the
        # device thread drops it on its next block.
        old = self._sources_by_id.get(source_id)
        if old is not None:
            old['stopped'] = True
        self._sources_by_id[source_id] = source
        self._pending_sources.append(source)

    def _as_channel_gains(self, gains):
        if isinstance(gains, (int, float)):
            return (float(gains),) * self.channels
        gains = tuple(float(g) for g in gains)
        if len(gains) != self.channels:
            raise ValueError(f'{len(gains)} gains for a {self.channels}-channel device')
        return gains

    def has_source(self, source_id):
        """Whether a source with this id is currently loaded.

        The guard for gain-driving logic that runs on every tracker update: between trials the
        source is gone (stop_stim removes it) while the updates keep coming, and a raise per
        update would flood the client with errors for an ordinary moment of the run.
        """
        return source_id in self._sources_by_id

    def set_source_gains(self, source_id, gains):
        """
        Retarget a source's per-channel gains; the device ramps each channel across one buffer
        block (~6 ms at the defaults), so a step never clicks.

        ``gains`` may be a scalar (every channel -- a distance rolloff on a mono rig) or one value
        per channel (a pan; see :func:`stimpack.audio.util.constant_power_gains`). Meant to be
        called from server-side logic at tracker rate -- the caller that already knows the
        geometry -- so the update lands with no RPC hop.
        """
        source = self._sources_by_id.get(source_id)
        if source is None:
            raise ValueError(f"no source named '{source_id}' is loaded")
        source['target_gains'] = self._as_channel_gains(gains)

    def start_stim(self, **kwargs):
        """
        Begin playing the loaded sound. Returns immediately; the device thread does the work.

        Accepts and ignores the keywords the other modules take (``append_stim_frames`` and friends)
        because protocols start every module at once with ``target('all').start_stim(...)``.
        """
        self._requested_at = time()
        self._onset_dac_time = None
        self._underruns = 0
        self._cursor = 0

        if self._buffer is None and not self._sources_by_id:
            # No sound loaded for this trial. Not a problem -- a protocol that plays on some trials
            # and not others is ordinary -- but the trial is a no-op here, and treating it as
            # playback would put a row in the log for every silent trial of every protocol.
            return

        if not self.started:
            # The device was never opened, so this would play nothing and, without this branch,
            # report nothing: exactly the silent failure the module contract exists to prevent. It
            # reported a truncated sound instead, which named the wrong cause. An error rather than
            # a warning -- a trial whose sound did not happen cannot be analysed as though it had.
            self.report('error', f'{self.module_name}: start_stim before the device was opened, so '
                                 f'nothing will play. The client opens it at the start of a run; a '
                                 f'script driving this manager must call start() itself.')
            return

        for source in self._sources_by_id.values():
            source['playing'] = True
        if self._buffer is not None:
            self._playing = True

    def stop_stim(self, **kwargs):
        """
        Stop playing, and record what the trial actually did.

        Stops by muting rather than by closing the stream: the device stays open for the whole run,
        because opening a stream costs tens of milliseconds and doing it per trial is where the
        original implementation's jitter partly lived.
        """
        was_playing = self._playing
        total_frames = self._frame_count()
        played_frames = min(self._cursor, total_frames)

        self._playing = False
        self._cursor = 0

        if was_playing:
            if self._underruns:
                # The card ran dry mid-sound: samples were dropped and the waveform the subject heard
                # is not the one that was loaded. Worth aborting the run over -- silently keeping a
                # trial whose stimulus is wrong is worse than stopping.
                self.report('error', f'audio: {self._underruns} buffer underrun(s) during the '
                                     f'trial; samples were dropped. Try a larger frames_per_buffer.')

            if total_frames - played_frames > self._truncation_tolerance():
                # The trial was much shorter than the sound, so the subject heard a truncated
                # version. A warning, not an error: a protocol may cut a sound off deliberately,
                # and only it knows.
                self.report('warning',
                            f'audio: stopped after {played_frames / self.sample_rate:.3f} s of a '
                            f'{total_frames / self.sample_rate:.3f} s sound')

            self._write_log(played_frames)

        # Release the loaded sounds, the way the visual module's stop_stim releases its stimuli.
        # That is what lets the next trial start from nothing, and so what lets load_stimuli pass
        # hold=True for every descriptor without sounds piling up across trials.
        self.sound_list = []
        self._buffer = None

        # Sources die with their trial -- unlike event sounds, because a looping sound that
        # outlived stop_stim would drone forever. Flagged rather than removed: the device thread
        # owns the active list and drops flagged entries on its next block.
        for source in self._sources_by_id.values():
            source['stopped'] = True
        self._sources_by_id = {}

    def play_event_sound(self, name, **kwargs):
        """
        Render a sound and play it now, on top of whatever else is playing.

        The counterpart to the load/start/stop lifecycle for sounds that are not trial stimuli:
        feedback cues fired by server-side logic (a catch chime from a state-dependent control
        function), which must survive the stop_stim that trial teardown broadcasts moments later.
        Overlapping events mix additively and each stops when its samples run out.

        Not written to the trial log: an event is not a stimulus descriptor, and the condition
        that fired it leaves its own record (``trial_end_reason``, subject state). A cue whose
        precise delivery time matters is not this -- it reaches the speaker a buffer or two after
        the handler runs -- and belongs on ``voltage_out``.
        """
        sound = make_as_sound({'name': name, **kwargs})
        if not isinstance(sound, BaseSound):
            raise ValueError(f"'{name}' is not a BaseSound subclass")

        if not self.started:
            # Same honesty as start_stim, softer verdict: a missing cue is worth a warning, but a
            # trial's analysis does not hinge on it the way it hinges on the trial's stimulus.
            self.report('warning', f'{self.module_name}: play_event_sound before the device was '
                                   f'opened, so nothing will play.')
            return

        rendered = self._render([sound])
        if rendered is not None:
            self._pending_events.append(rendered)

    def import_sound_module(self, path):
        """Load a labpack's ``sounds.py``, so its classes resolve by name here."""
        util.load_sound_module_from_path(path)

    def set_save_directory(self, save_directory):
        """Where to write the per-trial timing log. None turns logging off."""
        self._close_log()
        self.save_directory = save_directory

    def start(self):
        """Acquire the output device. Called by the server, not by ``__init__``."""
        if self.started:
            return
        self._open_device()
        self.started = True

    def close(self):
        self._playing = False
        if self.started:
            self._close_device()
            self.started = False
        # Events and sources die with the device, unlike with stop_stim: nothing can play them.
        self._pending_events = []
        self._active_events = []
        self._pending_sources = []
        self._active_sources = []
        self._sources_by_id = {}
        self._close_log()

    def on_connection_close(self):
        """A client disconnecting must not leave a sound playing."""
        self._playing = False
        self._cursor = 0

    # # # Rendering # # #

    def _render(self, sounds):
        """Mix a list of sounds into one interleaved int16 buffer."""
        if not sounds:
            return None

        waveforms = [np.asarray(sound.generate(self.sample_rate), dtype=np.float64) for sound in sounds]
        waveforms = [w for w in waveforms if w.size]
        if not waveforms:
            return None

        # Layered sounds of different lengths are padded to the longest and summed, so a short cue
        # over a long carrier does what it looks like it does.
        n_frames = max(len(w) for w in waveforms)
        mixed = np.zeros((n_frames, self.channels))
        for w in waveforms:
            if w.ndim == 1:
                # Mono spreads across every channel. A sound that wants per-channel content returns
                # a 2-D array instead and is used as-is.
                mixed[:len(w), :] += w[:, None]
            else:
                if w.shape[1] != self.channels:
                    raise ValueError(f'sound returned {w.shape[1]} channels, device has {self.channels}')
                mixed[:len(w), :] += w

        return util.to_int16(mixed.ravel(), legacy_overflow=self.legacy_int16)

    def _frame_count(self):
        if self._buffer is None:
            return 0
        return len(self._buffer) // self.channels

    def _truncation_tolerance(self):
        """
        How much of a sound may go unplayed before ``stop_stim`` calls it truncated.

        Not zero, and the reason is the common case rather than an edge one: a protocol that sets
        the sound's duration to ``stim_time`` will *always* lose the output latency off the end,
        because playback starts a buffer or two after the handler runs and ``stop_stim`` arrives on
        the clock regardless. Warning on that would fire every trial of every audio protocol, and a
        warning that always fires is one nobody reads.

        Four callback blocks is the estimate used when the device cannot say -- see
        :meth:`PyAudioManager._truncation_tolerance`, which asks it. Deliberately absolute rather
        than a fraction of the sound, so the threshold means the same thing at every duration.
        """
        return 4 * self.frames_per_buffer

    def _next_chunk(self, frame_count):
        """
        The next block of samples, as bytes. **Runs on the device's real-time thread.**

        Allocates only block-sized slices: no rendering, no logging, no locks. Everything it reads
        is set before playback starts, except the event queue, whose handoff is single-writer in
        each direction (see __init__).
        """
        n = frame_count * self.channels
        buffer = self._buffer     # bound once; a concurrent load_stim may replace it
        if self._playing and buffer is not None:
            start = self._cursor * self.channels
            chunk = buffer[start:start + n]
            self._cursor += frame_count
        else:
            chunk = None

        while self._pending_events:
            self._active_events.append([self._pending_events.pop(0), 0])
        while self._pending_sources:
            self._active_sources.append(self._pending_sources.pop(0))

        if not self._active_events and not self._active_sources:
            if chunk is None:
                return self._silence(frame_count)
            if len(chunk) < n:
                # The sound ended mid-block. Pad with silence rather than returning a short block,
                # which PortAudio would treat as the stream finishing.
                padded = np.zeros(n, dtype=np.int16)
                padded[:len(chunk)] = chunk
                return padded.tobytes()
            return chunk.tobytes()

        # Mix wide and clip once, so a chime over a loud carrier saturates instead of wrapping --
        # the same verdict to_int16 gives at render time. Float because source gains are float.
        mixed = np.zeros(n, dtype=np.float64)
        if chunk is not None:
            mixed[:len(chunk)] += chunk
        for event in self._active_events:
            piece = event[0][event[1]:event[1] + n]
            mixed[:len(piece)] += piece
            event[1] += n
        self._active_events = [event for event in self._active_events if event[1] < len(event[0])]

        for source in self._active_sources:
            if source['stopped'] or not source['playing']:
                continue
            samples, cursor = source['samples'], source['cursor']
            if source['loop']:
                piece = samples[(cursor + np.arange(frame_count)) % len(samples)]
                source['cursor'] = (cursor + frame_count) % len(samples)
            else:
                piece = samples[cursor:cursor + frame_count]
                source['cursor'] = cursor + frame_count
                if source['cursor'] >= len(samples):
                    source['stopped'] = True
                if len(piece) < frame_count:
                    piece = np.concatenate([piece, np.zeros(frame_count - len(piece))])

            # Gains ramp linearly across the block from where the last block left them to the
            # handler's latest target: a step applied instantly is a click; 256 frames (~6 ms at
            # the defaults) is not. target_gains is read once -- the handler replaces the whole
            # tuple, so a concurrent update lands next block, never mid-ramp.
            target = source['target_gains']
            current = source['current_gains'] or target
            for channel in range(self.channels):
                if current[channel] == target[channel]:
                    envelope = target[channel]
                else:
                    envelope = np.linspace(current[channel], target[channel], frame_count)
                mixed[channel::self.channels] += piece * envelope * 32767.0
            source['current_gains'] = target
        self._active_sources = [source for source in self._active_sources
                                if not source['stopped']]

        return np.clip(mixed, -32768, 32767).astype(np.int16).tobytes()

    def _silence(self, frame_count):
        return np.zeros(frame_count * self.channels, dtype=np.int16).tobytes()

    # # # Logging # # #

    def _write_log(self, played_frames):
        if self.save_directory is None:
            return
        if self.log_file is None:
            os.makedirs(self.save_directory, exist_ok=True)
            self.log_file = open(os.path.join(self.save_directory, 'audio_log.txt'), 'a')

        # The requested time is when the handler ran; the DAC time is when the card says the first
        # sample reached the output. The gap between them is the output latency, and it is the whole
        # reason this log exists -- see the timing discussion in docs/source/audio.rst.
        names = ','.join(type(s).__name__ for s in self.sound_list) or 'none'
        self.log_file.write(
            f'{self._requested_at!r}\t{self._onset_dac_time!r}\t'
            f'{played_frames / self.sample_rate:.6f}\t{self._underruns}\t{names}\n')
        self.log_file.flush()

    def _close_log(self):
        if self.log_file is not None:
            self.log_file.flush()
            self.log_file.close()
            self.log_file = None

    # # # Device hooks, for subclasses # # #

    def _open_device(self):
        raise NotImplementedError('AudioManager is the base class; use PyAudioManager for a real '
                                  'sound card or NullAudioManager for the software stand-in.')

    def _close_device(self):
        raise NotImplementedError


class PyAudioManager(AudioManager):
    """
    Plays through a sound card via PyAudio.

    Callback mode, not ``stream.write()``: PyAudio supports both, and only the callback form leaves
    the server free to keep routing while a sound plays.
    """

    def __init__(self, device_index=None, **kwargs):
        """
        :param device_index: PortAudio output device, or None for the system default. A rig with
            more than one card should name it -- the default moves when a monitor is plugged in.
        """
        super().__init__(**kwargs)
        self.device_index = device_index
        self._pyaudio = None
        self._stream = None
        self._pa_continue = None

    def _open_device(self):
        # Imported here rather than at module scope so that `import stimpack.audio` works on a
        # machine with no PortAudio. Only a server actually configured for audio pays for it.
        try:
            import pyaudio
        except ImportError as e:
            raise ImportError('PyAudioManager needs PyAudio: pip install stimpack[audio] '
                              '(and PortAudio system-side: brew install portaudio, or '
                              'apt install portaudio19-dev)') from e

        self._pyaudio = pyaudio.PyAudio()
        self._pa_continue = pyaudio.paContinue
        self._underflow_flag = pyaudio.paOutputUnderflow

        self._stream = self._pyaudio.open(
            format=pyaudio.paInt16,
            channels=self.channels,
            rate=self.sample_rate,
            output=True,
            output_device_index=self.device_index,
            frames_per_buffer=self.frames_per_buffer,
            stream_callback=self._callback,
        )
        self._stream.start_stream()
        self._warn_if_resampling()

    def _warn_if_resampling(self):
        """
        Warn when the requested rate is not the device's own, because the OS will resample.

        Do not be tempted to check ``stream._rate``: PyAudio stores the rate you asked for, so it
        can never disagree with itself. And PortAudio does not refuse an unsupported rate here --
        CoreAudio accepted 12345 Hz on the machine this was written on -- it silently resamples,
        which costs latency and a little quality and is invisible from the stream object. The
        device's declared default is the only thing that says what the hardware actually runs at.
        """
        try:
            info = (self._pyaudio.get_device_info_by_index(self.device_index)
                    if self.device_index is not None
                    else self._pyaudio.get_default_output_device_info())
            device_rate = int(info['defaultSampleRate'])
        except Exception:
            return          # a device that will not describe itself is not worth failing over

        if device_rate != self.sample_rate:
            self.report('warning',
                        f"audio: playing at {self.sample_rate} Hz on '{info.get('name', '?')}', "
                        f'which runs at {device_rate} Hz natively -- the OS is resampling. Set '
                        f'sample_rate={device_rate} to avoid it.')

    def _truncation_tolerance(self):
        """
        The base class's guess, replaced by what this device actually reports.

        A fixed number of blocks lands too close to the real latency to be useful: on the machine
        this was written on, four blocks is 21 ms and PortAudio reports 22.7 ms, so a protocol whose
        sound is as long as its trial warned or not depending on jitter -- the worst kind of
        warning, quiet enough to look meaningful and frequent enough to be noise. Asking the stream
        makes the threshold scale with the device instead, and the extra blocks keep it clear of
        the boundary rather than sitting on it.
        """
        stream = self._stream
        if stream is None:
            return super()._truncation_tolerance()
        try:
            latency = stream.get_output_latency()
        except Exception:
            return super()._truncation_tolerance()
        return int(latency * self.sample_rate) + 2 * self.frames_per_buffer

    def _callback(self, in_data, frame_count, time_info, status):
        if status and (status & self._underflow_flag):
            self._underruns += 1
        if self._playing and self._onset_dac_time is None and self._buffer is not None:
            # PortAudio's own estimate of when this block reaches the output, which is the closest
            # thing to a real onset time available without recording a sync signal.
            self._onset_dac_time = time_info.get('output_buffer_dac_time')
        return (self._next_chunk(frame_count), self._pa_continue)

    def _close_device(self):
        if self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
            finally:
                self._stream = None
        if self._pyaudio is not None:
            try:
                self._pyaudio.terminate()
            finally:
                self._pyaudio = None


class NullAudioManager(AudioManager):
    """
    The software stand-in: renders and times everything, plays nothing.

    What ``keytrac`` is for locomotion. It makes an audio protocol developable on a laptop with no
    sound card, and it is what the test suite uses -- a suite that played courtship song at whoever
    ran it would not be run twice.

    Timing is simulated from a monotonic clock, so ``stop_stim`` still reports a truncated sound and
    the log still has a row. There are no underruns and no DAC time, because there is no device.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.played = []        # (sound names, requested_at, played_seconds) per trial, for tests
        self._started_at = None

    def _open_device(self):
        pass

    def _close_device(self):
        pass

    def start_stim(self, **kwargs):
        super().start_stim(**kwargs)
        self._started_at = monotonic()

    def stop_stim(self, **kwargs):
        # No callback thread advances the cursor here, so work out how far playback would have got.
        if self._playing and self._started_at is not None:
            elapsed_frames = int((monotonic() - self._started_at) * self.sample_rate)
            self._cursor = min(elapsed_frames, self._frame_count())
            self.played.append((tuple(type(s).__name__ for s in self.sound_list),
                                self._requested_at,
                                self._cursor / self.sample_rate))
        super().stop_stim(**kwargs)
        self._started_at = None
