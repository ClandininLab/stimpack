# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

stimpack presents multisensory stimuli to a subject, in open or closed loop, and records what was
presented with timing precise enough to align it with whatever the rig acquires alongside. It drives perspective-corrected visual displays, movement trackers
and analog output hardware from one protocol. Everything lab-specific — rig geometry, hardware
drivers, protocols — lives outside the package in a **labpack**; stimpack never imports from one.

Python ≥ 3.10 (PEP 604 unions are evaluated at import time). `main` holds the 0.2.0 release; the
`dev` branch carries the 1.0 work, versioned `1.0.0.dev0` and containing the breaking renames
described below.

## Commands

```bash
pip install -e .[test]

ruff check .                        # what CI lints with (F + E9 only; docs/ excluded)

pytest -m unit                      # ~5s; pure logic, no GL/GUI/hardware
pytest -m "integration or gui"      # real objects over a fake RPC link; PyQt6 GUI offscreen
pytest -m gl                        # needs an OpenGL context; skips if none
pytest -m e2e                       # live server + real screen subprocesses; skips without GL
pytest                              # everything in one process — the only tier that catches
                                    # cross-tier state leaks (QThread teardown bugs)

pytest tests/unit/test_rpc.py::test_name -x          # single test
pytest -m gl --update-goldens                        # regenerate tests/gl/reference/, then review
xvfb-run -a pytest                                   # fully invisible run
```

`-m hardware` needs a real rig and never runs in CI. GL goldens must be regenerated on
software/Mesa so their tolerances stay portable.

Against a real labpack:

```bash
stimpack --check-labpack            # config keys + module_paths; imports nothing
stimpack --check-labpack --deep     # imports each protocol, checks where its calls land
stimpack                            # the experiment GUI
```

Docs: `cd docs && make html` (Sphinx, sources in `docs/source/`).

CI (`.github/workflows/test.yml`) runs the tiers separately so a failure names the layer. `e2e`
and the whole-suite run are `continue-on-error` — they are informational, the tiers above them gate.

## Architecture

Read `docs/dev/ARCHITECTURE.md` for the long version, but note it predates the 1.0 renames below
(it says target `daq` in places, and *epoch*/*epoch run* for *trial*/*series*); its own header
says so. `docs/source/` is the current, authoritative documentation and is kept in step with the
code.

### Processes wired by fire-and-forget RPC

```
ExperimentGUI ── BaseClient ──socket── BaseServer ──┬── visual      ── one subprocess per Screen (GL)
                                                    ├── locomotion  ── tracker
                                                    ├── voltage_out ── DAQ
                                                    └── audio       ── sound card
```

One message is one line of newline-delimited JSON: a list of
`{"name", "args", "kwargs", "target"}`. **There are no responses, no return values, no error
channel on the request path.** `__getattr__` proxies make remote calls look local, which has three
consequences worth internalizing:

- A mistyped name still produces a callable. `hasattr`/`getattr(obj, x, default)` are useless for
  asking whether the far end supports something — use `BaseProtocol.has_server_function()` /
  `has_module()`, populated by `BaseServer.on_connection_open`.
- The server reports what it can back over the same socket (`report_server_message`): **error**
  aborts the run, **warning** does not. The distinction is deliberate — "this rig has no opto" is a
  legitimate difference between rigs; "this call reached nothing" is a bug.
- `reject_private_attribute` keeps introspection (`__deepcopy__`, `_repr_html_`) from becoming
  network traffic.

Calls that must land together are batched with `MyMultiCall` — one JSON line, one
`handle_request_list`. `__call__` clears the batch on dispatch, so an instance can be refilled and
called again.

### Target routing (`BaseServer.handle_request_list`)

| `target` | Goes to |
|---|---|
| absent → `root` | `functions_on_root` **only** — not the modules |
| `visual` / `locomotion` / `voltage_out` / `audio` | that module |
| `all` | every module; each ignores names it does not define |

An untargeted call that finds nothing on root is an **error** (it was meant for something and
reached nothing); an explicit `target('root')` miss is a warning (labs register rig-specific
functions there). `target('all')` is what you want for "whichever module handles this".
`ROOT_FUNCTION_NAMES` in `experiment/server.py` must stay in step with the registrations in
`__init__` — an e2e test asserts it.

The `visual` module is itself a mini-server: `VisualStimServer` fans each request out to one
subprocess per `Screen`, and stamps `kwargs['t'] = time()` on `start_stim`/`pause_stim`/`update_stim`
so every screen shares one `t=0`.

### The module contract

A *module* is a role, not a type: anything in `BaseServer.modules` with `handle_request_list`.
`BaseManager` (`stimpack/module.py`) is the standard implementation for modules that execute
requests as calls on themselves and own hardware — error isolation per handler, unknown names
reported rather than dropped, `target('all')` broadcasts quietly skipped. `VisualStimServer`
deliberately does **not** inherit it: it is a transceiver, and an inherited no-op default would
shadow `__getattr__` forwarding to the screens.

Naming rule: a **Server** serves sockets, a **Manager** owns hardware.

### Run lifecycle

A **run** (series) of **trials**. Parameters live in tiers: `run_parameters` (per run),
`protocol_parameters` (per run; a list value of length > 1 is a *swept dimension*, tuples are
single values), `trial_protocol_parameters` (the chosen value per trial), `trial_stim_parameters`
(the stimulus descriptor; an entry may carry a `target`, defaulting to `visual`).
`all_combinations` picks Cartesian product vs. zip-and-tile.

The client ships a declarative descriptor once — including trajectory dicts, hydrated server-side
by `make_as`/`make_as_trajectory` — and the server evaluates motion frame by frame against the
shared clock. The client does no per-frame math. Trial timing is client-side `sleep()` and is
therefore approximate; the photodiode corner square (`visual_stim/square.py`) is the authoritative
timing record.

RPC handlers on a screen run **inside `paintGL`**, serialized with drawing.

### Naming migration (pre-1.0 → 1.0)

Renaming would break every labpack (one lab has ~1500 references), so both spellings work and each
old name warns once per process. `stimpack/experiment/deprecated_names.py` holds the machinery
(`deprecated_method`, `deprecated_attribute`, `calls_legacy_override`, `RunParameters`). When
touching any of these paths, keep both spellings working:

- epoch → **trial**, epoch run → **series** (matching NWB's vocabulary)
- `num_epochs` → `num_trials`, `get_epoch_parameters` → `get_trial_parameters`
- target `daq` → `voltage_out` (the capability, not the device category)
- `stimpack.device.*` → `stimpack.daq` / `stimpack.locomotion` (`stimpack/device/` is a re-export
  shim, removed in 2.0)

Aliases are scheduled for removal in 2.0; `--check-labpack` reports which ones a labpack uses.

### The labpack boundary

Labpack modules (`protocol`, `data`, `client`, `daq`) are imported **by file path** from
`cfg['module_paths']`, so a broken path fails quietly — which is exactly what
`experiment/util/check_labpack.py` exists to catch. Custom stimuli go a different route:
`import_stim_module(path)` execs the lab's `stimuli.py`/`trajectory.py`/`distribution.py` under a
random namespace, and because they subclass the same `BaseProgram`/`Trajectory`/`Distribution` they
become resolvable by name through `get_all_subclasses` — no registration step.
`other_stim_module_paths` was removed in 1.0; import from the client instead.

## Conventions

- Comments explain **why**, at length where the reasoning is non-obvious (a past bug, a subtle
  interaction, a rejected alternative). Match that density; a comment restating the code is noise.
- Commit messages are imperative sentences describing the change's intent, not conventional-commit
  prefixes: *"Rename BaseModule to BaseManager: 'module' is a role, no class defines it"*.
- Changes to loading, routing or naming can break a labpack silently. Run `--check-labpack` against
  a real one, and prefer reporting over dropping.
- Tests must not take over the desktop: `QT_QPA_PLATFORM=offscreen` and `STIMPACK_NO_FOCUS=1` are
  `setdefault` in `tests/conftest.py`, and screen-building tests use `helpers.unobtrusive_screen`.
- Shared test doubles are in `tests/fakes.py` and `tests/helpers.py` (deliberately not a conftest —
  tier directories are not packages and the name would collide).
