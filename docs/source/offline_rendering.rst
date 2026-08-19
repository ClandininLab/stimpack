==================================
Offline rendering: stimuli to file
==================================

:func:`~stimpack.visual_stim.offline.render_stim` turns stimulus descriptors into frames, PNGs
or an ``.mp4`` -- no rig, no server, no window, no wall clock. Stimuli are pure functions of
time, so an offline render is just a loop over ``t = n / fps``, and two runs on one machine
produce byte-identical output::

    from stimpack.visual_stim.offline import render_stim

    patch = {'name': 'MovingPatch', 'width': 20, 'height': 20, 'color': [1, 0.5, 0, 1],
             'sphere_radius': 1.0, 'angle': 0, 'phi': 0,
             'theta': {'name': 'TVPairs', 'tv_pairs': [(0, -40), (2, 40)], 'kind': 'linear'}}

    render_stim(patch, duration=2.0, fps=60, out='moving_patch.mp4')     # ffmpeg on PATH
    frames = render_stim(patch, duration=2.0, fps=60, out=None)          # (N, H, W, 3) uint8

The descriptors are the same dicts ``load_stim`` takes -- including a saved trial's
``trial_stim_parameters``, passed verbatim (descriptors targeting other modules, a sound say,
are skipped with a warning). ``examples/visual_stim/render_movie_offline.py`` is the runnable
version of the above.

Point-of-view movies
====================

``subject_trajectory`` drives the subject position per frame, with the same trajectory dicts
stimuli use::

    turn = {'theta': {'name': 'TVPairs', 'tv_pairs': [(0, 0), (2, 90)], 'kind': 'linear'}}
    render_stim(patch, duration=2.0, fps=60, subject_trajectory=turn, out='pov.mp4')

For attitude work, note ``Screen(rotation_frame='subject')`` selects intrinsic
yaw -> pitch -> roll (``phi`` is always the subject's own pitch, whatever the heading); the
default ``'world'`` keeps the historical fixed-axis composition every recorded trial used, and
the two agree exactly whenever at most one angle is nonzero. All six subject-state keys are
accepted -- ``x``, ``y``, ``z``, ``theta``, ``phi``, ``roll`` --
so attitude-tracked replays work too, not just planar ones. Because the data file records every
trial's descriptors and (for closed-loop runs) the position history each screen rendered from,
any recorded trial can be re-rendered this way after the fact: the trial from the animal's point
of view, regenerated rather than captured.

On a machine with two GPUs, the default standalone context may land on the integrated one;
pass ``backend='egl'`` (or your own ``ctx=``) to choose. Which device renders affects speed
always and pixels sometimes, so reproducible work should pin it.

What it renders, and what it does not
=====================================

The flat and multi-subscreen path renders here, on a standalone GL context -- the same route the
golden-image tests use, so it works on a machine with no display at all. Deliberate limits:

- **Curved (cube-map) screens** raise: the warp lives in the on-rig renderer. To capture those,
  render on the rig: ``start_stim(t=0, pre_render=True, pre_render_timepoints=...,
  append_stim_frames=True)`` steps the real renderer through explicit timepoints instead of the
  wall clock, and ``save_rendered_movie(path)`` writes the frames -- full fidelity, subframes
  and all. That path needs a windowing system, but not a physical display:
  ``xvfb-run -a python your_script.py`` renders it fully invisibly on any Linux machine
  (measured). What does not work is Qt's ``offscreen`` platform plugin, which refuses to render
  QOpenGLWidget at all -- the reason this module drives GL directly.
- **No photodiode square**: it marks trial timing for acquisition hardware, and a movie has none.
- **One image per timepoint**, whatever the screen's ``subframes`` says -- movies want images,
  not DLP channel packing.

Determinism is per machine and driver: different GPUs legitimately differ in low bits. For
cross-machine comparison, do what ``tests/gl`` does -- pin a software renderer (Mesa) and
compare with a tolerance.

.. autofunction:: stimpack.visual_stim.offline.render_stim

.. autofunction:: stimpack.visual_stim.offline.render_frames
