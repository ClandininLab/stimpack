"""
Render stimuli offline: no rig, no server, no window, no wall clock.

Frames are a deterministic function of the timepoints you ask for -- stimuli are pure functions
of ``t``, so an offline render is a loop over ``t = n / fps``, not a second rendering path. The
same stimulus descriptors ``manager.load_stim`` takes are accepted here, including a list saved
in a data file, so a recorded trial can be re-rendered after the fact; with
``subject_trajectory`` driving the subject position, that re-render is the trial from the
animal's point of view.

Renders on a standalone GL context (the same route the golden-image tests use), so it works on a
machine with no display at all. What it deliberately does not do:

- **Curved (cube-map) screens.** The warp path lives in the on-rig renderer; offline support for
  it means extracting that from the Qt widget, which is its own project. Flat and multi-subscreen
  screens render here; a ``CurvedScreen`` raises.
- **The photodiode corner square.** It marks trial timing for acquisition hardware; a movie has
  no acquisition hardware. (It is also drawn by the widget, not the stimuli.)
- **Subframe multiplexing.** Frames come out one timepoint each, unpacked, whatever the screen's
  ``subframes`` says -- a movie wants images, not DLP channel packing.
- **Encoding options.** ``.mp4`` shells out to ffmpeg; anything fancier, render PNGs and encode
  yourself.

Determinism is per machine and driver: two runs here are byte-identical, but different GPUs
legitimately differ in low bits. For cross-machine comparisons do what ``tests/gl`` does -- pin a
software renderer (Mesa/llvmpipe) and compare with a tolerance.

Note the Qt *offscreen* platform is NOT a way to run the full widget headless: QOpenGLWidget does
not render there at all (measured: context created, zero frames painted, "QOpenGLWidget is not
supported on this platform"). That is why this module drives the GL context directly.
"""
import os
import shutil
import subprocess
import tempfile
import warnings
from types import SimpleNamespace

import moderngl
import numpy as np

from stimpack.util import get_all_subclasses
from stimpack.visual_stim import stimuli
from stimpack.visual_stim.curved_screen import CurvedScreen
from stimpack.visual_stim.screen import Screen
from stimpack.visual_stim.trajectory import make_as_trajectory, return_for_time_t

DEFAULT_SUBJECT_POSITION = {'x': 0, 'y': 0, 'z': 0, 'theta': 0, 'phi': 0, 'roll': 0}


def _resolve_stim_class(name):
    """The class a descriptor's ``name`` means, by the same rule the on-rig fallback uses:
    global subclass scan, newest definition wins, unknown names fail loudly."""
    candidates = [x for x in get_all_subclasses(stimuli.BaseProgram) if x.__name__ == name]
    if not candidates:
        raise ValueError(f"no stimulus named '{name}'. Import your labpack's stimulus module "
                         f"first; its BaseProgram subclasses become resolvable by name.")
    if len(candidates) > 1:
        warnings.warn(f"{len(candidates)} classes named '{name}' are registered; using the most "
                      f"recent, from {getattr(candidates[-1], '__module__', '?')}.")
    return candidates[-1]


def render_frames(stim_specs, screen=None, timepoints=(0.0,), subject_trajectory=None,
                  size=(512, 512), background=(0.0, 0.0, 0.0, 1.0), ctx=None, backend=None):
    """
    Render stimulus descriptors at the given timepoints. Returns ``(N, H, W, 3)`` uint8.

    :param stim_specs: one descriptor dict or a list of them -- the same
        ``{'name': ..., **params}`` dicts ``load_stim`` takes. Descriptors naming a non-visual
        ``target`` (a sound, say) are skipped with a warning, so a trial's saved
        ``trial_stim_parameters`` can be passed verbatim.
    :param screen: a :class:`~stimpack.visual_stim.screen.Screen`; the default is a single flat
        square screen. Subscreen geometry is honored; a CurvedScreen raises (see module docstring).
    :param timepoints: seconds; each becomes one frame, in order.
    :param subject_trajectory: optional dict with any of ``'x'``, ``'y'``, ``'z'`` (meters) and
        ``'theta'``, ``'phi'``, ``'roll'`` (degrees) mapping to trajectory dicts (e.g.
        ``{'name': 'TVPairs', ...}``) -- the same six keys the live path's subject state carries.
        Drives the subject position per frame: the point-of-view mechanism. Position replayed
        from a recorded trial's log belongs here. (Note ``phi`` pitches about the world's x axis,
        not the yawed subject's own -- see ``get_perspective``.)
    :param size: (width, height) pixels of the output frames.
    :param background: RGBA clear color, the role ``idle_color`` plays on a rig.
    :param ctx: an existing standalone moderngl context to render in (a test's, say). Default:
        create one and release it afterwards.
    :param backend: passed to ``moderngl.create_standalone_context`` when it creates the context.
        On a machine with two GPUs the default backend may pick the integrated one (measured:
        default -> Intel iGPU, ``backend='egl'`` -> the NVIDIA card, on one dual-GPU Linux box);
        which device renders affects speed always and pixels sometimes, so for reproducible work
        pin it -- or build your own context and pass ``ctx=``.
    """
    # Imported here, not at module top: framework pulls in the Qt widget machinery, and this
    # module must import (and its callers' --help must print) on a machine with no GL at all.
    from stimpack.visual_stim.framework import StimDisplay, get_perspective

    if screen is None:
        # square_size=(0, 0): no photodiode square in a movie (and offline never draws one).
        screen = Screen(fullscreen=False, vsync=False, square_size=(0, 0))
    if isinstance(screen, CurvedScreen):
        raise NotImplementedError(
            'offline rendering draws the flat/subscreen path; the curved-screen warp lives in '
            'the on-rig renderer. Render on the rig with start_stim(pre_render=True, ...) and '
            'save_rendered_movie instead.')

    specs = [stim_specs] if isinstance(stim_specs, dict) else list(stim_specs)

    own_ctx = ctx is None
    if own_ctx:
        kwargs = {'backend': backend} if backend is not None else {}
        ctx = moderngl.create_standalone_context(require=330, **kwargs)

    width, height = int(size[0]), int(size[1])
    color_rb = ctx.renderbuffer((width, height))
    depth_rb = ctx.depth_renderbuffer((width, height))
    fbo = ctx.framebuffer(color_attachments=[color_rb], depth_attachment=depth_rb)

    # The same per-frame state the on-rig renderer asserts: separate alpha blend so coverage
    # cannot thin the framebuffer, depth testing for the split blended pass.
    ctx.enable(moderngl.BLEND)
    ctx.enable(moderngl.DEPTH_TEST)
    ctx.blend_func = (moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA,
                      moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA)

    # A stand-in for the widget, so draw_stimuli and release_stims run UNBOUND on it rather than
    # being reimplemented here. They read only .screen, .stim_list and .subject_position, and
    # they carry logic that must not fork -- the split blended pass is what keeps blending
    # independent of draw order, and a copy here would drift from the fix the rig gets.
    shim = SimpleNamespace(screen=screen, stim_list=[], subject_position=dict(DEFAULT_SUBJECT_POSITION))

    try:
        for spec in specs:
            spec = dict(spec)
            target = spec.pop('target', 'visual')
            if target != 'visual':
                warnings.warn(f"skipping descriptor {spec.get('name')!r}: target {target!r} is "
                              f"not renderable offline (this renders the visual module only)")
                continue
            stim = _resolve_stim_class(spec.pop('name'))(screen=screen)
            stim.initialize(ctx)
            stim.kwargs = spec
            stim.configure(**spec)
            shim.stim_list.append(stim)

        trajectories = {}
        if subject_trajectory is not None:
            unknown = set(subject_trajectory) - set(DEFAULT_SUBJECT_POSITION)
            if unknown:
                raise ValueError(f'unknown subject_trajectory keys {sorted(unknown)}; '
                                 f'valid: {sorted(DEFAULT_SUBJECT_POSITION)}')
            trajectories = {key: make_as_trajectory(value)
                            for key, value in subject_trajectory.items()}

        viewports = [sub.get_viewport(width, height) for sub in screen.subscreens]
        frames = np.empty((len(timepoints), height, width, 3), dtype=np.uint8)

        for index, t in enumerate(timepoints):
            t = float(t)
            fbo.use()
            fbo.clear(*background)

            position = dict(DEFAULT_SUBJECT_POSITION)
            for key, trajectory in trajectories.items():
                position[key] = return_for_time_t(trajectory, t)
            shim.subject_position = position

            perspectives = [get_perspective(position, sub.pa, sub.pb, sub.pc,
                                            screen.horizontal_flip,
                                            rotation_frame=screen.rotation_frame)
                            for sub in screen.subscreens]
            StimDisplay.draw_stimuli(shim, t, viewports, perspectives, framebuffer=fbo)

            raw = fbo.read(components=3, alignment=1)
            # GL's origin is bottom-left; an image's is top-left.
            frames[index] = np.flipud(np.frombuffer(raw, np.uint8).reshape(height, width, 3))

        return frames
    finally:
        StimDisplay.release_stims(shim)
        fbo.release()
        color_rb.release()
        depth_rb.release()
        if own_ctx:
            ctx.release()


def render_stim(stim_specs, screen=None, duration=None, fps=30.0, timepoints=None,
                subject_trajectory=None, size=(512, 512), background=(0.0, 0.0, 0.0, 1.0),
                out=None, backend=None):
    """
    Render a stimulus to frames, PNGs or an .mp4 -- :func:`render_frames` plus output handling.

    :param duration: seconds; with ``fps`` it becomes ``timepoints = arange(duration * fps) / fps``.
        Give either this or explicit ``timepoints``.
    :param out: ``None`` returns the ``(N, H, W, 3)`` array; a path ending in ``.mp4`` writes a
        movie (needs ffmpeg on PATH); any other path is a directory that gets one
        ``frame_%05d.png`` per timepoint. Returns the path it wrote.

    Other parameters as in :func:`render_frames`.
    """
    if timepoints is None:
        if duration is None:
            raise ValueError('give duration (with fps), or explicit timepoints')
        timepoints = np.arange(int(round(duration * fps))) / float(fps)

    frames = render_frames(stim_specs, screen=screen, timepoints=timepoints,
                           subject_trajectory=subject_trajectory, size=size,
                           background=background, backend=backend)
    if out is None:
        return frames

    out = str(out)
    if out.endswith('.mp4'):
        _write_mp4(frames, out, fps)
        return out

    os.makedirs(out, exist_ok=True)
    for index, frame in enumerate(frames):
        _write_png(frame, os.path.join(out, f'frame_{index:05d}.png'))
    return out


def _write_png(frame, path):
    # Qt writes the PNG: PyQt6 is already a hard dependency, and pillow/imageio are not.
    # QImage (unlike QPixmap) needs no QApplication.
    from PyQt6.QtGui import QImage
    frame = np.ascontiguousarray(frame)
    height, width, _ = frame.shape
    image = QImage(frame.data, width, height, 3 * width, QImage.Format.Format_RGB888)
    if not image.save(path):
        raise OSError(f'could not write {path}')


def _write_mp4(frames, path, fps):
    if shutil.which('ffmpeg') is None:
        raise RuntimeError('ffmpeg not found on PATH; render to a directory of PNGs instead '
                           '(out=<directory>) and encode however you like')
    with tempfile.TemporaryDirectory() as tmp:
        for index, frame in enumerate(frames):
            _write_png(frame, os.path.join(tmp, f'frame_{index:05d}.png'))
        # pad: yuv420p requires even dimensions; pad rather than scale, so pixels stay pixels.
        result = subprocess.run(
            ['ffmpeg', '-y', '-framerate', str(fps), '-i', os.path.join(tmp, 'frame_%05d.png'),
             '-vf', 'pad=ceil(iw/2)*2:ceil(ih/2)*2', '-pix_fmt', 'yuv420p', path],
            capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f'ffmpeg failed:\n{result.stderr[-2000:]}')
