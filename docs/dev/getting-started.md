# Getting started

A practical path from install to running your own stimulus. For the concepts
behind each step, see [`ARCHITECTURE.md`](ARCHITECTURE.md).

---

## Install

```bash
git clone https://github.com/clandininlab/stimpack
cd stimpack
python3 -m venv ~/.stimpack_env && source ~/.stimpack_env/bin/activate
pip install -e .
```

Requirements: **Python ≥ 3.10** (the code uses `X | Y` type unions at import
time). Core deps (numpy, scipy, pandas, matplotlib, PyQt6, moderngl, h5py,
PyYAML, scikit-image, platformdirs; PyOpenGL on Linux) install automatically. A
GPU with OpenGL 3.3 is required for rendering.

> The README currently tells you to `git checkout beyond_xorg`; that branch is
> stale. Use `main` unless you have a specific reason not to (see
> [`IMPROVEMENTS.md`](IMPROVEMENTS.md) #10).

---

## Run the bundled examples

The `examples/` directory is the fastest way to see the renderer work. Each
script launches its own stim server and plays a stimulus — no config or GUI
needed.

```bash
python examples/1-hello_world.py                  # a windowed Checkerboard, 5 epochs
python examples/visual_stim/show_all.py           # cycles through 14 built-in stimuli
python examples/visual_stim/single_stim.py MovingSpot
python examples/visual_stim/moving_patch.py       # trajectory-driven patch sweep
python examples/visual_stim/loom.py               # looming spot (Loom trajectory)
python examples/visual_stim/vr_walk.py            # a VR walk past towers
python examples/rpc/client.py                     # minimal RPC echo demo
```

The numbered tutorials build up the core ideas:

1. **`1-hello_world.py`** — `launch_stim_server(Screen(...))`, set an idle
   background, `load_stim`/`start_stim`/`stop_stim` in an epoch loop.
2. **`2-custom_screen_server.py`** — define a `SubScreen` with physical `pa/pb/pc`
   corners for perspective‑corrected fullscreen display.
3. **`3-multiple_screens.py`** — two `Screen`s on different `display_index`es
   driven by one server.
4. **`4-custom_stimuli.py`** — `manager.import_stim_module('./example_custom_module/')`
   then `load_stim('ShowImage', image_path='./assets/cactus.png')`.

### The minimal script pattern

```python
from stimpack.visual_stim.stim_server import launch_stim_server
from stimpack.visual_stim.screen import Screen

manager = launch_stim_server(Screen(fullscreen=False, vsync=True))
manager.set_idle_background(0.5)

for _ in range(5):
    manager.load_stim(name='MovingSpot', radius=10, color=[1,1,1,1],
                      theta={'name':'TVPairs','tv_pairs':[[0,-45],[2,45]],'kind':'linear'})
    manager.start_stim()
    # ... sleep(stim_time) ...
    manager.stop_stim()
```

Note the `theta` kwarg is a **trajectory dict** — the server evaluates the motion
frame‑by‑frame; the client sends it once.

---

## Run the experiment GUI

Recording real experiments goes through the GUI (installed as the `stimpack`
console command). The GUI needs a **labpack** — a repo of your lab's configs,
protocols, and stimuli.

```bash
stimpack
```

On first launch, the *Initialize Rig* dialog asks for:

* **Labpack Dir** — point it at your labpack (a template is at
  `github.com/ClandininLab/labpack`). The path persists in stimpack's user‑config
  directory.
* **Config** — pick a `<labpack>/configs/*.yaml`.
* **Rig** — pick a `rig_config` entry from that file.

Then:

* **Main tab** — pick a protocol, choose/edit parameters and a preset, and click
  **View** (no saving) or **Record** (saves to HDF5). Pause/Stop control the run.
* **Subject tab** — enter subject metadata (fields come from the config).
* **File tab** — create/browse the HDF5 data file.
* **Ensemble tab** — chain `(protocol, preset)` runs to play back sequentially.

See [`labpack-guide.md`](labpack-guide.md) for building the labpack the GUI
consumes, and [`reference-experiment.md`](reference-experiment.md) for the config
schema and HDF5 layout.

---

## Add your own stimulus

Two options:

* **Out‑of‑tree (no reinstall):** put a `stimuli.py` in a directory whose classes
  subclass `stimpack.visual_stim.base.BaseProgram`, then
  `manager.import_stim_module('/path/to/dir')` and `load_stim('YourClass', ...)`.
  (See `examples/example_custom_module/` and tutorial 4.)
* **In your labpack:** add the class under `labpack/visual_stim/<name>/stimuli.py`
  and point `module_paths.visual_stim` at it. See
  [`labpack-guide.md`](labpack-guide.md).

Minimal stimulus:

```python
from stimpack.visual_stim.base import BaseProgram
from stimpack.visual_stim import shapes

class MySpot(BaseProgram):
    def configure(self, radius=10, color=(1,1,1,1)):
        self.radius = radius; self.color = color
    def eval_at(self, t, subject_position={}):
        self.stim_object = shapes.GlSphericalCirc(
            circle_radius=self.radius, color=self.color)
```

---

## Troubleshooting pointers

* **"Could not connect to server."** — the server subprocess failed to start
  within 10 s. Run the server script directly to see its stderr (the launcher
  doesn't surface child crashes; see [`IMPROVEMENTS.md`](IMPROVEMENTS.md) #15).
* **Blank/black window on Wayland** — stimpack forces the EGL path on Wayland;
  ensure PyOpenGL is installed. Be aware the EGL corner‑square path has a known
  per‑frame leak ([`IMPROVEMENTS.md`](IMPROVEMENTS.md) #7).
* **Nothing happens after a remote call** — remote RPC calls are fire‑and‑forget
  with no error channel; a typo'd method name is a silent no‑op. Check the server
  process's stdout for `warnings.warn` messages.
