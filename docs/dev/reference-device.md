# Reference: `stimpack.device`

The hardware/IO abstraction between the experiment server and physical rigs. Two
independent concerns: **DAQ triggering** (synchronizing external acquisition) and
**closed‑loop locomotion** (feeding a subject's movement into the renderer).

> Note: stimpack core ships only the *abstract* DAQ base plus an on‑server proxy,
> and only `KeyTrac` as a concrete locomotion source. Real hardware drivers
> (NI‑DAQ, LabJack, FicTrac, Lightcrafter) live in the labpacks — see
> [`labpack-guide.md`](labpack-guide.md). Closed‑loop flow is in
> [`ARCHITECTURE.md`](ARCHITECTURE.md) §8.

Files: `daq.py`, `locomotion/loco_managers/loco_managers.py`,
`locomotion/loco_managers/keytrac_managers.py`, `locomotion/keytrac/keytrac.py`.

---

## DAQ — `daq.py`

### `DAQ`
Abstract base for trigger/output devices. Provides the module RPC contract
(`handle_request_list` reflection‑dispatches `request['name']` to a method of the
same name) and a no‑op `send_trigger` that just warns if a subclass didn't
override it.

### `DAQonServer(DAQ)`
A **client‑side proxy** used when the real DAQ hardware lives on the stim server.
Client code calls `send_trigger()` / `output_step()` as if the DAQ were local;
the calls are turned into RPC requests targeted at the server's `daq` module.
`set_manager(manager)` injects the socket client; each method forwards via an
optional `MyMultiCall` and/or `self.manager.target('daq')`.

**Trigger path at run time:** the client loads the trigger device from config
(`load_trigger_device`, `eval(f'daq.{...}')`); if it's a `DAQonServer`, the
client injects the manager. At epoch‑run / per‑epoch boundaries the client calls
`trigger_device.send_trigger()`, which either fires TTL directly (local hardware)
or RPCs the server's DAQ module.

---

## Locomotion — `loco_managers.py`

### `LocoManager`
Minimal base for anything registered as the server's `locomotion` module —
no‑op `start`/`close`/`set_save_directory` plus reflection `handle_request_list`.
`BaseServer` asserts `loco_class` subclasses this.

### `LocoSocketManager(host, port, udp=True)`
Owns the UDP/TCP socket receiving newline‑delimited position lines from the
locomotion source. `connect()` (UDP: bind + non‑blocking), `receive_message
(wait_for)` (select‑gated `recvfrom`), `get_line(wait_for, get_most_recent)`
(extracts the most‑recent or oldest complete frame from the buffer),
`send_message`, `close`.

### `LocoClosedLoopManager(LocoManager)`
The closed‑loop engine.

| Method | Purpose |
|---|---|
| `start()` / `close()` | Connect the socket, open the log file / tear down. |
| `get_data(wait_for, get_most_recent)` | `get_line` → `_parse_line` → dict. |
| `_parse_line(line)` | **Abstract** — a subclass maps the device's line format to `{x,y,z,theta,phi,roll,frame_num,ts}`. The base prints a "please implement" message. |
| `set_pos_0(loco_pos, …)` / `map_loco_to_server_pos(pairs, …)` | Establish the offset `pos_0 = loco_reading − server_pos` that zeroes the tracker to server coordinates. |
| `update_pos(update_x…roll, return_pos)` | Read the tracker, compute `pos = reading − pos_0` per axis, push the enabled axes to `stim_server.set_subject_state`. |
| `loop_start()` / `loop_stop()` | Start/stop the background reader thread. |
| `loop_start_closed_loop()` / `loop_stop_closed_loop()` | Toggle whether readings drive the scene (vs. just logging). |
| `loop_update_closed_loop_vars(...)` | Choose which axes are live (default x/y/z/theta on; phi/roll off). |
| `loop_custom_fxn` | Optional per‑iteration callback `fn(pos)`. |

---

## KeyTrac — keyboard‑driven fake locomotion

The only concrete locomotion source in core; a demo/testing stand‑in for a real
treadmill.

* **`keytrac.py` — `KeyTrac`** — a standalone PyQt6 app (separate process).
  WASD/QE/etc. keypresses mutate a 6‑DOF `subject_pos` and it streams `KT, …`
  lines over UDP. Supports absolute and **relative** (heading‑aware, sin/cos)
  control modes; arrow keys scale the step size; it listens for a `reset_pos`
  command. Displays a `keytrac_map.png` keybinding cheat‑sheet.
* **`keytrac_managers.py`**
  * `KeytracManager(LocoManager)` — launches/kills the KeyTrac app as a detached
    subprocess (`start_new_session=True`); `close()` sends SIGINT then kills.
  * `KeytracClosedLoopManager` — composes a `KeytracManager` (spawn) with
    `LocoClosedLoopManager` (socket + loop). Implements `_parse_line` for `KT, …`
    lines (rad→deg for theta/phi/roll) and overrides `set_pos_0` to also command
    KeyTrac to reset. **This is the default locomotion class for the built‑in
    local server** (`client.py`).

---

## Extending the device layer

* **New DAQ driver:** subclass `DAQ`, override `send_trigger` (and optionally
  `output_step`), reference it in the rig config `trigger` field.
* **New locomotion source:** subclass `LocoClosedLoopManager`, implement
  `_parse_line` for that device's line format; pass it as `loco_class` to the
  server. (The labpacks' `FtClosedLoopManager` for FicTrac is the canonical
  example.)
* Choose closed‑loop axes with `loop_update_closed_loop_vars`; install a
  per‑frame callback via `loop_custom_fxn`; or install **server‑side** control via
  a protocol's `server_side_state_dependent_control` staticmethod.
