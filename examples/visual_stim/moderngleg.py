import moderngl
import numpy as np

from PIL import Image
from PyQt6 import QtWidgets, QtGui
from PyQt6.QtOpenGLWidgets import QOpenGLWidget


# set default format with OpenGL context
format = QtGui.QSurfaceFormat()
format.setVersion(3, 3)
format.setProfile(QtGui.QSurfaceFormat.OpenGLContextProfile.CoreProfile)
QtGui.QSurfaceFormat.setDefaultFormat(format)

# launch application
app = QtWidgets.QApplication([])
app.setApplicationName('Stimpack visual_stim screen')

ctx = moderngl.create_context(standalone=False)

prog = ctx.program(
    vertex_shader="""
                    #version 330
                    in vec2 in_vert;
                    void main() {
                        gl_Position = vec4(in_vert, 0.0, 1.0);
                    }
    """,
    fragment_shader="""
                    #version 330
                    out float fragColor;
                    void main() {
                        fragColor = 1.0;  // Example stencil value, change as needed
                    }
    """,
)

vertices = np.asarray([
                -1.0, -1.0,  # Bottom-left corner
                1.0, -1.0,  # Bottom-right corner extended beyond the screen
                -1.0,  1.0,  # Top-left corner extended beyond the screen
], dtype='f4')

vbo = ctx.buffer(vertices.tobytes())
vao = ctx.vertex_array(prog, vbo, "in_vert")
stencil_texture = ctx.texture((500,500), components=1, dtype='f1')
stencil_fbo = ctx.framebuffer(color_attachments=[stencil_texture])

stencil_fbo.use()
stencil_fbo.clear(0.0, 0.0, 0.0, 1.0)
vao.render()  # "mode" is moderngl.TRIANGLES by default

Image.frombytes(
    "L", stencil_texture.size, stencil_texture.read(),
    "raw", "L", 0, -1
).show()