"""Do the rendered rings land at the angles they claim?

The unit tests check the geometry the stimulus builds. This checks the thing someone at a rig
actually looks at: pixels. A ring boundary at 20 degrees has to arrive 20 degrees off axis in the
rendered image, because the whole use of this pattern is measuring positions off a photograph of it.

Rendered through a flat screen with a known frustum rather than through the cube map, deliberately.
On a flat screen spanning +-45 degrees a direction at angle t lands at NDC tan(t) / tan(45), which
is an independent closed-form answer -- so this tests the stimulus against trigonometry rather than
against the renderer it would be checking.
"""
import pytest

pytest.importorskip("numpy")
pytest.importorskip("moderngl")

import numpy as np  # noqa: E402

from stimpack.visual_stim import stimuli  # noqa: E402
from stimpack.visual_stim.framework import get_perspective  # noqa: E402
from stimpack.visual_stim.screen import Screen, SubScreen  # noqa: E402

pytestmark = pytest.mark.gl

SIZE = 512
# A flat screen 60 cm square at 30 cm: exactly +-45 degrees, so NDC is tan(angle).
PA, PB, PC = (-0.30, 0.30, -0.30), (+0.30, 0.30, -0.30), (-0.30, 0.30, +0.30)
SUBJECT = {'x': 0, 'y': 0, 'z': 0, 'theta': 0, 'phi': 0, 'roll': 0}


def render_annuli(ctx, **configure):
    screen = Screen(subscreens=[SubScreen(pa=PA, pb=PB, pc=PC)], fullscreen=False, vsync=False)
    stim = stimuli.AlternatingAnnuli(screen=screen)
    stim.initialize(ctx)
    stim.configure(**configure)

    fbo = ctx.simple_framebuffer((SIZE, SIZE))
    fbo.use()
    fbo.clear(0.5, 0.5, 0.5, 1.0)          # grey, so both ring colours are distinguishable from it
    stim.paint_at(0.0, [(0, 0, SIZE, SIZE)], [get_perspective(SUBJECT, PA, PB, PC, False)],
                  subject_position=SUBJECT)
    ctx.finish()
    image = np.frombuffer(fbo.read(components=1, alignment=1), dtype=np.uint8).reshape(SIZE, SIZE)
    fbo.release()
    return image


def to_angle(boundary_index):
    """Pixel *boundary* `boundary_index` as an angle, through the frustum used here.

    Boundaries, not centres: a hard edge shows up as a change between two pixels, so what has been
    located is the line between them. Pixel i spans NDC i/(SIZE/2) - 1 to (i+1)/(SIZE/2) - 1, and
    on this screen NDC is tan(angle).
    """
    return np.degrees(np.arctan(boundary_index / (SIZE / 2) - 1.0))


def boundaries_along_centre_row(image):
    """Angles, in degrees, where the pattern changes value, right of the centre."""
    row = image[SIZE // 2].astype(int)
    changes = np.flatnonzero(np.abs(np.diff(row)) > 60)
    angles = to_angle(changes + 1)
    return angles[angles > 0]


def test_ring_boundaries_land_at_the_angles_they_claim(headless_gl):
    image = render_annuli(headless_gl, band_width=10.0, max_radius=40.0, colors=(1.0, 0.0),
                          theta=0, phi=0, n_azimuth=256)

    found = boundaries_along_centre_row(image)
    expected = [10.0, 20.0, 30.0, 40.0]
    assert len(found) == len(expected), f'expected boundaries at {expected}, found {found}'
    # One pixel is 0.13 degrees at the outermost ring here, and the ring polygon at n_azimuth=256
    # is wrong by 3e-5 of that -- so this tolerance is rasterisation, and nothing else. A real
    # geometry error, such as building the pattern in the tangent plane, is 1.2 degrees at 45.
    assert np.allclose(found, expected, atol=0.15), f'boundaries at {found}, expected {expected}'


def test_the_bands_really_are_equal_width_in_angle(headless_gl):
    """Stated separately from where they start, because that is the claim someone measures."""
    image = render_annuli(headless_gl, band_width=8.0, max_radius=40.0, colors=(1.0, 0.0),
                          theta=0, phi=0, n_azimuth=256)
    found = boundaries_along_centre_row(image)
    widths = np.diff(np.concatenate([[0.0], found]))
    assert np.allclose(widths, 8.0, atol=0.15), f'band widths {widths}, expected 8 degrees each'


def test_the_pattern_is_centred_where_it_is_aimed(headless_gl):
    """An off-axis pattern is the case that matters: the rings are aimed at the screen's axis, not
    at the subject's forward direction, so getting this wrong would mis-centre every rig with a
    tilted screen -- the exact thing the protocol is used to check."""
    # A single bright disc of 10 degrees radius, so its edges are unambiguous.
    image = render_annuli(headless_gl, band_width=10.0, max_radius=10.0, colors=(1.0, 0.0),
                          theta=0, phi=-15, n_azimuth=256)

    # Read the disc's top and bottom off the column through azimuth 0. Midpoint and half-extent
    # rather than a centre of mass: a disc projected onto a flat screen off-axis is not symmetric
    # in the image, so its centroid is not its centre, but its two edges still bracket it.
    lit = np.flatnonzero(image[:, SIZE // 2] > 200)
    assert len(lit), 'nothing was drawn'
    bottom, top = to_angle(lit[0]), to_angle(lit[-1] + 1)

    assert (bottom + top) / 2 == pytest.approx(-15.0, abs=0.15), \
        f'pattern centred at elevation {(bottom + top) / 2:.2f}, aimed at -15'
    assert (top - bottom) / 2 == pytest.approx(10.0, abs=0.15), \
        f'disc radius {(top - bottom) / 2:.2f} degrees, configured as 10'
