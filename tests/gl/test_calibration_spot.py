"""The calibration spot, on a real GL context.

Its whole job is to put light at a known place in the projector image, so what is tested is that
the light lands where it was asked for -- in projector coordinates, unwarped, on black.
"""
import pytest

pytest.importorskip("numpy")
pytest.importorskip("moderngl")

import numpy as np  # noqa: E402

from stimpack.visual_stim.calibration import CalibrationSpot  # noqa: E402

pytestmark = pytest.mark.gl

SIZE = 96


def render(ctx, aspect_ratio=1.0, **show):
    spot = CalibrationSpot()
    spot.initialize(ctx, aspect_ratio=aspect_ratio)
    if show:
        spot.show(**show)

    target = ctx.simple_framebuffer((SIZE, SIZE))
    target.use()
    target.clear(0.0, 0.0, 0.0, 1.0)
    spot.paint()
    ctx.finish()
    return np.frombuffer(target.read(components=3, alignment=1),
                         dtype=np.uint8).reshape(SIZE, SIZE, 3)


def centroid(image):
    """Where the lit pixels are, in NDC."""
    lit = image[..., 0] > 40
    assert lit.any(), 'nothing was drawn'
    rows, cols = np.nonzero(lit)
    # image row 0 is the bottom of the framebuffer
    return (2 * cols.mean() / (SIZE - 1) - 1, 2 * rows.mean() / (SIZE - 1) - 1)


def test_a_hidden_spot_draws_nothing(headless_gl):
    image = render(headless_gl)
    assert image.max() == 0


@pytest.mark.parametrize('ndc', [(0.0, 0.0), (0.5, 0.0), (-0.6, 0.4), (0.0, -0.7)])
def test_the_spot_lands_where_it_was_asked_for(headless_gl, ndc):
    """A photometer reading is only useful if the position it was taken at is the position the
    correction will be indexed by."""
    image = render(headless_gl, ndc_x=ndc[0], ndc_y=ndc[1], radius=0.12)
    x, y = centroid(image)
    assert abs(x - ndc[0]) < 0.03, f'x off: asked {ndc[0]}, got {x:.3f}'
    assert abs(y - ndc[1]) < 0.03, f'y off: asked {ndc[1]}, got {y:.3f}'


def test_the_rest_of_the_screen_stays_black(headless_gl):
    """A photometer aimed at the spot collects whatever else the screen shows, and on a white bowl
    that is not small."""
    image = render(headless_gl, ndc_x=0.0, ndc_y=0.0, radius=0.1)
    corner = image[:SIZE // 6, :SIZE // 6]
    assert corner.max() == 0, 'the field around the spot is not black'


def test_intensity_is_what_was_asked_for(headless_gl):
    """The reading is taken at a commanded value, so it has to be the one that was commanded."""
    full = render(headless_gl, ndc_x=0, ndc_y=0, radius=0.2, intensity=1.0)
    half = render(headless_gl, ndc_x=0, ndc_y=0, radius=0.2, intensity=0.5)

    assert full[SIZE // 2, SIZE // 2, 0] > 250
    assert 120 <= half[SIZE // 2, SIZE // 2, 0] <= 136


def test_the_spot_is_round_in_the_image_not_in_ndc(headless_gl):
    """NDC is anisotropic -- x spans the width, y the height, and the image is wider than tall --
    so a circle in NDC reaches the photometer as an ellipse."""
    aspect = 1.6
    image = render(headless_gl, aspect_ratio=aspect, ndc_x=0.0, ndc_y=0.0, radius=0.25)

    lit = image[..., 0] > 40
    width = lit.any(axis=0).sum()
    height = lit.any(axis=1).sum()

    # a spot round in the image is taller than it is wide in NDC, by the aspect ratio
    assert height / width == pytest.approx(aspect, rel=0.08), f'{width} wide, {height} tall'
