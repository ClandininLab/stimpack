"""Does the warp pass actually land on the display?

test_cubemap and test_curved_vs_planar both drive the two passes by hand -- they bind a framebuffer
of their own and call ``render_warp`` into it. That covers the cube map and the geometry, and misses
the one step only ``StimDisplay.paint_through_cube_map`` performs: getting back to the display
framebuffer after six framebuffer switches. A mistake there renders a perfect cube map into a cube
face and shows the operator a black screen, with every other test still passing.

So this drives the real method, against a framebuffer standing in for the window, and asks the only
question those tests cannot: did anything reach it.
"""
import pytest

pytest.importorskip("numpy")
pytest.importorskip("moderngl")
pytest.importorskip("OpenGL")

import numpy as np  # noqa: E402

from stimpack.visual_stim.cubemap import CubeMapRenderer  # noqa: E402
from stimpack.visual_stim.curved_screen import CurvedScreen, ScreenMesh  # noqa: E402
from stimpack.visual_stim.framework import StimDisplay  # noqa: E402
from stimpack.visual_stim.screen import Screen  # noqa: E402

pytestmark = pytest.mark.gl

SIZE = 64
CUBE = 64


def forward_mesh(half_width=1.0):
    """A screen centred in the display, every direction pointing forward: only the +Y face.

    half_width < 1 leaves projector image around it that the screen does not cover -- on the bowl
    that is the black surround outside the lit ellipse, and it is nearly half the frame.
    """
    w = float(half_width)
    ndc = np.array([[-w, -w], [w, -w], [-w, w], [w, w]], dtype=np.float32)
    directions = np.tile(np.array([0, 1, 0], dtype=np.float32), (4, 1))
    triangles = np.array([[0, 1, 2], [1, 3, 2]], dtype=np.int32)
    positions = np.tile(np.array([0, 0.3, 0], dtype=np.float32), (4, 1))
    return ScreenMesh(ndc=ndc, directions=directions, triangles=triangles, positions=positions)


class WholeFaceStim:
    """Paints the face it is given a flat colour, without needing a real stimulus's geometry."""

    COLOR = (0.0, 1.0, 0.0, 1.0)

    def paint_at(self, t, viewports, perspectives, subject_position=None):
        # The cube face framebuffer is bound; clearing it is enough to stand for drawing into it.
        import moderngl
        ctx = moderngl.get_context()
        ctx.fbo.clear(*self.COLOR)


def display_for(ctx, renderer, stim_list, stim_started):
    display = StimDisplay.__new__(StimDisplay)
    display.ctx = ctx
    display.cube_renderer = renderer
    display.stim_list = stim_list
    display.stim_started = stim_started
    display.idle_background = (0.5, 0.5, 0.5, 1.0)
    display.subject_position = {'x': 0, 'y': 0, 'z': 0, 'theta': 0, 'phi': 0, 'roll': 0}
    return display


def run_paint(ctx, stim_list, stim_started):
    """Paint one frame the way paintGL does, and read back what the display got."""
    window_tex = ctx.texture((SIZE, SIZE), 4)
    window = ctx.framebuffer(color_attachments=[window_tex])
    renderer = CubeMapRenderer(ctx, forward_mesh(), resolution=CUBE)
    try:
        # paintGL binds the window framebuffer and clears it black before painting the subframe.
        window.use()
        window.clear(0.0, 0.0, 0.0, 1.0)

        display = display_for(ctx, renderer, stim_list, stim_started)
        display.paint_through_cube_map(0.0, SIZE, SIZE)
        ctx.finish()

        image = np.frombuffer(window.read(components=4, alignment=1),
                              dtype=np.uint8).reshape(SIZE, SIZE, 4)
        return image, ctx.fbo.glo, window.glo
    finally:
        renderer.release()
        window.release()
        window_tex.release()


def test_the_idle_background_reaches_the_display(headless_gl):
    """Pre-time: the faces are cleared and nothing is drawn, and the screen shows that grey.

    On the rig this looked like it already worked, because a CurvedScreen inherits a full-viewport
    subscreen and the standby path clears the whole window to idle_background directly -- never
    touching the cube map. The grey was real and told us nothing about the warp.
    """
    image, _, _ = run_paint(headless_gl, stim_list=[], stim_started=False)
    assert image[..., :3].mean() == pytest.approx(128, abs=4), \
        f'display mean {image[..., :3].mean():.0f}, expected the idle grey through the warp'


def test_a_stimulus_reaches_the_display(headless_gl):
    """The reported symptom, in one assertion: at stimulus onset the screen went black."""
    image, _, _ = run_paint(headless_gl, stim_list=[WholeFaceStim()], stim_started=True)
    green = image[..., 1].mean()
    assert green > 200, f'display green {green:.0f}: the warp did not reach the display'


def test_the_display_framebuffer_is_bound_when_the_pass_returns(headless_gl):
    """Whatever is drawn after the warp -- the photodiode square, the calibration spot -- goes to
    whichever framebuffer this pass left bound. Leaving a cube face bound loses those too, which
    is why the square stopped marking frames on the bowl during a trial."""
    _, bound, window = run_paint(headless_gl, stim_list=[WholeFaceStim()], stim_started=True)
    assert bound == window, \
        f'left framebuffer {bound} bound, not the display ({window})'


# --- standby: no stimulus loaded, which is a different branch of paint_subframe ----------------

class FakeSquare:
    def paint(self):
        pass

    def set_viewport(self, *args):
        pass


class FakeCalibrationSpot:
    visible = False

    def paint(self):
        pass


def run_subframe(ctx, renderer, screen):
    """Paint one standby frame through the real paint_subframe, with no stimulus loaded."""
    window_tex = ctx.texture((SIZE, SIZE), 4)
    window = ctx.framebuffer(color_attachments=[window_tex])
    try:
        window.use()

        display = display_for(ctx, renderer, stim_list=[], stim_started=False)
        display.screen = screen
        display.subscreen_viewports = [sub.get_viewport(SIZE, SIZE) for sub in screen.subscreens]
        display.square_program = FakeSquare()
        display.calibration_spot = FakeCalibrationSpot()
        display.profile_frame_times = []
        display.pre_render = False
        display.use_subject_trajectory = False
        display.paint_subframe(0.0, SIZE, SIZE)
        ctx.finish()

        return np.frombuffer(window.read(components=4, alignment=1),
                             dtype=np.uint8).reshape(SIZE, SIZE, 4)
    finally:
        window.release()
        window_tex.release()


def test_standby_lights_only_what_the_screen_covers(headless_gl):
    """Between trials the background must land where the screen is, and nowhere else.

    A CurvedScreen inherits a full-viewport SubScreen it never otherwise uses, so the planar
    standby branch would clear the whole projector image to idle_background -- lighting the parts
    that miss the screen entirely (nearly half the frame on a bowl) and skipping the mesh's
    per-vertex brightness gain. The subject then saw one background between trials and a different
    one during them, from the same idle_color.
    """
    ctx = headless_gl
    screen = CurvedScreen(fullscreen=False, vsync=False)
    # Half the display wide, so there is an uncovered surround to check.
    renderer = CubeMapRenderer(ctx, forward_mesh(half_width=0.5), resolution=CUBE)
    try:
        image = run_subframe(ctx, renderer, screen)
    finally:
        renderer.release()

    quarter, three_quarters = SIZE // 4, 3 * SIZE // 4
    covered = image[quarter + 2:three_quarters - 2, quarter + 2:three_quarters - 2, :3]
    surround = image[:quarter - 2, :, :3]

    assert covered.mean() == pytest.approx(128, abs=4), \
        f'the screen itself is at {covered.mean():.0f}, expected the idle grey'
    assert surround.max() == 0, \
        f'lit {surround.max()} outside the screen, where no screen is to light'


def test_standby_on_a_planar_screen_still_fills_the_viewport(headless_gl):
    """The planar path is unchanged: with no curved screen there is no mesh to confine anything
    to, and a flat subscreen's viewport is exactly the region it should fill."""
    ctx = headless_gl
    screen = Screen(fullscreen=False, vsync=False)
    image = run_subframe(ctx, renderer=None, screen=screen)
    assert image[..., :3].mean() == pytest.approx(128, abs=4), \
        f'planar standby mean {image[..., :3].mean():.0f}, expected the idle grey everywhere'
