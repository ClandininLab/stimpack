"""Turning the cube map must change which faces are drawn and nothing else.

The optimisation is only ever worth having if it is invisible: the same scene, warped onto the same
screen, must produce the same pixels whether the cube is axis-aligned or turned to suit the screen.
Everything else here is in service of that one property.

The failure this guards is specific and quiet. The scene is rendered into each face by a matrix, and
the screen mesh samples the cube by direction; turning the cube means rotating both, in opposite
senses, and composing with the subject's heading in the right order. Get any of that wrong and the
picture is still a picture -- plausible, and rotated. `CUBE_FACES` carries the same warning about its
own up-vectors, for the same reason.
"""
import warnings

import numpy as np
import pytest

pytest.importorskip("numpy")
pytest.importorskip("moderngl")

import moderngl  # noqa: E402

from stimpack.visual_stim.cubemap import (  # noqa: E402
    CubeMapRenderer, distance_to_face_region, face_matrices, faces_for_cap, faces_for_directions,
    orientation_for_cap, rotation_taking)
from stimpack.visual_stim.curved_screen import (  # noqa: E402
    CurvedScreen, PinholeProjector, SphericalSurface, build_screen_mesh)

pytestmark = pytest.mark.gl

SCENE_VS = '''#version 330
in vec3 in_pos;
in vec3 in_color;
uniform mat4 matrix;
out vec3 v_color;
void main() { v_color = in_color; gl_Position = matrix * vec4(in_pos * 5.0, 1.0); }
'''
SCENE_FS = '''#version 330
in vec3 v_color;
out vec4 f_color;
void main() { f_color = vec4(v_color, 1.0); }
'''


def bowl(cap_half_angle=60.0, tilt_deg=10.0):
    """A cap like a real rig's, small enough to keep these tests quick."""
    tilt = np.radians(tilt_deg)
    axis = np.array([0.0, np.cos(tilt), -np.sin(tilt)])
    surface = SphericalSurface(radius=0.0775, elevation_range=(90 - cap_half_angle, 90),
                              pole=tuple(axis), n_azimuth=48, n_elevation=12)
    projector = PinholeProjector(position=tuple(axis * 0.305), look_at=(0, 0, 0),
                                 throw_ratio=1.575, aspect_ratio=1.6)
    return surface, projector, build_screen_mesh(surface, projector)


def scene_buffers(ctx, steps=64):
    """A sphere around the subject, painted with its own direction: the point at direction d is
    coloured (d + 1) / 2.

    Chosen so the correct answer is computable rather than merely reproducible. A misoriented cube
    produces a completely different colour field, while re-rasterising the same scene into
    differently turned faces differs only by interpolation -- about one 8-bit step. A scene of
    hard-edged triangles cannot tell those two apart: its edges land differently against the face
    boundaries either way, and the resulting seam noise swamps the signal.
    """
    azimuth = np.linspace(-np.pi, np.pi, steps + 1)
    elevation = np.linspace(-np.pi / 2, np.pi / 2, steps // 2 + 1)
    A, E = np.meshgrid(azimuth, elevation)
    points = np.stack([np.cos(E) * np.sin(A), np.cos(E) * np.cos(A), np.sin(E)], axis=-1)

    triangles = []
    for i in range(len(elevation) - 1):
        for j in range(len(azimuth) - 1):
            triangles += [points[i, j], points[i, j + 1], points[i + 1, j],
                          points[i, j + 1], points[i + 1, j + 1], points[i + 1, j]]
    vertices = np.array(triangles, dtype='f4')

    program = ctx.program(vertex_shader=SCENE_VS, fragment_shader=SCENE_FS)
    vbo = ctx.buffer(np.hstack([vertices, (vertices + 1) / 2]).astype('f4').tobytes())
    vao = ctx.vertex_array(program, [(vbo, '3f 3f', 'in_pos', 'in_color')])
    return program, vao, len(vertices)


def warp_to_pixels(ctx, mesh, orientation, subject_position=None, resolution=256, size=(160, 128)):
    """Render the scene through a cube at this orientation and read back the warped image."""
    program, vao, n_vertices = scene_buffers(ctx)
    renderer = CubeMapRenderer(ctx, mesh, resolution=resolution, orientation=orientation)
    matrices = face_matrices(subject_position, orientation=orientation)
    target = ctx.simple_framebuffer(size)
    try:
        for face in renderer.face_indices:
            renderer.use_face(face, (0.0, 0.0, 0.0, 1.0))
            program['matrix'].write(matrices[face])
            vao.render(moderngl.TRIANGLES, vertices=n_vertices)
        target.use()
        target.clear(0.0, 0.0, 0.0, 1.0)
        ctx.viewport = (0, 0, *size)
        renderer.render_warp()
        ctx.finish()
        pixels = np.frombuffer(target.read(components=3, alignment=1), dtype=np.uint8)
        return pixels.reshape(size[1], size[0], 3).astype(float) / 255.0, len(renderer.face_indices)
    finally:
        target.release(); vao.release(); program.release()


# --- the property the whole feature rests on ------------------------------------------------------

def test_turning_the_cube_does_not_change_the_image(headless_gl):
    """Same scene, same screen, different cube orientation -- the projector must see the same thing.

    If the scene matrices and the sampling directions are rotated inconsistently, this is where it
    shows: the image survives, rotated or mirrored, and every other test still passes.
    """
    ctx = headless_gl
    _, _, mesh = bowl()
    plain, n_plain = warp_to_pixels(ctx, mesh, orientation=None)
    turned, n_turned = warp_to_pixels(ctx, mesh, orientation=orientation_for_cap(
        [0, np.cos(np.radians(10)), -np.sin(np.radians(10))], np.radians(60)))

    lit = plain.max(axis=2) > 0.02
    assert lit.mean() > 0.3, 'the test scene lit almost nothing; it cannot detect a difference'
    assert n_turned < n_plain, f'orientation should have saved a face: {n_plain} -> {n_turned}'

    difference = np.abs(plain - turned).max(axis=2)[lit]
    assert difference.max() < 0.02, (
        f'turning the cube changed the image by up to {difference.max():.4f}; interpolation alone '
        f'is about one 8-bit step')


def test_it_still_agrees_once_the_subject_turns(headless_gl):
    """Heading is applied by rotating each face's axes, and the screen's orientation composes with
    that. Compose them the other way round and this is the only test that fails."""
    ctx = headless_gl
    _, _, mesh = bowl()
    heading = {'x': 0.0, 'y': 0.0, 'z': 0.0, 'theta': 47.0, 'phi': 13.0, 'roll': 0.0}
    orientation = orientation_for_cap([0, np.cos(np.radians(10)), -np.sin(np.radians(10))],
                                      np.radians(60))

    plain, _ = warp_to_pixels(ctx, mesh, None, subject_position=heading)
    turned, _ = warp_to_pixels(ctx, mesh, orientation, subject_position=heading)

    lit = plain.max(axis=2) > 0.02
    assert lit.mean() > 0.3, 'nothing rendered, so agreement is meaningless'
    assert np.abs(plain - turned).max(axis=2)[lit].max() < 0.02


def test_an_identity_orientation_is_the_unrotated_path(headless_gl):
    """Belt and braces: passing the identity must not perturb anything."""
    ctx = headless_gl
    _, _, mesh = bowl()
    plain, n_plain = warp_to_pixels(ctx, mesh, orientation=None)
    identity, n_identity = warp_to_pixels(ctx, mesh, orientation=np.eye(3))
    assert n_identity == n_plain
    assert np.abs(plain - identity).max() < 1e-6


# --- that it actually saves faces -----------------------------------------------------------------

@pytest.mark.parametrize('cap, expected', [(60.0, 3), (65.0, 3), (68.0, 4), (75.0, 4)])
def test_the_chosen_orientation_saves_faces(cap, expected):
    """The whole point. 'auto' takes the corner while the cap clears arccos(1/3) by CORNER_MARGIN,
    and the edge after that. 65 is in the table because a round-number cutoff excluded it while it
    still had 5.5 degrees in hand -- and 65 is what a real rig runs."""
    _, _, mesh = bowl(cap_half_angle=cap)
    axis = np.array([0, np.cos(np.radians(10)), -np.sin(np.radians(10))])
    orientation = orientation_for_cap(axis, np.radians(cap))

    before = faces_for_directions(mesh.directions, mesh.triangles)
    after = faces_for_directions(mesh.directions @ orientation.T, mesh.triangles)
    assert len(after) == expected, f'{cap} deg: expected {expected} faces, got {len(after)}'
    assert len(after) < len(before)


# --- the closed form the choice rests on ----------------------------------------------------------

@pytest.mark.parametrize('axis, expected', [
    ((0, 0, 1), {0.0, np.degrees(np.arccos(-1 / np.sqrt(3))), 45.0}),      # a face centre
    ((0, 1, 1), {0.0, np.degrees(np.arccos(2 / np.sqrt(6))), 90.0}),       # an edge midpoint
    ((1, 1, 1), {0.0, np.degrees(np.arccos(1 / 3))}),                      # a corner
])
def test_the_distances_match_their_closed_forms(axis, expected):
    """These four numbers are the whole design. 45, arccos(2/sqrt6), arccos(1/3), arccos(-1/sqrt3)."""
    axis = np.asarray(axis, float) / np.linalg.norm(axis)
    found = {round(np.degrees(distance_to_face_region(axis, f)), 6) for f in range(6)}
    assert found == {round(v, 6) for v in expected}


@pytest.mark.parametrize('half_angle, faces', [(70.0, 3), (70.52, 3), (70.54, 6)])
def test_the_corner_threshold_is_arccos_one_third(half_angle, faces):
    """A cap on a cube corner touches three faces until exactly arccos(1/3) = 70.53 degrees, and six
    immediately after. That cliff is why 'auto' stops using the corner well before it."""
    corner = np.array([1.0, 1.0, 1.0]) / np.sqrt(3)
    assert len(faces_for_cap(corner, np.radians(half_angle))) == faces


def test_auto_prefers_margin_over_the_smallest_count():
    """At 68 degrees the corner still gives three faces, on 2.5 degrees of margin -- inside
    CORNER_MARGIN. 'auto' declines it: falling off that threshold costs three faces at once."""
    axis = np.array([0.0, 1.0, 0.0])
    auto = orientation_for_cap(axis, np.radians(68.0))
    corner = orientation_for_cap(axis, np.radians(68.0), prefer='corner')
    assert len(faces_for_cap(auto @ axis, np.radians(68.0))) == 4
    assert len(faces_for_cap(corner @ axis, np.radians(68.0))) == 3


def test_a_rotation_really_lands_where_it_says():
    for target in ((1, 1, 1), (0, 1, 1), (0, 0, 1)):
        axis = np.array([0.2, 0.9, -0.3]); axis /= np.linalg.norm(axis)
        rotation = rotation_taking(axis, target)
        wanted = np.asarray(target, float) / np.linalg.norm(target)
        assert np.allclose(rotation @ axis, wanted, atol=1e-9)
        assert np.allclose(rotation @ rotation.T, np.eye(3), atol=1e-9)
        assert np.isclose(np.linalg.det(rotation), 1.0)


def test_an_antiparallel_rotation_does_not_divide_by_zero():
    """cross(a, -a) is zero, so the general formula has no axis to use."""
    rotation = rotation_taking([0, 0, 1], [0, 0, -1])
    assert np.allclose(rotation @ np.array([0, 0, 1.0]), [0, 0, -1], atol=1e-9)
    assert np.isclose(np.linalg.det(rotation), 1.0)


# --- refusing what it cannot honour ---------------------------------------------------------------

def test_a_non_rotation_is_refused(headless_gl):
    _, _, mesh = bowl()
    with pytest.raises(ValueError, match='rotation'):
        CubeMapRenderer(headless_gl, mesh, resolution=64, orientation=np.diag([1.0, 2.0, 1.0]))
    with pytest.raises(ValueError, match='3x3'):
        CubeMapRenderer(headless_gl, mesh, resolution=64, orientation=np.eye(4))


def cylinder_screen(**kwargs):
    from stimpack.visual_stim.curved_screen import CylindricalSurface
    return CurvedScreen(
        surface=CylindricalSurface(radius=0.15, azimuth_range=(-60, 60),
                                   height_range=(-0.06, 0.06)),
        projector=PinholeProjector(position=(0, 0.6, 0.0), look_at=(0, 0, 0), up=(0, 0, 1),
                                   throw_ratio=0.8), **kwargs)


def test_auto_works_on_a_cylinder_without_complaining():
    """'auto' reads the mesh's directions, not the surface's parameters, so a shape that is not a
    cap is not a special case. It used to warn that a cylinder had no axis to aim at -- noise on
    every launch, for rigs that had asked for nothing unreasonable."""
    screen = cylinder_screen(cube_orientation='auto')
    with warnings.catch_warnings():
        warnings.simplefilter('error')                  # any warning at all fails this
        mesh = screen.build_mesh()
        orientation = screen.resolve_cube_orientation(mesh)

    faces = faces_for_directions(
        mesh.directions if orientation is None else mesh.directions @ orientation.T, mesh.triangles)
    assert len(faces) <= len(faces_for_directions(mesh.directions, mesh.triangles))


def test_a_rotation_is_kept_only_when_it_actually_helps():
    """The closed form is about a cap; a real screen need not be one. So the candidate is measured
    against this mesh and discarded if it saves nothing, rather than trusted."""
    screen = cylinder_screen(cube_orientation='auto')
    mesh = screen.build_mesh()
    before = len(faces_for_directions(mesh.directions, mesh.triangles))
    orientation = screen.resolve_cube_orientation(mesh)
    if orientation is not None:
        assert len(faces_for_directions(mesh.directions @ orientation.T, mesh.triangles)) < before


def test_a_screen_covering_the_whole_sphere_has_nothing_to_aim_at():
    """The centroid of an even spread is the origin, which is not a direction. No rotation, no
    warning, and no normalising of a zero vector."""
    class WholeSphere:
        directions = np.array([[1., 0, 0], [-1, 0, 0], [0, 1., 0],
                               [0, -1, 0], [0, 0, 1.], [0, 0, -1]])
        triangles = np.array([[0, 2, 4], [1, 3, 5]])

    assert CurvedScreen(cube_orientation='auto').resolve_cube_orientation(WholeSphere()) is None


def test_the_default_leaves_the_cube_where_it_was():
    """Every rig that predates this must be unaffected."""
    assert CurvedScreen().cube_orientation is None
    assert CurvedScreen().resolve_cube_orientation() is None


def test_the_orientation_survives_serialization():
    """A screen is rebuilt from this dict in the display subprocess; an orientation lost in transit
    would leave the faces drawn and the directions sampled disagreeing."""
    from stimpack.visual_stim.screen import Screen

    for value in ('auto', 'corner', None):
        screen = CurvedScreen(surface=SphericalSurface(elevation_range=(30, 90)),
                              cube_orientation=value)
        rebuilt = Screen.deserialize(screen.serialize())
        assert rebuilt.cube_orientation == value
        expected = screen.resolve_cube_orientation()
        got = rebuilt.resolve_cube_orientation()
        assert (got is None) == (expected is None)
        if expected is not None:
            assert np.allclose(got, expected)


def test_the_warped_colour_is_the_direction_it_should_be(headless_gl):
    """Absolute, not comparative: the scene paints direction d as (d + 1) / 2, so every lit fragment
    must come back as its own direction.

    The comparison tests above would both pass if the two paths were wrong in the same way -- they
    share every line except the rotation. This one has no such escape.
    """
    ctx = headless_gl
    _, _, mesh = bowl()
    size = (160, 128)
    orientation = orientation_for_cap([0, np.cos(np.radians(10)), -np.sin(np.radians(10))],
                                      np.radians(60))

    for label, rotation in (('unrotated', None), ('turned', orientation)):
        image, _ = warp_to_pixels(ctx, mesh, rotation, size=size)

        # sample the image where the mesh says a known direction lands
        errors = []
        for ndc, direction in zip(mesh.ndc[mesh.lit], mesh.directions[mesh.lit]):
            if not np.all(np.abs(ndc) < 0.9):
                continue                            # keep clear of the edges and their seams
            # framebuffer.read() hands back rows bottom-up, so NDC y maps straight to the row
            col = int(np.clip((ndc[0] + 1) / 2 * size[0], 0, size[0] - 1))
            row = int(np.clip((ndc[1] + 1) / 2 * size[1], 0, size[1] - 1))
            expected = (np.asarray(direction) + 1) / 2
            errors.append(np.abs(image[row, col] - expected).max())

        assert len(errors) > 50, f'{label}: too few sample points to be meaningful'
        assert np.percentile(errors, 90) < 0.05, (
            f'{label}: warped colour disagrees with the direction it represents '
            f'(90th percentile {np.percentile(errors, 90):.3f})')
