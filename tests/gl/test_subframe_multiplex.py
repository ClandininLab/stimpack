"""Packing three timepoints into the colour channels of one frame.

A DLPC350 in video-pattern mode can read the three 8-bit channels of a frame as three successive
patterns, so a 120 Hz video link drives a 360 Hz monochrome display. The renderer's side of that is
to draw three timepoints per frame and mask each into one channel.

What has to be true, and what these check:

  - the three channels carry *different* moments, not three copies of one
  - they are in the right temporal order, since which channel the projector shows first is set by
    its pattern LUT and is therefore configuration, not a constant
  - a masked pass leaves the other channels alone, which is what lets three passes share one
    framebuffer with no intermediate textures

An error in the ordering is the dangerous one: three frames scrambled in time still look like
motion, just wrong.
"""
import pytest

pytest.importorskip("numpy")
pytest.importorskip("moderngl")

import moderngl  # noqa: E402
import numpy as np  # noqa: E402

from stimpack.visual_stim.screen import Screen  # noqa: E402

pytestmark = pytest.mark.gl

VS = '#version 330\nin vec2 pos;\nvoid main(){ gl_Position = vec4(pos, 0.0, 1.0); }'
FS = '#version 330\nuniform float level;\nout vec4 f;\nvoid main(){ f = vec4(level, level, level, 1.0); }'


def ramp_program(ctx):
    """A full-screen fill whose brightness is a function of time, so each subframe differs."""
    program = ctx.program(vertex_shader=VS, fragment_shader=FS)
    quad = ctx.buffer(np.array([-1, -1, 3, -1, -1, 3], dtype='f4').tobytes())
    return program, ctx.vertex_array(program, [(quad, '2f', 'pos')])


def render_packed(ctx, screen, brightness_at, size=8):
    """Render one display frame through the subframe loop, and read the packed pixel back."""
    target = ctx.simple_framebuffer((size, size))
    target.use()
    target.color_mask = (True, True, True, True)
    target.clear(0.0, 0.0, 0.0, 1.0)

    program, vao = ramp_program(ctx)
    try:
        for subframe, mask in enumerate(screen.subframe_color_masks()):
            target.color_mask = mask
            target.clear(0.0, 0.0, 0.0, 1.0)
            program['level'].value = brightness_at(subframe * screen.subframe_interval)
            vao.render(moderngl.TRIANGLES, vertices=3)
        target.color_mask = (True, True, True, True)
        ctx.finish()
        return np.frombuffer(target.read(components=3, alignment=1), dtype=np.uint8)[:3] / 255.0
    finally:
        vao.release(); program.release(); target.release()


# --- the screen's own bookkeeping ----------------------------------------------------------------

def test_subframe_interval_is_the_pattern_rate():
    screen = Screen(subframes=3, refresh_rate=120)
    assert 1 / screen.subframe_interval == pytest.approx(360)


def test_one_subframe_is_ordinary_rendering():
    """The default has to be a no-op, or every existing rig changes behaviour."""
    screen = Screen()
    assert screen.subframes == 1
    assert screen.subframe_interval == 0.0
    assert screen.subframe_color_masks() == [(True, True, True, True)]


def test_channel_order_is_configuration_not_a_constant():
    """Which channel the projector shows first comes from its pattern LUT."""
    masks = Screen(subframes=3, refresh_rate=120,
                   subframe_channel_order=(2, 0, 1)).subframe_color_masks()
    assert masks[0] == (False, False, True, True), 'first subframe should go to blue'
    assert masks[1] == (True, False, False, True), 'second to red'
    assert masks[2] == (False, True, False, True), 'third to green'


@pytest.mark.parametrize('kwargs, reason', [
    (dict(subframes=2), 'only 1 or 3 map onto 8-bit channels'),
    (dict(subframes=3), 'refresh_rate is needed to space them in time'),
    (dict(subframes=3, refresh_rate=120, subframe_channel_order=(0, 0, 1)), 'not a permutation'),
])
def test_nonsense_configurations_are_rejected(kwargs, reason):
    with pytest.raises(ValueError):
        Screen(**kwargs)


# --- what actually lands in the framebuffer ------------------------------------------------------

def test_the_three_channels_carry_three_different_moments(headless_gl):
    """The whole point: if all three held the same instant, this would be a 120 Hz display with
    extra steps."""
    ctx = headless_gl
    screen = Screen(subframes=3, refresh_rate=120)

    # brightness ramps steeply enough that 1/360 s is clearly visible
    packed = render_packed(ctx, screen, brightness_at=lambda dt: 0.2 + 100.0 * dt)

    assert len(set(np.round(packed, 2))) == 3, f'channels are not distinct: {packed}'
    assert packed[0] < packed[1] < packed[2], f'not increasing with time: {packed}'


def test_the_channels_follow_the_configured_order(headless_gl):
    """Reordering the LUT must reorder where the timepoints land, or the configuration is a lie."""
    ctx = headless_gl
    ramp = lambda dt: 0.2 + 100.0 * dt        # noqa: E731

    default = render_packed(ctx, Screen(subframes=3, refresh_rate=120), ramp)
    swapped = render_packed(ctx, Screen(subframes=3, refresh_rate=120,
                                        subframe_channel_order=(2, 1, 0)), ramp)

    # same three values, reversed across the channels
    assert np.allclose(sorted(default), sorted(swapped), atol=0.01)
    assert np.allclose(default, swapped[::-1], atol=0.01), \
        f'reversing the channel order did not reverse the packing: {default} vs {swapped}'


def test_a_masked_pass_leaves_the_other_channels_alone(headless_gl):
    """Three passes share one framebuffer with no intermediate textures, which only works because a
    masked clear and a masked draw both touch just their own channel."""
    ctx = headless_gl
    target = ctx.simple_framebuffer((8, 8))
    target.use()
    target.color_mask = (True, True, True, True)
    target.clear(1.0, 1.0, 1.0, 1.0)                 # start white

    program, vao = ramp_program(ctx)
    try:
        target.color_mask = (False, True, False, True)
        target.clear(0.0, 0.0, 0.0, 1.0)
        program['level'].value = 0.0
        vao.render(moderngl.TRIANGLES, vertices=3)   # blacken green only
        target.color_mask = (True, True, True, True)
        ctx.finish()
        px = np.frombuffer(target.read(components=3, alignment=1), dtype=np.uint8)[:3]
    finally:
        vao.release(); program.release(); target.release()

    assert px[0] > 250 and px[2] > 250, f'a masked pass touched other channels: {px}'
    assert px[1] < 5, f'the masked channel was not written: {px}'


def test_a_single_subframe_screen_renders_greyscale_as_before(headless_gl):
    """subframes=1 must leave all three channels equal -- the existing behaviour, unchanged."""
    ctx = headless_gl
    packed = render_packed(ctx, Screen(), brightness_at=lambda dt: 0.5)
    assert np.allclose(packed, packed[0], atol=0.01), f'channels diverged at subframes=1: {packed}'
