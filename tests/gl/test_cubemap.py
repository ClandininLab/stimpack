"""Cube-map render and warp, on a real GL context.

The load-bearing test is the first one. A cube map is sampled in a left-handed frame, so the six
face orientations are not something you can reason out and trust -- get one wrong and the picture is
still plausible, just rotated or mirrored on part of the screen, which on a stimulus display is a
silently wrong experiment rather than an obvious bug. So each face is rendered a distinct colour and
sampled back along a known direction.
"""
import pytest

pytest.importorskip("numpy")
pytest.importorskip("moderngl")
pytest.importorskip("OpenGL")

import moderngl  # noqa: E402
import numpy as np  # noqa: E402

from stimpack.visual_stim.cubemap import (  # noqa: E402
    CUBE_FACES, CubeMapRenderer, face_view_projections,
)
from stimpack.visual_stim.curved_screen import (  # noqa: E402
    CylindricalSurface, PinholeProjector, ScreenMesh, SphericalSurface, build_screen_mesh,
)
from stimpack.visual_stim.screen import Screen  # noqa: E402

pytestmark = pytest.mark.gl

# A distinct colour per face, in GL face order (+X, -X, +Y, -Y, +Z, -Z).
FACE_COLORS = ((1.0, 0.0, 0.0, 1.0), (0.0, 1.0, 0.0, 1.0), (0.0, 0.0, 1.0, 1.0),
               (1.0, 1.0, 0.0, 1.0), (1.0, 0.0, 1.0, 1.0), (0.0, 1.0, 1.0, 1.0))


def flat_mesh(directions):
    """A screen mesh of one triangle per direction, each filling the whole projector image.

    Lets a test ask "what colour does the cube give for this direction?" by reading one pixel.
    """
    ndc = np.array([[-3.0, -3.0], [3.0, -3.0], [0.0, 3.0]] * len(directions), dtype=np.float32)
    dirs = np.repeat(np.asarray(directions, dtype=np.float32), 3, axis=0)
    triangles = np.arange(len(ndc), dtype=np.int32).reshape(-1, 3)
    return ScreenMesh(ndc=ndc, directions=dirs, triangles=triangles, positions=dirs)


def fill_faces(renderer, colors=FACE_COLORS):
    for index, color in enumerate(colors[:renderer.faces]):
        renderer.use_face(index, clear_color=color)


def sample_direction(ctx, direction, resolution=32):
    """Render a full-screen triangle carrying `direction` and read the colour that comes back."""
    renderer = CubeMapRenderer(ctx, flat_mesh([direction]), resolution=resolution)
    try:
        fill_faces(renderer)
        target = ctx.simple_framebuffer((8, 8))
        target.use()
        target.clear(0.0, 0.0, 0.0, 1.0)
        renderer.render_warp(viewport=(0, 0, 8, 8))
        ctx.finish()
        return np.frombuffer(target.read(components=4), dtype=np.uint8)[:4] / 255.0
    finally:
        renderer.release()


def test_each_cube_face_is_sampled_by_the_direction_that_should_hit_it(headless_gl):
    """Render a distinct colour per face, then look up each face's own axis and check it comes back.

    This is what pins the face order and the up vectors in CUBE_FACES. Without it, an orientation
    mistake shows as a stimulus that is subtly rotated somewhere on the screen.
    """
    ctx = headless_gl
    for index, (forward, _up) in enumerate(CUBE_FACES):
        got = sample_direction(ctx, forward)
        expected = np.array(FACE_COLORS[index])
        assert np.allclose(got, expected, atol=0.02), (
            f'direction {forward} should sample face {index} ({expected[:3]}), got {got[:3]}')


DIRECTION_VS = """
    #version 330
    in vec3 in_vert;
    out vec3 v_world;
    uniform mat4 Mvp;
    void main() { v_world = in_vert; gl_Position = Mvp * vec4(in_vert, 1.0); }
"""
DIRECTION_FS = """
    #version 330
    in vec3 v_world;
    out vec4 f_color;
    void main() { f_color = vec4(normalize(v_world) * 0.5 + 0.5, 1.0); }
"""


def enclosing_box(ctx, program, half=2.0):
    """A box around the origin whose fragments report their own world direction as colour."""
    h = half
    corners = np.array([[-h, -h, -h], [h, -h, -h], [h, h, -h], [-h, h, -h],
                        [-h, -h, h], [h, -h, h], [h, h, h], [-h, h, h]], dtype='f4')
    quads = [(0, 1, 2, 3), (5, 4, 7, 6), (4, 0, 3, 7), (1, 5, 6, 2),
             (4, 5, 1, 0), (3, 2, 6, 7)]
    tris = []
    for a, b, c, d in quads:
        tris += [corners[a], corners[b], corners[c], corners[a], corners[c], corners[d]]
    buf = ctx.buffer(np.array(tris, dtype='f4').tobytes())
    return ctx.vertex_array(program, [(buf, '3f', 'in_vert')]), len(tris)


def test_every_face_records_the_direction_it_actually_looks_at(headless_gl):
    """Renders a scene that colours each fragment by its own world direction, then reads it back.

    This is what catches an up vector being wrong. Sampling only a face's central axis cannot: that
    point is invariant to rotation within the face, so a flipped `up` still passes. A mutation test
    confirmed exactly that gap, which is why this exists -- an in-face orientation error produces a
    stimulus that is mirrored or rotated over part of the screen and looks entirely reasonable.
    """
    ctx = headless_gl
    ctx.enable(moderngl.DEPTH_TEST)

    # Every face needs a probe that is off-axis in BOTH of its in-face directions. A face's own
    # axis is invariant to rotation within that face, and a probe off-axis in only one direction is
    # invariant to a mirror in the other -- so either alone lets an up vector be wrong undetected.
    probes = []
    for axis in range(3):
        for sign in (+1, -1):
            for du, dv in ((0.45, 0.30), (-0.35, 0.40)):
                probe = [0.0, 0.0, 0.0]
                probe[axis] = float(sign)
                probe[(axis + 1) % 3] = du
                probe[(axis + 2) % 3] = dv
                probes.append(tuple(probe))
    renderer = CubeMapRenderer(ctx, flat_mesh(probes), resolution=128)
    program = ctx.program(vertex_shader=DIRECTION_VS, fragment_shader=DIRECTION_FS)
    box, n_vertices = enclosing_box(ctx, program)
    try:
        for index, matrix in enumerate(face_view_projections()):
            renderer.use_face(index)
            program['Mvp'].write(np.ascontiguousarray(matrix.T))   # column-major for GL
            box.render(moderngl.TRIANGLES, vertices=n_vertices)

        target = ctx.simple_framebuffer((len(probes), 1))
        target.use()
        target.clear(0.0, 0.0, 0.0, 1.0)
        # each probe triangle covers one pixel column, in order
        for i in range(len(probes)):
            ctx.viewport = (i, 0, 1, 1)
            renderer.cube.use(0)
            renderer.program['cube'].value = 0
            renderer.vao.render(vertices=3, first=i * 3)
        ctx.finish()

        # alignment=1: GL pads rows to 4 bytes by default, and a row of N RGB pixels is not a
        # multiple of 4 for most N, which would shift every value after the first.
        got = np.frombuffer(target.read(components=3, alignment=1),
                            dtype=np.uint8).reshape(-1, 3) / 255.0
        for probe, colour in zip(probes, got):
            expected = np.asarray(probe, dtype=float)
            expected = expected / np.linalg.norm(expected) * 0.5 + 0.5
            assert np.allclose(colour, expected, atol=0.03), (
                f'direction {probe}: cube reports {(colour - 0.5) * 2}, '
                f'expected {(expected - 0.5) * 2}')
    finally:
        box.release(); program.release(); renderer.release()


def test_directions_between_faces_stay_on_one_of_the_two(headless_gl):
    """A direction near an edge must land on a neighbouring face, not somewhere unrelated."""
    ctx = headless_gl
    got = sample_direction(ctx, (1.0, 0.0, 0.9))          # between +X and +Z
    plausible = [np.array(FACE_COLORS[0]), np.array(FACE_COLORS[4])]
    assert any(np.allclose(got, c, atol=0.05) for c in plausible), \
        f'edge direction gave {got[:3]}, expected +X or +Z'


def test_face_matrices_are_returned_in_gl_face_order(headless_gl):
    """face_matrices()[i] has to belong to GL_TEXTURE_CUBE_MAP_POSITIVE_X + i, or the scene is
    rendered into the wrong faces and every direction samples the wrong thing."""
    matrices = face_view_projections()
    assert len(matrices) == 6

    for (forward, _up), matrix in zip(CUBE_FACES, matrices):
        # a point one unit along this face's axis should land near the centre of that face's image
        point = np.array([*forward, 1.0], dtype='f4')
        clip = matrix @ point
        assert clip[3] > 0, f'the point along {forward} landed behind the camera'
        ndc = clip[:2] / clip[3]
        assert np.allclose(ndc, 0, atol=1e-5), f'axis {forward} maps to {ndc}, expected the centre'


def test_a_nonsense_resolution_is_rejected_with_a_clear_message(headless_gl):
    """Left to moderngl this surfaces as "invalid color attachment", which does not point at the
    resolution. The framebuffer-completeness check inside remains as insurance for the case GL
    reports by flag rather than exception -- a black screen with no explanation anywhere."""
    with pytest.raises(ValueError, match='at least 1 pixel'):
        CubeMapRenderer(headless_gl, flat_mesh([(1, 0, 0)]), resolution=0)
    with pytest.raises(ValueError, match='6 faces'):
        CubeMapRenderer(headless_gl, flat_mesh([(1, 0, 0)]), resolution=32, faces=7)


def test_the_whole_screen_is_one_draw_call_regardless_of_tessellation(headless_gl):
    """The point of this approach: screen complexity does not multiply scene complexity."""
    ctx = headless_gl
    projector = PinholeProjector(position=(0, 0, 0.30), forward=(0, 0, -1), up=(0, 1, 0))

    for n_azimuth, n_elevation in ((12, 3), (72, 18)):
        surface = SphericalSurface(radius=0.15, n_azimuth=n_azimuth, n_elevation=n_elevation)
        mesh = build_screen_mesh(surface, projector)
        renderer = CubeMapRenderer(ctx, mesh, resolution=64)
        try:
            assert renderer.n_vertices == mesh.n_triangles * 3
            fill_faces(renderer)
            target = ctx.simple_framebuffer((32, 32))
            target.use()
            target.clear(0.0, 0.0, 0.0, 1.0)
            renderer.render_warp(viewport=(0, 0, 32, 32))   # one call, any tessellation
            ctx.finish()
            assert ctx.error == 'GL_NO_ERROR'
            rendered = np.frombuffer(target.read(components=3), dtype=np.uint8)
            assert rendered.any(), 'the warp pass drew nothing'
        finally:
            renderer.release()


def test_a_second_renderer_can_be_built_after_releasing_the_first(headless_gl):
    """moderngl's default gc_mode frees nothing on its own, and GL reuses names aggressively, so
    this is where lifetime mistakes show up."""
    ctx = headless_gl
    for _ in range(3):
        renderer = CubeMapRenderer(ctx, flat_mesh([(1, 0, 0)]), resolution=32)
        fill_faces(renderer)
        renderer.release()
        renderer.release()                                  # idempotent
    assert ctx.error == 'GL_NO_ERROR' 


def test_the_corner_square_survives_the_warp(headless_gl):
    """The photodiode square must land in projector space, unresampled, after the warp.

    It is the frame-timing signal, so its position has to be exact on the physical display and its
    intensity has to be the value asked for. Drawing it before the warp -- or letting the warp cover
    it -- would put it somewhere else on the screen, or soften its edges, and the photodiode trace
    would drift from the frames it is supposed to mark.
    """
    from stimpack.visual_stim.square import SquareProgram

    ctx = headless_gl
    size = 64
    screen = Screen(fullscreen=False, vsync=False,
                    square_size=(0.25, 0.25), square_loc=(-1.0, -1.0))

    renderer = CubeMapRenderer(ctx, flat_mesh([(1, 0, 0)]), resolution=32)
    square = SquareProgram(screen=screen)
    square.initialize(ctx)
    square.set_viewport(size, size)
    square.turn_on()
    try:
        fill_faces(renderer, colors=[(0.0, 0.0, 1.0, 1.0)] * 6)      # warp paints everything blue

        target = ctx.simple_framebuffer((size, size))
        target.use()
        target.clear(0.0, 0.0, 0.0, 1.0)
        renderer.render_warp(viewport=(0, 0, size, size))
        square.paint()                                                # as paintGL does, afterwards
        ctx.finish()

        image = np.frombuffer(target.read(components=3, alignment=1),
                              dtype=np.uint8).reshape(size, size, 3)
    finally:
        renderer.release()

    # square_loc is the lower-left corner in NDC, square_size a fraction of the display
    corner = image[:size // 8, :size // 8]
    elsewhere = image[size // 2:, size // 2:]

    assert (corner[..., 0] > 200).all() and (corner[..., 2] > 200).all(), \
        f'the corner square is not white where it should be: {corner.reshape(-1, 3)[0]}'
    assert (elsewhere[..., 2] > 200).all() and (elsewhere[..., 0] < 60).all(), \
        'the rest of the display should still show the warped scene'


def test_the_corner_square_is_not_softened_by_the_warp(headless_gl):
    """Resampling would blur its edges; a photodiode wants a hard step."""
    from stimpack.visual_stim.square import SquareProgram

    ctx = headless_gl
    size = 64
    screen = Screen(fullscreen=False, vsync=False,
                    square_size=(0.25, 0.25), square_loc=(-1.0, -1.0))
    square = SquareProgram(screen=screen)
    square.initialize(ctx)
    square.set_viewport(size, size)
    square.turn_on()

    target = ctx.simple_framebuffer((size, size))
    target.use()
    target.clear(0.0, 0.0, 0.0, 1.0)
    square.paint()
    ctx.finish()
    image = np.frombuffer(target.read(components=1, alignment=1), dtype=np.uint8).reshape(size, size)

    # every pixel is either fully on or fully off -- no intermediate values along the edge
    intermediate = ((image > 20) & (image < 235)).sum()
    assert intermediate == 0, f'{intermediate} pixels sit between on and off; the square is soft'


@pytest.mark.parametrize('surface, radius, label', [
    (SphericalSurface(radius=0.06, elevation_range=(-90, 0), n_azimuth=48, n_elevation=12),
     0.06, 'bowl'),
    (CylindricalSurface(radius=0.06, height_range=(-0.04, 0.04), n_azimuth=48, n_height=6),
     0.06, 'cylinder'),
])
def test_a_real_screen_shape_renders_through_the_whole_path(headless_gl, surface, radius, label):
    """Both supported shapes, end to end: build the mesh, fill the cube, warp it out.

    The geometry has unit tests and the cube map has its own; this is the join between them, where a
    mesh that is right on paper can still produce a vertex buffer the warp cannot draw.
    """
    ctx = headless_gl
    projector = PinholeProjector.wintech_pro4500(position=(0, -0.25, -0.15), look_at=(0, 0, -0.03))
    mesh = build_screen_mesh(surface, projector)
    assert mesh.n_triangles > 0

    renderer = CubeMapRenderer(ctx, mesh, resolution=128)
    try:
        fill_faces(renderer)
        target = ctx.simple_framebuffer((96, 96))
        target.use()
        target.clear(0.0, 0.0, 0.0, 1.0)
        renderer.render_warp(viewport=(0, 0, 96, 96))
        ctx.finish()

        assert ctx.error == 'GL_NO_ERROR', f'{label}: {ctx.error}'
        image = np.frombuffer(target.read(components=3, alignment=1), dtype=np.uint8)
        drawn = (image.reshape(-1, 3).max(axis=1) > 30).mean()
        assert drawn > 0.05, f'{label}: the warp covered only {drawn:.1%} of the display'
        coverage = mesh.coverage(radius=radius)
        assert 0 < coverage['fraction'] <= 1
    finally:
        renderer.release()
