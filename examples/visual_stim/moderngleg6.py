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
        self.vao_mask1 = None
        self.vao_mask2 = None
        self.vao_scene = None
        self.stencil_fbo = None
        self.stencil_texture = None
        self.counter = 0

    def initializeGL(self):
        self.ctx = moderngl.create_context()

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

        # Define vertices for two different stencils
        vertices_mask1 = np.array([
            -0.5, -0.5,  # Bottom-left corner
            +0.5, -0.5,  # Bottom-right corner
            -0.5, +0.5,  # Top-left corner
        ], dtype='f4')

        vertices_mask2 = np.array([
            +0.5,  +0.5,  # Top-right corner
            +0.5,  -0.5,  # Bottom-right corner
            -0.5,  +0.5,  # Top-left corner
        ], dtype='f4')

        self.vbo_mask1 = self.ctx.buffer(vertices_mask1.tobytes())
        self.vao_mask1 = self.ctx.vertex_array(
            self.prog_mask,
            [(self.vbo_mask1, '2f', 'in_vert')]
        )

        self.vbo_mask2 = self.ctx.buffer(vertices_mask2.tobytes())
        self.vao_mask2 = self.ctx.vertex_array(
            self.prog_mask,
            [(self.vbo_mask2, '2f', 'in_vert')]
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

        self.mask_vaos = [self.vao_mask1, self.vao_mask2]

        # Set the MVP matrices for scene rendering
        mvp1 = np.eye(4, dtype='f4')  # Replace with actual MVP matrix
        mvp2 = np.eye(4, dtype='f4')  # Replace with actual MVP matrix

        self.mvps = [mvp1, mvp2]

        self.main_fbo = self.ctx.detect_framebuffer()

    def render_scene_with_stencil(self, mask_vao, mvp):

        ## Step 1: Render the stencil mask to the texture
        self.ctx.disable(moderngl.BLEND)
        self.stencil_fbo.use()
        self.stencil_fbo.clear(0.0, 0.0, 0.0, 0.0)
        mask_vao.render(moderngl.TRIANGLES)
        self.ctx.enable(moderngl.BLEND)

        # Visualize the stencil buffer (for debugging)
        # if self.counter <1:
        #     Image.frombytes(
        #         "L", self.stencil_texture.size, self.stencil_texture.read(),
        #         "raw", "L", 0, -1
        #     ).show()
        #     print("Framebuffer created with ID:", self.stencil_fbo.glo)
        #     print(f"Stencil texture bound with ID:", self.stencil_texture.glo)


        ## Step 2: Render the scene using the stencil mask
        self.main_fbo.use()

        # Bind the stencil texture to texture unit 0
        stencil_location = 0
        self.prog_scene['use_stencil'].value = True
        self.prog_scene['stencil_mask'].value = stencil_location
        self.stencil_texture.use(location=stencil_location)

        # Render the scene with the MVP matrix
        self.prog_scene['MVP'].write(mvp.tobytes())
        self.vao_scene.render(moderngl.TRIANGLE_STRIP)

        # Disable the stencil mask for the next rendering
        self.prog_scene['use_stencil'].value = False


    def paintGL(self):
        print("Painting")
        self.main_fbo = self.ctx.detect_framebuffer()
        self.ctx.clear(0.0, 0.0, 0.0, 1.0)

        if self.counter % 2 == 0:
            for (mask_vao, mvp) in zip(self.mask_vaos, self.mvps):
                self.render_scene_with_stencil(mask_vao, mvp)
        else:
            # Render the scene without the stencil mask
            self.main_fbo.use()
            self.ctx.clear(0.0, 0.0, 0.0, 1.0)
            self.vao_scene.render(moderngl.TRIANGLE_STRIP)

        self.counter += 1

    def resizeGL(self, w, h):
        self.ctx.viewport = (0, 0, w, h)
        # Update texture and framebuffer size
        self.stencil_texture.release()
        self.stencil_texture = self.ctx.texture((w, h), 1, dtype='f1')
        self.stencil_fbo.release()
        self.stencil_fbo = self.ctx.framebuffer(color_attachments=[self.stencil_texture])

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