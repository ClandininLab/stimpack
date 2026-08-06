"""Does the subframe offset actually reach the stimulus?

The gl tests cover the packing -- three channels, distinct, in the configured order. What they do
not cover is StimDisplay's own loop, because they reimplement it. This drives the real
paint_subframe with a stimulus that records when it was asked to paint, which is the one thing the
renderer contributes: without the offset the three channels would hold the same instant, and the
whole mode would be a 120 Hz display with extra steps.
"""
import pytest

pytest.importorskip("numpy")
pytest.importorskip("PyQt6")

from stimpack.visual_stim.framework import StimDisplay  # noqa: E402
from stimpack.visual_stim.screen import Screen  # noqa: E402

pytestmark = pytest.mark.unit


class RecordingStim:
    """Stands in for a stimulus, noting the time it was painted at."""

    def __init__(self):
        self.painted_at = []

    def paint_at(self, t, viewports, perspectives, subject_position=None):
        self.painted_at.append(t)


class FakeFramebuffer:
    def __init__(self):
        self.masks = []

    def clear(self, *args, **kwargs):
        pass


class FakeContext:
    def __init__(self):
        self.fbo = FakeFramebuffer()
        self.clears = 0

    def clear(self, *args, **kwargs):
        # The calibration path blacks out the whole context before drawing the spot; the ordinary
        # path clears viewports through the framebuffer instead.
        self.clears += 1


class FakeSquare:
    def __init__(self):
        self.paints = 0

    def paint(self):
        self.paints += 1

    def set_viewport(self, *args):
        pass


class FakeCalibrationSpot:
    """Hidden, which is the normal state. A visible spot owns the whole frame and suppresses the
    corner square, so these tests would be measuring the wrong thing with it on."""

    visible = False

    def paint(self):
        pass


def display_for(screen, stim):
    """A StimDisplay with just enough filled in to run paint_subframe, and no Qt or GL."""
    display = StimDisplay.__new__(StimDisplay)
    display.screen = screen
    display.ctx = FakeContext()
    display.stim_list = [stim]
    display.stim_started = True
    display.pre_render = False
    display.use_subject_trajectory = False
    display.subject_position = {'x': 0, 'y': 0, 'z': 0, 'theta': 0, 'phi': 0, 'roll': 0}
    display.subscreen_viewports = [(0, 0, 8, 8)]
    display.square_program = FakeSquare()
    display.profile_frame_times = []
    display.idle_background = (0.5, 0.5, 0.5, 1.0)
    display.cube_renderer = None
    display.calibration_spot = FakeCalibrationSpot()
    display.stim_start_time = 0.0
    display.get_stim_time = lambda t: t
    return display


def test_each_subframe_is_painted_at_its_own_time():
    """1/360 s apart, which is what the extra passes are for."""
    screen = Screen(subframes=3, refresh_rate=120)
    stim = RecordingStim()
    display = display_for(screen, stim)

    for subframe, _mask in enumerate(screen.subframe_color_masks()):
        display.paint_subframe(subframe * screen.subframe_interval, 8, 8)

    assert len(stim.painted_at) == 3
    gaps = [b - a for a, b in zip(stim.painted_at, stim.painted_at[1:])]
    for gap in gaps:
        assert gap == pytest.approx(1 / 360, abs=2e-3), \
            f'subframes {gap * 1000:.2f} ms apart, expected {1000 / 360:.2f} ms'


def test_a_single_subframe_screen_paints_once_with_no_offset():
    """The default path must be untouched: one paint, at the time it would have had before."""
    screen = Screen()
    stim = RecordingStim()
    display = display_for(screen, stim)

    masks = screen.subframe_color_masks()
    assert len(masks) == 1
    display.paint_subframe(0.0, 8, 8)

    assert len(stim.painted_at) == 1


def test_the_corner_square_is_drawn_once_per_subframe():
    """It is the photodiode signal, so under multiplexing it has to mark subframes -- otherwise it
    reports 120 Hz for a display running at 360 and the timing cannot be checked at all."""
    screen = Screen(subframes=3, refresh_rate=120)
    display = display_for(screen, RecordingStim())

    for subframe, _mask in enumerate(screen.subframe_color_masks()):
        display.paint_subframe(subframe * screen.subframe_interval, 8, 8)

    assert display.square_program.paints == 3


def test_frames_are_profiled_per_subframe_while_running():
    """Three timepoints are three opportunities to drop one, so the profile should see all three."""
    screen = Screen(subframes=3, refresh_rate=120)
    display = display_for(screen, RecordingStim())

    for subframe, _mask in enumerate(screen.subframe_color_masks()):
        display.paint_subframe(subframe * screen.subframe_interval, 8, 8)

    assert len(display.profile_frame_times) == 3


def test_nothing_is_profiled_before_the_stimulus_starts():
    """#43: this used to accumulate from load_stim onward, so pre-time frames were folded into the
    frame-time statistics print_profile reports -- anyone reading those to check for dropped frames
    was reading polluted numbers."""
    screen = Screen(subframes=3, refresh_rate=120)
    display = display_for(screen, RecordingStim())
    display.stim_started = False

    for subframe, _mask in enumerate(screen.subframe_color_masks()):
        display.paint_subframe(subframe * screen.subframe_interval, 8, 8)

    assert display.profile_frame_times == []


def test_a_stimulus_that_has_not_started_is_not_painted():
    """Pre-time should clear to the idle background, not draw the stimulus."""
    screen = Screen(subframes=3, refresh_rate=120)
    stim = RecordingStim()
    display = display_for(screen, stim)
    display.stim_started = False

    display.paint_subframe(0.0, 8, 8)

    assert stim.painted_at == []


def test_a_visible_calibration_spot_suppresses_the_corner_square_in_every_subframe():
    """Where the two rendering features meet, and the merge that brought them together had to
    choose. A photometer aimed at the calibration spot collects whatever else the screen is
    showing, so the corner square must not be drawn -- and 'not drawn' has to hold for each
    subframe, not just once per frame, or two thirds of the square's light still lands in the
    reading."""
    screen = Screen(subframes=3, refresh_rate=120)
    display = display_for(screen, RecordingStim())
    display.calibration_spot = FakeCalibrationSpot()
    display.calibration_spot.visible = True

    for subframe, _mask in enumerate(screen.subframe_color_masks()):
        display.paint_subframe(subframe * screen.subframe_interval, 8, 8)

    assert display.square_program.paints == 0


def test_the_corner_square_returns_when_the_spot_is_hidden():
    """The ordinary case: one square per subframe, so the photodiode marks 360 Hz rather than 120."""
    screen = Screen(subframes=3, refresh_rate=120)
    display = display_for(screen, RecordingStim())

    for subframe, _mask in enumerate(screen.subframe_color_masks()):
        display.paint_subframe(subframe * screen.subframe_interval, 8, 8)

    assert display.square_program.paints == 3


# --- the commissioning stimulus -------------------------------------------------------------------

def test_each_subframe_lands_on_its_own_position():
    """The whole point of SubframeTimingCheck: three subframes, three azimuths, in order. If two
    subframes sampled the same step the stimulus could not tell a working display from a broken
    one."""
    from scipy.interpolate import interp1d

    from stimpack.experiment.example_protocol import SubframeTimingCheck

    protocol = SubframeTimingCheck.__new__(SubframeTimingCheck)
    rate, n, separation = 360.0, 3, 10.0
    pairs = protocol.subframe_positions(stim_time=0.1, n_subframes=n, subframe_rate=rate,
                                        separation=separation, center=0.0)

    times, values = zip(*pairs)
    held = interp1d(times, values, kind='previous', fill_value='extrapolate')

    # the times a frame's subframes are actually rendered at, for a few video frames
    for frame in range(4):
        sampled = [float(held(frame / (rate / n) + k / rate)) for k in range(n)]
        assert sampled == [0.0, separation, 2 * separation], f'frame {frame} gave {sampled}'


def test_the_staircase_holds_rather_than_slides():
    """Interpolating between steps would put a subframe between two positions, which is exactly the
    smearing this stimulus exists to detect."""
    from scipy.interpolate import interp1d

    from stimpack.experiment.example_protocol import SubframeTimingCheck

    protocol = SubframeTimingCheck.__new__(SubframeTimingCheck)
    pairs = protocol.subframe_positions(0.05, 3, 360.0, 10.0, 0.0)
    times, values = zip(*pairs)
    held = interp1d(times, values, kind='previous', fill_value='extrapolate')

    # Step k spans (k-0.5, k+0.5) intervals, so it is centred on the instant subframe k renders.
    # Sample either side of that centre and the value must not change.
    interval = 1 / 360.0
    within = [float(held((1 + f) * interval)) for f in (-0.4, -0.2, 0.0, 0.2, 0.4)]
    assert len(set(within)) == 1, f'position moved within a single subframe: {within}'


def test_the_check_stimulus_declares_what_the_rig_was_told():
    """subframe_rate and n_subframes are parameters, not read from the screen -- this is the
    stimulus you run when you do not yet believe the screen is doing what it was told."""
    from stimpack.experiment.example_protocol import SubframeTimingCheck

    defaults = SubframeTimingCheck.get_protocol_parameter_defaults(None)

    assert defaults['n_subframes'] == 3
    assert defaults['subframe_rate'] == 360.0
    assert SubframeTimingCheck.get_run_parameter_defaults(None)['idle_color'] == 0.0, \
        'a photodiode should see the corner square, not the background'


def test_a_multiplexing_screen_says_so_and_says_it_cannot_be_verified(capsys):
    """subframes=3 is a claim about the projector, not about stimpack. If the projector is in
    ordinary video mode the result is a plausible colour image rather than an error, so the only
    warning available is saying it out loud."""
    from stimpack.visual_stim.framework import StimDisplay

    display = StimDisplay.__new__(StimDisplay)
    display.screen = Screen(subframes=3, refresh_rate=120)
    display.report_subframe_mode()

    printed = capsys.readouterr().out
    assert '3 subframes' in printed
    assert '360' in printed, 'the resulting rate should be stated, not left to arithmetic'
    assert 'cannot verify' in printed


def test_an_ordinary_screen_says_that_too(capsys):
    """Silence would be ambiguous: nothing configures subframes today, so 'no message' and
    'not multiplexing' would look the same."""
    from stimpack.visual_stim.framework import StimDisplay

    display = StimDisplay.__new__(StimDisplay)
    display.screen = Screen()
    display.report_subframe_mode()

    assert '1 subframe' in capsys.readouterr().out


def test_the_reported_channel_order_is_the_configured_one(capsys):
    """A wrong order reorders three frames in time and still looks like motion, so it is worth
    printing rather than assuming."""
    from stimpack.visual_stim.framework import StimDisplay

    display = StimDisplay.__new__(StimDisplay)
    display.screen = Screen(subframes=3, refresh_rate=120, subframe_channel_order=(2, 1, 0))
    display.report_subframe_mode()

    assert 'channel order BGR' in capsys.readouterr().out


# --- changing subframes at run time ---------------------------------------------------------------

def _display_with(screen):
    from stimpack.visual_stim.framework import StimDisplay
    display = StimDisplay.__new__(StimDisplay)
    display.screen = screen
    display.stim_started = False
    return display


def test_the_next_frame_follows_immediately(capsys):
    """paintGL asks for the masks and the interval every frame and caches neither, so there is
    nothing to rebuild -- which is what makes a run-time switch possible at all."""
    display = _display_with(Screen(subframes=1, refresh_rate=120))
    assert display.screen.subframe_color_masks() == [(True, True, True, True)]
    assert display.screen.subframe_interval == 0.0

    display.set_subframes(3)

    assert len(display.screen.subframe_color_masks()) == 3
    assert display.screen.subframe_interval == pytest.approx(1 / 360)


def test_it_refuses_mid_stimulus(capsys):
    """Half a trial at one temporal structure and half at another is not recoverable from the
    data, and nothing downstream would report it."""
    display = _display_with(Screen(subframes=1, refresh_rate=120))
    display.stim_started = True

    with pytest.raises(RuntimeError, match='while a stimulus is running'):
        display.set_subframes(3)

    assert display.screen.subframes == 1, 'the screen must be left alone when refused'


def test_switching_announces_the_new_state(capsys):
    """The claim about the projector is worth repeating every time it changes, not only at
    start-up: nothing in stimpack can check it."""
    display = _display_with(Screen(subframes=1, refresh_rate=120))
    capsys.readouterr()

    display.set_subframes(3)

    printed = capsys.readouterr().out
    assert '3 subframes' in printed and '360' in printed


def test_a_rejected_value_leaves_the_screen_untouched():
    """set_subframes validates through the same path as the constructor, so a screen cannot reach
    a state it could not have been built in."""
    display = _display_with(Screen(subframes=3, refresh_rate=120))

    with pytest.raises(ValueError):
        display.set_subframes(4)
    with pytest.raises(ValueError):
        display.set_subframes(3, channel_order=(0, 0, 1))

    assert display.screen.subframes == 3
    assert display.screen.subframe_channel_order == (0, 1, 2)


def test_the_name_is_advertised_so_a_labpack_can_ask_first():
    """SCREEN_FUNCTION_NAMES is what VisualStimServer advertises, so has_server_function can answer
    without a round trip -- which is how a labpack degrades gracefully on an older stimpack."""
    from stimpack.visual_stim.framework import SCREEN_FUNCTION_NAMES, StimDisplay

    assert 'set_subframes' in SCREEN_FUNCTION_NAMES
    assert callable(getattr(StimDisplay, 'set_subframes'))
