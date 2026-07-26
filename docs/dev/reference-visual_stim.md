# Reference: `stimpack.visual_stim`

The real‑time OpenGL renderer, its stimulus library, and the geometry/parameter
machinery that feeds it. Uses **moderngl** (GL context, buffers, VAOs, shaders)
and **PyQt6** (`QOpenGLWidget`, windowing), with **PyOpenGL** only on the EGL
path and **numpy** throughout.

> The rendering flow, perspective math, and multi‑screen process model are
> covered in [`ARCHITECTURE.md`](ARCHITECTURE.md) §2, §6, §7. This file is the
> module reference plus the full stimulus catalog.

Files: `stim_server.py`, `framework.py`, `screen.py`, `perspective.py`,
`square.py`, `base.py`, `stimuli.py`, `shapes.py`, `trajectory.py`,
`distribution.py`, `shared_pixmap.py`, `util.py`, `draw.py`.

---

## Render core

### `stim_server.py` — `VisualStimServer(MySocketServer)`
The **root** of the visual subsystem. Launches one screen subprocess per
`Screen` (`launch_screen()` → `launch_server(framework.py, …)`) and stores a
per‑screen RPC client in `self.screen_managers`. Overrides `handle_request_list`
to split requests into:

* **root** functions (registered via `register_function_on_root`): `close`,
  `load_shared_pixmap_stim`, `start_shared_pixmap_stim`,
  `clear_shared_pixmap_stim` — run in the `VisualStimServer` process;
* everything else — forwarded to **every** screen subprocess, after stamping
  `kwargs['t'] = time()` onto `start_stim`/`pause_stim`/`update_stim` so all
  screens share one `t=0`.

Entry points: `launch_stim_server(screen_or_screens, **kwargs)` (spawns the
server subprocess, returns a client), `run_stim_server(...)` (instantiate + loop),
`main()` (argv → `run_stim_server`).

`launch_screen(screen, **kwargs)` selects the windowing backend from
`XDG_SESSION_TYPE`/`QT_QPA_PLATFORM`, sets `DISPLAY`/`QT_QPA_PLATFORM`, forces EGL
on Wayland, serializes the `Screen`, and spawns `framework.py`.

### `framework.py` — `StimDisplay(QOpenGLWidget)`
One per screen subprocess. Owns the moderngl context and the per‑frame render
loop. `main()` deserializes the `Screen`, starts a threaded `MySocketServer`,
builds the `StimDisplay`, and registers ~22 control functions on it.

Selected methods (all RPC‑exposed):

| Method | Effect |
|---|---|
| `initializeGL()` | Creates the GL context (EGL via PyOpenGL, or `moderngl.create_context(require=330)`), enables blend + depth test, initializes the corner square. |
| `paintGL()` | The render loop — see below. |
| `load_stim(name, hold=False, **kwargs)` | Resolve class by name (`get_all_subclasses(BaseProgram)`), instantiate, `initialize(ctx)`, `configure(**kwargs)`. `hold=False` first clears the stim list. |
| `start_stim(t, append_stim_frames=False, pre_render=False, pre_render_timepoints=None)` | Set `stim_start_time`; begin animation from `t`. |
| `stop_stim(print_profile=False)` | Release each stim's VBOs/VAO/program, `destroy()`, clear samplers, reset state. |
| `update_stim(t, **kwargs)` | Dispatch `update(**kwargs)` to each loaded stim (RPC‑driven mid‑stimulus updates). |
| `set_subject_state(state)` | Update `subject_position` (x,y,z,theta,phi,roll). |
| `set_subject_trajectory(x,y,theta)` | Drive the subject viewpoint from trajectories. |
| `corner_square_*`, `set_corner_square`, `show/hide_corner_square` | Photodiode sync‑square control. |
| `set_idle_background(color)` | Interleave/blank color. |
| `save_rendered_movie(path, downsample_xy=4)` | Save appended frames (see caveat below). |
| `import_stim_module(path)` / `unload_stim_module(barcodes=None)` | Runtime load/unload of out‑of‑tree stim modules under a random barcode namespace. |

**`paintGL` per frame:** quit if `shutdown_flag`; `server.process_queue()` (runs
queued RPC handlers on this thread); compute device‑pixel size and per‑subscreen
viewports; clear; if a stim is loaded, choose `t` (wall clock or pre‑render
timepoint), optionally update subject state from a trajectory, compute one
`get_perspective(...)` matrix per subscreen, and `stim.paint_at(...)` each stim;
draw the corner square; `ctx.finish()`; `self.update()` (schedule next frame —
continuous repaint).

### `perspective.py` — `GenPerspective(pa, pb, pc, subject_xyz, horizontal_flip)`
Kooima generalized off‑axis perspective. `.matrix` builds `P·(Mᵀ·T)` as
column‑major float32 bytes for the `Mvp` uniform. `rotx/roty/rotz(theta)` return
a *new* `GenPerspective` with the screen corners rotated about the subject —
this is how heading (yaw/pitch/roll) is realized. `get_perspective(...)` in
`framework.py` composes them: `.rotz(theta).rotx(phi).roty(roll)`.

### `screen.py` — `Screen` and `SubScreen`
`SubScreen(pa, pb, pc, viewport_ll, viewport_width, viewport_height)`: physical
corners in meters (`pa` lower‑left, `pb` lower‑right, `pc` upper‑left) + the NDC
viewport rectangle on the display. `get_viewport(w,h)` converts NDC → device
pixels. `Screen` is a list of subscreens plus `x_display`, `display_index`,
`fullscreen`, `vsync`, corner‑square size/loc/colors, `horizontal_flip`,
`use_egl`. Computes `width`/`height` in meters from the corners. Both
`serialize()`/`deserialize()` for cross‑process transport.

### `square.py` — `SquareProgram`
Standalone GL program drawing the corner photodiode square (a quad in a small
NDC viewport) with per‑frame toggle / on / off / explicit color. Drawn every
frame by `paintGL`. *(On the EGL path `paint()` recreates its program+VBO+VAO
every frame — see [`IMPROVEMENTS.md`](IMPROVEMENTS.md) #7.)*

### `base.py` — `BaseProgram`
Abstract base for every stimulus. Holds the ctx, the shared vertex/fragment
shaders, and pre‑reserved VBOs (sized by `num_tri`, default 500). Contract:

* `configure(*args, **kwargs)` — build‑time params; wrap time‑varying kwargs with
  `make_as_trajectory`; call `add_texture_gl` for textured stims. *(default no‑op)*
* `eval_at(t, subject_position)` — per‑frame: rebuild `self.stim_object`
  (vertices/colors/tex_coords) and/or call `update_texture_gl`. *(default no‑op)*
* `paint_at(t, viewports, perspectives, subject_position)` — calls `eval_at`,
  writes geometry into the VBOs, then renders once per subscreen with that
  subscreen's `Mvp` matrix and viewport.
* `update(*args, **kwargs)` — RPC‑driven mid‑stimulus hook (unused by shipped
  core stimuli; used by some clandinin dot‑field stimuli).
* `add_texture_gl(img, interpolation)` / `update_texture_gl(img)` — texture upload.
* `destroy()` — subclass cleanup (e.g. `PixMap` closes its shared memory).

The shared fragment shader multiplies a texture's `.r` (mono) or `.rgb` by the
vertex color and takes alpha from the vertex color.

### `draw.py` — `draw_screens(screens)`
Offline matplotlib 3D utility to plot each subscreen triangle and its outward
normal (should point toward the origin/viewer). A **calibration/debug tool, not
part of the render loop.**

---

## Stimulus catalog (`stimuli.py`)

Every class subclasses `BaseProgram`; load it by class name. Curved stimuli are
positioned by `theta` (azimuth) / `phi` (elevation) in degrees at a given
`sphere_radius`/`cylinder_radius`. Any numeric kwarg can be given a **trajectory
dict** instead of a constant (see below).

| Class | Key `configure()` params | What it is |
|---|---|---|
| `ConstantBackground` | `color`, `center`, `side_length` | Full‑field constant color box (idle/background). |
| `Floor` | `color`, `z_level`, `side_length` | A flat ground plane. |
| `TexturedGround` | `color`, `z_level`, `side_length`, `rand_seed` | Randomly textured ground (VR floor). |
| `CheckerboardFloor` | `mean`, `contrast`, `center`, `side_length`, `patch_width` | Checkerboard ground plane. |
| `MovingPatch` | `width`, `height`, `sphere_radius`, `color`, `theta`, `phi`, `angle` | Rectangular patch on a sphere. |
| `MovingPatchOnCylinder` | `width`, `height`, `cylinder_radius`, `color`, `theta`, `phi`, `angle` | Patch on a cylinder. |
| `MovingEllipse` | `width`, `height`, `sphere_radius`, `color`, `theta`, `phi`, `angle` | Elliptical patch on a sphere. |
| `MovingEllipseOnCylinder` | … `cylinder_radius` … | Ellipse on a cylinder. |
| `MovingSpot` | `radius`, `sphere_radius`, `color`, `theta`, `phi` | Circular spot on a sphere. **Looming is done by giving `radius` a `Loom` trajectory.** |
| `LoomingCircle` | `radius`, `color`, `starting_distance`, `speed`, `n_steps` | A circle approaching in depth. |
| `UniformWhiteNoise` | `width`, `height`, `sphere_radius`, `distribution_data`, … | Full‑patch temporally‑refreshed noise. |
| `TexturedSphericalPatch` | `width`, `height`, `sphere_radius`, `color`, `theta`, `phi`, `angle`, `n_steps_x`, `n_steps_y` | Base class for textured spherical patches. |
| `RandomGridOnSphericalPatch` | `patch_width`, `patch_height`, `distribution_data`, `update_rate`, `start_seed`, … | Random grid (noise) on a spherical patch. |
| `TexturedCylinder` | `color`, `cylinder_radius`, `cylinder_location`, `cylinder_height`, `theta`, `phi`, `angle` | Base class for cylinder‑textured stimuli. |
| `CylindricalGrating` | `period`, `mean`, `contrast`, `offset`, `grating_angle`, `profile` (`sine`/`square`) | Static grating on a cylinder. |
| `RotatingGrating` | `rate`, `hold_duration`, `period`, … | Drifting grating (rate deg/s). |
| `ExpandingEdges` | `rate`, `period`, `vert_extent`, `theta_offset`, … | Expanding bar edges. |
| `RandomBars` | `period`, `width`, `vert_extent`, `theta_offset`, `background`, … | Random 1‑D bar noise on a cylinder. |
| `RandomGrid` | `patch_width`, `patch_height`, `cylinder_vertical_extent`, `cylinder_angular_extent`, … | Full‑field random 2‑D grid noise. |
| `Checkerboard` | `patch_width`, `patch_height`, … | Static checkerboard on a cylinder. |
| `MovingBox` | `x_length`, `y_length`, `z_length`, `color`, `x`, `y`, `z`, `yaw`, `pitch`, `roll` | A 3‑D box moving in world space (VR). |
| `Tower` | `color`, `cylinder_radius`, `cylinder_height`, `cylinder_location`, `n_faces` | A world‑space cylinder landmark. |
| `Forest` | `color`, `cylinder_radius`, `cylinder_height`, `n_faces`, `cylinder_locations` | Many towers at once. |
| `PixMap` | `memname`, `frame_size`, `rgb_texture`, `width`, `radius`, … | Renders a shared‑memory pixmap stream (see below) onto a cylinder. |

*(The labpacks add many more — dot fields, coherence pulses, `HorizonCylinder`,
`MovingFly`, `ProgressiveStarfield`, etc. — via the same `BaseProgram` contract;
see [`labpack-guide.md`](labpack-guide.md).)*

---

## Geometry — `shapes.py`

`GlVertices` is the CPU‑side mesh container: `vertices` (3×N), `colors` (4×N),
`tex_coords` (2×N). Transform methods (`rotate`, `rotx/y/z`, `scale`,
`translate`, `set_color`, `shift_texture`) each return a new `GlVertices`;
`add()` merges meshes; `.data` interleaves+flattens for the VBO.

Primitives & surfaces: `GlTri`, `GlQuad`, `GlCircle`, `GlCube`, `GlBox`,
`GlSphericalRect`, `GlSphericalTexturedRect`, `GlSphericalEllipse`,
`GlSphericalCirc`, `GlCylindricalWithPhiRect`, `GlCylindricalWithPhiEllipse`,
`GlCylinder` (with texture repeat), and point clouds `GlSphericalPoints`,
`GlCylindricalPoints`, `GlPointCollection`. Curved surfaces are tessellated near
the equator so that heading `(0,0,0)` points down `+y`.

---

## Time‑varying params — `trajectory.py`

Any stimulus kwarg can be a **trajectory dict** `{'name': <TrajClass>, ...}`
instead of a constant. `make_as_trajectory(param)` hydrates the dict into a
`Trajectory` instance (via `stimpack.util.make_as`); a non‑dict passes through
unchanged. `return_for_time_t(param, t)` calls `param.getValue(t)` for a
`Trajectory` else returns the constant.

| Class | Behavior |
|---|---|
| `TVPairs` | Interpolates `(time, value)` pairs (`scipy.interpolate.interp1d`); `kind` selects linear/nearest/etc. |
| `Sinusoid` | `offset + amplitude·sin(2π·frequency·t + …)`. |
| `SinusoidInTimeWindow` | A sinusoid active only within a time window. |
| `Loom` | Angular size of an approaching object (looming). |

---

## Randomized params — `distribution.py`

Mirror of the trajectory system for noise stimuli. `make_as_distribution(dict)`
→ a `Distribution`; each exposes `get_random_values(output_shape)`. Subclasses:
`Uniform`, `Gaussian`, `Binary`, `Ternary`. Noise stimuli seed `np.random`
deterministically (`seed = round(start_seed + t·update_rate)`) so a run is
reproducible.

---

## Shared‑memory pixmaps — `shared_pixmap.py` + the `PixMap` stim

For streaming arbitrary frames (e.g. movies, externally‑generated noise) into the
renderer without going over the RPC socket:

* A **producer** (`SharedPixMapStimulus` subclass, e.g. `WhiteNoise`) creates a
  named `multiprocessing.shared_memory` block and a `sched`+`threading` loop that
  writes frames into it at a nominal frame rate (`genframe()` is the override
  point).
* The **consumer** is the `PixMap` stimulus, loaded with the same `memname`; each
  `eval_at` reinterprets the shared buffer as an ndarray and `update_texture_gl`
  uploads it.

Wired on the server via the root functions `load_shared_pixmap_stim` /
`start_shared_pixmap_stim` / `clear_shared_pixmap_stim`. *(The producer's
`close()` currently leaks the shared block — see
[`IMPROVEMENTS.md`](IMPROVEMENTS.md) #8.)*

---

## `util.py` (visual_stim)

* **Coordinate math** used by `shapes.py`: `rotate(pts, yaw, pitch, roll)`,
  `rot_mat`/`rotx/y/z`, `spherical_to_cartesian`, `cylindrical_to_cartesian`,
  `cylindrical_w_phi_to_cartesian`, `translate`, `scale`, `normalize`.
* `get_rgba(val, def_alpha=1)` — normalize a color name / scalar / len‑3 / len‑4
  to an RGBA tuple.
* `qimage2ndarray(...)` — QImage → ndarray (uses Qt5‑era API; see movie caveat).
* **Dynamic module loading:** `load_stim_module_from_path(path, module_name,
  submodules=['stimuli','trajectory','distribution'])` execs a lab's stim modules
  under a random barcode namespace; `generate_lowercase_barcode(length, existing)`
  and `unload_module(name)` manage them. This is how `import_stim_module` makes
  out‑of‑tree stimuli resolvable by class name (they subclass `BaseProgram`, so
  `get_all_subclasses` finds them).

---

## Extending the renderer

1. **New stimulus:** subclass `BaseProgram` (or `TexturedCylinder`/
   `TexturedSphericalPatch` for textured ones); implement `configure()` and
   `eval_at()`; it is auto‑discovered by name — no registration.
2. **New mesh:** subclass `GlVertices` in `shapes.py`.
3. **New trajectory / distribution:** subclass `Trajectory` / `Distribution`;
   reference it as `{'name': 'YourClass', ...}` inside a stim kwarg.
4. **Ship an out‑of‑tree library:** put `stimuli.py`/`trajectory.py`/
   `distribution.py` in a directory and `import_stim_module(path)` it.
5. **Custom screen geometry:** supply `Screen` objects with lists of `SubScreen`
   corners; `horizontal_flip=True` for rear projection.
