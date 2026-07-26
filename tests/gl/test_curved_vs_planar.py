"""Does the curved path put a stimulus where the planar path does?

The planar path is the one that has been running on real rigs for years, so it is the reference. A
flat screen can be described either way -- as a SubScreen through a Kooima frustum, or as a
(degenerate) curved screen mesh through a cube map -- and the two must agree. Where they would most
easily disagree is the heading convention: get_perspective rotates the screen corners by yaw about
z, then pitch about x, then roll about y, and the cube path has to rotate its face axes the same
way. Get that wrong and everything looks fine until a subject turns, which is to say until closed
loop is running.

Compared by the centroid of a small bright spot rather than pixel-by-pixel, because the two paths
resample differently and an exact match is not the claim. Where the spot lands is.
"""
import pytest

pytest.importorskip("numpy")
pytest.importorskip("moderngl")
pytest.importorskip("OpenGL")

import moderngl  # noqa: E402
import numpy as np  # noqa: E402

from stimpack.visual_stim import stimuli  # noqa: E402
from stimpack.visual_stim.cubemap import CubeMapRenderer, face_matrices  # noqa: E402
from stimpack.visual_stim.curved_screen import ScreenMesh  # noqa: E402
from stimpack.visual_stim.framework import get_perspective  # noqa: E402
from stimpack.visual_stim.screen import Screen, SubScreen  # noqa: E402

pytestmark = pytest.mark.gl

SIZE = 192
# A flat screen in front of the subject: 60 cm square, 30 cm away, so it spans +-45 degrees. Wide on
# purpose -- yaw and pitch compose differently depending on their order, but only by a second-order
# amount, so small angles leave the two orders indistinguishable. A mutation swapping them passed
# against a +-26 degree screen.
PA, PB, PC = (-0.30, 0.30, -0.30), (+0.30, 0.30, -0.30), (-0.30, 0.30, +0.30)


def flat_screen_mesh(subject_xyz=(0, 0, 0), steps=24):
    """The same flat patch, described the way a curved screen is: projector NDC plus direction."""
    u, v = np.meshgrid(np.linspace(0, 1, steps + 1), np.linspace(0, 1, steps + 1), indexing='ij')
    pa, pb, pc = (np.array(p, dtype=float) for p in (PA, PB, PC))
    points = (pa + u[..., None] * (pb - pa) + v[..., None] * (pc - pa)).reshape(-1, 3)

    ndc = np.stack([2 * u - 1, 2 * v - 1], axis=-1).reshape(-1, 2)
    directions = points - np.asarray(subject_xyz, dtype=float)
    directions /= np.linalg.norm(directions, axis=1, keepdims=True)

    n = steps + 1
    i, j = np.meshgrid(np.arange(steps), np.arange(steps), indexing='ij')
    ll = (i * n + j).reshape(-1)
    triangles = np.concatenate([
        np.stack([ll, ll + n, ll + n + 1], axis=-1),
        np.stack([ll, ll + n + 1, ll + 1], axis=-1),
    ]).astype(np.int32)
    return ScreenMesh(ndc=ndc, directions=directions, triangles=triangles, positions=points)


def make_stim(ctx, theta, phi):
    screen = Screen(subscreens=[SubScreen(pa=PA, pb=PB, pc=PC)], fullscreen=False, vsync=False)
    stim = stimuli.MovingSpot(screen=screen)
    stim.initialize(ctx)
    stim.configure(radius=8, sphere_radius=1, color=[1, 1, 1, 1], theta=theta, phi=phi)
    return stim


def centroid(image):
    """Centre of mass of the bright pixels, in pixels, or None if nothing was drawn."""
    mask = image > 60
    if mask.sum() < 4:
        return None
    ys, xs = np.nonzero(mask)
    return np.array([xs.mean(), ys.mean()])


def render_planar(ctx, subject_position, theta, phi):
    fbo = ctx.simple_framebuffer((SIZE, SIZE))
    fbo.use()
    fbo.clear(0.0, 0.0, 0.0, 1.0)
    stim = make_stim(ctx, theta, phi)
    perspective = get_perspective(subject_position, PA, PB, PC, False)
    stim.paint_at(0.0, [(0, 0, SIZE, SIZE)], [perspective], subject_position=subject_position)
    ctx.finish()
    image = np.frombuffer(fbo.read(components=1, alignment=1), dtype=np.uint8).reshape(SIZE, SIZE)
    fbo.release()
    return image


def render_curved(ctx, subject_position, theta, phi, resolution=512):
    # The mesh is built from the rig origin, not from subject_position: it is fixed geometry saying
    # which direction each part of the screen lies in. Virtual movement is applied by rendering the
    # cube from the virtual position, which is how the planar path does it too -- GenPerspective
    # keeps its eye at the origin and translates the world. Building the mesh from the virtual
    # position instead applies the translation twice, which showed up here as a 14 px offset.
    renderer = CubeMapRenderer(ctx, flat_screen_mesh(), resolution=resolution)
    stim = make_stim(ctx, theta, phi)
    try:
        for face, matrix in enumerate(face_matrices(subject_position)):
            renderer.use_face(face, clear_color=(0.0, 0.0, 0.0, 1.0))
            stim.paint_at(0.0, [(0, 0, resolution, resolution)], [matrix],
                          subject_position=subject_position)

        fbo = ctx.simple_framebuffer((SIZE, SIZE))
        fbo.use()
        fbo.clear(0.0, 0.0, 0.0, 1.0)
        renderer.render_warp(viewport=(0, 0, SIZE, SIZE))
        ctx.finish()
        image = np.frombuffer(fbo.read(components=1, alignment=1),
                              dtype=np.uint8).reshape(SIZE, SIZE)
        fbo.release()
        return image
    finally:
        renderer.release()


def subject(x=0.0, y=0.0, z=0.0, theta=0.0, phi=0.0, roll=0.0):
    return {'x': x, 'y': y, 'z': z, 'theta': theta, 'phi': phi, 'roll': roll}


@pytest.mark.parametrize('subject_position, label', [
    (subject(), 'at rest'),
    (subject(theta=25), 'yawed +25'),
    (subject(theta=-20), 'yawed -20'),
    (subject(phi=15), 'pitched +15'),
    (subject(theta=20, phi=-10), 'yawed and pitched'),
    (subject(theta=35, phi=30), 'yawed and pitched hard'),
    (subject(theta=-30, phi=25, roll=20), 'all three at once'),
    (subject(roll=30), 'rolled +30'),
    (subject(x=0.02, z=-0.01), 'translated'),
])
def test_a_spot_lands_in_the_same_place_either_way(headless_gl, subject_position, label):
    """The heading convention is what this is really testing.

    get_perspective composes yaw about z, then pitch about x, then roll about y, applied to the
    screen corners. face_view_projections has to apply the same composition to its face axes. A
    different order, or a sign flip, leaves both paths looking perfectly sensible in isolation and
    disagreeing the moment a subject turns.
    """
    ctx = headless_gl
    ctx.enable(moderngl.DEPTH_TEST)

    planar = centroid(render_planar(ctx, subject_position, theta=0, phi=0))
    curved = centroid(render_curved(ctx, subject_position, theta=0, phi=0))

    assert planar is not None, f'{label}: the planar path drew no spot'
    assert curved is not None, f'{label}: the curved path drew no spot'
    offset = np.linalg.norm(planar - curved)
    assert offset < 4.0, (f'{label}: spot at {planar} through the planar path, {curved} through '
                          f'the curved one -- {offset:.1f} px apart on a {SIZE} px screen')


@pytest.mark.parametrize('theta, phi', [(0, 0), (25, 0), (-30, 10), (0, -20)])
def test_a_spot_placed_off_centre_agrees_too(headless_gl, theta, phi):
    """Moving the stimulus rather than the subject, which exercises the same maths from the other
    side: if only one of the two were wrong, these would drift apart."""
    ctx = headless_gl
    ctx.enable(moderngl.DEPTH_TEST)

    planar = centroid(render_planar(ctx, subject(), theta, phi))
    curved = centroid(render_curved(ctx, subject(), theta, phi))

    assert planar is not None and curved is not None, f'spot at ({theta}, {phi}) was not drawn'
    offset = np.linalg.norm(planar - curved)
    assert offset < 4.0, f'spot at ({theta}, {phi}): {offset:.1f} px apart'


@pytest.mark.parametrize('subject_position, theta, phi, label', [
    (subject(roll=30), 25, 0, 'rolled, stimulus off to the side'),
    (subject(roll=-25), 0, 20, 'rolled the other way, stimulus above'),
    (subject(theta=15, roll=20), -20, 15, 'yawed and rolled, stimulus off-axis'),
])
def test_roll_is_checked_with_the_stimulus_off_the_roll_axis(headless_gl, subject_position,
                                                             theta, phi, label):
    """Roll is about +y, the direction the subject faces, so a stimulus dead ahead sits on the axis
    and does not move when it changes -- negating roll passed every other case here. The stimulus
    has to be off-centre for roll to be observable at all."""
    ctx = headless_gl
    ctx.enable(moderngl.DEPTH_TEST)

    planar = centroid(render_planar(ctx, subject_position, theta, phi))
    curved = centroid(render_curved(ctx, subject_position, theta, phi))

    assert planar is not None and curved is not None, f'{label}: no spot drawn'
    offset = np.linalg.norm(planar - curved)
    assert offset < 4.0, f'{label}: {offset:.1f} px apart'


def test_the_comparison_would_notice_a_wrong_heading(headless_gl):
    """Guards the test itself: if a yaw of 25 degrees moved nothing, the checks above would pass
    against a curved path that ignored heading entirely."""
    ctx = headless_gl
    ctx.enable(moderngl.DEPTH_TEST)

    still = centroid(render_curved(ctx, subject(), theta=0, phi=0))
    turned = centroid(render_curved(ctx, subject(theta=25), theta=0, phi=0))

    assert still is not None and turned is not None
    assert np.linalg.norm(still - turned) > 20, \
        'yawing the subject barely moved the stimulus; this comparison proves little'
