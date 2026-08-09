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

from stimpack.visual_stim import stimuli  # noqa: E402
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
    """Paints the face it is given a flat colour, without needing a real stimulus's geometry.

    Carries eval_at because every real stimulus does: the render loop evaluates each stimulus once
    for the frame and then draws it per face, so a stand-in without one is not standing in for
    anything that exists.
    """

    COLOR = (0.0, 1.0, 0.0, 1.0)

    def __init__(self):
        self.eval_times = []

    def eval_at(self, t, subject_position=None):
        self.eval_times.append(t)

    def paint_at(self, t, viewports, perspectives, subject_position=None, prepare=True):
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


# --- eval_at runs once per frame, not once per face ----------------------------------------------
#
# The two render paths call paint_at differently. The planar one hands over every subscreen at once,
# so BaseProgram.paint_at evaluates the stimulus once and then draws it per viewport. The cube path
# has to bind a different framebuffer per face, so it called paint_at once per face -- and each of
# those calls evaluated the stimulus again, at the same t.
#
# A stateless stimulus survives that; a stateful one does not. It cost a rig an
# `IndexError: list index out of range` from a dot field that pops one refresh time per evaluation
# and got five per frame. Whether a given stimulus survives is luck: LoomingCircle happens to, since
# it integrates (t - t_prev) and the repeat calls see zero elapsed, while a stimulus comparing
# `t % p <= t_prev % p` fires again on every repeat because the comparison is not strict.
#
# So the contract is: exactly one eval_at per stimulus per displayed frame, whatever the face count.

def wide_mesh():
    """A screen spanning azimuth -80..+80 at the horizon, so it needs +X, +Y and -X."""
    azimuth = np.radians(np.linspace(-80, 80, 9))
    directions = np.stack([np.sin(azimuth), np.cos(azimuth), np.zeros_like(azimuth)], axis=-1)
    top = directions + np.array([0.0, 0.0, 0.3])
    directions = np.concatenate([directions, top / np.linalg.norm(top, axis=1, keepdims=True)])

    u = np.linspace(-1, 1, 9)
    ndc = np.concatenate([np.stack([u, np.full_like(u, -1.0)], axis=-1),
                          np.stack([u, np.full_like(u, +1.0)], axis=-1)])
    lower = np.arange(8)
    triangles = np.concatenate([
        np.stack([lower, lower + 1, lower + 9], axis=-1),
        np.stack([lower + 1, lower + 10, lower + 9], axis=-1),
    ]).astype(np.int32)
    return ScreenMesh(ndc=ndc.astype(np.float32), directions=directions.astype(np.float32),
                      triangles=triangles, positions=(directions * 0.3).astype(np.float32))


class CountingSpot(stimuli.MovingSpot):
    """A real stimulus that records how often it is evaluated and how often it uploads."""

    def __init__(self, screen):
        super().__init__(screen=screen)
        self.eval_times = []
        self.uploads = 0

    def eval_at(self, t, subject_position={'x': 0, 'y': 0, 'z': 0, 'theta': 0, 'phi': 0, 'roll': 0}):
        self.eval_times.append(t)
        super().eval_at(t, subject_position=subject_position)

    def initialize(self, ctx):
        super().initialize(ctx)
        counted, outer = self.vbo_vert.write, self

        def write(*args, **kwargs):
            outer.uploads += 1
            return counted(*args, **kwargs)
        self.vbo_vert.write = write


def drive_one_frame(ctx, mesh, stim_list, t=0.25):
    renderer = CubeMapRenderer(ctx, mesh, resolution=CUBE)
    window_tex = ctx.texture((SIZE, SIZE), 4)
    depth = ctx.depth_renderbuffer((SIZE, SIZE))
    window = ctx.framebuffer(color_attachments=[window_tex], depth_attachment=depth)
    try:
        window.use()
        window.clear(0.0, 0.0, 0.0, 1.0)
        display = display_for(ctx, renderer, stim_list, stim_started=True)
        display.paint_through_cube_map(t, SIZE, SIZE)
        ctx.finish()
        return len(renderer.face_indices)
    finally:
        renderer.release(); window.release(); window_tex.release(); depth.release()


def test_a_stimulus_is_evaluated_once_per_frame_not_once_per_face(headless_gl):
    ctx = headless_gl
    mesh = wide_mesh()

    stim = CountingSpot(screen=Screen(fullscreen=False, vsync=False))
    stim.initialize(ctx)
    stim.configure(radius=8, sphere_radius=1, color=[1, 1, 1, 1], theta=0, phi=0)

    faces = drive_one_frame(ctx, mesh, [stim])

    assert faces > 1, 'this mesh must need several faces or the test proves nothing'
    assert stim.eval_times == [0.25], \
        f'evaluated {len(stim.eval_times)} times across {faces} faces, expected once'


def test_every_stimulus_in_the_list_is_evaluated_once(headless_gl):
    ctx = headless_gl
    mesh = wide_mesh()

    stims = []
    for theta in (-20, 0, 20):
        stim = CountingSpot(screen=Screen(fullscreen=False, vsync=False))
        stim.initialize(ctx)
        stim.configure(radius=6, sphere_radius=1, color=[1, 1, 1, 1], theta=theta, phi=0)
        stims.append(stim)

    faces = drive_one_frame(ctx, mesh, stims)

    assert [len(s.eval_times) for s in stims] == [1, 1, 1], \
        f'across {faces} faces, eval counts were {[len(s.eval_times) for s in stims]}'


def test_nothing_is_evaluated_before_the_stimulus_starts(headless_gl):
    """Pre-time draws no stimuli, so it must not advance one either."""
    ctx = headless_gl
    mesh = wide_mesh()

    stim = CountingSpot(screen=Screen(fullscreen=False, vsync=False))
    stim.initialize(ctx)
    stim.configure(radius=8, sphere_radius=1, color=[1, 1, 1, 1], theta=0, phi=0)

    renderer = CubeMapRenderer(ctx, mesh, resolution=CUBE)
    window_tex = ctx.texture((SIZE, SIZE), 4)
    window = ctx.framebuffer(color_attachments=[window_tex])
    try:
        window.use()
        display = display_for(ctx, renderer, [stim], stim_started=False)
        display.paint_through_cube_map(0.25, SIZE, SIZE)
        ctx.finish()
    finally:
        renderer.release(); window.release(); window_tex.release()

    assert stim.eval_times == []


def test_geometry_is_uploaded_once_per_frame_not_once_per_face(headless_gl):
    """The vertex buffer is the expensive part of paint_at, and the geometry is the same for every
    face. Re-sending it per face made the cube pass scale with face count in vertices as well as in
    draw calls -- which is what turning the cube exists to avoid."""
    ctx = headless_gl
    mesh = wide_mesh()

    stim = CountingSpot(screen=Screen(fullscreen=False, vsync=False))
    stim.initialize(ctx)
    stim.configure(radius=8, sphere_radius=1, color=[1, 1, 1, 1], theta=0, phi=0)

    faces = drive_one_frame(ctx, mesh, [stim])

    assert faces > 1, 'this mesh must need several faces or the test proves nothing'
    assert stim.uploads == 1, \
        f'uploaded the vertex buffer {stim.uploads} times across {faces} faces, expected once'


def test_the_planar_path_still_uploads_and_evaluates_once(headless_gl):
    """paint_at's default must be unchanged: one call does everything, for every subscreen given."""
    ctx = headless_gl
    stim = CountingSpot(screen=Screen(fullscreen=False, vsync=False))
    stim.initialize(ctx)
    stim.configure(radius=8, sphere_radius=1, color=[1, 1, 1, 1], theta=0, phi=0)

    fbo = ctx.simple_framebuffer((SIZE, SIZE))
    fbo.use()
    fbo.clear(0.0, 0.0, 0.0, 1.0)
    subject = {'x': 0, 'y': 0, 'z': 0, 'theta': 0, 'phi': 0, 'roll': 0}
    identity = np.eye(4, dtype='f4').tobytes(order='F')
    stim.paint_at(0.5, [(0, 0, SIZE, SIZE), (0, 0, SIZE // 2, SIZE // 2)],
                  [identity, identity], subject_position=subject)
    ctx.finish()
    fbo.release()

    assert stim.eval_times == [0.5]
    assert stim.uploads == 1, 'two subscreens must still cost one upload'
