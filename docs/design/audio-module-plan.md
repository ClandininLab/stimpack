# Plan: an `audio` module, ported from multistim

*What to build to give stimpack the auditory capability that `multistim` prototyped, in what order,
and where to stop. Follows the contract in `docs/source/writing_a_module.rst`.*

The organising principle: **the scientific content of multistim's audio module is about 25 lines of
numpy, and everything around it is machinery stimpack already has.** The port is mostly deletion.

**Status** (branch `feat/audio`): Phases 0–4 done. A protocol's ``trial_stim_parameters`` route by
target, the client opens and releases the device around a run, and a mixed visual+audio trial has
been driven end to end through a real socket to a real sound card. Phase 5 has mechanisms 1 and 2
(DAC-time reporting, per-trial log); **mechanism 3, the recorded sync signal, is not built** — read
the timing section before trusting alignment. Phase 6 (docs page, the two false captions) not
started.

---

## What is actually there

`../multistim` is the pre-stimpack lineage — `flystim` + `flyrpc` + `visprotocol` + `visanalysis`.
Its audio support is four files:

| File | What it is |
|---|---|
| `flystim/flystim/audio.py` (89 lines) | `sine_song()`, `pulse_song()`, and `AudioPlay` — a PyAudio wrapper run as its own RPC server subprocess |
| `flystim/flystim/stim_server.py:60-97` | `MultiStimServer`, which splits requests on a `device='speaker'` kwarg and forwards them to that subprocess |
| `visprotocol/.../yh_audio_protocol.py`, `example_audio_protocol.py` | `SineSongProtocol`, `PulseSongProtocol`, and a `BaseProtocol` that overrides `loadStimuli`/`startStimuli` to add `device='speaker'` |
| `visprotocol/.../clandinin_protocol.py:291` | `DuoProtocol`, which holds a visual and an audio protocol and merges their parameter dicts under `_visual` / `_auditory` suffixes so both get saved |

Plus a GUI "Audio" tab and a "Multistim" checkbox in `ImagingExperimentGUI.py`, and one saved
preset (`resources/yh/parameter_presets/PulseSong.yaml`).

### What survives the port

**The two waveforms, and their parameterisation.** `sine_song(sr, volume, duration, freq)` and
`pulse_song(sr, volume, duration, freq, pcycle, ncycle)` — the pulse being a Gaussian-windowed
cosine repeated at a fixed cycle period. That is the part that encodes what the experiment is, and
it ports essentially unchanged.

### What does not, and why

- **`device='speaker'`.** This is precisely the problem `target()` was introduced to solve. It
  becomes `target('audio')`, and the routing, the batching and the error path come for free.
- **The blocking write.** `AudioPlay.start_stim` calls `stream.write(...)` for the whole waveform.
  stimpack's `BaseServer` runs with `threaded=False`, so handlers execute *inline on the accept
  loop*: a blocking write would freeze routing for the length of the sound. No `stop_stim`, no
  `end_trial`, no error reporting, and the visual `stop_stim` batched in the same multicall
  arriving one sound-length late. multistim's own example notes the symptom —
  `audio_multicall.py:35`, "using multicall does not decrease the jittering of the onset of the two
  stimuli". The stream must be callback-driven and `start_stim` must return immediately.
- **`getattr(sys.modules[__name__], name)` name resolution.** stimpack resolves stimuli through
  `get_all_subclasses`, which is what lets a labpack add its own without a registration step. Sounds
  should resolve the same way.
- **`DuoProtocol`.** Unnecessary. `multicall.target('all').start_stim()` in
  `BaseProtocol.start_stimuli` already broadcasts to every module, and each ignores names it does
  not define. A module implementing `load_stim`/`start_stim`/`stop_stim` is driven by the existing
  trial loop with **no protocol changes at all**. The whole visual+audio combination problem
  dissolves.
- **`AudioPlay.__del__`.** Device acquisition and release are `start()` and `close()`.

### Two defects to port deliberately, not accidentally

**1. `pulse_song` overflows int16 at `volume=1.0`, which is the value every shipped protocol uses.**
With the default `pcycle=0.016`, `ncycle=0.020`, `sr=44100`, the segment length is
`int(0.036 * 44100) = 1587` — odd. `t` is then mean-centred onto a grid containing exactly zero, so
`y = exp(0) * cos(0) = 1.0` exactly at the centre of every pulse. `np.floor(1.0 * 2**15) = 32768`,
one past the int16 maximum, and the cast wraps it to **−32768**: a full-scale negative spike at the
peak of all 28 pulses per second. Verified against the multistim arithmetic. `sine_song` has the
same hazard but only reaches it when a sample lands on the crest.

**2. The realised duration is not the requested duration.** `cycles = round(duration/(pcycle +
ncycle))` quantises to the cycle period, then `np.delete(samples, slice(0, int(seg/4)))` trims a
quarter-segment. A 1.0 s request yields 0.998639 s. Audio and visual stimulus lengths therefore
disagree by up to one cycle, silently.

Both are real bugs, and both are baked into existing data. **Gate:** decide before Phase 1 whether
bit-exactness with old recordings matters. Recommendation: port the arithmetic verbatim, pin it with
a unit test that reproduces the multistim output including the overflow, and ship the corrected
behaviour as a constructor flag defaulting to correct — so new data is clean and old data remains
reproducible on request.

---

## Phase 0 — decided

**Output path: a sound card, through PyAudio.** The alternative was the DAQ analog out, whose onset
is sample-clocked and therefore aligned to the acquisition clock by construction; the sound card's
is known only to within its output buffer. That buffer — 5–20 ms, and not constant run to run — is
accepted as the timing budget. Phase 5 exists to record what it actually was on each trial rather
than to pretend it is zero.

PyAudio over `sounddevice` because it is what multistim used and what the rig is known to work with.
This costs nothing structural: **PyAudio's blocking `write` is a choice, not the API.** Passing
`stream_callback=` to `PyAudio.open()` gives the same pull-based callback model, and the callback
receives `time_info['output_buffer_dac_time']`, which is exactly what Phase 5 needs. The port is
non-blocking either way; it just uses PyAudio's callback mode rather than its blocking mode.

**Placement: core, as a top-level package parallel to `visual_stim` and `locomotion`.** So
`stimpack/audio/`, with the same internal split those two use — sounds in one module, the manager in
another, path-loading helpers in a third — rather than a single flat file. This makes two captions
false, and they change with it: `README.md:87` and `docs/source/overview.rst:32` both currently say
"no auditory module ships with stimpack; a lab adds one as a new module rather than a change to the
core."

---

## Phase 1 — the sounds, as classes

**Deliverable.** `stimpack/audio/sounds.py`: a `BaseSound` with `configure(**kwargs)` and
`generate(sample_rate) -> np.ndarray`, and `SineSong`, `PulseSong`, `WhiteNoise`, `Silence`
subclasses. CamelCase, to match `MovingPatch` and to be resolvable by name through
`get_all_subclasses(BaseSound)` exactly as stimuli are.

Time-varying parameters go through `make_as_trajectory`, the same hydration the visual path uses, so
an amplitude ramp is a trajectory dict in the descriptor rather than a pre-computed array on the
wire.

Pure numpy, no device, no imports beyond the core dependency set — so the whole phase is testable
under `-m unit` and runs in CI on every push.

**Independent benefit.** Even with no manager, this is a usable waveform library, and it is where
the two defects above get pinned by test.

---

## Phase 2 — the manager

**Deliverable.** `stimpack/audio/managers.py`:

```python
class AudioManager(BaseManager):
    module_name = 'audio'        # prefix on errors reported to the client

    def load_stim(self, name, hold=False, **kwargs): ...
    def start_stim(self, **kwargs): ...     # returns immediately
    def stop_stim(self, **kwargs): ...
    def start(self): ...                    # acquire the device here, not in __init__
    def close(self): ...
```

A *Manager*, not a Server: it owns a device and serves no sockets.

**Non-blocking is the whole point.** `PyAudio.open(..., stream_callback=cb)`, where `cb` does
nothing but copy from a buffer rendered at `load_stim` and return `(chunk, pyaudio.paContinue)`.
Not `stream.write()`, which is what made the original block its own server loop.

`stop_stim` must actually stop: zero the buffer and let the callback drain, rather than closing the
stream mid-trial. Keep the stream open for the run and reuse it; opening a PortAudio stream per
trial costs tens of milliseconds and is where the original's jitter partly lived.

**Ship the software stand-in in the same phase** — `writing_a_module.rst` asks for it, and keytrac
is the precedent. A `NullAudioManager` that renders the waveform, records what it was asked to play
and when, and opens no device. That is what makes the module developable on a laptop, testable in
CI, and silent during `pytest`.

**Dependency.** `pyaudio` goes in an extra — `pip install stimpack[audio]` — imported lazily inside
`AudioManager.start()`, so a core install neither grows a PortAudio dependency nor fails to import.
`stimpack.util.open_message_window` is the precedent for the lazy import. PyAudio needs PortAudio
system-side (`brew install portaudio`, `apt install portaudio19-dev`), which is reason enough on its
own to keep it out of `install_requires`.

---

## Phase 3 — registration and routing

**Deliverable.** The module reachable as `target('audio')` on a stock server.

- `BaseServer.__init__` gains `audio_class=None, audio_kwargs={}`, following `daq_class` exactly,
  including the `None` means "this rig has no such hardware" convention.
- `KNOWN_TARGETS` in `experiment/server.py` gains `'audio'`, which is what stops
  `--check-labpack` from reporting every audio call as a typo'd target.
- `config_tools.get_audio_available(cfg)` and an `audio_available` rig-config key, mirroring
  `loco_available` / `daq_available`, so a protocol can guard its calls and a rig without a sound
  card produces no warnings.
- `client.py:507` currently calls `set_save_directory` on `target('locomotion')` alone. If the audio
  module logs (Phase 5), that call becomes `target('all')`.

No change to `handle_request_list`. The routing already works; it only has to know the name exists.

---

## Phase 4 — the protocol path

**The one real API question.** `BaseProtocol.load_stimuli` sends `trial_stim_parameters` to
`target('visual')` unconditionally. Audio needs a way in.

**Recommendation: let a stim descriptor name its own target.**

```python
self.trial_stim_parameters = [
    {'name': 'MovingPatch', 'width': 10, ...},                    # no target -> 'visual', as today
    {'name': 'PulseSong', 'target': 'audio', 'freq': 225.0, ...},
]
```

`load_stimuli` pops `target`, defaulting to `'visual'`, and dispatches accordingly. This is worth
preferring over a parallel `trial_audio_parameters` attribute for three reasons:

1. It reuses the routing idiom rather than inventing a second one alongside it.
2. **It needs no data-layer change.** `BaseData.create_trial` and `NWBData` already handle a
   list-valued `trial_stim_parameters` by prefixing `stim0_`, `stim1_`. Audio parameters get saved
   per trial, in both backends, for free — which is exactly the problem `DuoProtocol` was written to
   solve by hand.
3. It is backwards compatible by construction: a descriptor without `target` behaves as it does
   today.

`start_stimuli` needs no change at all — `target('all').start_stim()` and
`target('all').stop_stim()` already reach the module.

**Also in this phase:** labpack sound modules. `module_paths.audio_stim` in the config, an
`import_sound_module(path)` on the manager mirroring `import_stim_module`, imported at connect time
next to the visual one in `client.py:170`. Same `exec`-under-a-barcode-namespace mechanism, so a
lab's own songs resolve by name with no registration.

---

## Phase 5 — the timing record, honestly

This is the phase most likely to be skipped and most likely to be regretted.

**The client's `sleep()` does not time the trial, and it does not time the sound either.** For
vision the authoritative record is hardware: the corner square under a photodiode, recorded on the
acquisition system alongside the neural data. Audio needs its equivalent, and *"the server called
`start_stim` at time t"* is not it — between that call and air moving there is a PortAudio output
buffer of 5–20 ms that varies run to run.

Three mechanisms, in increasing order of trustworthiness:

1. **Report the DAC time.** The PyAudio callback receives `time_info['output_buffer_dac_time']` for
   the block containing the first sample. Push it to the client with `self.report(...)`, which is
   how a fire-and-forget module returns information at all. Costs nothing and is far better than the
   call time.
2. **Log per trial.** `set_save_directory` gives the module the experiment directory;
   `LocoManager.save_pos_history_to_file` is the precedent. One line per trial: requested onset,
   DAC onset, realised duration, and the resolved sound parameters.
3. **Emit a sync signal, and record it.** The real answer. Either a second audio channel carrying a
   click at sample 0, recorded by the acquisition system, or a TTL on `voltage_out` batched into the
   same multicall. This is the corner square for sound, and it is the only mechanism that survives a
   driver update.

**Gate.** If nobody will record the sync channel, mechanisms 1 and 2 are the whole phase and the
module's timing claims should say so in the docs rather than implying alignment it cannot deliver.

`t` deserves one note. `VisualStimServer` stamps `kwargs['t'] = time()` on `start_stim` and
deliberately copies rather than mutates, so `t` does not leak to other modules
(`stim_server.py:196-207`). Do not undo that to share a clock: the audio module should stamp its own
arrival time. The two differ by a few microseconds of routing, which is three orders of magnitude
below the output latency that actually limits you.

---

## Phase 6 — tests, docs, examples

**Tests.** `-m unit` for waveform generation (including the two pinned defects) and for dispatch
through `BaseManager` — `tests/unit/test_base_manager.py` is the model. `-m integration` for routing
over the fake link, extending `tests/integration/test_server_routing.py`. `-m hardware` for anything
that opens a real device. The stand-in from Phase 2 is what keeps `pytest` silent; a test suite that
plays courtship song at whoever runs it will not be run twice.

**Docs.** `docs/source/audio.rst`, modelled on `voltage_out.rst` and `locomotion.rst`; add the target
to `modules_and_targets.rst`; fix the two "no auditory module ships with stimpack" captions
(`README.md:87`, `docs/source/overview.rst:32`). An `examples/5-audio_stimulus.py` in the shape of
`1-hello_world.py`.

**Porting table for the old protocols**, since `yh_audio_protocol.py` is the migration target:

| multistim | stimpack |
|---|---|
| `manager.load_stim(**params, device='speaker')` | `multicall.target('audio').load_stim(**params)` |
| `manager.start_stim(device='speaker')` | already covered by `target('all').start_stim()` |
| `'name': 'sine_song'` | `'name': 'SineSong'` |
| `DuoProtocol(cfg, vprotocol, aprotocol)` | one protocol, two entries in `trial_stim_parameters` |
| `getEpochParameters` | `get_trial_parameters` (the 1.0 alias handles the old name) |

No deprecation shim is owed. multistim is a separate lineage, not a labpack, so nothing in the
field imports these names from stimpack and there is no `device='speaker'` compatibility path to
maintain.

---

## Risks, in the order they are likely to bite

**PortAudio latency is not a constant.** It varies with device, driver, host API and buffer size,
and on macOS it differs between built-in output and USB interfaces. Anything that assumes a fixed
offset will be wrong on the next machine. This is what Phase 5 mechanism 3 exists for.

**The audio callback runs on a real-time thread.** No allocation, no locks, no logging inside it.
Pre-render the whole waveform at `load_stim` and let the callback do nothing but copy. This is the
opposite of the original's structure and is not negotiable.

**Sample-rate mismatch.** A device that will not open at 44100 silently resamples, or refuses. Query
and report at `start()`, and fail loudly rather than playing a detuned song.

**`volume=1.0` is the default everywhere in the old presets.** Whatever is decided about the
overflow, a full-scale default is one clipped sample away from a click. Consider defaulting to 0.9
and documenting why.

**Scope creep into stereo.** `Note.md` in multistim lists "stereo sound stimulus" as a demand.
Mono first; the channel count belongs in `BaseSound.generate`'s return shape from the start (`(n,)`
or `(n, channels)`) so adding it later is not a rewrite, but do not build it in Phase 1.

---

## What this is not

- Not a change to the RPC layer, the routing, the trial loop or the data format. If any of those
  need editing, something has gone wrong — the point of the module contract is that they do not.
- Not a port of `DuoProtocol`, the GUI "Audio" tab, or the "Multistim" checkbox. Those exist to
  work around the absence of target routing.
- Not closed-loop audio. Sound that responds to the animal is a different design; the module should
  not be shaped to preclude it, but nothing here delivers it.
- Not an analysis path. `visanalysis` is out of scope.

---

## Suggested order of work

1. **Phase 0** — done: PyAudio to a sound card, in core as `stimpack/audio/`.
2. **Phase 1** — the sounds. Independently useful, fully CI-tested, no hardware.
3. **Phase 2** — the manager plus the stand-in. The stand-in is what unblocks everything after
   without a sound card on the desk.
4. **Phase 3** — registration. Small, mechanical.
5. **Phase 4** — the `target` key on stim descriptors. The only real API decision; worth its own
   review because it touches `BaseProtocol.load_stimuli`, which every labpack subclasses.
6. **Phase 5** — timing. Do at least mechanisms 1 and 2 before anyone collects data with this.
7. **Phase 6** — docs and examples, including the two captions that currently promise the opposite.

Phases 1–3 are a working module on a laptop. Phase 4 makes it usable from a protocol. Phase 5 makes
the data trustworthy.

## Design review notes (2026-08-12)

Recorded from the design review discussion, so the reasoning is not lost in the PR thread.

**The protocol layer gains vocabulary, not structure.** The litmus applied to this (and any
future) module PR: does it add *vocabulary* (stimulus names, a target) or *structure* (parallel
classes a protocol author must choose between)? Vocabulary composes; structure forks. This PR
adds vocabulary -- there is no `AudioProtocol` base class, and `AudiovisualPairing` is the
existence proof: one protocol, two modalities, one batch, one start. The example protocols are
*experiments*, which is the level at which "audio has its own protocols" is category-correct --
the same way `MovingPatch` is a visual experiment, not visual infrastructure.

**Presentation vs device action, and where the line really is.** Descriptors route to
*presentations*: things stimpack renders end to end, where the parameters determine the
experience. `voltage_out` stays imperative not because the animal does not experience opto, but
because only the lab can close the loop from parameters to experience (the same waveform is
light, shock or reward depending on wiring), and because stimpack deliberately defines no DAQ
vocabulary for a descriptor name to resolve against. The routing is target-agnostic on purpose:
a lab that implements the `load_stim`/`start_stim`/`stop_stim` verbs on its own DAQ subclass gets
declarative, broadcast-synchronized voltage output with zero stimpack changes. The
acquisition-trigger TTL, by contrast, is infrastructure -- not experienced by the animal -- and
will never be a presentation under any design.

**The run-bracket gates differ between modules, deliberately.** Locomotion brackets on user
intent (`do_loco`: tracking changes the experiment's semantics, so it is a per-run choice); audio
brackets on hardware presence (`has_module('audio')`: an open idle stream is silent and cheap,
and holding it open across the run is what keeps onset latency stable trial to trial). A
`do_audio` checkbox would be a parameter with no decision behind it.

**Failure modes.** No playable output on the default local server means *no module* (every audio
load is a reported warning), not `NullAudioManager` (which would run an audio protocol to silent
completion). The Null manager is for *chosen* silence: developing off-rig, CI.

**One reserved word.** `target` in a stimulus descriptor is routing, popped before any stimulus
sees its parameters -- no stimulus of any modality can take a parameter by that name. Documented
in audio.rst.

**A sharp edge found during review, not created by this PR.** `end_trial` stops presentations via
the `stop_stim` broadcast, but a self-scheduled `voltage_out` thread (`stream_with_timing`) runs
to completion: an ended-early trial does not cancel its opto schedule. Now cautioned in
behavior_ended_trials.rst; the structural fix is a lab-side `stop_stim` on the DAQ driver --
the same open door as above.
