# Stimpack architecture

This document explains how stimpack is put together: the process topology, the
RPC protocol that wires it, how commands are routed to the right place, the
epoch/run lifecycle, an end‑to‑end trace of a single stimulus, and the
threading/process model. Once these are clear, every individual module reads as
an obvious consequence.

---

## 1. The core idea: processes wired by fire‑and‑forget RPC

Stimpack is not one program. It is a small constellation of OS processes that
talk over TCP sockets using a deliberately minimal RPC scheme:

* **One message = one line of newline‑terminated JSON**, decoding to a *request
  list* — a JSON array of request dicts `{"name": <fn>, "args": [...],
  "kwargs": {...}, "target": <module>?}`.
* **There are no responses.** No return values, no request IDs, no error
  channel. A caller fires a remote function call and never hears back. Both ends
  can independently *originate* requests, which is the only reason the channel
  looks bidirectional.
* A `__getattr__` proxy makes remote calls look exactly like local method calls:
  `client.load_stim("MovingPatch", width=10)` serializes and sends; it does not
  execute anything locally.

This one‑way, schemaless design is what keeps latency low and the layers
decoupled — but it is also the root of several robustness limitations noted in
[`IMPROVEMENTS.md`](IMPROVEMENTS.md) (a failed remote call is silently invisible
to the caller; a raised handler exception isn't isolated).

See [`reference-rpc.md`](reference-rpc.md) for the class‑level detail.

---

## 2. Process topology

A fully‑configured rig looks like this:

```
        ┌─────────────────────────────────────────────────────────────┐
        │  CLIENT process (experiment GUI, or a plain script)          │
        │    stimpack.experiment.gui.ExperimentGUI                     │
        │    ├── BaseClient      ── owns MySocketClient ──┐            │
        │    ├── BaseProtocol    (decides what to show)   │            │
        │    └── BaseData        (writes HDF5)            │            │
        └────────────────────────────────────────────────┼────────────┘
                                                          │  TCP socket
                                                          │  (JSON request lists)
        ┌─────────────────────────────────────────────────▼────────────┐
        │  SERVER process   stimpack.experiment.server.BaseServer       │
        │  (a MySocketServer; routes by target)                         │
        │                                                               │
        │   root functions:  print_on_server, set_subject_state,        │
        │                    load/unload_server_side_state_dependent... │
        │                                                               │
        │   self.modules = {                                            │
        │     'visual'     : VisualStimServer  ───────────┐            │
        │     'locomotion' : LocoClosedLoopManager subclass│            │
        │     'daq'        : DAQ subclass                  │            │
        │   }                                              │            │
        └──────────────────────────────────────────────────┼───────────┘
                                                            │ per-screen sockets
                    ┌───────────────────────────┬───────────┴───────────┐
                    ▼                           ▼                        ▼
        ┌───────────────────┐      ┌───────────────────┐    ┌───────────────────┐
        │ SCREEN subprocess │      │ SCREEN subprocess │    │  (aux screen …)   │
        │ visual_stim/      │      │ visual_stim/      │    │                   │
        │   framework.py    │      │   framework.py    │    │                   │
        │ StimDisplay       │      │ StimDisplay       │    │                   │
        │ (Qt QOpenGLWidget │      │ …                 │    │                   │
        │  + moderngl ctx)  │      │                   │    │                   │
        └───────────────────┘      └───────────────────┘    └───────────────────┘

   Side processes (talk to the SERVER, not the client):
     • FicTrac / KeyTrac  ──UDP text lines──▶  locomotion module
     • DLPC350 Lightcrafters  ──USB‑HID──  (opened in the rig server's main())
```

Key facts about the topology:

* The **`visual` module is itself a mini‑server tree.** `VisualStimServer`
  (`visual_stim/stim_server.py`) launches **one subprocess per `Screen`** via
  `launch_screen()` → `launch_server(framework.py, …)`, and holds one RPC client
  per screen in `self.screen_managers`. A command sent to `target('visual')` is
  fanned out to every screen subprocess.
* **Each screen subprocess owns its own OpenGL context** and runs an independent
  Qt render loop. Screens are isolated processes so that a per‑display GL context
  and (on multi‑GPU/multi‑X‑display rigs) a distinct `$DISPLAY` can be used.
* The **server can be local or remote.** `BaseClient` either launches a local
  server subprocess (the default, or a labpack‑specified `local_server_path`) or
  connects to an already‑running remote server named in the rig config
  (`use_remote_server`, host/port). This is how the same GUI drives a laptop demo
  or a two‑photon rig across the room.

### Subprocess launch handshake

`rpc/launch.py:launch_server(module_or_filename, **kwargs)`:

1. Builds `cmd = [sys.executable, <server_script>, json.dumps(kwargs)]`. The
   parent **chooses** the port (`find_free_port()`) and passes it down in the
   JSON blob — the child does not report a port back.
2. `subprocess.Popen(cmd)`, and `atexit.register(proc.wait)`.
3. Polls `MySocketClient(host, port)` every 0.1 s for up to 10 s, retrying only
   on `ConnectionRefusedError`; raises `Exception('Could not connect to server.')`
   on timeout.

The child follows the `echo_server.py` template: `get_kwargs()` parses
`sys.argv[1]`, builds a `MySocketServer`, registers its functions, and blocks in
`loop()`.

---

## 3. Target routing: `visual` / `locomotion` / `daq` / `all` / `root`

The RPC layer only *stamps* a `target` key; it never reads it. Routing is done
by `BaseServer.handle_request_list` (`experiment/server.py`):

| `target` | Where it runs |
|---|---|
| *(absent)* → defaults to `root` | The server's own `functions_on_root` registry (e.g. `print_on_server`, `set_subject_state`). |
| `root` | Same as above. |
| `visual` | The `VisualStimServer` module → fanned out to every screen subprocess. |
| `locomotion` | The `LocoManager` subclass module. |
| `daq` | The `DAQ` subclass module. |
| `all` | Delivered to **every** module in `self.modules`. |

On the client you write:

```python
manager.target('visual').load_stim('MovingPatch', width=10, height=10)
manager.target('all').start_stim(append_stim_frames=False)
manager.print_on_server('hello')      # no target → runs on root
```

`VisualStimServer.handle_request_list` then does a **second** split: some names
(`close`, the shared‑pixmap functions) are registered "on root" of the visual
server and run in the `VisualStimServer` process itself; everything else is
forwarded to the screen subprocesses. It also **stamps a wall‑clock timestamp**
`kwargs['t'] = time()` onto the time‑sensitive commands `start_stim`,
`pause_stim`, `update_stim` so that all screens share one authoritative `t=0`.

`MySocketServer.target()`/`__getattr__` provide the *same call syntax* for
in‑process code (a locomotion manager holds `stim_server=self` and calls
`self.stim_server.set_subject_state(...)`) — but there it dispatches locally
instead of over a socket.

---

## 4. Batching: `MyMultiCall`

Because each RPC call is its own line on the wire, commands that must land
*together* (e.g. "start the stimulus on all screens AND start the photodiode
square at the same instant") are grouped with `MyMultiCall`:

```python
multicall = MyMultiCall(manager)
multicall.target('all').start_stim(append_stim_frames=False)
multicall.target('visual').corner_square_toggle_start()
multicall()          # flush: one JSON line containing both requests
```

The whole batch is parsed and executed in one `handle_request_list` call, so the
commands are near‑coincident. `protocol.py:start_stimuli` uses this pervasively.
(Note: `MyMultiCall.__call__` does **not** clear its request list — reusing an
instance re‑sends everything; the protocol code always makes a fresh one.)

---

## 5. The experiment lifecycle (run → epoch → pre/stim/tail)

An experiment is a **run** (a "series") of **epochs** (trials). Parameters live
in tiers:

| Tier | Scope | Example |
|---|---|---|
| `run_parameters` | one dict per run | `num_epochs`, `idle_color`, `pre_run_time`, `randomize_order`, `do_loco` |
| `protocol_parameters` | one dict per run; **values are the sweep space** | `angle = [0, 45, 90, …]` (a list ⇒ swept dimension) |
| `epoch_protocol_parameters` | the single chosen value **per epoch**, saved to HDF5 | `angle = 45` |
| `epoch_stim_parameters` | the concrete stimulus descriptor for that epoch | `{'name':'MovingPatch', 'angle':45, …}` |

### Parameter sweeping (`get_parameter_sequence`)

`tuple(protocol_parameters.values())` is turned into a sequence:

* A value that is a **list of length > 1** becomes a swept dimension; scalars and
  **tuples** are treated as single constant values (so `width_height=(28,28)` is
  one value, `width_height=[(10,7),(20,14)]` sweeps two).
* `all_combinations=True` → `itertools.product` (Cartesian) of the list‑valued
  params. `all_combinations=False` → lists are tiled to the longest and zipped
  (params stay associated).
* `randomize_order=True` permutes within each pass through the sequence.

### The run loop

`BaseClient.start_run` (`experiment/client.py`):

```
prepare_run(recompute=False)          # process_input_parameters, check required
                                      # params, precompute_epoch_parameters,
                                      # __estimate_run_time, push idle background
create_epoch_run(protocol)            # HDF5: series_NNN group (if recording)
[start_loco / send acquisition trigger / start_loco_loop]
on_run_start(manager)                 # optional server-side closed-loop control;
                                      # sleep(pre_run_time)
while num_epochs_completed < num_epochs:
    QApplication.processEvents()      # keep GUI responsive; honor stop/pause
    start_epoch(...)                  # ← one trial
on_run_finish(manager)                # sleep(post_run_time); frame-tracker off
[stop_loco]
```

### One epoch

`BaseClient.start_epoch` → `BaseProtocol.load_stimuli` + `start_stimuli`:

```
load_precomputed_epoch_parameters()   # this epoch's stim + protocol params
create_epoch(protocol)                # HDF5: epoch_NNN group (if recording)
[per-epoch acquisition trigger]
load_stimuli(manager):
    target('visual').set_idle_background(bg)
    target('visual').load_stim('ConstantBackground', color=bg, hold=True)
    target('visual').load_stim(**epoch_stim_parameters, hold=True)
start_stimuli(manager):
    sleep(pre_time)                   # blank/idle
    ┌ multicall:
    │   [loco set_pos_0 / closed-loop start, if do_loco]
    │   target('all').start_stim(...)
    │   target('visual').corner_square_toggle_start()
    └ multicall()                     # ← stimulus becomes visible here
    sleep(stim_time)                  # stimulus plays
    ┌ multicall:
    │   target('all').stop_stim(...)
    │   corner square off; closed-loop stop; save_pos_history_to_file
    └ multicall()
    sleep(tail_time)                  # blank/idle
end_epoch(protocol); advance_epoch_counter()
```

Timing is driven by `sleep()` on the **client** side, while each stimulus's
motion is evaluated from the **server**‑stamped `t=0`. The photodiode "corner
square" (see §7) provides the ground‑truth frame timing that acquisition
hardware records alongside the neural data.

---

## 6. End‑to‑end trace: showing one `MovingPatch`

1. **Protocol** builds `epoch_stim_parameters = {'name':'MovingPatch',
   'width':10, 'height':10, 'angle':45, 'color':[1,1,1,1], 'theta':{'name':
   'TVPairs', 'tv_pairs':[[0,-45],[2,45]], 'kind':'linear'}, 'pre_time':1,
   'stim_time':2, 'tail_time':1}`. Note the `theta` kwarg is a **trajectory
   dict**, not a number.
2. **Client** sends `target('visual').load_stim('MovingPatch', **kwargs)`.
3. **VisualStimServer** forwards it to every screen subprocess.
4. **StimDisplay.load_stim** (`framework.py`) resolves the class by name via
   `get_all_subclasses(BaseProgram)`, instantiates `MovingPatch(screen)`, calls
   `initialize(ctx)` (compiles shaders, reserves VBOs), then `configure(**kwargs)`.
   `configure` wraps each time‑varying kwarg with `make_as_trajectory(...)`, so
   `self.theta` becomes a `TVPairs` object.
5. **Client** sends `target('all').start_stim()` (a `MyMultiCall` timestamps it).
   `StimDisplay.start_stim` sets `stim_start_time = t`.
6. Every frame, **`StimDisplay.paintGL`** runs:
   * drains the RPC queue (`server.process_queue()`),
   * computes one **perspective matrix per subscreen** from the subject's
     position/heading via `get_perspective(subject_position, pa, pb, pc, flip)`,
   * calls `stim.paint_at(stim_time, viewports, perspectives, subject_position)`.
7. **`BaseProgram.paint_at`** calls `eval_at(t)`, which for `MovingPatch`
   evaluates `return_for_time_t(self.theta, t)` (interpolating the trajectory)
   and rebuilds the patch mesh (a `GlSphericalRect`) at that angle; then it
   flattens the vertex/color/texcoord arrays into the VBOs and issues one
   `vao.render()` per subscreen with that subscreen's MVP matrix and viewport.
8. After `stim_time`, the client sends `target('all').stop_stim()`, which
   releases the stimulus's GL buffers and clears the display to the idle color.

The crucial payoff: **the client never does any per‑frame geometry or timing
math.** It ships a declarative descriptor (including trajectory dicts) once, and
the server evaluates motion frame‑by‑frame against a shared clock. This is why
`make_as`/`make_as_trajectory` (dict → object hydration) is load‑bearing across
the whole codebase.

---

## 7. The perspective pipeline

Stimpack renders **physically‑calibrated, perspective‑correct** imagery so that
a stimulus subtends the intended visual angle on a subject whose eye is at a
known real‑world point.

* A `SubScreen` is defined by three corner points in **meters** — `pa`
  (lower‑left), `pb` (lower‑right), `pc` (upper‑left) — plus the NDC viewport
  rectangle it occupies on the physical display device. A `Screen` is a list of
  subscreens (one display can host several projected faces).
* `GenPerspective` (`perspective.py`) implements Kooima's *generalized
  perspective projection*: from the screen corners and the eye point `pe` it
  builds an off‑axis frustum and returns `P·(Mᵀ·T)` as a column‑major float32
  `mat4`, ready for the `Mvp` GLSL uniform.
* **Subject heading** is applied by rotating the *screen corners about the
  subject* (`.rotz(theta).rotx(phi).roty(roll)`), i.e. yaw/pitch/roll of the eye
  are realized as counter‑rotations of the world — see `get_perspective` in
  `framework.py`.
* `horizontal_flip` supports rear‑projection displays.

The **corner square** (`square.py:SquareProgram`) draws a small quad in a
configurable screen corner whose brightness toggles every frame while a stimulus
runs. A photodiode over that corner gives the acquisition system a hardware
timestamp for every displayed frame — the definitive alignment between stimulus
and recorded neural signal.

---

## 8. Closed‑loop VR

```
FicTrac / KeyTrac  ──UDP text lines──▶  LocoSocketManager (bound UDP socket)
                                          │  get_line() → _parse_line()
                                          ▼
                            LocoClosedLoopManager.update_pos()
                              pos = raw_reading − pos_0   (per axis)
                              (only the enabled axes: default x,y,z,theta)
                                          │
                                          ▼
                            stim_server.set_subject_state(update_dict)
                              │  (optional server_side_state_dependent_control hook)
                              ▼
                            target('all').set_subject_state(...)
                                          ▼
                            StimDisplay.subject_position  ──▶  get_perspective()
                                          ▼
                                   the scene follows the animal
```

* A background loop thread (`loop_start`) repeatedly reads the tracker and pushes
  subject state. `loop_start_closed_loop()`/`loop_stop_closed_loop()` toggle
  whether the readings actually drive the scene; `loop_update_closed_loop_vars`
  chooses which axes are live.
* `set_pos_0` / `map_loco_to_server_pos` establish the offset that zeroes the
  tracker to server coordinates at the start of each epoch.
* A protocol can install a `@staticmethod server_side_state_dependent_control
  (manager, previous_state, state_update)` that runs on the **server** inside
  `set_subject_state` on every update — used for reward gating and for wrapping
  position on a virtual linear track.

Only `KeyTrac` (keyboard‑driven fake locomotion) ships in stimpack core;
`FtClosedLoopManager` (real FicTrac ball tracking) lives in the labpacks.

---

## 9. Threading & process model (what runs where)

| Context | What executes there |
|---|---|
| **Client main thread** | The GUI event loop; `start_run`'s epoch loop, which calls `QApplication.processEvents()` and `sleep()`s for pre/stim/tail. The actual run is on a `runSeriesThread` (QThread) so the GUI stays responsive. |
| **`MySocketClient` reader thread** (daemon) | Reads inbound lines and `queue.put`s them. Nobody drains the client queue by default — server→client pushes are effectively unused. |
| **Server accept loop** | `MySocketServer.loop()` accepts **one connection at a time** and reads request lines. `BaseServer`/`VisualStimServer` run `threaded=False`, so handlers execute inline on this loop. |
| **Screen subprocess** | A Qt event loop; the reader thread enqueues requests and **`paintGL` drains the queue every frame**, so `load_stim`/`start_stim`/`set_subject_state` run on the GL/render thread, serialized with drawing. |
| **Locomotion loop thread** (daemon) | Reads the tracker socket and pushes subject state. |

Two consequences worth internalizing:

* Because RPC handlers on a screen run **inside `paintGL`**, an exception in a
  handler propagates out of the Qt paint callback — there is no per‑request
  exception isolation (see [`IMPROVEMENTS.md`](IMPROVEMENTS.md) #1).
* `sleep()`‑based epoch timing on the client means run timing is *approximate*
  and can drift under GUI load; the corner square is the authoritative timing
  record, not the client clock.

---

## 10. Configuration & the labpack boundary

Stimpack itself ships **no lab‑specific configuration**. At startup the GUI:

1. Reads the persisted labpack path from
   `<user_config_dir('stimpack')>/path_to_labpack.txt`.
2. Lists `<labpack>/configs/*.yaml` and loads the chosen one (`yaml.safe_load`),
   falling back to a built‑in default dict.
3. Uses `cfg['module_paths']` to dynamically import the lab's `protocol`,
   `data`, `client`, and `daq` modules **by file path**, and
   `cfg['rig_config'][current_rig]` for screen center, data directory, loco
   availability, server options, and the trigger‑device expression.

Custom **stimuli** are loaded a different way: the server calls
`import_stim_module(path)` → `load_stim_module_from_path`, which `exec`s the
lab's `stimuli.py`/`trajectory.py`/`distribution.py` under a random "barcode"
namespace. Because those classes subclass the *same* `BaseProgram`/`Trajectory`/
`Distribution`, they show up in `get_all_subclasses` and become resolvable by
name — no explicit registration.

See [`labpack-guide.md`](labpack-guide.md) and
[`reference-experiment.md`](reference-experiment.md) (config schema) for details.

---

## 11. A note on branches & packaging

The stimpack README instructs users to `git checkout beyond_xorg`, but that
branch is stale relative to `main` (the code documented here is `main`). The
`experiment`, `visual_stim`, and other subpackages require **Python ≥ 3.10**
(they use PEP 604 `X | Y` unions at import time), which `setup.py` does not
declare. These and other packaging issues are catalogued in
[`IMPROVEMENTS.md`](IMPROVEMENTS.md).
