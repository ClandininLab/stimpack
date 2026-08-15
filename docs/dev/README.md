# Stimpack developer documentation

Internals documentation for the **stimpack** framework, written for someone
changing stimpack itself. The user-facing documentation lives in
[`docs/source/`](../source) (rendered at stimpack.readthedocs.io) and is the
authoritative description of current behavior; when the two disagree, trust it.

Stimpack is a client/server system for **precise, perspective‑corrected
multisensory stimulation of a subject** — visual displays of any geometry,
sound, analog outputs — together with the experiment‑control, data‑saving and
closed‑loop locomotion machinery that surrounds a neuroscience rig.

---

## The two packages at a glance

| Package | Repo | Role |
|---|---|---|
| **stimpack** | `github.com/ClandininLab/stimpack` | The framework. Rendering engine, RPC layer, experiment orchestrator, module abstractions. Lab‑agnostic. |
| **labpack‑template** | `github.com/ClandininLab/labpack-template` | The template a lab copies and fills in: protocols, custom stimuli, device drivers, rig config YAMLs, and server scripts. |

The dependency direction is strictly one‑way: **a labpack imports from
stimpack; stimpack never imports from a labpack.** A labpack is discovered at
runtime (its path is stored in `path_to_labpack.txt` in stimpack's user‑config
dir) and its modules are loaded dynamically by file path from a YAML config.

---

## How to read these docs

Start with **ARCHITECTURE.md** — it explains the one idea that makes the rest of
the codebase legible: everything is a set of processes wired together by a
minimal fire‑and‑forget JSON‑over‑TCP RPC, and stimulus/experiment control is
just remote method calls tagged with a *target* module.

| Doc | What's in it |
|---|---|
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Process topology, the RPC protocol & `target()` routing, the run/trial lifecycle, an end‑to‑end data‑flow walkthrough, and the threading/process model. **Read this first.** |
| [`getting-started.md`](getting-started.md) | Install, run the bundled examples, launch the experiment GUI, and write your first protocol / config / custom stimulus. |
| [`reference-rpc.md`](reference-rpc.md) | `stimpack.rpc` — `MyTransceiver`, `MySocketClient/Server`, `launch_server`, `MyMultiCall`, the wire codec. |
| [`reference-visual_stim.md`](reference-visual_stim.md) | The renderer: `VisualStimServer`, per‑screen `StimDisplay`, perspective math, `Screen`/`SubScreen`, `BaseProgram`, the **full stimulus catalog**, shapes, trajectories, distributions, shared‑memory pixmaps. |
| [`reference-experiment.md`](reference-experiment.md) | `BaseProtocol` (parameter tiers & sequencing), `BaseClient`, `BaseServer`, the PyQt6 GUI, the **HDF5 data format**, and the **config/labpack schema**. |
| [`reference-device.md`](reference-device.md) | DAQ triggering, the locomotion/closed‑loop engine (`LocoClosedLoopManager`), and `KeyTrac`. |
| [`labpack-guide.md`](labpack-guide.md) | How to build a labpack from the template: structure, configs & presets, drivers, and rig servers. |
| [`IMPROVEMENTS.md`](IMPROVEMENTS.md) | A point‑in‑time audit from before 1.0, kept because other docs cite its stable issue numbers (`#N`). Much of it has since been fixed — check the code before acting on anything in it. |

---

## One‑paragraph mental model

A **client** (the PyQt6 GUI, or a plain script) holds a socket connection to a
**server**. The server owns pluggable **modules** — `visual`, `audio`,
`locomotion`, `voltage_out` — behind a `target()` namespace. The `visual`
module is itself a small tree of processes: a root `VisualStimServer` that fans
commands out to **one subprocess per physical screen**, each running a
Qt/OpenGL render loop. A **protocol** object (a `BaseProtocol` subclass in the
labpack) decides, trial by trial, which stimuli to show and how to sweep their
parameters, and drives the run by issuing batched RPC calls
(`manager.target('visual').load_stim(...)`, `target('all').start_stim()`, …).
Recorded runs are written through pluggable data backends — **HDF5 or NWB**.
Closed‑loop VR works by a locomotion source (FicTrac / KeyTrac) streaming the
subject's position into the server, which shares it with every module, so the
scene follows the subject without a round trip through the client.

Vocabulary note: parts of these documents predate the 1.0 renames and still say
target `daq` (now `voltage_out`) and *epoch*/*epoch run* (now *trial*/*series*).
Both spellings work at runtime; `stimpack --check-labpack` reports which ones a
labpack still uses.
