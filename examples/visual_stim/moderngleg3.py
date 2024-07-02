import moderngl
import numpy as np
import sys

from PyQt6 import QtWidgets, QtGui
from PyQt6.QtOpenGLWidgets import QOpenGLWidget

class ModernGLWidget(QOpenGLWidget):
    def __init__(self):
        super().__init__()

        self.ctx = None
        self.prog = None
        self.vao = None
    
    def initializeGL(self):
        # Create ModernGL context
        self.ctx = moderngl.create_context()
        
        # Create shader program
        self.prog = self.ctx.program(
            vertex_shader="""
                #version 330
                in vec2 in_vert;
                void main() {
                    gl_Position = vec4(in_vert, 0.0, 1.0);
                }
            """,
            fragment_shader="""
                #version 330
                out vec4 fragColor;
                void main() {
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


