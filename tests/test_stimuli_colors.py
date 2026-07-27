"""
Regression tests for the colour handling fixed in 0.2.0.

UniformWhiteNoise wrapped its sampled intensity as [c, c, c, 1] where c was already a length-1
array, producing a ragged nested sequence. NumPy accepted that until 1.24 and raises on it now,
so on any current install the stimulus did not run at all.

These need no GL context: they cover the CPU-side colour computation that runs before anything
is handed to the GPU.
"""
import warnings

import numpy as np
import pytest

from stimpack.visual_stim.util import get_rgba
from stimpack.visual_stim import stimuli
from stimpack.visual_stim.screen import Screen


def test_size_one_array_is_monochrome():
    assert get_rgba(np.array([0.25])) == (0.25, 0.25, 0.25, 1)


def test_size_one_array_does_not_go_through_deprecated_float():
    # float() on an ndim>0 array is deprecated since NumPy 1.25 and is slated to raise, which
    # would break this stimulus a second time. get_rgba must use .item() instead.
    with warnings.catch_warnings():
        warnings.simplefilter('error', DeprecationWarning)
        assert get_rgba(np.array([0.25])) == (0.25, 0.25, 0.25, 1)
        assert get_rgba(np.float32(0.5))[0] == pytest.approx(0.5)


def test_wrapping_it_first_is_what_broke():
    # The pre-fix expression, kept as executable documentation of the failure.
    c = np.array([0.25])
    with pytest.raises(ValueError, match='inhomogeneous'):
        get_rgba([c, c, c, 1])


def test_uniform_white_noise_evaluates():
    stim = stimuli.UniformWhiteNoise(screen=Screen(fullscreen=False, vsync=False))
    stim.configure(width=10, height=10, update_rate=60.0, start_seed=0)
    stim.eval_at(0.0)                       # raised ValueError before the fix

    colors = stim.stim_object.colors
    assert colors.shape[0] == 4             # r, g, b, a per vertex
    assert np.all((colors[:3] >= 0) & (colors[:3] <= 1))
    # monochrome: the three channels agree on every vertex
    assert np.allclose(colors[0], colors[1]) and np.allclose(colors[1], colors[2])


def test_uniform_white_noise_is_reseeded_per_update_interval():
    stim = stimuli.UniformWhiteNoise(screen=Screen(fullscreen=False, vsync=False))
    stim.configure(width=10, height=10, update_rate=10.0, start_seed=0)

    def intensity(t):
        stim.eval_at(t)
        return float(stim.stim_object.colors[0, 0])

    assert intensity(0.0) == intensity(0.04)        # same 0.1 s bin -> same seed
    assert intensity(0.0) != intensity(0.5)         # a later bin redraws
