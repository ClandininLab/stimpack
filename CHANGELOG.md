# Changelog

## 0.2.0

The first release since 0.1.0 (November 2023). Roughly two and a half years of work on `main`,
summarised by theme rather than by commit.

### Displays beyond a single X screen

Stimpack no longer assumes Xorg with one X screen per display. The display environment is detected
rather than assumed, so Wayland, Xorg with several screens per display, Windows and macOS all work.
On Linux under Wayland an EGL context is created and handed to ModernGL; elsewhere GLX is used, and
`Screen(use_egl=...)` overrides the choice.

### Screens and geometry

- `SubScreen` describes a screen by its physical corners in metres plus a viewport on the display,
  so several subscreens can share one display device.
- Vertex arrays are created once and released when a stimulus stops, rather than rebuilt per frame.
- Window sizing uses the available geometry when not fullscreen.
- A frame counter and a debug mode that reports GL errors.

### Protocols and the GUI

- Several user protocol modules can be loaded at once, and the dropdown marks which module each
  protocol came from.
- Example protocols are separated from the framework, so a labpack's own protocols stand alone.
- `pre_run_time` and `post_run_time` run parameters, included in the run-time estimate.
- Ensembles: the protocol page is disabled while one runs, and preset dialogs open in the preset
  directory.
- An *update subject* button writes the metadata currently entered in the Subject tab into the
  HDF5 file.
- Server-side state-dependent control can be defined in the protocol.

### Configuration and module loading

- Custom stimulus modules are loaded from labpack-relative paths given in the config, rather than
  from absolute paths.
- A local server can be launched automatically from the config.
- Stimulus modules are unloaded when a connection drops.

### Devices

- Type hints and stronger checks through the DAQ and client classes.
- `send_trigger` and `output_step` take optional types.
- KeyTrac resets its position in `set_pos_0`, and prefixes its output.

### Fixes

- Gamma correction mismatch between rendered geometry and `glClear`.
- `cartesian_to_spherical`.
- A specified local server exits gracefully.
- The error message box uses the right icon.
- **`UniformWhiteNoise` did not run at all.** It wrapped an already-array intensity as
  `[c, c, c, 1]`, a ragged nested sequence that NumPy has refused since 1.24 — so on any current
  install the stimulus raised `ValueError` the moment it was evaluated.
- **`get_rgba` called `float()` on an array**, which NumPy deprecated in 1.25 and intends to
  raise on. That is the same defect one release from recurring, and it would take every
  distribution-driven monochrome stimulus with it.
- **The startup dialogs re-ran `QWidget.__init__` on themselves.** Both are created by their
  callers as `Cls(parent=dialog)`, and `setupUI` then constructed the same widget a second time.
  That is undefined behaviour in PyQt: the widget is destroyed out from under the object still
  referencing it, so a session that opens the dialog more than a couple of times can die with a
  `RuntimeError` or a segfault far from the cause.

### Tests

This release adds a small test suite covering the three fixes above (`tests/`). It is the
beginning of one, not a comprehensive suite — the broader test tiers live on the development
branch and arrive with the next release.

### Notes on versioning

Three version numbers were in flight before this release, and it is worth recording why this one
skips ahead:

- **0.1.0** is what PyPI has, from November 2023.
- **0.1.1** was set in `setup.py` in May 2024 but never published.
- **v0.1.2** is a tag from September 2024 that points at a commit on the `nwb_integration` branch,
  not on `main`. It is left in place, since it may have been installed from, but it does not name
  an ancestor of this release.

0.2.0 is therefore the first number that is unambiguously above everything that came before.
