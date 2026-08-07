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
from stimpack.visual_stim.curved_screen import ScreenMesh  # noqa: E402
from stimpack.visual_stim.framework import StimDisplay  # noqa: E402

pytestmark = pytest.mark.gl

SIZE = 64
CUBE = 64


def forward_mesh():
    """A screen filling the display, every direction pointing forward: only the +Y face."""
    ndc = np.array([[-1, -1], [1, -1], [-1, 1], [1, 1]], dtype=np.float32)
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
