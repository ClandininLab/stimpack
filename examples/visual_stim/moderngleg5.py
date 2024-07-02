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
        self.prog_mask = None
        self.prog_scene = None
        self.vao_mask = None
        self.vao_scene = None
        self.stencil_fbo = None
        self.stencil_texture = None
        self.stencil_location = 0
        self.counter = 0

    def initializeGL(self):
        self.ctx = moderngl.create_context()
        self.ctx.blend_func = (moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA)

        # Create the stencil mask program
        self.prog_mask = self.ctx.program(
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
                    fragColor = 1.0; // Set the mask value to 1.0 in the stencil area
                }
            """,
        )

        # Create the scene rendering program
        self.prog_scene = self.ctx.program(
            vertex_shader="""
                #version 330
                in vec3 in_vert;
                in vec2 in_tex;

                uniform mat4 MVP;

                out vec2 v_tex_coord;
                out vec2 v_screen_coord;

                void main() {
                    gl_Position = MVP * vec4(in_vert, 1.0);
                    v_tex_coord = in_tex;

                    // Calculate screen-space coordinates
                    v_screen_coord = (gl_Position.xy / gl_Position.w) * 0.5 + 0.5;
                }
            """,
            fragment_shader="""
                #version 330
                uniform bool use_stencil;
                uniform sampler2D stencil_mask;
                in vec2 v_tex_coord;
                in vec2 v_screen_coord;

                out vec4 fragColor;

                void main() {
                    // Use the screen-space coordinates to sample the stencil mask
                    if (use_stencil) {
                        float mask_value = texture(stencil_mask, v_screen_coord).r;
                        if (mask_value < 0.5) {
                            discard;
                        }
                    }
                    fragColor = vec4(1.0, 0.0, 0.0, 0.5); // Red color
                }
            """,
        )

        # Define a triangle for mask rendering
        vertices_mask = np.array([
            -0.5, -0.5,  # Bottom-left corner
            +0.5, -0.5,  # Bottom-right corner
             0.0,  0.5,  # Top-center
        ], dtype='f4')

        self.vbo_mask = self.ctx.buffer(vertices_mask.tobytes())
        self.vao_mask = self.ctx.vertex_array(
            self.prog_mask,
            [(self.vbo_mask, '2f', 'in_vert')]
        )

        # Define a simple quad for scene rendering with texture coordinates
        vertices_scene = np.array([
            # positions     # tex coords
            -1.0, -1.0, 0.0, 0.0, 0.0,  # Bottom-left corner
            +1.0, -1.0, 0.0, 1.0, 0.0,  # Bottom-right corner
            -1.0, +1.0, 0.0, 0.0, 1.0,  # Top-left corner
            +1.0, +1.0, 0.0, 1.0, 1.0,  # Top-right corner
        ], dtype='f4')

        self.vbo_scene = self.ctx.buffer(vertices_scene.tobytes())
        self.vao_scene = self.ctx.vertex_array(
            self.prog_scene,
            [(self.vbo_scene, '3f 2f', 'in_vert', 'in_tex')]
        )

        # Create the stencil texture and framebuffer
        self.stencil_texture = self.ctx.texture((self.width(), self.height()), 1, dtype='f1')
        self.stencil_fbo = self.ctx.framebuffer(color_attachments=[self.stencil_texture])
        
        # Render the stencil mask to the texture
        self.ctx.disable(moderngl.BLEND) # disable alpha blending
        self.stencil_fbo.use()
        self.stencil_fbo.clear(0.0, 0.0, 0.0, 0.0)
        self.vao_mask.render(moderngl.TRIANGLES)
        self.ctx.enable(moderngl.BLEND)

        self.prog_scene['stencil_mask'].value = self.stencil_location

    def paintGL(self):
        print("Painting")
        main_fbo = self.ctx.detect_framebuffer()

        # Step 2: Render the scene using the stencil mask
        main_fbo.use()
        self.ctx.clear(0.0, 0.0, 0.0, 1.0)
        
        # Bind the stencil texture to texture unit 0
        self.prog_scene['use_stencil'].value = (self.counter % 2 == 0)
        self.stencil_texture.use(location=self.stencil_location)

        # Set the MVP matrix for scene rendering
        mvp = np.eye(4, dtype='f4')  # Replace with actual MVP matrix
        self.prog_scene['MVP'].write(mvp.tobytes())

        self.vao_scene.render(moderngl.TRIANGLES)

        self.counter += 1

    def resizeGL(self, w, h):
        self.ctx.viewport = (0, 0, w, h)

        self.ctx.disable(moderngl.BLEND) # disable alpha blending

        # Update texture and framebuffer size
        self.stencil_texture.release()
        self.stencil_texture = self.ctx.texture((w, h), 1, dtype='f1')
        self.stencil_fbo.release()
        self.stencil_fbo = self.ctx.framebuffer(color_attachments=[self.stencil_texture])

        # Render the stencil mask to the texture
        self.stencil_fbo.use()
        self.stencil_fbo.clear(0.0, 0.0, 0.0, 0.0)
        self.vao_mask.render(moderngl.TRIANGLES)

        self.ctx.enable(moderngl.BLEND)


if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)

    fmt = QtGui.QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QtGui.QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setDepthBufferSize(24)
    QtGui.QSurfaceFormat.setDefaultFormat(fmt)

    window = ModernGLWidget()
    window.setWindowTitle("ModernGL with PyQt6 - Stencil Mask")
    window.resize(800, 600)
    window.show()
    sys.exit(app.exec())