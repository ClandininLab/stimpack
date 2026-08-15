# Reference: `stimpack.experiment`

The experiment‑control layer: turns a user protocol into a timed run against the
stimulus/hardware servers, drives the PyQt6 GUI, and persists metadata to HDF5.

> The run/epoch/pre‑stim‑tail lifecycle and parameter tiers are explained in
> [`ARCHITECTURE.md`](ARCHITECTURE.md) §5. This file is the module reference,
> plus the **HDF5 data format** and the **config/labpack schema**.

Files: `protocol.py`, `client.py`, `server.py`, `gui.py`, `data.py`,
`example_protocol.py`, `util/config_tools.py`, `util/h5io.py`.

---

## `protocol.py` — `BaseProtocol(cfg)`

A protocol declares *what* to show and *how to sweep* it, and drives each epoch's
timing. You subclass it and, at minimum, override:

| Method | Return / purpose |
|---|---|
| `get_run_parameter_defaults()` | dict of run‑scope params (`num_epochs`, `idle_color`, `pre_run_time`, `randomize_order`, `all_combinations`, …). |
| `get_protocol_parameter_defaults()` | dict whose **values define the sweep space** (a `list` of length>1 ⇒ swept dimension; scalars/tuples ⇒ constant). |
| `get_epoch_parameters()` | Call `super().get_epoch_parameters()` to materialize `self.epoch_protocol_parameters` (one value per param this epoch), then build `self.epoch_stim_parameters` — the stimulus descriptor(s). |

Optional lifecycle hooks (call `super()` first): `prepare_run`,
`process_input_parameters`, `load_stimuli`, `start_stimuli`, `on_run_start`,
`on_run_finish`. Flags: `trigger_on_epoch_run`, `trigger_on_epoch`,
`use_precomputed_epoch_parameters`, `use_server_side_state_dependent_control`.

Core machinery:

* **`get_parameter_sequence(parameter_list, all_combinations, randomize_order)`** —
  the sweep engine (`itertools.product` for all‑combinations, tile‑and‑zip
  otherwise; per‑pass permutation when randomized). Stores the sequence + per‑
  epoch index array in `persistent_parameters`.
* **`precompute_epoch_parameters(refresh)`** — loops `num_epochs`, calls
  `get_epoch_parameters` + `check_required_epoch_protocol_parameters`, and caches
  per‑epoch `stim`/`protocol` parameter lists so the run loop has no per‑epoch
  compute cost. `__estimate_run_time` sums pre/stim/tail + pre/post‑run times.
* **Presets:** `load_parameter_presets` / `update_parameter_presets(name)` /
  `select_protocol_preset(name)` read/write per‑protocol YAML in the labpack's
  preset directory (warn on unknown params).
* `adjust_center(relative_center)` — offset by the rig's `screen_center`.

`SharedPixMapProtocol(BaseProtocol)` adds a parallel shared‑pixmap track for
movie/streamed stimuli.

`example_protocol.py` ships `DriftingSquareGrating`, `MovingPatch`, and
`LinearTrackWithTowers` (the last demonstrates closed‑loop VR with a
`server_side_state_dependent_control` staticmethod).

---

## `client.py` — `BaseClient(cfg)`

Owns the connection and runs the experiment.

* **Server selection** (in `__init__`): a remote server (`use_remote_server`,
  connect a `MySocketClient`), a labpack‑specified `local_server_path` (launched
  as a subprocess), or the built‑in default local `BaseServer` (with a
  `KeytracClosedLoopManager` for demo locomotion). Also loads the trigger device
  and imports user visual‑stim modules onto the server.
* `start_run(protocol_object, data, save_metadata_flag=True)` — the run loop
  (see [`ARCHITECTURE.md`](ARCHITECTURE.md) §5): `prepare_run`, create the HDF5
  epoch‑run group, optional locomotion + acquisition trigger, `on_run_start`,
  then the `while` loop over `start_epoch` honoring stop/pause, then
  `on_run_finish`.
* `start_epoch(...)` — one trial: load precomputed params, create the HDF5 epoch
  group, optional per‑epoch trigger, `load_stimuli`, `start_stimuli`, `end_epoch`.
* `stop_run`/`pause_run`/`resume_run` — set flags checked by the loop.
* `start_loco`/`start_loco_loop`/`stop_loco` — locomotion setup/teardown.
* `close()` — terminate a launched local server subprocess.

---

## `server.py` — `BaseServer(MySocketServer)`

Hosts the pluggable modules and routes requests (see
[`ARCHITECTURE.md`](ARCHITECTURE.md) §3).

* Constructs `self.modules = {'visual': VisualStimServer(**visual_stim_kwargs),
  'locomotion': loco_class(stim_server=self, …), 'daq': daq_class(**daq_kwargs)}`
  (locomotion/daq optional).
* `handle_request_list` splits into `root` requests (own `functions_on_root`
  registry) and per‑module / `all` requests.
* Root functions: `print_on_server`, `set_subject_state`,
  `load_server_side_state_dependent_control(protocol_module_path, protocol_name)`,
  `unload_server_side_state_dependent_control`.
* `set_subject_state(state_update)` — optionally runs the loaded closed‑loop
  control hook, stores `self.subject_state`, forwards to `target('all')`.
* `on_connection_close()` — propagates to every module.
* `close()` — `target('all').close()`.

**Closed‑loop control:** a protocol with `use_server_side_state_dependent_control
= True` sends `root.load_server_side_state_dependent_control(path, class_name)`
at run start; the server imports that module from disk and grabs the static
`server_side_state_dependent_control`, which then runs inside every
`set_subject_state`.

---

## `gui.py` — `ExperimentGUI`

The PyQt6 front‑end (console entry point `stimpack`). On startup an
`InitializeRigGUI` modal picks the labpack directory, config YAML, and rig; the
GUI then dynamically imports the lab's `protocol`/`data`/`client` modules
(falling back to stimpack built‑ins) and builds a 4‑tab UI:

* **Main** — protocol selector, preset dropdown, parameter grid, run controls
  (View / Record / Pause / Stop). Bools render as checkboxes; other params as
  text fields parsed by a recursive `parse_param_str` (numbers via `eval`;
  lists/tuples via a hand‑rolled tokenizer; parse errors pop a dialog and restore
  the default).
* **Ensemble** — an ordered list of `(protocol, preset)` pairs run sequentially;
  saved/loaded as `.spens` YAML files.
* **Subject** — subject‑metadata form; fields beyond `subject_id`/`age`/`notes`
  come from `cfg['subject_metadata']`.
* **File** — an HDF5 browser (via `h5io`) for inspecting/editing the current data
  file's groups and attributes.

A run executes on a `runSeriesThread` (QThread) calling
`client.start_run(...)`; a `QTimer` updates elapsed‑time and epoch‑count labels;
on completion the series counter advances and the file tree refreshes.
`InitializeExperimentGUI` is the modal for creating a new HDF5 file.

---

## `data.py` — `BaseData(cfg)` and the HDF5 format

Every method opens the file fresh (`h5py.File`, `'w-'`/`'r+'`/`'r'`) and closes
it; nothing is held open. The file hierarchy:

```
<experiment_file_name>.hdf5
├── (attrs: date, init_unix_time, data_directory, experimenter,
│           rig_config name, + every rig_config key stringified)
├── Subjects/
│   └── <subject_id>/                (attrs: subject metadata, init_unix_time)
│       └── epoch_runs/
│           └── series_NNN/          (attrs: run_parameters + protocol_parameters
│               │                            + protocol_ID + run_start_unix_time)
│               ├── acquisition/     (reserved for downstream acquisition code)
│               ├── epochs/
│               │   ├── epoch_001/   (attrs: epoch_unix_time, epoch_end_unix_time,
│               │   │                        stim params, epoch_protocol params)
│               │   └── epoch_002/ …
│               ├── rois/            (reserved)
│               └── stimulus_timing/ (reserved)
└── Notes/                           (attrs: unix_timestamp → note text)
```

| Method | Purpose |
|---|---|
| `initialize_experiment_file()` | Create the file (`'w-'`), write top‑level attrs, create `Subjects`/`Notes`. |
| `create_subject(md)` / `update_subject(md)` | Subject metadata as attrs. |
| `create_epoch_run(protocol)` | `series_NNN` group with run + protocol params. |
| `create_epoch(protocol)` / `end_epoch(protocol)` | `epoch_NNN` with stim + epoch‑protocol params and timestamps. |
| `create_note(text)` | Timestamped note attr. |
| `get_existing_series` / `get_highest_series_count` / `reload_series_count` | Series bookkeeping. |
| `get_existing_subject_data` / `select_subject` | Subject queries. |

`hdf5ify_parameter(value)` coerces params into attr‑safe forms (`None` →
`'None'`, `dict` → `str(dict)`, lists → arrays with string fallback, ragged
tuples → strings).

> **Caveat:** `create_epoch` serializes `epoch_stim_parameters` only when it is a
> `tuple` or `dict` — a **`list`** of stimuli (which `load_stimuli` supports) is
> silently not saved (see [`IMPROVEMENTS.md`](IMPROVEMENTS.md) #16‑adjacent).

---

## `util/config_tools.py` — config & labpack resolution

Bridges stimpack to a lab's configuration.

* **Labpack location:** persisted in
  `<user_config_dir('stimpack')>/path_to_labpack.txt`
  (`get_labpack_directory`/`set_labpack_directory`); a stored path is discarded
  if it no longer contains `configs/*.yaml`.
* **Config discovery:** `get_available_config_files` globs `<labpack>/configs/
  *.yaml`; `get_configuration_file` `yaml.safe_load`s the chosen file or returns
  `get_default_config()`.
* **Per‑rig getters** read `cfg['rig_config'][cfg['current_rig_name']]`:
  `get_screen_center` (default `[0,0]`), `get_data_directory` (default cwd),
  `get_loco_available` (default `True`), `get_server_options`, plus
  `get_experimenter` and `get_parameter_preset_directory`.
* **Dynamic module loading:** `load_user_module(cfg, name, …)` /
  `load_user_module_from_path(path, name)` import a labpack module by file path
  (via `importlib`), registered in `sys.modules`.
* **Trigger device:** `load_trigger_device(cfg)` loads the user `daq` module and
  constructs the device with `eval(f'daq.{trigger_expr}')` from the rig config.

> Robustness caveats worth knowing: the per‑rig getters do
> `cfg.get('rig_config').get(...)`, which raises `AttributeError` if
> `rig_config` is absent; user modules are cached under **generic names**
> (`'data'`, `'protocol'`, …) which can collide in `sys.modules`. See
> [`IMPROVEMENTS.md`](IMPROVEMENTS.md).

### Config YAML schema (recognized keys)

```yaml
experimenter: JohnDoe
subject_metadata:            # each becomes a GUI dropdown on the Subject tab
  genotype: [wildtype, mutantA]
parameter_presets_dir: presets/johndoe
module_paths:                # labpack-relative or absolute file paths
  protocol: [labpack/protocol/johndoe_protocol.py]
  data:      labpack/data.py            # class must be named Data(cfg)
  client:    labpack/client.py          # class must be named Client(cfg)
  daq:       labpack/device/daq.py
  visual_stim: [labpack/visual_stim/johndoe]   # dirs exec'd on the server
rig_config:
  my_rig:
    screen_center: [0, 0]
    data_directory: /data/johndoe
    loco_available: true
    trigger: "DAQonServer()"            # eval'd as daq.<this>
    server_options:
      use_remote_server: false
      local_server_path: server/my_rig.py
      host: 127.0.0.1
      port: 60629
```

---

## `util/h5io.py`

Five stateless helpers backing the GUI's File‑tab browser: `get_hierarchy`
(nested dict of groups, excluding acquisition/epochs/stimulus_timing/etc.),
`get_path_from_tree_item`, `get_attributes_from_group`, `change_attribute`,
and the recursive walker. *(Opens files `'r+'` even for read‑only queries — see
[`IMPROVEMENTS.md`](IMPROVEMENTS.md) #41.)*
