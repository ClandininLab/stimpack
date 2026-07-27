"""
Regression tests for two stimulus bugs fixed on the nwb_integration branch.

Both were found on the rig rather than by a test, and neither had one, so they are pinned here.
Neither test needs a GL context: both cover the CPU-side geometry/colour computation that runs
before anything is handed to the GPU.
"""
import warnings

import numpy as np
import pytest

from stimpack.visual_stim.util import get_rgba
from stimpack.visual_stim import stimuli
from stimpack.visual_stim.screen import Screen


class TestUniformWhiteNoiseColor:
    """
    UniformWhiteNoise wrapped its sampled intensity as [c, c, c, 1] where c was already a
    length-1 array, producing a ragged nested sequence. NumPy accepted that silently until
    1.24 and raises on it now, so the stimulus did not run at all on any current install.

    The distribution returns an array because the same call samples grids elsewhere;
    get_rgba already treats any size-1 value as monochrome, so it should be handed over as-is.
    """

    def test_size_one_array_is_monochrome(self):
        rgba = get_rgba(np.array([0.25]))
        assert rgba == (0.25, 0.25, 0.25, 1)

    def test_size_one_array_does_not_go_through_deprecated_float(self):
        # float() on an ndim>0 array is deprecated since NumPy 1.25 and is slated to raise, which
        # would break this stimulus a second time. get_rgba must use .item() instead.
        with warnings.catch_warnings():
            warnings.simplefilter('error', DeprecationWarning)
            assert get_rgba(np.array([0.25])) == (0.25, 0.25, 0.25, 1)
            assert get_rgba(np.float32(0.5))[0] == pytest.approx(0.5)

    def test_wrapping_it_first_is_what_broke(self):
        # The pre-fix expression, kept as executable documentation of the failure.
        c = np.array([0.25])
        with pytest.raises(ValueError, match='inhomogeneous'):
            get_rgba([c, c, c, 1])

    def test_eval_at_builds_a_stim_object(self):
        stim = stimuli.UniformWhiteNoise(screen=Screen(fullscreen=False, vsync=False))
        stim.configure(width=10, height=10, update_rate=60.0, start_seed=0)
        stim.eval_at(0.0)                       # raised ValueError before the fix
        colors = stim.stim_object.colors
        assert colors.shape[0] == 4             # r, g, b, a per vertex
        assert np.all((colors[:3] >= 0) & (colors[:3] <= 1))
        # monochrome: the three channels agree on every vertex
        assert np.allclose(colors[0], colors[1]) and np.allclose(colors[1], colors[2])

    def test_intensity_is_reseeded_per_update_interval(self):
        stim = stimuli.UniformWhiteNoise(screen=Screen(fullscreen=False, vsync=False))
        stim.configure(width=10, height=10, update_rate=10.0, start_seed=0)

        def intensity(t):
            stim.eval_at(t)
            return float(stim.stim_object.colors[0, 0])

        assert intensity(0.0) == intensity(0.04)        # same 0.1 s bin -> same seed
        assert intensity(0.0) != intensity(0.5)         # a later bin redraws


class TestRandomGridPatchHeight:
    """
    RandomGrid converted a patch's angular height to meters on the cylinder wall with
    r*tan(theta), which is the rise of a patch spanning 0..theta -- not one centered on the
    horizon, which is what the grid actually lays out. The correct half-angle form is
    2*r*tan(theta/2). The two agree only in the small-angle limit and diverge fast: the old
    formula makes a 60 deg patch 50% too tall, so the grid overshot its stated vertical extent.
    """

    @staticmethod
    def correct(radius, patch_height_deg):
        return 2 * radius * np.tan(np.radians(patch_height_deg / 2))

    @staticmethod
    def old(radius, patch_height_deg):
        return radius * np.tan(np.radians(patch_height_deg))

    def test_subtends_the_requested_angle(self):
        # A patch centered on the horizon spanning +/- h/2 rises r*tan(h/2) each way.
        for radius in (0.5, 1.0, 2.0):
            for h in (5, 15, 30, 60):
                half = self.correct(radius, h) / 2
                assert np.degrees(np.arctan2(half, radius)) == pytest.approx(h / 2)

    def test_old_formula_overshoots_and_the_error_grows(self):
        errors = [self.old(1.0, h) / self.correct(1.0, h) - 1 for h in (5, 15, 30, 60)]
        assert all(e > 0 for e in errors)               # always too tall
        assert errors == sorted(errors)                 # and worse at larger angles
        assert errors[0] < 0.01 and errors[-1] > 0.4    # invisible when small, gross when not

    def test_configured_grid_matches_requested_extent(self, monkeypatch):
        stim = stimuli.RandomGrid(screen=Screen(fullscreen=False, vsync=False))
        # configure() ends by uploading the patch texture, which needs a live GL context. The
        # geometry under test is all computed before that, so stub the upload out.
        monkeypatch.setattr(type(stim), 'add_texture_gl', lambda self, *a, **k: None)
        radius, patch_height, extent = 1.0, 15, 60
        stim.configure(patch_width=15, patch_height=patch_height, cylinder_radius=radius,
                       cylinder_vertical_extent=extent)

        assert stim.n_patches_height == extent // patch_height
        # The cylinder is exactly as tall as its patches stacked at the correct per-patch height.
        assert stim.cylinder_height == pytest.approx(
            stim.n_patches_height * self.correct(radius, patch_height))
        # The old formula built a cylinder taller than the extent the caller asked for.
        assert stim.n_patches_height * self.old(radius, patch_height) > stim.cylinder_height
