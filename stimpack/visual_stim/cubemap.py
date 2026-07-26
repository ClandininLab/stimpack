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


def face_view_projections(subject_position=None, near=1e-4, far=1000.0):
    """The six view-projection matrices that fill a cube map, as arrays, in GL face order.

    :param subject_position: the same dict the planar path uses -- {'x','y','z','theta','phi','roll'}
        -- or None for a subject at the origin facing +y. Heading is applied by rotating each face's
        axes, so cube-space stays aligned with the rig and the screen mesh's directions (which are
        fixed rig geometry) can sample it directly.

        The rotation order matches get_perspective exactly: yaw about z, then pitch about x, then
        roll about y. Anything else here would leave the curved path disagreeing with the planar one
        the moment a subject turned, which is the kind of difference nobody notices until closed
        loop behaves oddly.
    """
    from stimpack.visual_stim.util import rotx, roty, rotz

    eye = (0.0, 0.0, 0.0)
    rotate = lambda v: v                                          # noqa: E731
    if subject_position is not None:
        eye = (subject_position.get('x', 0.0), subject_position.get('y', 0.0),
               subject_position.get('z', 0.0))
        theta = np.radians(subject_position.get('theta', 0.0))
        phi = np.radians(subject_position.get('phi', 0.0))
        roll = np.radians(subject_position.get('roll', 0.0))

        def rotate(v):                                            # noqa: F811
            return roty(rotx(rotz(np.asarray(v, dtype=float), theta), phi), roll)

    projection = face_projection_matrix(near, far)
    return [projection @ face_view_matrix(eye, rotate(forward), rotate(up))
            for forward, up in CUBE_FACES]


def face_matrices(subject_position=None, near=1e-4, far=1000.0):
    """The same six matrices as bytes, laid out exactly as get_perspective returns them.

    Column-major float32, so a stimulus's `paint_at` can take these in place of the planar
    perspectives with no change to any stimulus.
    """
    return [m.astype('f4').tobytes(order='F')
            for m in face_view_projections(subject_position, near, far)]


def drain_gl_errors(GL):
    """Empty the GL error queue before calling into raw GL.

    PyOpenGL checks glGetError after every call and raises whatever it finds; moderngl never clears
    that queue. So an error produced anywhere earlier surfaces at the next raw call and is reported
    against it, with entirely plausible arguments -- glFramebufferTexture2D blamed for something
    that happened several operations before, which cost an hour of looking for a bug in the
    attachment that was not there. Our own errors are still caught: the completeness check runs
    after the calls it guards.
    """
    while GL.glGetError() != GL.GL_NO_ERROR:
        pass


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

        if int(resolution) < 1:
            raise ValueError(f'cube resolution must be at least 1 pixel, got {resolution}')
        if not 1 <= int(faces) <= 6:
            raise ValueError(f'a cube map has 6 faces; asked for {faces}')

        self.ctx = ctx
        self.resolution = int(resolution)
        self.faces = int(faces)
        self._gl = GL

        self.cube = ctx.texture_cube((self.resolution, self.resolution), 4)
        self.cube.filter = (ctx.LINEAR, ctx.LINEAR)
        # Without this, sampling near a face boundary blends towards that face's border instead of
        # across into its neighbour, and the seams show up as lines on the screen.
        drain_gl_errors(GL)
        GL.glEnable(GL.GL_TEXTURE_CUBE_MAP_SEAMLESS)

        self._depth = ctx.depth_renderbuffer((self.resolution, self.resolution))
        # One framebuffer, re-pointed at a different cube face each time. Its placeholder colour
        # attachment is a renderbuffer rather than a 2D texture on purpose: a GL texture name keeps
        # the target it was first bound to, so after this object is released and its names are
        # reused, a name that had been a 2D texture cannot become a cube face -- which made a second
        # CubeMapRenderer in the same context fail with GL_INVALID_OPERATION. A renderbuffer lives
        # in a different namespace, so the question cannot arise.
        self._color_placeholder = ctx.renderbuffer((self.resolution, self.resolution), 4)
        self._fbo = ctx.framebuffer(color_attachments=[self._color_placeholder],
                                    depth_attachment=self._depth)
        self._attached_face = None

        self.program = ctx.program(vertex_shader=WARP_VERTEX_SHADER,
                                   fragment_shader=WARP_FRAGMENT_SHADER)
        self._vbo = ctx.buffer(mesh.interleaved().tobytes())
        self.vao = ctx.vertex_array(
            self.program, [(self._vbo, '2f 3f', 'in_ndc', 'in_direction')])
        self.n_vertices = mesh.n_triangles * 3

    def use_face(self, index, clear_color=(0.0, 0.0, 0.0, 1.0)):
        """Make one cube face the render target. Draw the scene, then move to the next face.

        The framebuffer is moderngl's; only the attachment is raw GL. Creating framebuffers with
        glGenFramebuffers instead raised GL_INVALID_VALUE on bind inside the screen subprocess while
        passing under a standalone context -- the name belongs to whichever context PyOpenGL was
        talking to, which is not reliably the one moderngl holds inside a Qt widget.
        """
        if not 0 <= index < self.faces:
            raise IndexError(f'face {index} is out of range for {self.faces} faces')

        GL = self._gl
        self._fbo.use()

        drain_gl_errors(GL)
        GL.glFramebufferTexture2D(GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT0,
                                  GL.GL_TEXTURE_CUBE_MAP_POSITIVE_X + index, self.cube.glo, 0)

        if self._attached_face is None:
            # Checked once: GL reports an incomplete framebuffer by flag rather than exception, so
            # otherwise the failure is a black screen with no explanation anywhere.
            status = GL.glCheckFramebufferStatus(GL.GL_FRAMEBUFFER)
            if status != GL.GL_FRAMEBUFFER_COMPLETE:
                raise RuntimeError(f'cube-map framebuffer is incomplete (status 0x{status:x})')
        self._attached_face = index

        self.ctx.viewport = (0, 0, self.resolution, self.resolution)
        self._fbo.clear(*clear_color)

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
        """Free the GL objects. moderngl's default gc_mode does not do this for us."""
        for owned in (self.vao, self._vbo, self.program, self._fbo,
                      self._color_placeholder, self._depth, self.cube):
            try:
                owned.release()
            except Exception:
                pass
