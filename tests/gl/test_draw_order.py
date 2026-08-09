"""Draw order must not change an opaque scene. Where it does, why, and what the split fixes.

Blending against a depth buffer is order-dependent: a fragment that is only partly covered still
writes depth as though it were opaque, so whatever is behind it is depth-rejected and it blends
against the background instead. An opaque scene then renders differently depending on which
stimulus was drawn first.

**This is not caused by analytic edges.** Any stimulus with ``color`` alpha below 1 has always had
it -- a MovingBox at alpha 0.5, with no analytic edge anywhere in it, is order-dependent by 400
pixels. What analytic edges changed is that every declared boundary is now a partly covered
fragment, so stimuli nobody thinks of as translucent inherit it.

An earlier version of this file called the defect latent, on the grounds that every protocol uses
one ``sphere_radius`` and co-planar fragments cannot depth-reject each other. **The second half of
that is false.** Depth in the buffer is distance along the view axis, not radial distance, so two
spots at the same ``sphere_radius`` and different azimuth sit at cos(theta) apart and do occlude
each other. Measured on 100 same-radius dots, reversing the draw order moved 3519 pixels. It is
live, not latent.

``split_blended_pass`` is the fix, and is on by default: opaque fragments first with depth writes
on, then blended ones with them off. It takes those 3519 pixels to 22. What is left is
blended-on-blended, where neither fragment writes depth -- pinned below so the residue is a known
quantity. The tests here drive ``paint_at`` directly and choose the pass structure themselves, so
they measure both arrangements regardless of what the default is.
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
PA, PB, PC = (-0.30, 0.30, -0.30), (+0.30, 0.30, -0.30), (-0.30, 0.30, +0.30)
SUBJECT = {'x': 0, 'y': 0, 'z': 0, 'theta': 0, 'phi': 0, 'roll': 0}


def _screen(split=False):
    return Screen(subscreens=[SubScreen(pa=PA, pb=PB, pc=PC)], fullscreen=False, vsync=False,
                  split_blended_pass=split)


def _make(ctx, name, **kwargs):
    stim = getattr(stimuli, name)(screen=_screen())
    stim.initialize(ctx)
    stim.configure(**kwargs)
    return stim


def _render(ctx, factories, size=SIZE, split=False):
    """Draw these stimuli in this order, the way paint_subframe walks stim_list.

    Blending and depth testing are what this module is about, and a bare context has neither. Left
    off, two white spots simply overwrite each other identically and every assertion here passes on
    a scene with none of the behaviour under test in it -- which is how the first version of this
    file reported the known defect as fixed.
    """
    ctx.enable(moderngl.BLEND)
    ctx.enable(moderngl.DEPTH_TEST)
    perspective = get_perspective(SUBJECT, PA, PB, PC, False)
    fbo = ctx.simple_framebuffer((size, size))
    try:
        fbo.use()
        fbo.clear(0.0, 0.0, 0.0, 1.0)
        stims = [factory() for factory in factories]
        viewports, perspectives = [(0, 0, size, size)], [perspective]
        if not split:
            for stim in stims:
                stim.paint_at(0.0, viewports, perspectives, subject_position=SUBJECT)
        else:
            # StimDisplay.draw_stimuli, in miniature: opaque fragments with depth writes on, then
            # blended ones with them off.
            for stim in stims:
                stim.paint_at(0.0, viewports, perspectives, subject_position=SUBJECT, pass_kind=1)
            fbo.depth_mask = False
            for stim in stims:
                stim.paint_at(0.0, viewports, perspectives, subject_position=SUBJECT,
                              prepare=False, pass_kind=2)
            fbo.depth_mask = True
        ctx.finish()
        return np.frombuffer(fbo.read(components=1, alignment=1),
                             dtype=np.uint8).reshape(size, size).astype(int)
    finally:
        fbo.release()


def _differing(ctx, first, second, split=False):
    """How many pixels change when the two are drawn the other way round."""
    return int((np.abs(_render(ctx, [first, second], split=split)
                       - _render(ctx, [second, first], split=split)) > 0).sum())


def _spot(ctx, sphere_radius, theta, radius=12):
    return lambda: _make(ctx, 'MovingSpot', radius=radius, sphere_radius=sphere_radius,
                         color=[1, 1, 1, 1], theta=theta, phi=0)


def _background(ctx):
    return lambda: _make(ctx, 'ConstantBackground', color=[0.5, 0.5, 0.5, 1.0], side_length=100)


def test_one_sphere_radius_is_not_one_depth(headless_gl):
    """The correction that made this live rather than latent.

    Depth is distance along the view axis. A spot at azimuth theta on a sphere of radius 1 sits at
    cos(theta), so two spots at the same sphere_radius are at different depths unless they are
    symmetric about the axis -- and every protocol renders exactly this.
    """
    ctx = headless_gl
    assert _differing(ctx, _spot(ctx, 1.0, 0), _spot(ctx, 1.0, 10)) > 0, \
        'same sphere_radius, different azimuth: these are not co-planar and should not behave so'
    assert _differing(ctx, _spot(ctx, 1.0, 0), _spot(ctx, 1.0, 10), split=True) == 0


def test_shapes_that_do_not_overlap_do_not_care_about_order(headless_gl):
    """The control. If this ever fails, something other than partial coverage is order-dependent."""
    ctx = headless_gl
    assert _differing(ctx, _spot(ctx, 0.8, -25, radius=8), _spot(ctx, 2.0, +25, radius=8)) == 0


def test_the_framework_draws_the_background_first_which_is_the_correct_order(headless_gl):
    """Why the defect below is latent rather than live.

    BaseProtocol.load_stimuli sends ConstantBackground before the trial's own stimuli, so the far
    surface is already in the colour buffer when the near one's edge blends over it -- which is the
    order that gives the right answer. Checked against a supersampled reference rather than against
    the other ordering, so this says which one is correct and not merely that they differ.
    """
    ctx = headless_gl
    background, spot = _background(ctx), _spot(ctx, 1.0, 0, radius=15)

    reference = _render(ctx, [background, spot], size=SIZE * 4)
    reference = reference.reshape(SIZE, 4, SIZE, 4).mean(axis=(1, 3))

    far_first = np.abs(_render(ctx, [background, spot]) - reference).mean()
    near_first = np.abs(_render(ctx, [spot, background]) - reference).mean()

    assert far_first < 0.1, f'the shipped ordering is wrong by {far_first:.3f} per pixel'
    assert near_first > 4 * far_first, (
        f'near-first should be visibly worse ({near_first:.3f} vs {far_first:.3f}); if it is not, '
        f'the defect below may have been fixed and this test is no longer measuring anything')


@pytest.mark.xfail(reason='the single pass, which split_blended_pass=False still selects: analytic '
                          'coverage is alpha, and alpha is order-dependent. The test below asserts '
                          'the split fixes it.',
                   strict=True)
def test_overlapping_shapes_at_different_depths_do_not_care_about_order(headless_gl):
    """The defect, as the property that ought to hold, in a single pass.

    strict=True: if this starts passing without the split, something else has fixed order
    dependence and both this and the design note need revisiting.
    """
    ctx = headless_gl
    assert _differing(ctx, _spot(ctx, 0.8, -4), _spot(ctx, 2.0, +4)) == 0


def test_splitting_the_pass_makes_the_order_stop_mattering(headless_gl):
    """The fix, on the case that motivated it: two opaque shapes at different depths."""
    ctx = headless_gl
    before = _differing(ctx, _spot(ctx, 0.8, -4), _spot(ctx, 2.0, +4))
    after = _differing(ctx, _spot(ctx, 0.8, -4), _spot(ctx, 2.0, +4), split=True)

    assert before > 0, 'nothing to fix; the single-pass case is supposed to be order-dependent'
    assert after == 0, f'still {after} px order-dependent with the pass split'


def test_splitting_the_pass_also_fixes_a_translucent_shape_with_no_analytic_edge(headless_gl):
    """The half of this that predates analytic edges.

    A MovingBox is polyhedral and world-space, so nothing declares an equation for it -- but give it
    alpha below 1 and it blends, and blending against a depth buffer has always been
    order-dependent. Whatever the split is worth, it must be worth it here too, or it is a fix for
    edges rather than a fix for blending.
    """
    ctx = headless_gl

    def box(y, alpha):
        return lambda: _make(ctx, 'MovingBox', x_length=0.35, y_length=0.35, z_length=0.35,
                             color=[1, 1, 1, alpha], x=0, y=y, z=0, yaw=0, pitch=0, roll=0)

    assert _differing(ctx, box(1.2, 1.0), box(2.4, 1.0)) == 0, \
        'opaque geometry with no analytic edge should never have been order-dependent'

    before = _differing(ctx, box(1.2, 0.5), box(2.4, 0.5))
    after = _differing(ctx, box(1.2, 0.5), box(2.4, 0.5), split=True)
    assert before > 0, 'a translucent box is supposed to be order-dependent without the split'
    assert after < before / 10, f'translucent box: {before} px -> {after} px, expected far fewer'


def test_what_the_split_does_not_fix_is_blended_against_blended(headless_gl):
    """Stated so the residue is a known quantity rather than a surprise.

    Both fragments are in the second pass, neither writes depth, so they still composite in order.
    It needs per-sample storage to fix, which is what sample-mask coverage would give instead.
    """
    ctx = headless_gl

    # Two translucent shapes are all edge, so the residue is the whole overlap rather than a rim.
    # Distinguishable greys, because blending two shapes of the SAME colour is commutative and
    # would report order-independence whatever the renderer did.
    def faint(sphere_radius, theta, grey):
        return lambda: _make(ctx, 'MovingSpot', radius=12, sphere_radius=sphere_radius,
                             color=[grey, grey, grey, 0.5], theta=theta, phi=0)

    assert _differing(ctx, faint(0.8, -4, 0.25), faint(2.0, +4, 0.9), split=True) > 0, (
        'if this is zero the split has become order-independent for blended-on-blended too, '
        'which it cannot be without per-sample depth -- check what changed')
