"""A stimulus must not punch a hole in the window it is drawn in.

Analytic edges carry coverage in alpha, and the default blend function applies
(SRC_ALPHA, ONE_MINUS_SRC_ALPHA) to *all four* channels -- so a partially covered edge pixel
leaves the framebuffer at a*a + (1-a)*dst_a rather than dst_a. Against an opaque background that
is 0.75 at half coverage, and a compositing window manager renders the desktop through it: the rim
of every stimulus goes see-through on screen while looking correct in any RGB-only test.

StimDisplay therefore sets a separate alpha blend function. These tests pin that, at the two
levels it can go wrong -- the GL state the render loop configures, and what actually lands in a
framebuffer when a stimulus is drawn.
"""
import pytest

pytest.importorskip("numpy")
pytest.importorskip("moderngl")

import moderngl  # noqa: E402
import numpy as np  # noqa: E402

from stimpack.visual_stim import stimuli  # noqa: E402
from stimpack.visual_stim.framework import get_perspective  # noqa: E402
from stimpack.visual_stim.screen import Screen, SubScreen  # noqa: E402

pytestmark = pytest.mark.gl

SIZE = 256
PA, PB, PC = (-0.3, 0.3, -0.3), (0.3, 0.3, -0.3), (-0.3, 0.3, 0.3)
SUBJECT = {'x': 0, 'y': 0, 'z': 0, 'theta': 0, 'phi': 0, 'roll': 0}

# What StimDisplay.initializeGL sets. Duplicated deliberately: if that line changes, this test
# should fail rather than follow it.
SEPARATE_ALPHA = (moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA,
                  moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA)


def draw(ctx, name, **kwargs):
    """Draw one stimulus over an opaque background and return the RGBA it produced."""
    screen = Screen(subscreens=[SubScreen(pa=PA, pb=PB, pc=PC)], fullscreen=False, vsync=False)
    stim = getattr(stimuli, name)(screen=screen)
    stim.initialize(ctx)
    stim.configure(**kwargs)
    fbo = ctx.simple_framebuffer((SIZE, SIZE), components=4)
    try:
        fbo.use()
        fbo.clear(0.5, 0.5, 0.5, 1.0)          # an opaque idle background, as a rig has
        stim.paint_at(0.0, [(0, 0, SIZE, SIZE)],
                      [get_perspective(SUBJECT, PA, PB, PC, False)], subject_position=SUBJECT)
        ctx.finish()
        return np.frombuffer(fbo.read(components=4, alignment=1),
                             dtype=np.uint8).reshape(SIZE, SIZE, 4)
    finally:
        fbo.release()


@pytest.mark.parametrize('name, kwargs', [
    ('MovingSpot', dict(radius=15, sphere_radius=1, color=[1, 1, 1, 1], theta=0, phi=0)),
    ('MovingPatch', dict(width=30, height=30, sphere_radius=1, color=[1, 1, 1, 1],
                         theta=0, phi=0)),
    ('MovingEllipse', dict(width=30, height=18, sphere_radius=1, color=[1, 1, 1, 1],
                           theta=0, phi=0)),
])
def test_a_stimulus_leaves_the_framebuffer_opaque(headless_gl, name, kwargs):
    ctx = headless_gl
    ctx.enable(moderngl.BLEND)
    ctx.enable(moderngl.DEPTH_TEST)
    ctx.blend_func = SEPARATE_ALPHA

    image = draw(ctx, name, **kwargs)

    alpha = image[..., 3]
    assert alpha.min() == 255, (
        f'{name} left {(alpha < 255).sum()} pixels below full opacity (min {alpha.min()}); '
        f'the window would be see-through there')


def test_the_separate_blend_costs_nothing_in_colour(headless_gl):
    """The fix must not change the picture -- only what the compositor is told about it."""
    ctx = headless_gl
    ctx.enable(moderngl.BLEND)
    ctx.enable(moderngl.DEPTH_TEST)

    ctx.blend_func = (moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA)
    default = draw(ctx, 'MovingSpot', radius=15, sphere_radius=1, color=[1, 1, 1, 1],
                   theta=0, phi=0)
    ctx.blend_func = SEPARATE_ALPHA
    separate = draw(ctx, 'MovingSpot', radius=15, sphere_radius=1, color=[1, 1, 1, 1],
                    theta=0, phi=0)

    assert np.array_equal(default[..., :3], separate[..., :3]), 'colour changed'
    assert default[..., 3].min() < 255, 'the default blend was expected to leak; it did not'
    assert separate[..., 3].min() == 255


def test_a_translucent_stimulus_still_composites(headless_gl):
    """Alpha is still honoured as a *source* -- what changes is only the destination channel."""
    ctx = headless_gl
    ctx.enable(moderngl.BLEND)
    ctx.enable(moderngl.DEPTH_TEST)
    ctx.blend_func = SEPARATE_ALPHA

    image = draw(ctx, 'MovingPatch', width=30, height=30, sphere_radius=1,
                 color=[1.0, 1.0, 1.0, 0.5], theta=0, phi=0)

    centre = image[SIZE // 2, SIZE // 2]
    assert 150 < int(centre[0]) < 220, (
        f'a half-transparent white patch over mid-grey should land near 191, got {centre[0]}')
    assert image[..., 3].min() == 255
