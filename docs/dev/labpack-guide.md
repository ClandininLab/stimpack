# Labpack guide: extending stimpack for your lab

Stimpack ships **no lab‑specific configuration**. A *labpack* is a separate repo
that supplies everything a rig needs: config YAMLs, protocols, custom stimuli,
device drivers, and rig‑server scripts. This guide covers how to build one
(`labpack`, the template) and tours the Clandinin Lab's real instantiation
(`clandinin_labpack`).

---

## How stimpack finds and loads a labpack

1. **Location** — stimpack reads
   `<user_config_dir('stimpack')>/path_to_labpack.txt` for the labpack path (set
   it from the GUI's *Labpack Dir* button or `config_tools.set_labpack_directory`).
2. **Config** — the GUI lists `<labpack>/configs/*.yaml`; the chosen one is
   `yaml.safe_load`ed. `cfg['module_paths']` names the lab's modules **by file
   path** (labpack‑relative or absolute), resolved and imported dynamically.
3. **Modules loaded by convention:**
   * `client` → a class named **`Client`** (subclass of `BaseClient`)
   * `data` → a class named **`Data`** (subclass of `BaseData`)
   * `protocol` → a *list*; every `BaseProtocol` subclass becomes GUI‑selectable
   * `daq` → the DAQ driver module (namespace for the `trigger` expression)
   * `visual_stim` → a *list of directories* execed on the **server** process
4. **Custom stimuli** are loaded differently from the other modules: the server
   calls `import_stim_module(dir)` → `load_stim_module_from_path`, which `exec`s
   `stimuli.py`/`trajectory.py`/`distribution.py` under a random "barcode"
   namespace. Because the classes subclass the *same* stimpack
   `BaseProgram`/`Trajectory`/`Distribution`, they become resolvable by class
   name via `get_all_subclasses` — no registration call.

The dependency direction is strictly **labpack → stimpack**. A labpack imports
its stimpack counterpart (`stimpack.experiment.client`,
`stimpack.visual_stim.shapes`, …) and subclasses it; stimpack never imports the
labpack.

---

## Minimum viable labpack (from the `labpack` template)

The template is almost entirely thin passthrough subclasses plus new leaf
classes — that is the point; you copy and fill it in.

| File | What it contains / what to edit |
|---|---|
| `configs/example_config.yaml` | Rig config: experimenter, subject metadata, `rig_config` profiles, `parameter_presets_dir`, `module_paths`. **Copy per lab.** |
| `labpack/client.py` | `class Client(BaseClient): pass` — override client/GUI behavior here. |
| `labpack/data.py` | `class Data(BaseData): pass` — override HDF5/metadata behavior here. |
| `labpack/protocol/base_protocol.py` | Lab‑wide `BaseProtocol` passthrough — shared protocol helpers go here. |
| `labpack/protocol/JohnDoe_protocol.py` | Example protocols; **rename to `<you>_protocol.py`** and add your `BaseProtocol` subclasses. |
| `labpack/device/daq.py` | DAQ drivers (the template ships NI‑DAQ and LabJack examples). |
| `labpack/visual_stim/example/` | Custom `stimuli.py`/`shapes.py`/`trajectory.py`/`distribution.py` — **additive** subclasses of the stimpack originals (e.g. `MovingEllipsoid`, `GlIcosphere`, `SparseBinary`). |
| `server/example_server.py` | The display‑server entry point describing your rig's physical screen geometry; run it as the server. |

> **Important:** `labpack/visual_stim/example/` is an *additive extension* of
> stimpack's `visual_stim` (new subclasses that import the originals), **not** a
> copy or a fork of it. The one real duplication is that `example/` (template)
> and `clandinin/` (live) are parallel forks of *each other's* extension library.

### Writing a protocol

```python
from labpack.protocol import base_protocol

class MyStimulus(base_protocol.BaseProtocol):
    def get_run_parameter_defaults(self):
        return {'num_epochs': 40, 'idle_color': 0.5,
                'all_combinations': True, 'randomize_order': True}

    def get_protocol_parameter_defaults(self):
        return {'angle': [0, 45, 90, 135],      # a list ⇒ swept
                'width': 10,                     # scalar ⇒ constant
                'pre_time': 1.0, 'stim_time': 2.0, 'tail_time': 1.0}

    def get_epoch_parameters(self):
        super().get_epoch_parameters()           # fills epoch_protocol_parameters
        p = self.epoch_protocol_parameters
        self.epoch_stim_parameters = {
            'name': 'MovingPatch',
            'width': p['width'], 'height': p['width'],
            'angle': p['angle'],
            'color': [1, 1, 1, 1],
            'sphere_radius': 1,
        }
```

### Writing a custom stimulus

```python
# labpack/visual_stim/mylab/stimuli.py
from stimpack.visual_stim.base import BaseProgram
from stimpack.visual_stim import shapes

class MyStim(BaseProgram):
    def configure(self, size=10, color=(1,1,1,1)):
        self.size = size; self.color = color
    def eval_at(self, t, subject_position={}):
        self.stim_object = shapes.GlSphericalRect(
            width=self.size, height=self.size, color=self.color)
```

Point `module_paths.visual_stim` at `labpack/visual_stim/mylab` and reference the
class as `{'name': 'MyStim', 'size': 12}` from a protocol.

---

## The Clandinin instantiation (`clandinin_labpack`)

A production labpack for fly‑VR + two‑photon + optogenetics rigs. Same structure,
much larger.

### Protocols (`labpack/protocol/*`)

* **Per‑user modules** (`mc`, `MHT`, `yw`, `ah`, `et`, `lj`, `na`, `dt`, `JCS`,
  `izs`, `mz`, `JBM`, `JohnDoe`). Each researcher owns a `<initials>_protocol.py`
  loaded by their own `<initials>_config.yaml` — this is the intended ownership
  model, not accidental duplication.
* **`base_protocol.py`** adds lab‑wide helpers `get_moving_patch_parameters(...)`
  / `get_moving_spot_parameters(...)` that build `MovingPatch`/`MovingEllipse`
  stim dicts with linear `TVPairs` trajectories from center/angle/speed/size.
* `mc_protocol.py` (~2.5k lines) is the richest — opto pulse trains, DLPC current
  changes, PMT shutter gating, dot‑field coherence stimuli, `PanGlomSuite`,
  `OcclusionShape`, `LinearTrackWithTowers` (server‑side closed loop),
  tracked‑trajectory playback.

### Custom stimuli (`labpack/visual_stim/clandinin/*`)

New `BaseProgram` subclasses not in stimpack core: `HorizonCylinder`
(image‑textured horizon), many dot‑field/coherence stimuli
(`MovingDotField(_Cylindrical)`, `PatchFieldWithOnDemandCoherentPulses`,
`Refreshing`/`ExponentiallyRefreshing` variants), `ProgressiveStarfield`,
`MovingEllipsoid`, `MovingFly` (a composite fly model), `FixedDepthCueTower`.
Custom trajectories (`trajectory.py`): `TVPairsBounded`, `LoomGabb` (Gabbiani
rv‑ratio loom), `LoomRV`, `SquareWave`, `TriangularWave` — **looming is realized
as a `MovingSpot` whose `radius` is a `LoomGabb`/`LoomRV` trajectory**, not a
dedicated stim class. `distribution.py` adds `SparseBinary`; `shapes.py` adds
`GlIcosphere`/`GlFly`; `image.py` loads/whitens/filters textures.

### Rig servers (`server/*`)

A "rig server" is a per‑rig entry‑point script describing one physical setup and
running the socket server. A typical `main()`:

1. Creates `DLPC350` objects (`make_dlpc350_objects()`), sets per‑LED current,
   and `pattern_mode(fps=120)` so the DMD displays 1‑bit patterns advanced by
   VSYNC.
2. Builds one `Screen` per display (each with `SubScreen` corner geometry) plus a
   non‑fullscreen "Aux" mirror for the operator.
3. Picks `loco_class` (`FtClosedLoopManager` for real flies,
   `KeytracClosedLoopManager`/`RotaryEncoder…` for demos/tethered rigs) and
   `daq_class=LabJackTSeries`.
4. Constructs `BaseServer(...)` and calls `server.loop()`.

Notable scripts: `Bruker_TwoScreens.py` (canonical two‑screen 2p rig),
`Bruker_FlyRight_ft_strobe.py` (registers `set_dlpc_current` on root for mid‑run
DMD current changes), `40HrFitness*.py` (3‑screen behavior rigs), `magneto.py`
(magnetic tether via rotary encoder), `example_server.py` (aux screen + KeyTrac,
no DAQ).

### Device drivers (`labpack/device/*`)

* **`daq.py`** — `LabJackTSeries` (LabJack T4/T7 via `ljm`): imaging triggers,
  opto via DAC voltage steps and periodic/pulse‑wave stream‑out, digital‑line
  toggling (e.g. FIO6 to gate a PMT). Also `NIUSB6001`/`NIUSB6210` (nidaqmx) and
  the `DAQonServer` proxy.
* **`dlpc350.py`** — USB‑HID driver for the TI Lightcrafter 4500 DMD: externally
  triggered pattern mode (1‑/8‑bit patterns streamed over video, VSYNC‑advanced)
  and per‑LED PWM current. `make_dlpc350_objects()` enumerates connected DMDs.
* **`locomotion/.../fictrac_managers.py`** — `FtManager` spawns the FicTrac
  binary as a subprocess; `FtClosedLoopManager` receives FicTrac's per‑frame UDP
  output, converts ball‑radian deltas to metric x/y and unwrapped theta, and
  pushes subject‑state updates for closed loop.
* `misc/lcr_ctl.py` — a standalone CLI to set Lightcrafter fps/currents.

### Configs & presets

* `configs/<user>_config.yaml` — per user: experimenter, subject‑metadata
  dropdowns, per‑rig `server_options`/`trigger`, `parameter_presets_dir`,
  `module_paths`.
* `presets/<user>/<Protocol>.yaml` — saved `{run_parameters, protocol_parameters}`
  keyed by preset name.
* `presets/<user>/*.spens` — ordered `(protocol, preset)` run sequences for the
  Ensemble tab.

### Onboarding a new user (Clandinin pattern)

1. Add `configs/<initials>_config.yaml` (protocol path → your protocol module;
   `visual_stim` path → `labpack/visual_stim/clandinin`).
2. Add `labpack/protocol/<initials>_protocol.py` subclassing the lab
   `base_protocol.BaseProtocol`.
3. Add a `presets/<initials>/` directory.
4. Point `path_to_labpack.txt` at the repo and select your config in the GUI.
