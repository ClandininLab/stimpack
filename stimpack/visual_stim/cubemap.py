"""Render a scene into a cube map, then warp it onto a curved screen.

The two passes:

  1. the scene is drawn six times, once into each face of a cube map, from the subject's position
  2. the screen mesh is drawn once in projector coordinates; each fragment samples the cube along
     its own interpolated direction

Cost therefore scales with the scene and with the number of faces, not with how finely the screen is
tessellated -- the screen is one draw call whether it has 200 triangles or 20,000. That is the whole
reason for doing it this way rather than giving each facet its own frustum, which multiplies scene
complexity by screen complexity.

moderngl cannot attach a cube face to a framebuffer (TextureCube has no .face()), so that one step
drops to raw GL through PyOpenGL. Everything else stays managed. The alternative -- six separate 2D
textures -- would mean giving up hardware seamless filtering and hand-rolling the face selection,
and seams on a stimulus display are a data problem, not a cosmetic one.
"""
import numpy as np

# Face order matches GL_TEXTURE_CUBE_MAP_POSITIVE_X + i, which is what the attachment call wants.
#
# The up vectors are not free: a cube map is sampled in a left-handed frame, so the +Y and -Y faces
# are oriented differently from the other four, and the rest are flipped vertically relative to what
# a "look along this axis" matrix would naturally produce. These are the conventional values, and
# test_cubemap.py checks each one by rendering a distinct colour per face and sampling it back --
# getting this wrong produces a picture that is plausible and rotated, which is hard to spot by eye.
CUBE_FACES = (
    ((+1, 0, 0), (0, -1, 0)),      # +X
    ((-1, 0, 0), (0, -1, 0)),      # -X
    ((0, +1, 0), (0, 0, +1)),      # +Y
    ((0, -1, 0), (0, 0, -1)),      # -Y
    ((0, 0, +1), (0, -1, 0)),      # +Z
    ((0, 0, -1), (0, -1, 0)),      # -Z
)

WARP_VERTEX_SHADER = '''
    #version 330
    in vec2 in_ndc;
    in vec3 in_direction;
    out vec3 v_direction;
    void main() {
        v_direction = in_direction;
        gl_Position = vec4(in_ndc, 0.0, 1.0);
    }
'''

WARP_FRAGMENT_SHADER = '''
    #version 330
    uniform samplerCube cube;
    in vec3 v_direction;
    out vec4 f_color;
    void main() {
        f_color = texture(cube, normalize(v_direction));
    }
'''


def face_view_matrix(eye, forward, up):
    """A right-handed look-at matrix, column-major, ready for a `mat4` uniform."""
    eye = np.asarray(eye, dtype='f4')
    f = np.asarray(forward, dtype='f4')
    f = f / np.linalg.norm(f)
    s = np.cross(f, np.asarray(up, dtype='f4'))
    s = s / np.linalg.norm(s)
    u = np.cross(s, f)

    view = np.eye(4, dtype='f4')
    view[0, :3], view[1, :3], view[2, :3] = s, u, -f
    view[:3, 3] = -view[:3, :3] @ eye
    return view


def face_projection_matrix(near=1e-4, far=1000.0):
    """A symmetric 90-degree frustum: exactly one face of a cube, so the six tile without gaps."""
    projection = np.zeros((4, 4), dtype='f4')
    projection[0, 0] = projection[1, 1] = 1.0          # tan(45 degrees)
    projection[2, 2] = -(far + near) / (far - near)
    projection[2, 3] = -2.0 * far * near / (far - near)
    projection[3, 2] = -1.0
    return projection


def face_matrices(subject_position=(0, 0, 0), near=1e-4, far=1000.0):
    """The six view-projection matrices that fill a cube map from `subject_position`.

    Returned in GL face order, so index i belongs to GL_TEXTURE_CUBE_MAP_POSITIVE_X + i.
    """
    projection = face_projection_matrix(near, far)
    return [projection @ face_view_matrix(subject_position, forward, up)
            for forward, up in CUBE_FACES]


class CubeMapRenderer:
    """Owns the cube map, its framebuffers, and the warp pass.

    :param ctx: a moderngl context
    :param mesh: a ScreenMesh (see curved_screen) -- supplies the projector coordinates and
        directions that make up the warp geometry
    :param resolution: pixels per cube face. 512 is already well below what a fly resolves
        (0.18 degrees per texel over a 90 degree face, against ~5 degrees between ommatidia);
        1024 costs about 0.1 ms more per frame and 25 MB.
    """

    def __init__(self, ctx, mesh, resolution=1024, faces=6):
        from OpenGL import GL

        self.ctx = ctx
        self.resolution = int(resolution)
        self.faces = int(faces)
        self._gl = GL

        self.cube = ctx.texture_cube((self.resolution, self.resolution), 4)
        self.cube.filter = (ctx.LINEAR, ctx.LINEAR)
        # Without this, sampling near a face boundary blends towards that face's border instead of
        # across into its neighbour, and the seams show up as lines on the screen.
        GL.glEnable(GL.GL_TEXTURE_CUBE_MAP_SEAMLESS)

        self._depth = ctx.depth_renderbuffer((self.resolution, self.resolution))
        self._face_fbos = [self._attach_face(i) for i in range(self.faces)]

        self.program = ctx.program(vertex_shader=WARP_VERTEX_SHADER,
                                   fragment_shader=WARP_FRAGMENT_SHADER)
        self._vbo = ctx.buffer(mesh.interleaved().tobytes())
        self.vao = ctx.vertex_array(
            self.program, [(self._vbo, '2f 3f', 'in_ndc', 'in_direction')])
        self.n_vertices = mesh.n_triangles * 3

    def _attach_face(self, index):
        """Attach one cube face to a framebuffer. moderngl cannot do this, so it is raw GL."""
        GL = self._gl
        fbo = GL.glGenFramebuffers(1)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, fbo)
        GL.glFramebufferTexture2D(GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT0,
                                  GL.GL_TEXTURE_CUBE_MAP_POSITIVE_X + index, self.cube.glo, 0)
        GL.glFramebufferRenderbuffer(GL.GL_FRAMEBUFFER, GL.GL_DEPTH_ATTACHMENT,
                                     GL.GL_RENDERBUFFER, self._depth.glo)

        # Checked explicitly: an incomplete framebuffer raises no exception and renders nothing, so
        # the failure would be a black screen with no explanation anywhere.
        status = GL.glCheckFramebufferStatus(GL.GL_FRAMEBUFFER)
        if status != GL.GL_FRAMEBUFFER_COMPLETE:
            GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, 0)
            raise RuntimeError(f'cube-map framebuffer for face {index} is incomplete '
                               f'(status 0x{status:x})')
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, 0)
        return fbo

    def use_face(self, index, clear_color=(0.0, 0.0, 0.0, 1.0)):
        """Make one cube face the render target. Draw the scene, then move to the next face."""
        GL = self._gl
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self._face_fbos[index])
        GL.glViewport(0, 0, self.resolution, self.resolution)
        GL.glClearColor(*clear_color)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)

    def render_warp(self, viewport=None):
        """Draw the screen mesh into whatever framebuffer is currently bound.

        One draw call for the whole screen, however finely it is tessellated.
        """
        self.cube.use(0)
        self.program['cube'].value = 0
        if viewport is not None:
            self.ctx.viewport = viewport
        self.vao.render(vertices=self.n_vertices)

    def release(self):
        """Free the GL objects. The raw framebuffers are not managed by moderngl, so this matters."""
        GL = self._gl
        if self._face_fbos:
            GL.glDeleteFramebuffers(len(self._face_fbos), self._face_fbos)
            self._face_fbos = []
        for owned in (self.vao, self._vbo, self.program, self._depth, self.cube):
            try:
                owned.release()
            except Exception:
                pass
