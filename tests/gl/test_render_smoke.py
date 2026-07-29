"""Headless GL smoke test: the shared stimpack shaders compile and render.

Uses a standalone moderngl context (no PyQt/StimDisplay). Skipped automatically when no GL context
is available; in CI this runs under xvfb / a software GL driver. Marked `gl`.
"""
import pytest

pytest.importorskip("numpy")

pytestmark = pytest.mark.gl


def test_shared_shaders_compile_and_render(headless_gl):
    import numpy as np
    from stimpack.visual_stim.base import BaseProgram

    ctx = headless_gl

    # Compile stimpack's shared vertex/fragment shaders (the ones every stimulus uses).
    bp = BaseProgram(screen=None)
    prog = ctx.program(vertex_shader=bp.get_vertex_shader(),
                       fragment_shader=bp.get_fragment_shader())
    prog["use_texture"].value = False
    prog["rgb_texture"].value = False
    prog["Mvp"].write(np.eye(4, dtype="f4").tobytes())

    # A white triangle covering the center, in clip space (identity MVP).
    verts = np.array([[-0.8, -0.8, 0.0], [0.8, -0.8, 0.0], [0.0, 0.8, 0.0]], dtype="f4")
    colors = np.ones((3, 4), dtype="f4")
    vbo_v = ctx.buffer(verts.tobytes())
    vbo_c = ctx.buffer(colors.tobytes())
    vao = ctx.vertex_array(prog, [(vbo_v, "3f", "in_vert"), (vbo_c, "4f", "in_color")])

    fbo = ctx.simple_framebuffer((64, 64))
    fbo.use()
    fbo.clear(0.0, 0.0, 0.0, 1.0)  # black
    vao.render()

    pixels = np.frombuffer(fbo.read(components=3), dtype=np.uint8)
    # The triangle should have drawn *something* brighter than the black clear color.
    assert pixels.max() > 200, "expected a rendered white triangle over the black clear"


def test_context_setup_leaves_alpha_blending_on(headless_gl):
    """A raw GL enum handed to ctx.disable() is read as moderngl's flag bitmask, and
    GL_FRAMEBUFFER_SRGB (0x8DB9 = 36281) has the BLEND bit set -- so `disable sRGB` silently
    disabled alpha blending instead, for five months, while never touching sRGB.

    Asserted against raw GL state rather than a rendered image on purpose: with alpha = 1 the
    output is byte-identical either way (src*1 + dst*0 == src), so a golden image cannot see it.
    What gives it away is a stimulus with alpha < 1, and none of the built-in ones use that.
    """
    import moderngl
    from OpenGL import GL

    ctx = headless_gl

    # exactly what StimDisplay.initializeGL does
    ctx.enable(moderngl.BLEND)
    ctx.enable(moderngl.DEPTH_TEST)
    ctx.disable_direct(0x8DB9)

    assert bool(GL.glIsEnabled(GL.GL_BLEND)), 'alpha blending was switched off by the sRGB disable'
    assert bool(GL.glIsEnabled(GL.GL_DEPTH_TEST))
    assert not bool(GL.glIsEnabled(GL.GL_FRAMEBUFFER_SRGB)), 'sRGB encoding is on'

    # and the reason the old call was wrong, pinned so the trap is documented where it bit
    assert 0x8DB9 & moderngl.BLEND, 'the GL enum no longer collides with the BLEND flag'


def test_alpha_actually_composites(headless_gl):
    """The behaviour the flag exists for: a half-transparent red over blue should mix, not replace."""
    import numpy as np
    import moderngl

    ctx = headless_gl
    ctx.enable(moderngl.BLEND)
    ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
    ctx.disable_direct(0x8DB9)

    target = ctx.simple_framebuffer((4, 4))
    target.use()
    target.clear(0.0, 0.0, 1.0, 1.0)                  # blue background

    program = ctx.program(
        vertex_shader='#version 330\nin vec2 pos; void main(){ gl_Position = vec4(pos, 0.0, 1.0); }',
        fragment_shader='#version 330\nout vec4 f; void main(){ f = vec4(1.0, 0.0, 0.0, 0.5); }')
    quad = ctx.buffer(np.array([-1, -1, 1, -1, -1, 1, 1, 1], dtype='f4').tobytes())
    ctx.vertex_array(program, [(quad, '2f', 'pos')]).render(moderngl.TRIANGLE_STRIP)

    r, g, b = np.frombuffer(target.read(components=3), dtype=np.uint8)[:3]
    assert 100 < r < 155, f'red did not blend at half alpha (r={r})'
    assert 100 < b < 155, f'blue background was replaced rather than blended (b={b})'
