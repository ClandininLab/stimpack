"""Golden-image tests: confirm that stimuli render correctly and don't regress.

Each case renders a stimulus headlessly (a standalone moderngl context, the real Screen /
GenPerspective / BaseProgram classes — the same rendering path StimDisplay.paintGL uses, minus the
Qt window) and compares the result against a committed reference PNG.

Workflow (references are NOT auto-generated — a human must eyeball the first render):
  1. Generate:  pytest -m gl --update-goldens
  2. Review the PNGs written to tests/gl/reference/ — confirm each looks correct.
  3. Commit them. Thereafter this test fails if a change alters the rendered output.

Generate references in the same GL backend CI uses (software GL, LIBGL_ALWAYS_SOFTWARE=1) so the
committed images are reproducible across machines. See tests/gl/reference/README.md.
"""
import math
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("yaml")          # importing the screen/perspective path pulls in config_tools
pytest.importorskip("platformdirs")

from stimpack.visual_stim.screen import Screen
from stimpack.visual_stim.perspective import GenPerspective

pytestmark = pytest.mark.gl

REFERENCE_DIR = Path(__file__).parent / "reference"
FAILURE_DIR = Path(__file__).parent / "_failures"
RENDER_SIZE = (256, 256)  # (width, height)

# Representative, deterministic stimuli: a uniform fill, a spherical spot + patch, and two
# cylinder-textured patterns. Extend this list as coverage grows.
CASES = [
    dict(id="constant_background_gray", name="ConstantBackground",
         kwargs=dict(color=[0.5, 0.5, 0.5, 1.0]), tol=1.5),
    dict(id="moving_spot_center", name="MovingSpot",
         kwargs=dict(radius=15, sphere_radius=1, color=[1, 1, 1, 1], theta=0, phi=0), tol=3.0),
    dict(id="moving_patch_center", name="MovingPatch",
         kwargs=dict(width=25, height=25, sphere_radius=1, color=[1, 1, 1, 1],
                     theta=0, phi=0, angle=0), tol=3.0),
    dict(id="cylindrical_grating_square", name="CylindricalGrating",
         kwargs=dict(period=30, mean=0.5, contrast=1.0, profile="square"), tol=4.0),
    dict(id="checkerboard", name="Checkerboard",
         kwargs=dict(patch_width=15, patch_height=15), tol=4.0),

    # Perspective / positioning: a patch pushed off-center in azimuth+elevation, and one rotated
    # in-plane — these catch regressions in the projection / heading math.
    dict(id="moving_patch_offcenter", name="MovingPatch",
         kwargs=dict(width=25, height=25, sphere_radius=1, color=[1, 1, 1, 1],
                     theta=30, phi=20, angle=0), tol=3.0),
    dict(id="moving_patch_rotated", name="MovingPatch",
         kwargs=dict(width=45, height=12, sphere_radius=1, color=[1, 1, 1, 1],
                     theta=0, phi=0, angle=45), tol=3.5),

    # Alternate spherical shape builder.
    dict(id="moving_ellipse_center", name="MovingEllipse",
         kwargs=dict(width=45, height=22, sphere_radius=1, color=[1, 1, 1, 1],
                     theta=0, phi=0, angle=0), tol=3.0),

    # The same two patches on a cylinder wall rather than a sphere. Identical directions, different
    # surface — these hold the two apart, so a change to one cannot silently pass on the other.
    dict(id="moving_patch_on_cylinder", name="MovingPatchOnCylinder",
         kwargs=dict(width=25, height=25, cylinder_radius=1, color=[1, 1, 1, 1],
                     theta=0, phi=0, angle=0), tol=3.0),
    dict(id="moving_ellipse_on_cylinder", name="MovingEllipseOnCylinder",
         kwargs=dict(width=45, height=22, cylinder_radius=1, color=[1, 1, 1, 1],
                     theta=0, phi=0, angle=0), tol=3.0),

    # Grating variants: a sine profile (grayscale gradient, vs the square case above) and an angled
    # grating (exercises the tilted-texture generation path).
    dict(id="cylindrical_grating_sine", name="CylindricalGrating",
         kwargs=dict(period=30, mean=0.5, contrast=1.0, profile="sine"), tol=4.0),
    dict(id="cylindrical_grating_angled", name="CylindricalGrating",
         kwargs=dict(period=30, mean=0.5, contrast=1.0, profile="square", grating_angle=30), tol=5.0),

    # Time + trajectory evaluation: a looming spot whose radius is a Loom trajectory, rendered at
    # t=0.7 s — confirms trajectory evaluation (return_for_time_t) feeds the geometry.
    dict(id="looming_spot", name="MovingSpot",
         kwargs=dict(radius={"name": "Loom", "rv_ratio": 0.1, "stim_time": 1.0,
                             "start_size": 10, "end_size": 80},
                     sphere_radius=1, color=[1, 1, 1, 1], theta=0, phi=0),
         t=0.7, tol=3.0),

    # Deterministic seeded noise: a fixed start_seed must produce a stable pattern.
    dict(id="random_grid_seeded", name="RandomGrid",
         kwargs=dict(patch_width=15, patch_height=15,
                     distribution_data={"name": "Binary", "rand_min": 0, "rand_max": 1},
                     start_seed=42, update_rate=1.0), tol=5.0),

    # World-space VR geometry + a non-white color: a red tower in front of the subject.
    dict(id="tower_world", name="Tower",
         kwargs=dict(color=[1, 0, 0, 1], cylinder_radius=0.5, cylinder_height=1.0,
                     cylinder_location=[0, 3, 0], n_faces=32), tol=3.5),
]

SUBJECT_AT_ORIGIN = {"x": 0, "y": 0, "z": 0, "theta": 0, "phi": 0, "roll": 0}


def _make_screen():
    """Subject at the origin; one screen face at y=0.15 m spanning ~+/-45 deg in azimuth/elevation."""
    return Screen(pa=(-0.15, 0.15, -0.15), pb=(0.15, 0.15, -0.15), pc=(-0.15, 0.15, 0.15),
                  fullscreen=False, vsync=False)


def _perspective(subject_pos, pa, pb, pc, horizontal_flip):
    # Faithful reimplementation of framework.get_perspective (which lives in a module that imports
    # PyQt6/moderngl at top; we replicate it from the numpy-only GenPerspective to stay importable).
    x, y, z = subject_pos["x"], subject_pos["y"], subject_pos["z"]
    p = GenPerspective(pa=pa, pb=pb, pc=pc, subject_xyz=(x, y, z), horizontal_flip=horizontal_flip)
    return (p.rotz(math.radians(subject_pos["theta"]))
             .rotx(math.radians(subject_pos["phi"]))
             .roty(math.radians(subject_pos.get("roll", 0)))
             .matrix)


def _render(ctx, name, kwargs, t=0.0, size=RENDER_SIZE):
    """Render one stimulus to an (H, W, 3) uint8 array using the real stimpack rendering path."""
    import moderngl
    from stimpack.util import get_all_subclasses
    from stimpack.visual_stim import stimuli

    width, height = size

    # Mirror StimDisplay.initializeGL's context setup.
    ctx.enable(moderngl.BLEND)
    ctx.enable(moderngl.DEPTH_TEST)
    ctx.extra = {}

    color_rb = ctx.renderbuffer((width, height))
    depth_rb = ctx.depth_renderbuffer((width, height))
    fbo = ctx.framebuffer(color_attachments=[color_rb], depth_attachment=depth_rb)
    fbo.use()
    fbo.clear(0.0, 0.0, 0.0, 1.0)

    screen = _make_screen()
    viewports = [sub.get_viewport(width, height) for sub in screen.subscreens]
    perspectives = [_perspective(SUBJECT_AT_ORIGIN, sub.pa, sub.pb, sub.pc, screen.horizontal_flip)
                    for sub in screen.subscreens]

    candidates = [c for c in get_all_subclasses(stimuli.BaseProgram) if c.__name__ == name]
    assert len(candidates) == 1, f"expected exactly one stim class named {name!r}, got {len(candidates)}"
    stim = candidates[0](screen=screen)
    stim.initialize(ctx)
    stim.configure(**kwargs)
    stim.paint_at(t, viewports, perspectives, subject_position=SUBJECT_AT_ORIGIN)
    ctx.finish()

    raw = fbo.read(components=3, alignment=1)
    img = np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 3)
    return np.flipud(img).copy()  # GL origin is bottom-left; flip to a top-down image


def _mean_abs_error(a, b):
    return float(np.mean(np.abs(a.astype(np.int16) - b.astype(np.int16))))


OUTPUT_DIR = Path(__file__).parent / "_output"


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_stimulus_matches_reference(case, headless_gl, update_goldens, save_renders):
    Image = pytest.importorskip("PIL.Image")

    actual = _render(headless_gl, case["name"], case["kwargs"], t=case.get("t", 0.0))

    # Sanity: a stimulus should draw *something* (not leave the frame all black).
    assert actual.max() > 0, f"{case['id']}: rendered frame is entirely black"

    if save_renders:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        Image.fromarray(actual).save(OUTPUT_DIR / f"{case['id']}.png")

    ref_path = REFERENCE_DIR / f"{case['id']}.png"

    if update_goldens:
        REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
        Image.fromarray(actual).save(ref_path)
        pytest.skip(f"wrote reference {ref_path.name} — review it, then commit")

    if not ref_path.exists():
        pytest.skip(
            f"no reference for {case['id']}; run `pytest -m gl --update-goldens`, "
            f"review tests/gl/reference/{ref_path.name}, then commit it"
        )

    reference = np.asarray(Image.open(ref_path).convert("RGB"))
    assert reference.shape == actual.shape, f"{case['id']}: size {actual.shape} != reference {reference.shape}"

    mae = _mean_abs_error(actual, reference)
    if mae > case["tol"]:
        FAILURE_DIR.mkdir(parents=True, exist_ok=True)
        Image.fromarray(actual).save(FAILURE_DIR / f"{case['id']}.actual.png")
        diff = np.abs(actual.astype(np.int16) - reference.astype(np.int16)).astype(np.uint8)
        Image.fromarray(diff).save(FAILURE_DIR / f"{case['id']}.diff.png")
        pytest.fail(
            f"{case['id']}: mean abs pixel error {mae:.2f} exceeds tolerance {case['tol']}. "
            f"Rendered vs reference diff written to tests/gl/_failures/."
        )


def test_more_textured_stimuli_than_texture_units_still_render(headless_gl):
    """An epoch may hold more textured stimuli than the GPU has sampler units.

    Textures used to be bound once at load, each to a unit of its own, so an epoch was capped at
    GL_MAX_TEXTURE_IMAGE_UNITS textured stimuli -- 32 on the development GPU, 16 on some. A real
    protocol in clandinin_labpack already loads 31 in one epoch. Past the cap, the drivers tested
    here bind and render with no GL error at all, so the stimulus is simply wrong on screen with
    nothing to say so. Binding per draw means one unit suffices for any number of stimuli.
    """
    import moderngl
    from stimpack.visual_stim import stimuli

    ctx = headless_gl
    limit = ctx.info['GL_MAX_TEXTURE_IMAGE_UNITS']
    width, height = 64, 64

    ctx.enable(moderngl.BLEND)
    ctx.enable(moderngl.DEPTH_TEST)
    ctx.extra = {}

    color_rb = ctx.renderbuffer((width, height))
    depth_rb = ctx.depth_renderbuffer((width, height))
    fbo = ctx.framebuffer(color_attachments=[color_rb], depth_attachment=depth_rb)
    fbo.use()
    fbo.clear(0.0, 0.0, 0.0, 1.0)

    screen = _make_screen()
    viewports = [sub.get_viewport(width, height) for sub in screen.subscreens]
    perspectives = [_perspective(SUBJECT_AT_ORIGIN, sub.pa, sub.pb, sub.pc, screen.horizontal_flip)
                    for sub in screen.subscreens]

    for i in range(limit + 4):
        stim = stimuli.CylindricalGrating(screen=screen)
        stim.initialize(ctx)
        stim.configure(period=30, mean=0.5, contrast=1.0, profile='square', offset=float(i))
        assert stim.use_texture, 'CylindricalGrating should be textured'
        stim.paint_at(0.0, viewports, perspectives, subject_position=SUBJECT_AT_ORIGIN)

    ctx.finish()
    assert ctx.error == 'GL_NO_ERROR', f'GL error after {limit + 4} textured stimuli: {ctx.error}'

    img = np.frombuffer(fbo.read(components=3, alignment=1), dtype=np.uint8)
    assert img.any(), 'nothing was drawn'


def test_dynamic_texture_update_accepts_non_contiguous_arrays(headless_gl):
    """#31: update_texture_gl hands the array to GL directly when it can.

    A non-contiguous array (a slice, a transpose) has no usable buffer, so it must still go through
    .tobytes(). Both paths have to produce the same texture.
    """
    from stimpack.visual_stim.base import BaseProgram

    ctx = headless_gl
    ctx.extra = {}

    stim = BaseProgram(screen=_make_screen())
    stim.use_texture = True
    stim.initialize(ctx)

    contiguous = (np.arange(64 * 64, dtype=np.uint8).reshape(64, 64))
    stim.add_texture_gl(contiguous)

    stim.update_texture_gl(contiguous)                  # buffer-protocol path
    assert ctx.error == 'GL_NO_ERROR'

    non_contiguous = np.ascontiguousarray(contiguous)[::-1].T
    assert not non_contiguous.flags['C_CONTIGUOUS']
    stim.update_texture_gl(non_contiguous)              # .tobytes() fallback
    assert ctx.error == 'GL_NO_ERROR'


# --- analytic edges (docs/design/analytic-edges.md) ----------------------------------------------
#
# Both of these guard failures that pass a visual check: a disc drawn 0.38% small looks perfect,
# and so does an edge that ramps on an S-curve.

def test_a_disc_bound_contains_the_radius_it_was_asked_for():
    """The triangles are a bound now, not the shape, so they must CONTAIN the true circle.

    They used to sit on it, which put the chords between them 0.38% inside -- 0.076 degrees on a
    20 degree disc, nearly twice a pixel on a flat rig. A fragment shader can only remove coverage,
    never add it, so an inscribed bound would clip the exact circle straight back to a polygon and
    the whole exercise would be silently pointless.
    """
    from stimpack.visual_stim.shapes import GlSphericalCirc

    shape = GlSphericalCirc(circle_radius=20.0, sphere_radius=1.0)

    forward = np.array(shape.edge_frame)[2]
    directions = shape.vertices.T / np.linalg.norm(shape.vertices.T, axis=1, keepdims=True)
    angles = np.degrees(np.arccos(np.clip(directions @ forward, -1, 1)))
    rim = angles[angles > 1.0]                      # everything but the fan's hub

    assert rim.min() >= 20.0, (
        f'bound inscribes the circle: closest rim vertex at {rim.min():.4f} deg, needs >= 20')
    assert rim.max() < 20.0 * 1.2, 'bound is wastefully large'


def test_the_bound_is_tangent_to_the_shape_not_merely_near_it():
    """The bound has no fudge factor, and this is why it does not need one.

    Gnomonic projection -- divide a direction by its forward component -- takes great circles to
    straight lines, and a triangle edge between two points on a sphere sweeps a great circle. So in
    those coordinates the drawn polygon IS the polygon, and circumscribing the ellipse there
    circumscribes the real shape exactly, at any size.
    """
    from stimpack.visual_stim.shapes import GlSphericalCirc, GlSphericalEllipse, CANONICAL_PATCH_FRAME

    frame = np.array(CANONICAL_PATCH_FRAME)
    for shape, half_width, half_height in [(GlSphericalCirc(circle_radius=20), 20.0, 20.0),
                                           (GlSphericalCirc(circle_radius=70), 70.0, 70.0),
                                           (GlSphericalEllipse(width=45, height=22), 22.5, 11.0),
                                           (GlSphericalEllipse(width=110, height=8), 55.0, 4.0)]:
        directions = shape.vertices.T / np.linalg.norm(shape.vertices.T, axis=1, keepdims=True)
        ahead = directions @ frame[2]
        u = (directions @ frame[0]) / ahead / np.tan(np.radians(half_width))
        v = (directions @ frame[1]) / ahead / np.tan(np.radians(half_height))
        reach = np.sqrt(u**2 + v**2)
        rim = reach[reach > 0.3]                    # everything but the fan's hub

        # every rim vertex at exactly 1/cos(pi/8): the octagon whose EDGES touch the shape
        assert np.allclose(rim, 1 / np.cos(np.pi / 8)), (
            f'bound is not tangent: reach spans {rim.min():.4f} to {rim.max():.4f}')


def test_an_ellipse_with_equal_axes_is_exactly_the_disc():
    """The property that picked this definition over the one it replaces.

    The old ellipse was built on the azimuth/elevation grid, which is not uniform, so setting the
    axes equal gave a shape pinched at the diagonals by 0.35 deg -- four pixels -- rather than a
    circle. A cone has no such preferred direction, so the two shapes are now the same object.
    """
    from stimpack.visual_stim.shapes import GlSphericalCirc, GlSphericalEllipse

    for size in (10.0, 45.0, 60.0):
        disc = GlSphericalCirc(circle_radius=size/2)
        ellipse = GlSphericalEllipse(width=size, height=size)
        assert np.allclose(ellipse.vertices, disc.vertices), f'{size} deg: geometry differs'
        assert np.allclose(ellipse.edge_extent, disc.edge_extent), f'{size} deg: declaration differs'


def test_a_shape_too_big_for_a_cone_keeps_its_geometry():
    """A cone cannot describe more than a hemisphere. Past that there is no analytic form to
    declare, so the shape falls back to the fan and the geometry-defined edge rather than handing
    the shader an equation that would clip it to nothing."""
    from stimpack.visual_stim.shapes import GlSphericalCirc

    assert GlSphericalCirc(circle_radius=89).edge_kind == 1
    assert GlSphericalCirc(circle_radius=90).edge_kind == 0
    assert GlSphericalCirc(circle_radius=120).edge_kind == 0


def test_edge_coverage_is_linear_in_position_not_smoothstep():
    """A pixel 30% covered must emit 30% of the light. smoothstep emits 22%, and worse, makes
    emitted intensity a non-linear function of edge position -- so a constant-velocity edge would
    stall and then hurry once per pixel crossed, a smaller copy of the artefact this removes."""
    from stimpack.visual_stim.shapes import edge_coverage

    for offset, expected in [(-0.5, 1.0), (-0.2, 0.7), (0.0, 0.5), (0.2, 0.3), (0.5, 0.0)]:
        got = edge_coverage(distance=offset, pixel=1.0)
        smoothstep = 1 - (offset + 0.5)**2 * (3 - 2*(offset + 0.5))
        assert abs(got - expected) < 1e-6, (
            f'at {offset:+.1f} px, coverage {got:.3f} != {expected:.3f} '
            f'(smoothstep would give {smoothstep:.3f})')


def test_the_bounds_are_cheaper_than_the_polygons_they_replace():
    """n_steps stopped setting accuracy and started setting only surplus area, so it can fall."""
    from stimpack.visual_stim.shapes import GlSphericalCirc, GlSphericalEllipse

    assert GlSphericalCirc(circle_radius=10.0).vertices.shape[1] // 3 == 8
    assert GlSphericalEllipse(width=45, height=22).vertices.shape[1] // 3 == 8


def test_a_shape_that_declares_no_edge_is_untouched():
    """The path is strictly additive: an unconverted shape keeps a geometry-defined edge."""
    from stimpack.visual_stim.shapes import GlBox, GlCircle, GlCylinder

    for shape in (GlBox(), GlCylinder(), GlCircle()):
        assert shape.edge_kind == 0


def test_a_rect_bound_contains_the_angles_it_was_asked_for():
    """Same argument as the disc, in two axes: the drawn grid must contain the true rectangle.

    Its constant-azimuth sides are great circles, which triangle edges follow exactly, so those
    would be flush against the bound with nothing to spare -- and a shader can only remove
    coverage, never add it, so a rounding error at a corner would nick a real sliver off the
    patch. Hence the margin, and hence this test that the margin is on the outside.
    """
    from stimpack.visual_stim.shapes import GlSphericalRect

    shape = GlSphericalRect(width=20.0, height=30.0)

    frame = np.array(shape.edge_frame)
    directions = shape.vertices.T / np.linalg.norm(shape.vertices.T, axis=1, keepdims=True)
    azimuth = np.degrees(np.arctan2(directions @ frame[0], directions @ frame[2]))
    elevation = np.degrees(np.arcsin(np.clip(directions @ frame[1], -1, 1)))

    assert abs(azimuth).max() >= 10.0, f'bound cuts into the width at {abs(azimuth).max():.4f} deg'
    assert abs(elevation).max() >= 15.0, f'bound cuts into the height at {abs(elevation).max():.4f}'
    assert abs(azimuth).max() < 11.0 and abs(elevation).max() < 16.5, 'bound is wastefully large'

    assert np.allclose(np.degrees(shape.edge_extent), (10.0, 15.0)), (
        'edge_extent is the true half-extent the shader clips to, not the widened bound')


def test_a_rotation_turns_the_edge_frame_with_the_shape():
    """Every stimulus builds its patch facing forward and then rotates it into place, so if the
    frame did not turn too the shader would clip against a rectangle still sitting at the origin --
    which is most of the patch gone, and only for stimuli that move.
    """
    from stimpack.visual_stim.shapes import GlSphericalRect

    turned = GlSphericalRect(width=20.0, height=30.0).rotz(np.radians(90.0))

    frame = np.array(turned.edge_frame)
    assert np.allclose(frame @ frame.T, np.eye(3), atol=1e-9), 'rotation left the frame non-orthonormal'
    assert np.allclose(frame[2], (-1, 0, 0), atol=1e-9), (
        f'forward should have turned from +y to -x, got {frame[2]}')

    directions = turned.vertices.T / np.linalg.norm(turned.vertices.T, axis=1, keepdims=True)
    azimuth = np.degrees(np.arctan2(directions @ frame[0], directions @ frame[2]))
    assert abs(azimuth).max() < 11.0, 'the frame did not follow the geometry'


def test_recolouring_keeps_the_edge_but_moving_off_the_sphere_drops_it():
    """The declaration is an angular statement about a sphere centred on the subject. Colour does
    not touch that; translating or scaling invalidates it, and a wrong analytic edge is worse than
    none, so those fall back to the geometry rather than carrying a stale frame.
    """
    from stimpack.visual_stim.shapes import GlSphericalCirc

    disc = GlSphericalCirc(circle_radius=10.0)

    assert disc.set_color([1, 0, 0, 1]).edge_kind == disc.edge_kind
    assert disc.translate((0, 1, 0)).edge_kind == 0
    assert disc.scale(np.full((3, 1), 2.0)).edge_kind == 0


def _subtended_half_angle(row, screen_half_size=0.15, distance=0.15):
    """Half-angle of a lit run, reading the partial end pixels as fractional coverage.

    The whole point of analytic edges is that the boundary's position is carried by intensity
    rather than by which pixel is lit, so measuring it means using that intensity. Counting whole
    lit pixels instead would only ever be accurate to +/- half a pixel, which is the resolution
    this exists to beat.
    """
    lit = np.nonzero(row > 5)[0]
    coverage = (row[lit[0]] + row[lit[-1]]) / 255.0        # the two partial pixels, as fractions
    span = (len(lit) - 2 + coverage) / 2                   # in pixels, from the centre
    return math.degrees(math.atan(span / (len(row) / 2) * screen_half_size / distance))


@pytest.mark.parametrize('name,kwargs,want_width,want_height', [
    ('MovingSpot', dict(radius=15, sphere_radius=1, color=[1, 1, 1, 1], theta=0, phi=0), 15.0, 15.0),
    ('MovingEllipse', dict(width=45, height=22, sphere_radius=1, color=[1, 1, 1, 1],
                           theta=0, phi=0, angle=0), 22.5, 11.0),
])
def test_a_rendered_cone_patch_subtends_exactly_the_angle_it_was_asked_for(
        headless_gl, name, kwargs, want_width, want_height):
    """End to end, through the real render path: ask for 45 x 22 degrees and get 45 x 22 degrees.

    This is what the whole exercise buys. The polygon it replaces could not pass this -- it sat
    inside the true shape by 1 - cos(pi/n), and its `n_steps` was a free parameter that quietly set
    the answer. Here the size is set by the declaration and read back to a hundredth of a degree,
    from an image whose pixels are 0.35 degrees apart.
    """
    frame = _render(headless_gl, name, kwargs)[..., 0].astype(float)

    assert abs(_subtended_half_angle(frame[frame.shape[0] // 2]) - want_width) < 0.05
    assert abs(_subtended_half_angle(frame[:, frame.shape[1] // 2]) - want_height) < 0.05


def test_a_cylindrical_patch_declares_what_its_spherical_twin_does():
    """Why the cylindrical shapes needed no new shader code.

    ``cylindrical_w_phi_to_cartesian`` and ``spherical_to_cartesian`` put a given (theta, phi) in
    the *same direction* -- they differ only in how far along that ray the vertex sits. An edge
    declaration is a statement about direction, so it cannot tell the two surfaces apart, and one
    kind describes both.
    """
    from stimpack.visual_stim.shapes import (CANONICAL_PATCH_FRAME, GlCylindricalWithPhiEllipse,
                                             GlCylindricalWithPhiRect, GlSphericalEllipse,
                                             GlSphericalRect)

    frame = np.array(CANONICAL_PATCH_FRAME)

    def directions(shape):
        d = shape.vertices.T / np.linalg.norm(shape.vertices.T, axis=1, keepdims=True)
        return np.column_stack([np.arctan2(d @ frame[0], d @ frame[2]),
                                np.arcsin(np.clip(d @ frame[1], -1, 1))])

    for spherical, cylindrical in [(GlSphericalEllipse(width=45, height=22),
                                    GlCylindricalWithPhiEllipse(width=45, height=22)),
                                   (GlSphericalRect(width=20, height=30),
                                    GlCylindricalWithPhiRect(width=20, height=30))]:
        assert cylindrical.edge_kind == spherical.edge_kind
        assert np.allclose(cylindrical.edge_extent, spherical.edge_extent)
        assert np.allclose(directions(cylindrical), directions(spherical), atol=1e-12), (
            'the bound covers different directions on the two surfaces')
        # ...and the vertices really are on different surfaces, so this is not a trivial pass
        assert not np.allclose(cylindrical.vertices, spherical.vertices)


def test_sharp_texel_sampling_lands_on_texel_centres_and_ramps_only_at_boundaries():
    """The rule, stated without a GL context: NEAREST's result everywhere but the boundary.

    Sampling at these coordinates with LINEAR filtering must return the texel itself through the
    interior -- otherwise this blurs the pattern, which is the thing NEAREST exists to prevent --
    and a covered-fraction blend across one pixel at the boundary.
    """
    from stimpack.visual_stim.shapes import sharp_texel_coord

    texels_per_pixel = 1/8                          # magnified: one texel spans eight pixels

    # interior of texel 2 sits on its centre, 2.5, so LINEAR returns texel 2 exactly
    for offset in (-3, -2, -1, 1, 2, 3):
        assert sharp_texel_coord(2.5 + offset*texels_per_pixel, texels_per_pixel) == pytest.approx(2.5)

    # the boundary between texel 2 and 3 is at 3.0, and lands halfway between their centres
    assert sharp_texel_coord(3.0, texels_per_pixel) == pytest.approx(3.0)
    # half a pixel either side is fully one texel or fully the other
    assert sharp_texel_coord(3.0 - 0.5*texels_per_pixel, texels_per_pixel) == pytest.approx(2.5)
    assert sharp_texel_coord(3.0 + 0.5*texels_per_pixel, texels_per_pixel) == pytest.approx(3.5)

    # minified, it must become ordinary bilinear filtering rather than something worse
    positions = np.linspace(0, 5, 41)
    assert np.allclose(sharp_texel_coord(positions, 4.0), positions)


def test_a_hard_edged_texture_is_antialiased_where_it_falls(headless_gl):
    """A checkerboard must still be a checkerboard -- two levels, not a gradient -- but its
    boundaries must land on partially-lit pixels rather than snapping to the pixel grid."""
    grey = _render(headless_gl, 'Checkerboard', dict(patch_width=15, patch_height=15))[..., 0].astype(int)

    partial = ((grey > 5) & (grey < 250)).sum()
    assert partial > 0, 'texture boundaries are hard: no partially-lit pixels'
    # a thin seam along the checker boundaries, not a wash over the image
    assert partial < 0.15 * grey.size, f'pattern looks blurred: {partial} of {grey.size} px intermediate'


def test_a_drifting_grating_edge_moves_every_frame(headless_gl):
    """The defect this exists to remove, on the stimulus class where it bit hardest.

    A square grating drifting at 10 deg/s moves its edge 0.079 px per frame at 360 Hz. Without
    coverage the edge cannot sit between pixels, so it stayed on one for twelve frames and then
    jumped a whole pixel -- 27 of 29 frames frozen, three distinct positions in thirty. That
    discards exactly the temporal resolution 360 Hz exists to provide.
    """
    import moderngl

    screen = _make_screen()
    width = height = 256
    headless_gl.enable(moderngl.BLEND)
    headless_gl.enable(moderngl.DEPTH_TEST)
    headless_gl.extra = {}
    fbo = headless_gl.framebuffer(
        color_attachments=[headless_gl.renderbuffer((width, height))],
        depth_attachment=headless_gl.depth_renderbuffer((width, height)))
    viewports = [s.get_viewport(width, height) for s in screen.subscreens]
    perspectives = [_perspective(SUBJECT_AT_ORIGIN, s.pa, s.pb, s.pc, screen.horizontal_flip)
                    for s in screen.subscreens]

    from stimpack.util import get_all_subclasses
    from stimpack.visual_stim import stimuli
    stim = [c for c in get_all_subclasses(stimuli.BaseProgram)
            if c.__name__ == 'RotatingGrating'][0](screen=screen)
    stim.initialize(headless_gl)
    stim.configure(rate=10, period=20, mean=0.5, contrast=1.0, profile='square')

    def edge_positions(row):
        """Sub-pixel position of every dark-to-light crossing, by linear interpolation."""
        mid = (row.max() + row.min()) / 2
        found = []
        for k in np.nonzero((row[:-1] < mid) & (row[1:] >= mid))[0]:
            low, high = row[k], row[k+1]
            found.append(k + (0.5 if high == low else (mid - low) / (high - low)))
        return np.array(found)

    positions = []
    for frame in range(30):                              # 30 frames at 360 Hz
        fbo.use()
        fbo.clear(0, 0, 0, 1)
        stim.paint_at(frame / 360.0, viewports, perspectives, subject_position=SUBJECT_AT_ORIGIN)
        headless_gl.finish()
        img = np.flipud(np.frombuffer(fbo.read(components=3, alignment=1),
                                      dtype=np.uint8).reshape(height, width, 3))
        # track one bar by index; the bar count is stable over this many frames
        positions.append(edge_positions(img[height // 2, :, 0].astype(float))[3])

    positions = np.array(positions)
    steps = np.abs(np.diff(positions))

    assert (steps < 1e-3).sum() == 0, (
        f'edge frozen in {(steps < 1e-3).sum()} of {len(steps)} frames -- motion is quantised '
        f'to the pixel grid')
    assert steps.max() < 0.5, f'edge jumped {steps.max():.3f} px in one frame; smooth is 0.079'

@pytest.mark.parametrize('name,kwargs', [
    ('MovingPatchOnCylinder', dict(width=25, height=25, cylinder_radius=1, color=[1, 1, 1, 1],
                                   theta=0, phi=0, angle=0)),
    ('MovingEllipseOnCylinder', dict(width=45, height=22, cylinder_radius=1, color=[1, 1, 1, 1],
                                     theta=0, phi=0, angle=0)),
])
def test_a_rendered_cylindrical_patch_has_a_soft_edge(headless_gl, name, kwargs):
    """The end-to-end claim, on the cylinder: the boundary spans partially-lit pixels."""
    grey = _render(headless_gl, name, kwargs)[..., 0].astype(int)

    lit = (grey > 250).sum()
    partial = grey.size - lit - (grey < 5).sum()

    assert lit > 0, 'the patch did not render'
    assert partial > 0, 'edge is hard: no partially-lit pixels'
    assert partial < lit, f'edge implausibly soft: {partial} partial vs {lit} fully-lit pixels'


def test_a_rendered_rect_has_soft_edges_on_both_axes(headless_gl):
    """A patch straddling the screen centre, so both its width and its height are in view."""
    frame = _render(headless_gl, 'MovingPatch',
                    {'width': 30.0, 'height': 20.0, 'color': [1, 1, 1, 1],
                     'theta': 0, 'phi': 0, 'angle': 0, 'sphere_radius': 1.0})
    grey = frame[..., 0].astype(int)

    lit = (grey > 250).sum()
    partial = grey.size - lit - (grey < 5).sum()

    assert lit > 0, 'the patch did not render'
    assert partial > 0, 'edges are hard: no partially-lit pixels'
    assert partial < lit, f'edges implausibly soft: {partial} partial vs {lit} fully-lit pixels'


def test_a_rendered_disc_has_a_soft_edge_carrying_sub_pixel_position(headless_gl):
    """The end-to-end claim: through the real render path, a disc's boundary spans partially-lit
    pixels rather than jumping from lit to unlit.

    That intensity ramp is what carries edge position below the pixel grid. Without it an edge
    cannot sit between pixels, so at 5 deg/s it stays on one for about three frames and then jumps
    -- which is the temporal resolution 360 Hz exists to provide, discarded at the last step.
    """
    frame = _render(headless_gl, 'MovingSpot',
                    {'radius': 10.0, 'color': [1, 1, 1, 1], 'theta': 0, 'phi': 0,
                     'sphere_radius': 1.0})
    grey = frame[..., 0].astype(int)

    lit = (grey > 250).sum()
    dark = (grey < 5).sum()
    partial = grey.size - lit - dark

    assert lit > 0, 'the spot did not render'
    assert partial > 0, 'edge is hard: no partially-lit pixels, so position cannot go sub-pixel'
    # a ring one pixel wide around a disc, not a general haze over the image
    assert partial < lit, f'edge is implausibly soft: {partial} partial vs {lit} fully-lit pixels'
