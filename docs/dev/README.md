# Stimpack documentation

Generated documentation for the **stimpack** visual‑stimulus framework and its
lab‑customization packages **labpack** (template) and **clandinin_labpack** (the
Clandinin Lab's live instantiation).

Stimpack is a client/server system for **precise, perspective‑corrected visual
stimulation of a subject (typically a walking fly) in VR**, together with the
experiment‑control, data‑saving, optogenetics/DAQ‑triggering and closed‑loop
locomotion machinery that surrounds a neuroscience rig.

---

## The three packages at a glance

| Package | Repo | Role |
|---|---|---|
| **stimpack** | `github.com/ClandininLab/stimpack` | The framework. Rendering engine, RPC layer, experiment orchestrator, device abstractions. Lab‑agnostic. |
| **labpack** | `github.com/clandininlab/labpack` | A minimal **template** a lab clones and fills in: `Client`/`Data`/protocol/DAQ subclasses, custom stimuli, and a rig config YAML. Almost all passthrough. |
| **clandinin_labpack** | `github.com/ClandininLab/clandinin_labpack` | The Clandinin Lab's **real** labpack: ~15 per‑user protocol modules, rig server scripts, Lightcrafter/LabJack/FicTrac drivers, and per‑user configs & presets. |

The dependency direction is strictly one‑way: **labpack/clandinin_labpack import
from stimpack; stimpack never imports from them.** A labpack is discovered at
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
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Process topology, the RPC protocol & `target()` routing, the epoch/run lifecycle, an end‑to‑end data‑flow walkthrough, and the threading/process model. **Read this first.** |
| [`getting-started.md`](getting-started.md) | Install, run the bundled examples, launch the experiment GUI, and write your first protocol / config / custom stimulus. |
| [`reference-rpc.md`](reference-rpc.md) | `stimpack.rpc` — `MyTransceiver`, `MySocketClient/Server`, `launch_server`, `MyMultiCall`, the wire codec. |
| [`reference-visual_stim.md`](reference-visual_stim.md) | The renderer: `VisualStimServer`, per‑screen `StimDisplay`, perspective math, `Screen`/`SubScreen`, `BaseProgram`, the **full stimulus catalog**, shapes, trajectories, distributions, shared‑memory pixmaps. |
| [`reference-experiment.md`](reference-experiment.md) | `BaseProtocol` (parameter tiers & sequencing), `BaseClient`, `BaseServer`, the PyQt6 GUI, the **HDF5 data format**, and the **config/labpack schema**. |
| [`reference-device.md`](reference-device.md) | `DAQ` triggering, the locomotion/closed‑loop engine (`LocoClosedLoopManager`), and `KeyTrac`. |
| [`labpack-guide.md`](labpack-guide.md) | How to build a labpack, plus a tour of the Clandinin instantiation: rig servers, the DLPC350 Lightcrafter driver, FicTrac integration, configs & presets. |
| [`IMPROVEMENTS.md`](IMPROVEMENTS.md) | A prioritized, verified list of potential improvements (bugs, resource leaks, robustness, API, security, packaging, docs/tests). |

---

## One‑paragraph mental model

A **client** (the PyQt6 GUI, or a plain script) holds a socket connection to a
**server**. The server owns pluggable **modules** — `visual`, `locomotion`,
`daq` — behind a `target()` namespace. The `visual` module is itself a small
tree of processes: a root `VisualStimServer` that fans commands out to **one
subprocess per physical screen**, each running a Qt/OpenGL render loop. A
**protocol** object (user‑subclassed `BaseProtocol`) decides, epoch by epoch,
which stimulus to show and how to sweep its parameters, and drives the run by
issuing batched RPC calls (`manager.target('visual').load_stim(...)`,
`start_stim(...)`, …). Recorded runs are written to an **HDF5** file. Closed‑loop
VR works by a locomotion source (FicTrac / KeyTrac) streaming the subject's
position back into the server, which forwards it to the renderer's perspective
transform so the scene follows the animal.

*These docs were generated from a full read of the three repositories; the
observations in `IMPROVEMENTS.md` were independently verified against the code.*
