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
