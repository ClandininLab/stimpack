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

from stimpack.visual_stim.screen import (  # noqa: E402
    CHANNEL_NAMES, Screen, channel_indices, channel_names)

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
    (dict(subframes=4), 'a frame has only three channels to carry timepoints in'),
    (dict(subframes=0), 'a frame carries at least one'),
    (dict(subframes=3, refresh_rate=120, subframe_channel_order=(0, 0, 1)), 'not a permutation'),
])
def test_nonsense_configurations_are_rejected(kwargs, reason):
    with pytest.raises(ValueError):
        Screen(**kwargs)


def test_two_subframes_are_allowed():
    """The ceiling is the three channels of a frame, not a choice of 1 or 3: a rig with two usable
    LEDs, or one trading rate for exposure, wants two."""
    screen = Screen(subframes=2, refresh_rate=120)

    assert 1 / screen.subframe_interval == pytest.approx(240)
    assert screen.subframe_color_masks() == [(True, False, False, True),
                                             (False, True, False, True)]
    assert screen.subframe_channel_names() == ('red', 'green')


def test_the_channel_order_survives_a_change_of_subframes():
    """It stays a full permutation at any count, so switching 3 -> 2 -> 3 does not quietly lose
    which channel goes first."""
    screen = Screen(subframes=3, refresh_rate=120, subframe_channel_order=(2, 1, 0))

    screen.set_subframes(2)
    assert screen.subframe_channel_names() == ('blue', 'green')

    screen.set_subframes(3)
    assert screen.subframe_channel_names() == ('blue', 'green', 'red')


def test_names_and_masks_describe_the_same_permutation():
    """The two readings of one permutation. A rig configures its projector by name and the renderer
    by index; if these could disagree, a labpack setting both would have no way to notice."""
    screen = Screen(subframes=3, refresh_rate=120, subframe_channel_order=(2, 0, 1))

    for name, mask in zip(screen.subframe_channel_names(), screen.subframe_color_masks()):
        written = [CHANNEL_NAMES[i] for i, writable in enumerate(mask[:3]) if writable]
        assert written == [name], f'mask {mask} does not write {name}'


def test_names_and_indices_are_inverses():
    order = (2, 0, 1)
    assert channel_names(order) == ('blue', 'red', 'green')
    assert channel_indices(channel_names(order)) == order


@pytest.mark.parametrize('bad', [
    lambda: channel_names((0, 3)),
    lambda: channel_names((0, -1)),        # a legal Python index that quietly means 'blue'
    lambda: channel_names(('red',)),       # names where indices belong
    lambda: channel_indices(('red', 'infrared')),
])
def test_a_mistyped_channel_is_refused_rather_than_guessed(bad):
    with pytest.raises(ValueError):
        bad()


def test_an_unstated_refresh_rate_is_deferred_rather_than_refused():
    """None means "ask the display", which StimDisplay resolves from the Qt screen at start-up.
    Requiring it in configuration was asking an experimenter to repeat a number the system already
    knows, and one they could get wrong."""
    screen = Screen(subframes=3)

    assert screen.subframes == 3
    assert screen.refresh_rate is None


def test_asking_for_the_interval_before_it_is_resolved_says_so():
    """The error moves from construction to use, so it has to name the screen and say where the
    number normally comes from."""
    screen = Screen(subframes=3, name='bowl')

    with pytest.raises(ValueError, match='no refresh_rate'):
        screen.subframe_interval


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


def test_two_subframes_leave_the_third_channel_untouched(headless_gl):
    """Below the ceiling, the unused channel keeps what the frame was cleared to -- so a projector
    reading two patterns per frame gets two, and nothing stray in the third."""
    ctx = headless_gl
    packed = render_packed(ctx, Screen(subframes=2, refresh_rate=120),
                           brightness_at=lambda dt: 0.2 + 100.0 * dt)

    assert packed[0] < packed[1], f'not increasing with time: {packed}'
    assert packed[2] == pytest.approx(0.0, abs=0.01), f'the unused channel was written: {packed}'


def test_a_single_subframe_screen_renders_greyscale_as_before(headless_gl):
    """subframes=1 must leave all three channels equal -- the existing behaviour, unchanged."""
    ctx = headless_gl
    packed = render_packed(ctx, Screen(), brightness_at=lambda dt: 0.5)
    assert np.allclose(packed, packed[0], atol=0.01), f'channels diverged at subframes=1: {packed}'
