import sys
from PyQt6 import QtWidgets, QtGui
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from OpenGL.GL import *
from OpenGL.GL.shaders import compileProgram, compileShader
import numpy as np

class OpenGLWidget(QOpenGLWidget):
    def __init__(self):
        super().__init__()
        self.prog_mask = None
        self.prog_scene = None
        self.vao_mask1 = None
        self.vao_mask2 = None
        self.vao_scene = None
        self.counter = 0

    def initializeGL(self):
        self.prog_mask = self.create_program(
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
                    fragColor = 1.0;
                }
            """,
        )

        self.prog_scene = self.create_program(
            vertex_shader="""
                #version 330
                in vec3 in_vert;
                in vec2 in_tex;
                uniform mat4 MVP;
                out vec2 v_tex_coord;
                void main() {
                    gl_Position = MVP * vec4(in_vert, 1.0);
                    v_tex_coord = in_tex;
                }
            """,
            fragment_shader="""
                #version 330
                uniform bool use_stencil;
                in vec2 v_tex_coord;
                out vec4 fragColor;
                void main() {
                    if (use_stencil && gl_FragCoord.z < 0.5) {
                        discard;
                    }
                    fragColor = vec4(1.0, 0.0, 0.0, 0.5);
                }
            """,
        )

        self.vao_mask1 = self.create_vao(self.prog_mask, np.array([
            -0.5, -0.5,
            +0.5, -0.5,
            -0.5, +0.5,
        ], dtype='f4'))

        self.vao_mask2 = self.create_vao(self.prog_mask, np.array([
            +0.5, +0.5,
            +0.5, -0.5,
            -0.5, +0.5,
        ], dtype='f4'))

        self.vao_scene = self.create_vao(self.prog_scene, np.array([
            -1.0, -1.0, 0.0, 0.0, 0.0,
            +1.0, -1.0, 0.0, 1.0, 0.0,
            -1.0, +1.0, 0.0, 0.0, 1.0,
            +1.0, +1.0, 0.0, 1.0, 1.0,
        ], dtype='f4'), stride=5 * 4)

        self.mvps = [np.eye(4, dtype='f4'), np.eye(4, dtype='f4')]

        # Check framebuffer status
        if glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE:
            print("Framebuffer is not complete")

    def create_program(self, vertex_shader, fragment_shader):
        return compileProgram(
            compileShader(vertex_shader, GL_VERTEX_SHADER),
            compileShader(fragment_shader, GL_FRAGMENT_SHADER)
        )

    def create_vao(self, program, vertices, stride=2 * 4):
        vao = glGenVertexArrays(1)
        vbo = glGenBuffers(1)

        glBindVertexArray(vao)
        glBindBuffer(GL_ARRAY_BUFFER, vbo)
        glBufferData(GL_ARRAY_BUFFER, vertices.nbytes, vertices, GL_STATIC_DRAW)

        position = glGetAttribLocation(program, 'in_vert')
        glEnableVertexAttribArray(position)
        glVertexAttribPointer(position, 2, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))

        if stride == 5 * 4:
            tex_coord = glGetAttribLocation(program, 'in_tex')
            glEnableVertexAttribArray(tex_coord)
            glVertexAttribPointer(tex_coord, 2, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(3 * 4))

        glBindBuffer(GL_ARRAY_BUFFER, 0)
        glBindVertexArray(0)

        return vao

    def render_scene_with_stencil(self, vao, mvp):
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT)

        glUseProgram(self.prog_mask)
        glBindVertexArray(vao)
        glEnable(GL_STENCIL_TEST)
        glStencilFunc(GL_ALWAYS, 1, 0xFF)
        glStencilOp(GL_KEEP, GL_KEEP, GL_REPLACE)
        glDrawArrays(GL_TRIANGLES, 0, 3)

        glUseProgram(self.prog_scene)
        mvp_location = glGetUniformLocation(self.prog_scene, 'MVP')
        glUniformMatrix4fv(mvp_location, 1, GL_TRUE, mvp)

        use_stencil_location = glGetUniformLocation(self.prog_scene, 'use_stencil')
        glUniform1i(use_stencil_location, True)

        glStencilFunc(GL_EQUAL, 1, 0xFF)
        glStencilOp(GL_KEEP, GL_KEEP, GL_KEEP)
        glDrawArrays(GL_TRIANGLE_STRIP, 0, 4)

        glDisable(GL_STENCIL_TEST)
        glBindVertexArray(0)
        glUseProgram(0)

    def paintGL(self):
        if self.counter % 2 == 0:
            for vao, mvp in zip([self.vao_mask1, self.vao_mask2], self.mvps):
                self.render_scene_with_stencil(vao, mvp)
        else:
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
            glUseProgram(self.prog_scene)
            use_stencil_location = glGetUniformLocation(self.prog_scene, 'use_stencil')
            glUniform1i(use_stencil_location, False)
            glBindVertexArray(self.vao_scene)
            glDrawArrays(GL_TRIANGLE_STRIP, 0, 4)
            glBindVertexArray(0)
            glUseProgram(0)

        self.counter += 1

    def resizeGL(self, w, h):
        glViewport(0, 0, w, h)

if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)

    fmt = QtGui.QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QtGui.QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setStencilBufferSize(8)
    QtGui.QSurfaceFormat.setDefaultFormat(fmt)

    window = OpenGLWidget()
    window.setWindowTitle("PyOpenGL with PyQt6 - Stencil Mask")
    window.resize(800, 600)
    window.show()
    sys.exit(app.exec())