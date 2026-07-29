"""Choosing where to measure a rig's brightness falloff.

The GL half (drawing the spot) is in tests/gl/test_calibration_spot.py; this is the part that
decides where the spots go, which is pure arithmetic on a built mesh.
"""
import numpy as np
import pytest

from stimpack.visual_stim.calibration import calibration_samples
from stimpack.visual_stim.curved_screen import (MeasuredFalloff, PinholeProjector,
                                                SphericalSurface, build_screen_mesh,
                                                projector_irradiance)

pytestmark = pytest.mark.unit


def hemisphere_rig():
    surface = SphericalSurface(radius=0.0715, elevation_range=(0, 90),
                               n_azimuth=48, n_elevation=16)
    projector = PinholeProjector(position=(0, 0, 0.302067), look_at=(0, 0, 0),
                                 throw_ratio=1.57523511, aspect_ratio=1.6)
    return surface, projector, build_screen_mesh(surface, projector)


def test_samples_span_the_radius_of_the_image():
    """The residual varies with distance from the centre of the image, so samples bunched where
    there happens to be most screen would spend most readings on one radius."""
    surface, projector, mesh = hemisphere_rig()
    samples = calibration_samples(mesh, projector, n=16)

    lit_radius = MeasuredFalloff.radius_in_image(np.asarray(mesh.ndc)[mesh.lit],
                                                 projector.aspect_ratio)
    assert len(samples.positions) == 16
    span = np.ptp(lit_radius)
    assert samples.radius.min() < lit_radius.min() + 0.1 * span
    assert samples.radius.max() > lit_radius.max() - 0.1 * span

    # roughly even along the radius, rather than clustered
    gaps = np.diff(np.sort(samples.radius))
    assert gaps.max() < 4 * np.median(gaps), f'uneven spacing: {np.round(gaps, 4)}'


def test_samples_are_spread_around_the_image_not_along_one_line():
    """If the optics are not rotationally symmetric, two samples at a similar radius but different
    azimuth disagree and the scatter says so. All on one meridian, that asymmetry would be averaged
    into a radial curve that fits nothing."""
    surface, projector, mesh = hemisphere_rig()
    samples = calibration_samples(mesh, projector, n=16)

    azimuth = np.arctan2(samples.ndc[:, 1], samples.ndc[:, 0])
    # the mean of unit vectors is short when directions are spread, near 1 when they are aligned
    concentration = np.abs(np.mean(np.exp(1j * azimuth)))
    assert concentration < 0.5, f'samples cluster in direction (concentration {concentration:.2f})'


def test_only_lit_points_are_offered():
    """A spot where the projector does not reach measures the room."""
    surface, projector, mesh = hemisphere_rig()
    samples = calibration_samples(mesh, projector, n=16)

    assert np.all(np.abs(samples.ndc) <= 1 + 1e-9), 'a sample falls outside the projector image'
    assert np.all(projector_irradiance(surface, projector, samples.positions) > 0)


def test_the_three_forms_agree_with_each_other():
    """positions go to from_measurements, ndc drives the spot, radius is for plotting -- they have
    to describe the same points."""
    surface, projector, mesh = hemisphere_rig()
    samples = calibration_samples(mesh, projector, n=12)

    assert len(samples.positions) == len(samples.ndc) == len(samples.radius)
    assert np.allclose(projector.to_ndc(samples.positions), samples.ndc, atol=1e-6)
    assert np.allclose(MeasuredFalloff.radius_in_image(samples.ndc, projector.aspect_ratio),
                       samples.radius)


def test_the_samples_feed_straight_into_a_falloff():
    """The whole point of the helper: measure at these, hand the readings back, get a residual."""
    surface, projector, mesh = hemisphere_rig()
    samples = calibration_samples(mesh, projector, n=16)

    true_residual = 1 - 0.3 * samples.radius
    readings = 4.2 * projector_irradiance(surface, projector, samples.positions) * true_residual

    falloff = MeasuredFalloff.from_measurements(samples.positions, readings, surface, projector)
    assert np.allclose(falloff(samples.ndc), true_residual / true_residual.max(), atol=1e-6)


def test_asking_for_more_samples_than_there_are_lit_vertices_is_refused():
    surface, projector, _ = hemisphere_rig()
    coarse = build_screen_mesh(SphericalSurface(radius=0.0715, elevation_range=(0, 90),
                                                n_azimuth=4, n_elevation=2), projector)
    with pytest.raises(ValueError, match='tessellate'):
        calibration_samples(coarse, projector, n=500)
    with pytest.raises(ValueError, match='at least 2'):
        calibration_samples(coarse, projector, n=1)
