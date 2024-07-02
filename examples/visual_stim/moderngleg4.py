import moderngl
import numpy as np
import sys

from PyQt6 import QtWidgets, QtGui
from PyQt6.QtOpenGLWidgets import QOpenGLWidget

from PIL import Image

class ModernGLWidget(QOpenGLWidget):
    def __init__(self):
        super().__init__()

        self.ctx = None
        self.prog = None
        self.vao = None
        self.counter = 0
    
    def initializeGL(self):
        # Create ModernGL context
        self.ctx = moderngl.create_context()
        
        # Create shader program
        self.prog = self.ctx.program(
            vertex_shader="""
                #version 330
                in vec2 in_vert;
                out vec2 v_tex_coord;
                
                void main() {
                    gl_Position = vec4(in_vert, 0.0, 1.0);
                }
            """,
            fragment_shader="""
                #version 330

                in vec2 v_tex_coord;
                
                uniform bool use_stencil;
                uniform sampler2D stencil_texture;

                out vec4 fragColor;

                void main() {
                    if (use_stencil) {
                        float stencil_value = texture(stencil_texture, v_tex_coord).r;
                        if (stencil_value < 0.5) {
                            discard;
                        }
                    }

                    fragColor = vec4(1.0, 1.0, 1.0, 1.0); // Red color
                }
            """,
        )
        
        # Define a simple triangle
        vertices = np.asarray([
                        -0.75, -0.75,  # Bottom-left corner
                        0.75, -0.75,  # Bottom-right corner
                        0.0, 0.649,  # Top-left corner
        ], dtype='f4')
        
        # Create vertex array object
        vbo = self.ctx.buffer(vertices.tobytes())
        self.vao = self.ctx.vertex_array(
            self.prog,
            [(vbo, '2f', 'in_vert')]
        )

        # Create stencil texture with the size of the viewport
        self.stencil_texture = self.ctx.texture((500, 500), components=1, dtype='f1')
        stencil_fbo = self.ctx.framebuffer(color_attachments=[self.stencil_texture])

        stencil_fbo.use()
        stencil_fbo.clear(0.0, 0.0, 0.0, 0.0)  # Clear the framebuffer to ensure it's clean

        # Create a simple program to render the stencil pattern
        stencil_prog = self.ctx.program(
            vertex_shader='''
                #version 330
                in vec2 in_vert;
                void main() {
                    gl_Position = vec4(in_vert, 0.0, 1.0);
                }
                ''',
            fragment_shader='''
                #version 330
                out float fragColor;
                void main() {
                    fragColor = 1.0;  // stencil value
                }
                ''',
        )
        # Define a simple triangle
        stencil_vertices = np.array([
            -1.0, -1.0,  # Bottom-left corner
            1.0, -1.0,  # Bottom-right corner
            -1.0,  1.0,  # Top-left corner
        ], dtype='f4')

        stencil_vbo = self.ctx.buffer(stencil_vertices.tobytes())
        self.stencil_vao = self.ctx.vertex_array(stencil_prog, stencil_vbo, 'in_vert')

        # Render the triangle to the framebuffer
        self.stencil_vao.render(mode=moderngl.TRIANGLES)

        # Visualize the stencil buffer (for debugging)
        if self.counter <2:
            Image.frombytes(
                "L", self.stencil_texture.size, self.stencil_texture.read(),
                "raw", "L", 0, -1
            ).show()

    def paintGL(self):
        print("Painting")
        # Clear the screen
        self.ctx.detect_framebuffer().use()
        self.ctx.clear(0, 0, 0, 0)
        
        # Render the triangle
        self.vao.render(moderngl.TRIANGLES)

if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)

    # Set up the OpenGL format
    fmt = QtGui.QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QtGui.QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setDepthBufferSize(24)
    QtGui.QSurfaceFormat.setDefaultFormat(fmt)
    
    window = ModernGLWidget()
    window.setWindowTitle("ModernGL with PyQt6")
    window.resize(500, 500)
    window.show()
    sys.exit(app.exec())


