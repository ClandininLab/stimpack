# Potential improvements

A prioritized, **verified** review of stimpack / labpack / clandinin_labpack.
Each finding was checked against the actual code by an independent adversarial
pass; 7 candidate findings were refuted and dropped (see the end). Severities are
calibrated for the real deployment: a **local, single‑operator lab rig on a
trusted network**, so pure‑network security items are weighted down and
mid‑experiment reliability items are weighted up.

Numbers (`#N`) are stable IDs referenced from the other docs.

**How to read this:** items #1–#8 are the ones that can silently break a running
experiment or corrupt the render loop — fix these first. #9–#19 are meaningful
robustness/correctness issues. The rest are cleanups, packaging, and nits, plus
cross‑cutting recommendations at the end.

---

## Status

Work is on a `dev` branch in each repo, all pushed, nothing merged to `main`:
**stimpack 49 commits**, **labpack-template 10**, **clandinin_labpack 1**. Verified by
`ruff` + a **184-test suite** (unit / integration / gui / gl / e2e), which now also runs
whole in a single process. CI is wired but has never executed — an org-level GitHub
Actions billing lock.

**Fixed (35 of the 46 findings):** #1, #2, #3, #4, #6, #7\*, #8, #9\*, #10, #11, #12\*\*,
#13, #14, #15, #16, #17, #18, #19, #20, #21, #22†, #23†, #24, #25, #26, #27, #28, #29,
#30, #34, #35, #36, #37, #38, #39, #40, #41, #42, #43, plus the `numpy.matlib` deprecation.
<br>†#22/#23 fixed for the highest-value instances; a few low-risk sites remain.

**Built beyond the original review:**
- **Server → client error reporting** (#2 completed both ways): errors are pushed
  back over the socket, recorded by the client, abort the run, and pop a modal GUI
  alert — from root, module (voltage_out/loco), **and** screen subprocesses (Tier-2).
- **Run-outcome recording** (#16): `data.end_epoch_run` writes `run_status`
  (completed/stopped/aborted/error) + reason + end time on the series group;
  `start_run` runs in try/finally and aborts on a dead link or server error.
- **Test suite + CI** (#19, #35): 184 tests across five tiers — including
  golden-image stimulus rendering and **end-to-end runs against a live server with
  real screen and KeyTrac subprocesses** — plus `ruff` and GitHub Actions on 3.10–3.12.
- **`stimpack --check-labpack`**: a preflight for the failure mode behind every silent
  breakage found here — *a name that no longer resolves*. Tiers 1–2 (legacy config keys,
  `module_paths` resolution) import nothing and run at GUI startup; `--deep` adds tiers
  3–5, which import each protocol and **run it against a recording manager** to check
  that every stimulus name resolves and every call is addressed somewhere that exists.
  Validated against clandinin_labpack's pre-migration tree: it reports the untargeted
  `daq_*` calls and the unloadable custom stimuli that were live bugs for months.
- **Deterministic shutdown** — three real bugs found by making the whole suite run in one
  process: `runSeriesThread.__del__` called `self.wait()` (a QThread touched at GC time);
  `ExperimentGUI.closeEvent` never stopped the run thread (reachable by closing the GUI
  mid-series); and `MySocketClient` had no `close()` at all, so its reader thread could
  not be stopped. Plus `BaseClient.close()` now shuts the in-process server down, so
  screens and the detached KeyTrac process stop leaking on GUI exit.
- **Module targeting**: `target('voltage_out')` with `'daq'` aliased and warned once;
  the server advertises its modules on connect, so `protocol.has_module()` lets one
  protocol serve rigs with and without opto.
- **Locomotion/closed-loop fixes** found by those tests: `update_pos` no longer
  fabricates a position when a reading is missing (it was pushing `-pos_0`, which
  would teleport the subject); `loop_stop()` no longer stalls ~5 s; and
  `KeytracClosedLoopManager`'s host/port now reach `KeytracManager`.
- **Screen-error pump**: `VisualStimServer` drained screen queues only when a new
  request arrived, so screen-side errors were stranded — found by the e2e tier.
- `TCP_NODELAY` on RPC sockets; `ServerErrorDemo` protocol and
  `examples/rpc/error_reporting.py`; lazy PyQt6 import so the core is testable headless.

**Cross-repo:** the template was ~2 years stale and the live pack had drifted *past*
stimpack — custom stimuli silently not loading in 11 configs, opto silently not firing,
and opto args on a rewritten driver API. All migrated. The template's package is now
`template_labpack` (it collided with a lab's own `labpack`, so the two could not be
installed side by side), the repo is `labpack-template` and is a GitHub template
repository, and `scripts/rename_package.py` does the rename a new lab should do first.

**Notes / partials:**
- **\*#7** — the per-frame GL *leak* is fixed; the per-frame shader *recompile*
  (a proper EGL state reset) still wants on-rig work.
- **\*#9** — options 0 + A landed (`reject_private_attribute`, error reporting on
  unknown names). The deeper redesign (B/C/D) is still a decision to make. Note this
  bit three times during this work: `getattr(obj, 'x', default)` never falls back, it
  returns an RPC stub.
- **\*\*#12** — stimpack's `BaseServer` now defaults to loopback (audited safe).
  The rigs still bind all interfaces via the labpack wrapper, deliberately: the GUI
  reaches them over their LAN address. Hardening that is an ops decision (firewall /
  specific-IP bind / token auth), not a code default.
- **#5** — named constant + on-rig caveat; the `disable_direct`/gamma question needs
  hardware.

**Still open:**
- *Needs a decision:* #9 (`__getattr__` redesign, options B/C/D).
- *Needs the rig:* deeper #5/#7 (GL gamma / EGL shader recompile); #32 (24× MSAA and a
  24-bit alpha buffer, which can fail config selection on some drivers); and one real
  run per user to validate the migrated opto `channels_config` — those call paths were
  dead, so the first post-migration run is effectively a first run.
- *Wants profiling first, not opinion:* #31 (a full-frame `.tobytes()` copy per frame).
  #33 is **refuted in part**: `CylindricalGrating`'s nested loop is in `configure()`, so it runs
  once per load, not per frame. Only `RandomBars`' 255-element comprehension is in `eval_at()`.
- *Fixed, was mis-filed as polish:* #30. `n_textures_loaded` was the texture *unit index*, assigned
  permanently at load, so an epoch was capped at GL_MAX_TEXTURE_IMAGE_UNITS textured stimuli -- 32
  on the development GPU, 16 on some. A real protocol here loads 31 in one epoch. Past the cap the
  drivers tested render with no GL error, so it fails silently. Each stimulus owns its own shader
  program and draws alone, so one unit is enough: the bind moved into `paint_at`. Measured 0-8%
  *faster* than holding many units bound. `load_stim` now also releases on replace.
- *Remaining polish:* #44.
- *Structural, cross-repo:* #45/#46 (the `example/` vs `clandinin/` fork) and Bruker rig
  server de-duplication (four ~121-line files differing by 1–2 lines).
- *Not code:* the Actions billing lock; nothing merged to `main` in any repo; LAN
  hardening; DAQ/opto hardware-tier tests.

---

## Top priority — can break a live experiment

### #1 [High] RPC dispatch has no exception isolation
`rpc/transceiver.py:67` — `handle_request_list` calls `function(*args, **kwargs)`
with no `try/except`. On a **screen subprocess** this runs inside `paintGL`, so
an exception (a mismatched kwarg, a bad stim parameter) propagates out of a Qt
virtual and aborts the display process via `qFatal`. On `BaseServer`
(`threaded=False`) it runs inline in `loop()`, silently killing the loop thread
and leaving the server alive but permanently unresponsive. **This is the
amplifier that turns several findings below (e.g. #8) into full crashes.**
*Fix:* wrap the call in `try/except Exception`, log the request + traceback, and
continue.

### #2 [High] Outbound RPC swallows only `BrokenPipeError`
`rpc/transceiver.py:49` — `write_request_list` catches `BrokenPipeError` and does
nothing (no log). Two problems: (a) after the server dies, **every** subsequent
call is an invisible no‑op — the client never learns, and `sleep()`‑based epoch
timing marches on regardless; (b) `ConnectionResetError` (a sibling under
`OSError`, not a subclass) is **not** caught, so a peer reset escapes and kills
the sending thread — and because the loco loop sets `looping=True` before that,
it can't be restarted. *Fix:* catch `(BrokenPipeError, ConnectionResetError,
OSError)` uniformly; set a `connection_broken` flag and surface it; have
`start_run` check server health (and `proc.poll()`) each epoch.

### #3 [High] `unload_stim_module` mutates the list it iterates
`visual_stim/framework.py:557` — with `barcodes=None` (exactly what
`on_connection_close` passes) it aliases `barcodes = self.imported_stim_module_names`
and then `remove()`s from that same list while looping — so it unloads only every
*other* module. The skipped modules stay in `sys.modules`, so on the next client
connection re‑importing the same path, `load_stim` hits `assert num_candidates ==
1` (duplicate class) and **raises**. *Fix:* iterate a copy: `barcodes =
list(self.imported_stim_module_names)`.

### #4 [High] Locomotion `receive_message` ignores its own timeout
`device/locomotion/loco_managers/loco_managers.py:115` — the `select` call is
wrapped in `while not ready:`, so a finite `wait_for` (including `wait_for=0`)
never returns on timeout; it busy‑spins until a datagram arrives. `close()` calls
`receive_message(wait_for=0)` to drain, so if the tracker has stopped streaming,
**close hangs**. (In the bundled KeyTrac path a 500 ms heartbeat masks it; a real
tracker that stops does not.) The `if self.sock == -1` guard is dead code.
*Fix:* call `select` once; `if not ready and wait_for is not None: return None`;
only loop when `wait_for is None`.

### #5 [High] `ctx.disable(0x8DB9)` is both a magic constant and the wrong call
`visual_stim/framework.py:213` — intended to disable `GL_FRAMEBUFFER_SRGB` to fix
a gamma mismatch, but in moderngl `ctx.disable(<raw GL enum>)` does **not** touch
sRGB (raw enums need `ctx.disable_direct`); `0x8DB9`'s low bits instead alias
moderngl's own flag bits, so this silently toggles the wrong state. It sits under
a stray `#jcsimon, 5/18/26, debugging` comment while the neighboring lines use
readable `moderngl.BLEND`/`DEPTH_TEST`. *Fix:* use `ctx.disable_direct(0x8DB9)`
with a named `GL_FRAMEBUFFER_SRGB` constant (verify it actually corrects the
gamma), and delete the dated debug comment.

### #6 [Medium] Textured stimuli leak GPU memory every epoch
`visual_stim/framework.py:396` + `base.py:110` — `stop_stim` releases the VBOs,
VAO, and program but never `stim.texture`; `clear_samplers()` only unbinds. With
moderngl's default `gc_mode=None`, the texture is never freed. Every textured
epoch (gratings, noise, images) leaks a texture for the life of the process.
*Fix:* release the texture in `stop_stim`/`destroy()`; consider
`ctx.gc_mode = 'context_gc'` as a safety net.

### #7 [High] EGL corner square rebuilds its GL program every frame
`visual_stim/square.py:107` — on the EGL/Wayland path, `paint()` (called **every
frame**, and the square is drawn unconditionally) recompiles the shader program
and reallocates the VBO/VAO, overwriting the old ones without releasing them.
That is a per‑frame shader compile plus an unbounded GL‑object leak on every EGL
rig, even when no stimulus is running. *Fix:* fix the underlying EGL state reset
(re‑bind the existing program/VAO) rather than recreating; at minimum
`release()` the old objects first.

### #8 [High] `SharedPixMapStimulus.close()` raises `BufferError`
`visual_stim/shared_pixmap.py:29` — `global_frame` holds a live `np.ndarray`
view into `memblock.buf`, so `memblock.close()` raises `BufferError: cannot close
exported pointers exist` on its first line — `unlink()` and `thread.join()` never
run, leaking `/dev/shm` blocks. Combined with #1, this exception **crashes the
visual stim server at the end of the first epoch** of any shared‑pixmap protocol.
*Fix:* drop the ndarray view (`self.global_frame = None`) and join the thread
*before* `close()/unlink()`; reorder so unlink can't race the writer.

---

## Medium — robustness & correctness

### #9 [Medium] The `__getattr__` RPC proxy hides typos and errors
`rpc/transceiver.py:116` (and the `MySocketServer`/`BaseServer`/`MyMultiCall`
proxies) — any missing attribute becomes a fire‑and‑forget send. A misspelled
remote method never raises; it produces at most a once‑per‑message
`warnings.warn` on the server that the client never sees. All remote calls return
`None`, and `hasattr` is always `True`, which also breaks `copy`/`pickle` and
tooling that probes dunder attributes. *Fix:* `raise AttributeError` for names
starting with `_` (fixes copy/pickle immediately); prefer an explicit remote
namespace (`client.target(...)`), and consider request IDs + an optional
error/ack response.

### #10 [Medium] README pins users to the stale `beyond_xorg` branch
`README.md:5` — the install steps say `git checkout beyond_xorg`, but that branch
is 38 commits behind `main` (missing e.g. the gamma‑correction fix) and
contradicts `docs/source/install.rst` (`pip install stimpack`). New users
silently install ~2‑year‑old code. *Fix:* delete the checkout step (use `main` /
PyPI); reconcile README with the Sphinx docs to a single canonical install path.

### #11 [Medium] Unsafe YAML loading of presets and ensembles
`experiment/protocol.py:107` and `experiment/gui.py:691` use
`yaml.load(..., Loader=yaml.Loader)`, which honors `!!python/object/apply:...`
tags → arbitrary code execution when opening a `<Protocol>.yaml` preset (synced
between rigs/labs) or a `.spens` ensemble (opened via a file dialog).
`config_tools` already uses `safe_load`, so this is inconsistent. *Fix:* switch
both to `yaml.safe_load` (drop‑in — the data is plain scalars/lists/dicts).

### #12 [Medium] Unauthenticated RPC control channel exposed on all interfaces
`experiment/server.py:18` defaults `host=''` (`0.0.0.0`), while `MySocketServer`
and `client.py` use `127.0.0.1`. The RPC transport has **no authentication**, and
`framework.py:545` exposes `import_stim_module` over RPC, which `exec`s arbitrary
Python from a filesystem path — so any host that can reach the port can run code
on the rig machine. This is intended for the documented remote‑server mode, but
the all‑interfaces *default* is a footgun. *Fix:* default to `127.0.0.1`; require
an explicit host for remote use and document that the channel must be firewalled
to the trusted rig network.

### #13 [Medium] GUI parameter parser crashes on `inf`/`nan`
`experiment/gui.py:1035` — `parse_param_str` accepts a token as numeric via
`float(s)` (which allows `inf`/`nan`) but then evaluates it with `eval(s)`, which
raises `NameError` for those. The exception propagates out of a Qt slot
(triggered even by `editingFinished`, not just Run) → `qFatal` aborts the app.
*Fix:* replace `eval(s)` with `int(s)`‑then‑`float(s)` or `ast.literal_eval`;
never `eval` GUI text.

### #14 [Medium] Movie‑recording path is broken under PyQt6
`visual_stim/framework.py:323` — `append_stim_frames`/`save_rendered_movie` call
Qt5‑era APIs: `grabFrameBuffer()` (Qt6 is `grabFramebuffer()`),
`convertToFormat(4)` with a raw int (needs the `QImage.Format` enum), and
`byteCount()` (removed). Any attempt to record a stimulus movie raises
immediately. *Fix:* update to the PyQt6 API (`grabFramebuffer`,
`Format.Format_RGB32`, `sizeInBytes()`), accounting for `bytesPerLine` padding.

### #15 [Medium] `launch_server` doesn't detect a dead child
`rpc/launch.py:63` — the connect‑poll loop only catches `ConnectionRefusedError`,
so a child that exits immediately (ImportError in a rig server, missing display,
bad kwargs) still burns the full 10 s and reports only `Exception('Could not
connect to server.')`. Also `atexit.register(proc.wait)` is unbounded — a
non‑auto‑stop server can hang interpreter exit. *Fix:* call `proc.poll()` in the
loop and raise with the child's exit code + command; include cmd/host/port in the
timeout error; bound the atexit wait (`proc.wait(timeout=…)` then terminate).

### #16 [Medium] HDF5 write errors are uncontained; `end_epoch` lacks a guard
`experiment/data.py:173` — `create_epoch_run`/`create_epoch`/`create_note` guard
with `experiment_file_exists()`/`current_subject_exists()`, but `end_epoch` opens
`'r+'` unconditionally. No h5py call is wrapped, and the run executes on a QThread
with no `try/except`, so any `OSError` (file lock, disk full, dropped network
share) mid‑run aborts the whole GUI via `qFatal` — `on_run_finish` never runs,
locomotion keeps streaming, and the acquisition trigger is left dangling. *Fix:*
add the existence guard to `end_epoch`; wrap per‑epoch data ops so a failure calls
`on_run_finish`/`stop_loco` and surfaces the error to the status label.

### #17 [Medium] List‑valued stimulus parameters are silently not saved
`experiment/data.py:151` — `create_epoch` serializes `epoch_stim_parameters` only
when it is a `tuple` or a `dict`, but `protocol.load_stimuli` explicitly supports
a **`list`** of stimuli. A protocol that layers stimuli as a list runs correctly
but its stimulus parameters never reach the HDF5 file — silent metadata loss.
*Fix:* handle the `list` case in `create_epoch` (same per‑stim prefixing as the
`tuple` branch).

### #18 [Medium] Shared‑pixmap frames are scheduled at load time, not start time
`visual_stim/shared_pixmap.py:44` — `load_stream` enqueues every frame with
`sched.enter(ti, …)`, and `sched` fixes absolute deadlines at *enqueue* time. So
frames are timed from load, not from `start_stream`: the noise stream silently
stops updating `(load‑to‑start gap)` seconds early, and a large gap causes a
catch‑up burst. It also materializes `dur·fps` events up front. *Fix:* schedule
inside `start_stream` with `enterabs(self.t + ti, …)`, or use a stoppable
sleep‑until‑deadline loop thread.

### #19 [Medium] No CI runs tests/lint; the test suite is effectively empty
`.github/workflows/python-publish.yml` only builds+publishes on release. The sole
collectable test (`tests/visual_stim/test_hello.py`) asserts nothing; the real
test (`old_test_color_cube.py`) isn't collected and imports names
(`CaveSystem`, `rel_path`) that no longer exist; `common.py` uses PyQt5‑only APIs;
the stray `.travis.yml` has the classic `3.10`‑parses‑as‑`3.1` bug. *Fix:* add a
push/PR workflow running `pytest` (xvfb for GL) + lint/type across 3.10–3.12;
start with unit tests for the non‑GL surface (RPC serialization, `config_tools`,
`data` HDF5 I/O, protocol parameter sequencing); delete the dead `.travis.yml`.

---

## Lower priority — cleanups, correctness‑in‑depth, packaging

### #20 [Low] Config getters crash when `rig_config` is absent
`experiment/util/config_tools.py` (`get_screen_center`/`get_data_directory`/
`get_loco_available`, etc.) and `data.py:62` do
`cfg.get('rig_config').get(...)`, which raises `AttributeError` if `rig_config` is
missing rather than falling back. *Fix:* `cfg.get('rig_config', {})` and guard the
inner lookups.

### #21 [Low] User modules cached under generic `sys.modules` names
`config_tools.py:187` registers labpack modules as `'protocol'`, `'data'`,
`'client'`, `'daq'` — extremely common names that can collide with any installed
package of the same name. *Fix:* namespace them (e.g. `stimpack_labpack.<name>`)
or use the barcode scheme already used for stimuli.

### #22 [Low] Mutable default arguments
`visual_stim/stim_server.py:60` (`screens=[]`), `experiment/server.py:20`
(`visual_stim_kwargs={}` — actually mutated with a `'screens'` key),
`visual_stim/util.py:41` (`existing_barcodes=[]`), and the `subject_position={}`
defaults in `base.py`. Shared‑mutable‑default is a classic latent bug. *Fix:* use
`None` sentinels.

### #23 [Low] `assert` used for runtime validation
`framework.py:355` (`load_stim` "exactly one candidate"), `transceiver.py:34`
(duplicate function name), `util.make_as`, and various color/length asserts are
stripped under `python -O`, turning validation errors into silent wrong behavior.
*Fix:* raise explicit exceptions.

### #24 [Low] `client.py` forwards a non‑existent `return_process_handle` kwarg
`experiment/client.py:57` calls `launch_server(..., return_process_handle=True)`,
but `launch_server` has no such parameter — it lands in `**kwargs`, gets
JSON‑serialized, and is passed to the server subprocess as a bogus option. *Fix:*
remove it (`launch_server` already returns `(client, proc)`).

### #25 [Low] `loop_start` sets the `looping` flag inside the worker thread
`loco_managers.py:431` — the guard checks `loop_attrs['looping']` but the flag is
set *inside* the spawned thread, so two rapid `loop_start()` calls can both pass
the guard and start two readers on one socket. *Fix:* set the flag in
`loop_start` before spawning.

### #26 [Low] Closed‑loop thread has no exception handling
`loco_managers.py:430` — `loop_helper` has no `try/except`, so one malformed
datagram (a `_parse_line`/`float()` error) permanently and silently stops
closed‑loop updates mid‑run. *Fix:* wrap the loop body; log and continue.

### #27 [Low] `JSONDecodeError` silently discards RPC requests
`rpc/transceiver.py:241` (and the client loop) `continue` on a decode error, so a
corrupted/oversized line is dropped with no trace. *Fix:* at least warn with the
offending bytes.

### #28 [Low] `MyMultiCall.__call__` doesn't clear its request list
`rpc/multicall.py:20` — invoking the same instance twice re‑sends everything. The
protocol code always makes a fresh instance, so it's latent, but surprising.
*Fix:* clear `self.request_list` after flushing (or document single‑use).

### #29 [Low] `VisualStimServer` mutates shared request dicts under `target='all'`
`visual_stim/stim_server.py:131` — it injects `kwargs['t']` into request dicts
that (for `'all'`) are the same objects delivered to other modules. *Fix:*
copy before mutating.

### #30 [Low] `load_stim` drops previous stims without releasing GL resources
`framework.py:348` — `hold=False` replaces `self.stim_list` without releasing the
old stims' buffers (only `stop_stim` releases), and the `ctx.extra
['n_textures_loaded']` counter only resets in `stop_stim`, so repeated loads grow
it. *Fix:* release on replacement; centralize GL teardown in `destroy()`.

### #31 [Low] Per‑frame full‑frame texture copy
`visual_stim/base.py:127` — `update_texture_gl` does `texture_image.tobytes()`
every frame, copying the whole frame. *Fix:* write from a contiguous buffer /
reuse a preallocated array where possible.

### #32 [Low] Surface format requests 24× MSAA and a 24‑bit alpha buffer
`framework.py:620` — `setSamples(24)` and `setAlphaBufferSize(24)` are unusual
(alpha is normally 8 bits); this wastes framebuffer memory/fill or can fail config
selection on some drivers. *Fix:* use sane values (e.g. 4–8× MSAA, 8‑bit alpha)
and confirm on target hardware.

### #33 [Low] Per‑frame Python loops build grating/bar textures
`visual_stim/stimuli.py:687` (`CylindricalGrating` angled texture) and `:929`
(`RandomBars`) rebuild textures with scalar Python loops/comprehensions every
frame. *Fix:* vectorize with numpy.

### #34 [Low] `setup.py`: no `python_requires`, unpinned deps, non‑canonical names
`setup.py:3,11` — the code needs Python ≥ 3.10 (PEP 604 unions at import) but
`python_requires` is unset; `install_requires` has no version bounds; and
`'PyQT6'`/`'pyYaml'` use non‑canonical casing. *Fix:* add
`python_requires='>=3.10'`, pin lower bounds, and use `PyQt6`/`PyYAML`.

### #35 [Low] No `pyproject.toml`, no lint/type config
Despite recently added type hints, there's no `pyproject.toml`, ruff/flake8, or
mypy config. *Fix:* add a `pyproject.toml` (PEP 621 metadata + tool config) and a
minimal lint/type setup.

### #36 [Low] labpack packaging omits its subpackages
`labpack/setup.py:10` hardcodes `packages=['labpack']` (no `find_packages`), ships
no `__init__.py` files, and doesn't declare `stimpack`/`numpy`/`scipy` — so a
`pip install` of the template is incomplete. *Fix:* `find_packages()`, add
`__init__.py`, declare real dependencies.

### #37 [Low] `CONTRIBUTING.md` references a nonexistent branch and CI gate
`CONTRIBUTING.md:6` documents a `master` branch and a CI test‑gate that don't
exist. *Fix:* update to the real branch/CI once #19 lands.

### #38 [Low] Thin docstrings on the RPC backbone
`rpc/transceiver.py` — the client‑server core the README advertises has little
docstring coverage. *Fix:* document the wire protocol, the `__getattr__`
semantics, and threading expectations on the public methods.

### #39 [Nit] Window‑title ternary precedence bug
`framework.py:45` — `setWindowTitle(f'…{screen.name}' + " (EGL)" if screen.use_egl
else "")` parses as `(f'…' + " (EGL)") if use_egl else ""`, so a **non‑EGL**
window gets an **empty** title. *Fix:* parenthesize:
`f'…{screen.name}' + (" (EGL)" if screen.use_egl else "")`.

### #40 [Nit] Ineffective invariant assert
`loco_managers.py:158` — `assert endline != 1` should be `assert endline != -1`
(the comment says "must always be at least one linebreak"; `rfind` returns `-1`,
not `1`). *Fix:* correct the comparison.

### #41 [Low] `h5io` opens files read‑write for read‑only queries
`experiment/util/h5io.py:22` — `get_attributes_from_group` opens `'r+'` just to
read attrs (blocks concurrent readers, can fail on read‑only files) and
mishandles a list‑valued `additional_exclusions`. *Fix:* open `'r'` for queries;
normalize the exclusions argument.

### #42 [Nit] Name‑mangled `__estimate_run_time` blocks subclass override
`experiment/protocol.py:187` — the double‑underscore mangling prevents subclasses
from overriding it. *Fix:* single underscore unless private‑by‑design is intended.

### #43 [Nit] `profile_frame_times` grows unbounded while loaded‑but‑not‑started
`framework.py:299` — appended every frame between `load_stim` and `start_stim`.
*Fix:* only accumulate while started, or cap it.

### #44 [Nit] Loose/incorrect type hints in the RPC layer
`rpc/transceiver.py:117` — `*args: list, **kwargs: dict, -> callable` are
misleading. *Fix:* `*args: Any, **kwargs: Any` and `Callable[..., None]`.

### #45 [Nit] Duplicated dead color code across both labpacks
`clandinin/stimuli.py` (and the labpack template) — `MovingEllipsoid`/`MovingFly`
carry the same commented‑out time‑varying‑color block, silently ignoring color.
*Fix:* implement or delete, in one place (see #46).

### #46 [Low] Cross‑repo fork of the stim‑extension library
`labpack/visual_stim/example/*` (template) and
`clandinin_labpack/labpack/visual_stim/clandinin/*` are parallel forks of the
same extension library (shapes/util helpers, `MovingEllipsoid`, `SparseBinary`,
loom trajectories), drifting independently. *Fix:* factor the shared extensions
into one importable module the two labpacks depend on, rather than copy‑forking.
(Note: the per‑user *protocol* proliferation in clandinin_labpack is **not** a
defect — it's the intended per‑researcher ownership model.)

---

## Cross‑cutting recommendations

These themes tie many of the individual findings together; addressing them at the
theme level is higher‑leverage than one‑off fixes.

1. **Make the RPC layer fail loudly, not silently** (#1, #2, #9, #15, #27). The
   fire‑and‑forget design is fine for throughput, but it currently has *no*
   failure path: dispatch exceptions crash processes, write errors vanish, typos
   no‑op, and dead children look like timeouts. Add per‑request exception
   isolation, a connection‑health flag, child‑death detection, and — ideally — an
   optional request‑ID/ack channel so callers can detect and abort on failure.
   This single theme covers the majority of the "can break a live experiment"
   risk.

2. **Give GL resources a single, disciplined lifecycle** (#6, #7, #8, #30). Move
   all GL teardown into `BaseProgram.destroy()` (so subclasses like `PixMap`
   extend one place), release textures and the corner‑square objects, reset the
   texture‑unit counter there, and set `ctx.gc_mode = 'context_gc'` as a safety
   net. Fix the EGL corner‑square state reset so it stops rebuilding per frame.

3. **Stand up real tests and CI** (#19, and it would have caught #3, #8, #13,
   #14, #17, #39). Start with the non‑GL surface — RPC serialization,
   `config_tools`, `data` HDF5 round‑trips, protocol parameter sequencing — which
   is fast, deterministic, and currently completely untested. Add a headless‑GL
   smoke test (the `common.py` harness already has the bones). Run everything on
   push/PR.

4. **Modernize packaging and docs** (#10, #34, #35, #36, #37). A `pyproject.toml`
   with `python_requires>=3.10`, pinned/canonical deps, a lint/type config, and a
   README that matches the Sphinx docs would remove a class of onboarding
   friction.

5. **Harden configuration handling** (#11, #20, #21, #23). Use `safe_load`
   everywhere, navigate `cfg` defensively, namespace dynamically‑loaded modules,
   and replace `assert`‑based validation with real exceptions so `python -O`
   doesn't change behavior.

6. **De‑duplicate the labpack extension libraries** (#45, #46) so the template and
   the live lab code don't drift.

---

## What was checked and refuted

The following candidate findings were investigated and **dropped** as not real
(kept here so they aren't re‑raised):

* *"O(n²) `np.concatenate` per frame dominates CPU in shapes.py"* — geometry is
  rebuilt per frame (confirmed) but not via quadratic accumulation; `paint_at`
  runs once per stim per frame, not per viewport.
* *"et/lj protocol files are byte‑identical duplicates"* — true but intended:
  each researcher owns a per‑user protocol module loaded by their own config.
* *"mc_protocol re‑implements trajectory construction instead of using the base
  helper"* — the cited sites do not duplicate `get_moving_patch_parameters`.
* *"`get_kwargs` bare‑except silently starts servers with defaults"* — the
  malformed‑argv path is effectively dead (`Popen` with a list, no shell).
* *"`eval(f'daq.{...}')` trigger string is a code‑execution vector"* — accurate
  mechanically, but the config is trusted lab input; no trust boundary is crossed.
* *"`load_stim_module_from_path` doesn't validate spec before `exec_module`"* — it
  does check `os.path.exists` and constructs the path internally.
* *"labpack `daq.py` imports vendor drivers unconditionally"* — the deps are
  declared in `setup.py`, so `ImportError` can't occur in a proper install.
