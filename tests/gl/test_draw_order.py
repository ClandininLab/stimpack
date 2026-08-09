"""Draw order must not change an opaque scene. Where it still can, and why that is survivable.

An analytic edge carries sub-pixel coverage as alpha, and alpha is order-dependent: a partially
covered fragment writes depth as though it were fully covered, so anything behind it is
depth-rejected and the edge blends against the background instead of against what it actually
overlaps. Two opaque shapes at different depths therefore render differently depending on which is
drawn first.

That is a genuine defect and it is recorded here as one, in the xfail below. What keeps it latent
rather than live is measured in the tests around it:

  - shapes at the same depth are unaffected -- a dot field at one sphere_radius, which is what
    every protocol in the labpack this was found on actually renders
  - the framework's own ordering is the correct one. BaseProtocol.load_stimuli sends
    ConstantBackground before the trial's own stimuli, so the far surface is drawn first, and
    drawing far-first is exactly what makes the blend come out right

So the trap needs a near analytic shape loaded *before* a far one, which nothing does today. These
tests exist so that stops being true loudly rather than quietly.

Fixing it properly means splitting the draw into a global interior pass and a global edge pass --
interiors write depth in any order, then edges blend with depth testing but no depth write. That is
correct regardless of edge order and needs no sorting, but it doubles the draw calls and has to be
global across stim_list rather than per stimulus, so it is an architectural change rather than a
patch. See docs/design/analytic-edges.md.
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


def _screen():
    return Screen(subscreens=[SubScreen(pa=PA, pb=PB, pc=PC)], fullscreen=False, vsync=False)


def _make(ctx, name, **kwargs):
    stim = getattr(stimuli, name)(screen=_screen())
    stim.initialize(ctx)
    stim.configure(**kwargs)
    return stim


def _render(ctx, factories, size=SIZE):
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
        for factory in factories:
            factory().paint_at(0.0, [(0, 0, size, size)], [perspective],
                               subject_position=SUBJECT)
        ctx.finish()
        return np.frombuffer(fbo.read(components=1, alignment=1),
                             dtype=np.uint8).reshape(size, size).astype(int)
    finally:
        fbo.release()


def _differing(ctx, first, second):
    """How many pixels change when the two are drawn the other way round."""
    return int((np.abs(_render(ctx, [first, second]) - _render(ctx, [second, first])) > 0).sum())


def _spot(ctx, sphere_radius, theta, radius=12):
    return lambda: _make(ctx, 'MovingSpot', radius=radius, sphere_radius=sphere_radius,
                         color=[1, 1, 1, 1], theta=theta, phi=0)


def _background(ctx):
    return lambda: _make(ctx, 'ConstantBackground', color=[0.5, 0.5, 0.5, 1.0], side_length=100)


def test_shapes_at_one_depth_do_not_care_about_order(headless_gl):
    """The case every protocol in the labpack actually renders: one sphere_radius for everything.

    Co-planar fragments never depth-reject each other, so the partial-coverage problem below cannot
    arise however they are ordered.
    """
    ctx = headless_gl
    assert _differing(ctx, _spot(ctx, 1.0, -4), _spot(ctx, 1.0, +4)) == 0


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


@pytest.mark.xfail(reason='analytic coverage is alpha, and alpha is order-dependent: a partially '
                          'covered fragment writes depth as if fully covered, so what is behind it '
                          'is rejected. Fixing it means a global interior pass and a global edge '
                          'pass. Latent today -- see this module docstring.',
                   strict=True)
def test_overlapping_shapes_at_different_depths_do_not_care_about_order(headless_gl):
    """The defect itself, stated as the property that ought to hold.

    strict=True on purpose: if someone builds the two-pass split, this starts passing, the xfail
    becomes an error, and whoever did it is told to come back here and to the design note rather
    than leaving a stale 'known bug' behind.
    """
    ctx = headless_gl
    assert _differing(ctx, _spot(ctx, 0.8, -4), _spot(ctx, 2.0, +4)) == 0
