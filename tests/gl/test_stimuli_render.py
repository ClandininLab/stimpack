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
