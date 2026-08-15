"""Multisampling: what it buys, what it must not disturb, and that it stays off by default.

Analytic edges cover every shape that has an equation for its own boundary. Multisampling is for
the geometry that cannot: a box, a tower, a forest, an avatar -- and anything built by merging
shapes with ``add()``, which is drawn in one call with one edge equation.

What it buys is edge position quantized to 1/n of a pixel rather than a whole one. That is a finer
staircase, not the continuous sub-pixel motion an analytic edge gives, and the tests below pin both
halves of that: it helps the shapes without an equation, and leaves the shapes with one alone.

These all render through a flat frustum, which is where the option does its work. On a CurvedScreen
it reaches much less: the scene is rasterized into single-sample cube faces first, and only the warp
pass is multisampled. See docs/design/analytic-edges.md.
"""
import math

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("moderngl")
pytest.importorskip("yaml")
pytest.importorskip("platformdirs")

import moderngl  # noqa: E402

from stimpack.util import get_all_subclasses  # noqa: E402
from stimpack.visual_stim import stimuli  # noqa: E402
from stimpack.visual_stim.screen import Screen  # noqa: E402

from test_stimuli_render import _make_screen, _perspective, SUBJECT_AT_ORIGIN  # noqa: E402

pytestmark = pytest.mark.gl

SIZE = 512


def _supported(ctx, wanted):
    """Those of `wanted` the driver will actually give us. Sample counts are driver-dependent, so
    a test that hard-codes one is a test that fails on somebody else's machine."""
    usable = []
    for n in wanted:
        try:
            ctx.renderbuffer((8, 8), samples=n)
        except Exception:
            continue
        usable.append(n)
    return usable


def _render(ctx, name, kwargs, samples):
    """Render one stimulus, through a multisampled framebuffer when samples > 0.

    The same two steps StimDisplay.paintGL takes: draw into the multisampled buffer, then resolve
    it into an ordinary one with copy_framebuffer.
    """
    ctx.enable(moderngl.BLEND)
    ctx.enable(moderngl.DEPTH_TEST)
    ctx.extra = {}

    resolved = ctx.framebuffer(color_attachments=[ctx.renderbuffer((SIZE, SIZE))])
    if samples:
        fbo = ctx.framebuffer(
            color_attachments=[ctx.renderbuffer((SIZE, SIZE), samples=samples)],
            depth_attachment=ctx.depth_renderbuffer((SIZE, SIZE), samples=samples))
    else:
        fbo = ctx.framebuffer(color_attachments=[ctx.renderbuffer((SIZE, SIZE))],
                              depth_attachment=ctx.depth_renderbuffer((SIZE, SIZE)))

    screen = _make_screen()
    viewports = [s.get_viewport(SIZE, SIZE) for s in screen.subscreens]
    perspectives = [_perspective(SUBJECT_AT_ORIGIN, s.pa, s.pb, s.pc, screen.horizontal_flip)
                    for s in screen.subscreens]

    stim = [c for c in get_all_subclasses(stimuli.BaseProgram) if c.__name__ == name][0](screen=screen)
    stim.initialize(ctx)
    stim.configure(**kwargs)
    fbo.use()
    fbo.clear(0, 0, 0, 1)
    stim.paint_at(0, viewports, perspectives, subject_position=SUBJECT_AT_ORIGIN)
    ctx.finish()

    if samples:
        ctx.copy_framebuffer(resolved, fbo)
        fbo = resolved
    raw = fbo.read(components=3, alignment=1)
    return np.flipud(np.frombuffer(raw, dtype=np.uint8).reshape(SIZE, SIZE, 3))[..., 0].astype(int)


BOX = dict(x_length=0.3, y_length=0.3, z_length=0.3, color=[1, 1, 1, 1],
           x=0, y=2, z=0, yaw=0, pitch=0, roll=0)


def test_it_is_off_unless_a_rig_asks_for_it():
    """The cost differs by more than an order of magnitude between the GPUs in use -- 1.7% of a
    360 Hz frame at 4x on an RTX A4500, 89% on a software rasterizer -- so there is no default
    that suits every rig, and the default has to be none."""
    assert Screen().msaa_samples == 0
    assert Screen(msaa_samples=4).msaa_samples == 4
    assert Screen.deserialize(Screen(msaa_samples=8).serialize()).msaa_samples == 8


def test_it_antialiases_geometry_that_has_no_analytic_edge(headless_gl):
    """A box is polyhedral and world-space, so nothing in shapes.py has an equation for it. Its
    silhouette is hard, and multisampling is the only thing that softens it."""
    plain = _render(headless_gl, 'MovingBox', BOX, 0)
    assert ((plain > 5) & (plain < 250)).sum() == 0, 'the box should be hard-edged without this'

    # More samples does not light more edge pixels -- the silhouette is the same set of pixels
    # either way. What rises is how finely each one's coverage is resolved: n samples can express
    # n+1 fractions, so the number of distinct gray levels along the edge is the thing to watch.
    usable = _supported(headless_gl, (4, 8, 16))
    if len(usable) < 2:
        pytest.skip(f'driver offers too few sample counts to compare: {usable}')

    levels = {}
    for samples in usable:
        multisampled = _render(headless_gl, 'MovingBox', BOX, samples)
        partial = multisampled[(multisampled > 5) & (multisampled < 250)]
        assert partial.size > 0, f'{samples}x left the silhouette hard'
        assert partial.size < (multisampled > 250).sum(), f'{samples}x looks like a blur, not an edge'
        levels[samples] = len(np.unique(partial))

    counts = [levels[n] for n in usable]
    assert counts == sorted(counts) and counts[-1] > counts[0], (
        f'coverage should resolve more finely as samples rise, got {levels}')


def test_it_leaves_an_analytic_edge_alone(headless_gl):
    """Shapes that carry their own boundary equation are already exact and already carry sub-pixel
    coverage, so multisampling has nothing to add to them -- and must take nothing away. It is
    added for the geometry beside them, so it has to be safe to leave on."""
    usable = _supported(headless_gl, (4, 8))
    for name, kwargs in [('MovingSpot', dict(radius=15, sphere_radius=1, color=[1, 1, 1, 1],
                                             theta=0, phi=0)),
                         ('MovingPatch', dict(width=25, height=25, sphere_radius=1,
                                              color=[1, 1, 1, 1], theta=0, phi=0, angle=0))]:
        plain = _render(headless_gl, name, kwargs, 0)
        for samples in usable:
            multisampled = _render(headless_gl, name, kwargs, samples)
            drift = abs(multisampled.sum() - plain.sum()) / plain.sum()
            assert drift < 0.002, f'{name} at {samples}x changed its total light by {drift*100:.2f}%'


def test_the_edge_lands_between_pixels_more_finely_as_samples_rise(headless_gl):
    """The property, stated as what it actually is: multisampling quantizes edge position to 1/n of
    a pixel. It does not make motion continuous the way analytic coverage does -- an analytic edge
    on the same journey steps by 0.024 px where 4x steps by 0.251 -- so this asserts a finer
    staircase rather than a smooth one.
    """
    distance = 2.0
    step = distance * math.tan(math.radians(2.0 / 360))     # 2 deg/s at 360 Hz

    def edge_positions(samples, frames=12):
        found = []
        for frame in range(frames):
            grey = _render(headless_gl, 'MovingBox', dict(BOX, x=frame * step), samples)
            row = grey[SIZE // 2].astype(float)
            lit = np.nonzero(row > 5)[0]
            found.append(lit[0] + (1 - row[lit[0]] / 255.0))
        return np.array(found)

    usable = _supported(headless_gl, (8, 4))
    if not usable:
        pytest.skip('driver offers no multisampling')
    coarse = np.abs(np.diff(edge_positions(0)))
    fine = np.abs(np.diff(edge_positions(usable[0])))

    assert coarse.max() == pytest.approx(1.0, abs=0.02), 'without this the edge jumps a whole pixel'
    assert fine.max() < 0.5 * coarse.max(), (
        f'8x should quantize more finely than a whole pixel, got {fine.max():.3f}')


# --- the curved path, where it reaches much less -------------------------------------------------

from stimpack.visual_stim.cubemap import CubeMapRenderer  # noqa: E402
from stimpack.visual_stim.curved_screen import (  # noqa: E402
    CurvedScreen, PinholeProjector, SphericalSurface,
)
from stimpack.visual_stim.framework import StimDisplay  # noqa: E402


def _curved_screen(cube_resolution=512):
    """A bowl in front of the subject, lit by a projector on its own axis."""
    return CurvedScreen(
        surface=SphericalSurface(radius=0.0775, elevation_range=(25, 90), pole=(0, 1, 0),
                                 n_azimuth=180, n_elevation=32),
        projector=PinholeProjector(position=(0, 0.35, 0), look_at=(0, 0, 0), up=(0, 0, 1),
                                   throw_ratio=1.58),
        cube_resolution=cube_resolution, fullscreen=False, vsync=False)


def _render_curved(ctx, name, kwargs, samples, screen=None):
    """The same stimulus through the real cube-map path, into the same targets paintGL uses."""
    ctx.enable(moderngl.BLEND)
    ctx.enable(moderngl.DEPTH_TEST)
    ctx.extra = {}

    screen = screen or _curved_screen()
    mesh = screen.build_mesh()
    renderer = CubeMapRenderer(ctx, mesh, resolution=screen.cube_resolution,
                               orientation=screen.resolve_cube_orientation(mesh))

    resolved = ctx.framebuffer(color_attachments=[ctx.renderbuffer((SIZE, SIZE))],
                               depth_attachment=ctx.depth_renderbuffer((SIZE, SIZE)))
    if samples:
        target = ctx.framebuffer(
            color_attachments=[ctx.renderbuffer((SIZE, SIZE), samples=samples)],
            depth_attachment=ctx.depth_renderbuffer((SIZE, SIZE), samples=samples))
    else:
        target = resolved

    stim = [c for c in get_all_subclasses(stimuli.BaseProgram)
            if c.__name__ == name][0](screen=screen)
    stim.initialize(ctx)
    stim.configure(**kwargs)

    display = StimDisplay.__new__(StimDisplay)
    display.screen = screen
    display.ctx, display.cube_renderer = ctx, renderer
    display.stim_list, display.stim_started = [stim], True
    display.idle_background = (0.0, 0.0, 0.0, 1.0)
    display.subject_position = SUBJECT_AT_ORIGIN

    target.use()
    target.clear(0, 0, 0, 1)
    display.paint_through_cube_map(0.0, SIZE, SIZE)
    if samples:
        ctx.copy_framebuffer(resolved, target)
    ctx.finish()

    raw = resolved.read(components=3, alignment=1)
    renderer.release()
    return np.flipud(np.frombuffer(raw, dtype=np.uint8).reshape(SIZE, SIZE, 3))[..., 0].astype(int)


def _partial(grey):
    """Pixels neither background nor foreground -- what antialiasing creates and aliasing does not."""
    return int(((grey > 5) & (grey < 250)).sum())


def test_the_cube_faces_are_not_multisampled(headless_gl):
    """The mechanism behind the test below, asserted directly so it cannot change silently.

    msaa_samples multisamples the framebuffer paintGL draws into. The cube faces are rendered into
    framebuffers of the renderer's own, and those are single-sample -- a cube face is a texture
    attachment, and core GL 3.3 has no multisampled cube map. Multisampling them would mean an
    extra multisampled buffer and a resolve per face; that was prototyped and rejected on cost
    (docs/design/analytic-edges.md). If someone builds it, this fails and the docs need revisiting.

    That last sentence is checked, not assumed: this body was run against the prototype -- a
    renderer whose use_face binds a multisampled buffer -- and it goes red on the first face. A
    test asserting a property that is currently true is worth nothing until it has been seen to
    fail.
    """
    screen = _curved_screen(cube_resolution=128)
    mesh = screen.build_mesh()
    renderer = CubeMapRenderer(headless_gl, mesh, resolution=screen.cube_resolution)
    try:
        for face in renderer.face_indices:
            renderer.use_face(face)
            assert headless_gl.fbo.samples == 0, \
                f'face {face} is multisampled; the docs say the faces are not'
    finally:
        renderer.release()


def test_multisampling_transforms_the_flat_path_and_barely_touches_the_curved_one(headless_gl):
    """Stated as the comparison, because the absolute counts are driver-dependent and the
    difference between the paths is not.

    On the flat path multisampling *creates* the antialiasing: without it a box silhouette has no
    partially-covered pixels at all. On the curved path the warp has already done most of the job
    before multisampling sees anything -- it samples the cube bilinearly, and where the cube is
    finer than the output it averages as it goes -- so turning it on adds comparatively little.

    The practical consequence, and the reason to pin it: setting msaa_samples on a curved rig buys
    much less than the same setting on a flat one, and someone reading only the flat tests would
    not know that.
    """
    usable = _supported(headless_gl, (4,))
    if not usable:
        pytest.skip('driver offers no 4x multisampling')
    samples = usable[0]

    flat_plain = _partial(_render(headless_gl, 'MovingBox', BOX, 0))
    flat_ms = _partial(_render(headless_gl, 'MovingBox', BOX, samples))
    curved_plain = _partial(_render_curved(headless_gl, 'MovingBox', BOX, 0))
    curved_ms = _partial(_render_curved(headless_gl, 'MovingBox', BOX, samples))

    assert flat_plain == 0, 'a box through a flat frustum should be hard-edged without this'
    assert flat_ms > 100, f'{samples}x did not antialias the flat path at all ({flat_ms} px)'

    # These two catch the warp ceasing to resample smoothly -- a NEAREST cube filter, or a cube so
    # coarse the warp magnifies instead of minifying. Verified by setting the filter to NEAREST,
    # which takes curved_plain from 181 to 0.
    #
    # What they cannot catch is the cube faces *gaining* multisampling: that would antialias the
    # curved path further at zero widget samples, so the ratio would rise and both would hold more
    # strongly. test_the_cube_faces_are_not_multisampled is what pins that.
    assert curved_plain > 0, \
        'the warp resamples the cube, so the curved path should be partly antialiased already'
    assert curved_plain > 0.5 * curved_ms, (
        f'widget multisampling supplied most of the curved path\'s antialiasing '
        f'({curved_plain} -> {curved_ms} px), which the docs say it does not. Either the warp has '
        f'stopped smoothing, or something else now draws stimulus geometry into the widget target.')
