"""Offline rendering: deterministic, t-driven, full-color frames with no rig and no window.

Rendered against the same standalone-context route the golden tests use, so these run (and skip)
exactly where the rest of the gl tier does. Determinism claims here are per-machine, like the
goldens: byte-identity across runs on one driver, tolerance across drivers.
"""
import shutil

import numpy as np
import pytest

from stimpack.visual_stim.offline import render_frames, render_stim

pytestmark = pytest.mark.gl

PATCH = {'name': 'MovingPatch', 'width': 20, 'height': 20, 'color': [1, 0, 0, 1],
         'theta': 0, 'phi': 0, 'sphere_radius': 1.0, 'angle': 0}

SWEEP = {'name': 'TVPairs', 'tv_pairs': [(0.0, 0.0), (1.0, 60.0)], 'kind': 'linear'}
STILL = {'name': 'TVPairs', 'tv_pairs': [(0.0, 0.0), (1.0, 0.0)], 'kind': 'linear'}


def test_frames_have_the_promised_shape(headless_gl):
    frames = render_frames(PATCH, timepoints=[0.0, 0.1, 0.2], size=(96, 64), ctx=headless_gl)
    assert frames.shape == (3, 64, 96, 3)
    assert frames.dtype == np.uint8


def test_rendering_is_deterministic(headless_gl):
    once = render_frames(PATCH, timepoints=[0.0, 0.1], size=(64, 64), ctx=headless_gl)
    twice = render_frames(PATCH, timepoints=[0.0, 0.1], size=(64, 64), ctx=headless_gl)
    assert np.array_equal(once, twice)


def test_color_survives_capture(headless_gl):
    """A red stimulus renders red. The rig-side capture path lost everything but the blue
    channel for years; this pins the offline path never doing that."""
    frames = render_frames(PATCH, timepoints=[0.0], size=(64, 64), ctx=headless_gl)
    assert frames[..., 0].max() > 100        # red is there
    assert frames[..., 2].max() == 0         # and did not leak into blue


def test_a_subject_trajectory_moves_the_view(headless_gl):
    """The point-of-view mechanism: the same stimulus at the same t renders differently when the
    subject has turned -- which is what makes re-rendering a recorded trial a POV movie."""
    still = render_frames(PATCH, timepoints=[0.9], size=(64, 64), ctx=headless_gl,
                          subject_trajectory={'theta': STILL})
    turned = render_frames(PATCH, timepoints=[0.9], size=(64, 64), ctx=headless_gl,
                           subject_trajectory={'theta': SWEEP})
    assert not np.array_equal(still, turned)


def test_audio_descriptors_are_skipped_not_fatal(headless_gl):
    """A trial's saved trial_stim_parameters can be fed verbatim: non-visual descriptors are
    skipped with a warning, and the visual ones still render."""
    specs = [PATCH, {'name': 'SineSong', 'target': 'audio', 'duration': 1.0, 'freq': 225.0}]
    with pytest.warns(UserWarning, match="target 'audio'"):
        frames = render_frames(specs, timepoints=[0.0], size=(64, 64), ctx=headless_gl)
    assert frames[..., 0].max() > 100


def test_duration_and_fps_make_the_expected_timepoints(headless_gl, monkeypatch):
    seen = {}

    def spy(stim_specs, **kwargs):
        seen['timepoints'] = kwargs['timepoints']
        return np.zeros((len(kwargs['timepoints']), 2, 2, 3), dtype=np.uint8)

    monkeypatch.setattr('stimpack.visual_stim.offline.render_frames', spy)
    render_stim(PATCH, duration=0.2, fps=30.0)
    assert np.allclose(seen['timepoints'], np.arange(6) / 30.0)


def test_png_directory_output(headless_gl, tmp_path):
    out = render_stim(PATCH, timepoints=[0.0, 0.1], size=(32, 32), out=str(tmp_path / 'frames'))
    written = sorted(p.name for p in (tmp_path / 'frames').iterdir())
    assert written == ['frame_00000.png', 'frame_00001.png']
    assert out == str(tmp_path / 'frames')


@pytest.mark.skipif(shutil.which('ffmpeg') is None, reason='ffmpeg not on PATH')
def test_mp4_output(headless_gl, tmp_path):
    out = render_stim(PATCH, timepoints=[0.0, 0.1, 0.2], size=(33, 33),   # odd size: pad filter
                      fps=30.0, out=str(tmp_path / 'movie.mp4'))
    assert (tmp_path / 'movie.mp4').stat().st_size > 0
    assert out.endswith('movie.mp4')


# --- the rig-side capture path's storage, exercised without GL -----------------------------------

def test_save_rendered_movie_handles_both_frame_shapes(tmp_path):
    """(H, W) frames (subframe capture) stack to (H', W', N); (H, W, 3) frames (full color)
    stack to (H', W', 3, N) -- color channels must not be spatially averaged away."""
    from types import SimpleNamespace
    from stimpack.visual_stim.framework import StimDisplay

    gray = SimpleNamespace(stim_frames=[np.zeros((8, 8), dtype=np.uint8)] * 3)
    StimDisplay.save_rendered_movie(gray, str(tmp_path / 'gray.npy'), downsample_xy=2)
    assert np.load(tmp_path / 'gray.npy').shape == (4, 4, 3)

    color = SimpleNamespace(stim_frames=[np.zeros((8, 8, 3), dtype=np.uint8)] * 3)
    StimDisplay.save_rendered_movie(color, str(tmp_path / 'color.npy'), downsample_xy=2)
    assert np.load(tmp_path / 'color.npy').shape == (4, 4, 3, 3)
