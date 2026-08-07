"""The commissioning patterns: concentric annuli, and the beam at the projector's centre.

These are alignment targets, so what matters is that they are *exactly* what they claim. A ring at
44 degrees instead of 45 is invisible on a screen and ruins the measurement someone takes off it --
which is the whole reason the pattern exists. So the geometry is checked against the definition
(angle from the axis) rather than against a previous run of itself.

No GL context needed: this is the CPU-side geometry, before anything reaches the GPU.
"""
import numpy as np
import pytest

from stimpack.visual_stim import shapes, stimuli, util
from stimpack.visual_stim.screen import Screen

pytestmark = pytest.mark.unit


def angles_from_axis(vertices, axis=(0, 1, 0)):
    """Angle of every vertex from `axis`, in degrees."""
    axis = np.asarray(axis, dtype=float)
    axis = axis / np.linalg.norm(axis)
    unit = vertices / np.linalg.norm(vertices, axis=0)
    return np.degrees(np.arccos(np.clip(axis @ unit, -1, 1)))


class TestSphericalAnnuli:

    def test_bands_are_exactly_equal_in_angle(self):
        """The one claim the whole check rests on."""
        annuli = shapes.GlSphericalAnnuli(band_width=5.0, max_radius=45.0, n_azimuth=64)
        edges = np.unique(np.round(angles_from_axis(annuli.vertices), 9))

        assert np.allclose(edges, np.arange(0, 50, 5.0)), f'bands at {edges}'
        widths = np.diff(edges)
        assert np.abs(widths - 5.0).max() < 1e-9, f'unequal bands: {widths}'

    def test_it_is_not_the_tangent_plane_approximation(self):
        """GlSphericalCirc builds a patch by offsetting theta and phi about the patch centre, which
        is exact only to first order. At 45 degrees that lands 1.2 degrees short -- an error far
        larger than anything this pattern is used to measure, so it must not be built that way."""
        bound = np.radians(45.0)
        _, y, _ = util.spherical_to_cartesian(1.0, np.pi / 2 + bound * np.cos(np.pi / 4),
                                              np.pi / 2 + bound * np.sin(np.pi / 4))
        approximate = np.degrees(np.arccos(np.clip(y, -1, 1)))
        assert abs(approximate - 45.0) > 1.0, 'the approximation is better than assumed here'

        annuli = shapes.GlSphericalAnnuli(band_width=45.0, max_radius=45.0, n_azimuth=64)
        assert angles_from_axis(annuli.vertices).max() == pytest.approx(45.0, abs=1e-9)

    def test_every_vertex_is_on_the_sphere(self):
        annuli = shapes.GlSphericalAnnuli(band_width=10, max_radius=40, sphere_radius=0.5)
        assert np.allclose(np.linalg.norm(annuli.vertices, axis=0), 0.5)

    @pytest.mark.parametrize('theta, phi', [(0, 0), (30, 0), (0, -10), (-25, 15), (40, -30)])
    def test_rotating_it_carries_the_rings_with_the_axis(self, theta, phi):
        """Aimed the same way MovingSpot aims a patch, so `center` means the same thing in both."""
        rotation = (np.radians(theta), np.radians(phi), 0)
        axis = util.rotate(np.array([[0.0], [1.0], [0.0]]), *rotation)[:, 0]

        annuli = shapes.GlSphericalAnnuli(band_width=10, max_radius=30,
                                          n_azimuth=64).rotate(*rotation)
        edges = np.unique(np.round(angles_from_axis(annuli.vertices, axis), 6))
        assert np.allclose(edges, [0, 10, 20, 30]), f'rings at {edges} about the aimed axis'

        # And that axis is where MovingSpot would put a spot at the same theta/phi.
        disc = shapes.GlSphericalCirc(circle_radius=1, sphere_radius=1).rotate(*rotation)
        centre = disc.vertices.mean(axis=1)
        centre /= np.linalg.norm(centre)
        assert np.degrees(np.arccos(np.clip(axis @ centre, -1, 1))) < 1e-6

    def test_bands_alternate_and_each_is_one_flat_colour(self):
        annuli = shapes.GlSphericalAnnuli(band_width=10, max_radius=40, colors=(1.0, 0.0),
                                          n_azimuth=32)
        per_band = annuli.colors.reshape(4, 4, 32, 6)
        for band in range(4):
            assert np.ptp(per_band[:, band].reshape(4, -1), axis=1).max() == 0, \
                f'band {band} is not one colour'
        assert list(per_band[0, :, 0, 0]) == [1.0, 0.0, 1.0, 0.0]
        assert np.all(per_band[3] == 1.0), 'alpha must be opaque, or the bands composite'

    def test_a_partial_outer_band_is_rounded_up(self):
        """A truncated band reads as a band of its own, and someone measuring equal widths would
        find one that is not and go hunting for a bug in the warp."""
        annuli = shapes.GlSphericalAnnuli(band_width=7.0, max_radius=20.0, n_azimuth=32)
        edges = np.unique(np.round(angles_from_axis(annuli.vertices), 6))
        assert np.allclose(edges, [0, 7, 14, 21]), f'{edges}: the last band was truncated'

    @pytest.mark.parametrize('kwargs', [
        {'band_width': 0}, {'band_width': -5}, {'max_radius': 0}, {'n_azimuth': 2},
    ])
    def test_nonsense_is_refused(self, kwargs):
        with pytest.raises(ValueError):
            shapes.GlSphericalAnnuli(**kwargs)


class TestAlternatingAnnuli:

    def make(self, **kwargs):
        stim = stimuli.AlternatingAnnuli(screen=Screen(fullscreen=False, vsync=False))
        stim.configure(**kwargs)
        return stim

    def test_configure_builds_the_pattern_without_a_gl_context(self):
        stim = self.make(band_width=5, max_radius=45)
        assert stim.stim_object.vertices.shape[1] % 3 == 0
        edges = np.unique(np.round(angles_from_axis(stim.stim_object.vertices), 6))
        assert np.allclose(edges, np.arange(0, 50, 5.0))

    def test_it_fits_in_the_reserved_buffers(self):
        """BaseProgram reserves num_tri*3 vertices up front; overrunning it silently truncates the
        pattern, which on an alignment target would look like a screen edge that is not there."""
        stim = self.make(band_width=5, max_radius=60, n_azimuth=128)
        assert stim.stim_object.vertices.shape[1] // 3 <= stim.num_tri

    def test_eval_at_does_not_rebuild_it(self):
        """Static on purpose: it is a target to photograph, and rebuilding 3000 triangles a frame
        would cost real time for a pattern that never changes."""
        stim = self.make()
        before = stim.stim_object
        stim.eval_at(0.0)
        stim.eval_at(1.5)
        assert stim.stim_object is before

    def test_the_axis_is_aimed_by_theta_and_phi(self):
        stim = self.make(band_width=10, max_radius=30, theta=0, phi=-10)
        axis = util.rotate(np.array([[0.0], [1.0], [0.0]]), 0, np.radians(-10), 0)[:, 0]
        edges = np.unique(np.round(angles_from_axis(stim.stim_object.vertices, axis), 6))
        assert np.allclose(edges, [0, 10, 20, 30])
