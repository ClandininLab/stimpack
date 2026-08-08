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

# One face of a cube map spans a right angle, edge to edge through its centre. Named because the
# resolution arithmetic reads as nonsense without it: px/deg is resolution / CUBE_FACE_DEGREES.
CUBE_FACE_DEGREES = 90.0

# Pixels per face unless a rig says otherwise. See CubeMapRenderer for what it costs.
DEFAULT_CUBE_RESOLUTION = 1024

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
    in float in_gain;
    out vec3 v_direction;
    out float v_gain;
    void main() {
        v_direction = in_direction;
        v_gain = in_gain;
        gl_Position = vec4(in_ndc, 0.0, 1.0);
    }
'''

WARP_FRAGMENT_SHADER = '''
    #version 330
    uniform samplerCube cube;
    in vec3 v_direction;
    in float v_gain;
    out vec4 f_color;
    void main() {
        vec4 sampled = texture(cube, normalize(v_direction));
        // Evens out an uneven projector. rgb only: alpha says how to composite, not how bright
        // this is, and scaling it would make the correction depend on the blend mode.
        f_color = vec4(sampled.rgb * v_gain, sampled.a);
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


def region_planes_and_corners(face):
    """The four inward plane normals and four corners bounding one face's region on the sphere.

    A cube map samples by dominant axis, so face +Z owns {d : d_z >= |d_x| and d_z >= |d_y|} -- a
    spherical square cut by four planes through the origin, with corners at (+-1, +-1, 1)/sqrt(3).
    """
    axis, sign = ((0, +1), (0, -1), (1, +1), (1, -1), (2, +1), (2, -1))[face]
    centre = np.zeros(3)
    centre[axis] = sign
    others = [i for i in range(3) if i != axis]

    normals = []
    for other, side in itertools.product(others, (+1, -1)):
        normal = centre.copy()
        normal[other] = -side
        normals.append(normal / np.linalg.norm(normal))

    corners = []
    for s1, s2 in itertools.product((+1, -1), repeat=2):
        corner = centre.copy()
        corner[others[0]], corner[others[1]] = s1, s2
        corners.append(corner / np.linalg.norm(corner))

    return np.array(normals), np.array(corners)


def distance_to_face_region(direction, face):
    """Angular distance in radians from a unit vector to a face's region; 0 if inside it."""
    normals, corners = region_planes_and_corners(face)
    direction = np.asarray(direction, dtype=float)
    direction = direction / np.linalg.norm(direction)
    if np.all(normals @ direction >= -1e-12):
        return 0.0

    best = np.inf
    for normal in normals:                      # perpendicular foot on each bounding edge
        foot = direction - (direction @ normal) * normal
        length = np.linalg.norm(foot)
        if length > 1e-12:
            foot = foot / length
            if np.all(normals @ foot >= -1e-9):     # ...but only if it lands on the edge itself
                best = min(best, np.arccos(np.clip(direction @ foot, -1.0, 1.0)))
    for corner in corners:
        best = min(best, np.arccos(np.clip(direction @ corner, -1.0, 1.0)))
    return float(best)


def faces_for_cap(axis, half_angle):
    """Exactly the faces a spherical cap needs, without sampling anything.

    A cap of this half-angle about `axis` reaches face f precisely when f's region lies closer than
    half_angle. Used to choose an orientation; faces_for_directions is what the renderer actually
    asks, since a real screen need not be a cap.
    """
    return tuple(f for f in range(6) if distance_to_face_region(axis, f) < half_angle)


def orientation_for_cap(axis, half_angle, prefer='auto'):
    """A cube orientation that puts a cap on as few faces as possible, with margin to spare.

    Only two things matter, and neither is found by searching. A cap is rotationally symmetric about
    its own axis, so only the direction of that axis relative to the cube counts -- two degrees of
    freedom, not three, and any answer quoting a roll angle is quoting noise. And a face's region is
    an intersection of half-spaces, so "does the cap reach this face" is a distance from a point to
    a spherical square, which is closed-form.

    That leaves three alignments, with exact thresholds:

        cap axis at a face centre    5 faces for 45 deg   < half_angle <= 125.26 deg
        cap axis at an edge midpoint 4 faces for 35.26    < half_angle <= 90
        cap axis at a corner         3 faces for            half_angle <  70.53 = arccos(1/3)

    'auto' takes the corner when the cap fits it with room -- below 65 degrees, leaving over 5
    degrees of margin -- and the edge otherwise. Margin matters as much as the count: a cap just
    under 70.53 gets three faces on a knife edge, and falling off it costs three faces at once.

    :param axis: the cap's axis, in rig coordinates
    :param half_angle: radians
    :param prefer: 'auto', 'corner', 'edge', or 'none' for no rotation
    :returns: a 3x3 rotation taking rig directions to cube directions, or None for no rotation
    """
    if prefer == 'none':
        return None
    if prefer not in ('auto', 'corner', 'edge'):
        raise ValueError(f"prefer must be 'auto', 'corner', 'edge' or 'none', not {prefer!r}")

    corner_fits = half_angle < np.radians(65.0)
    target = {'corner': (1, 1, 1), 'edge': (0, 1, 1)}.get(
        prefer, (1, 1, 1) if corner_fits else (0, 1, 1))

    return rotation_taking(np.asarray(axis, dtype=float), np.asarray(target, dtype=float))


def rotation_taking(source, target):
    """The shortest rotation taking unit vector `source` onto `target`. Identity if already there."""
    a = np.asarray(source, dtype=float); a = a / np.linalg.norm(a)
    b = np.asarray(target, dtype=float); b = b / np.linalg.norm(b)
    v = np.cross(a, b)
    c = float(a @ b)
    if np.linalg.norm(v) < 1e-12:
        # Parallel or antiparallel: no unique axis, so pick any perpendicular one for the flip.
        if c > 0:
            return np.eye(3)
        perp = np.eye(3)[int(np.argmin(np.abs(a)))]
        v = np.cross(a, perp); v = v / np.linalg.norm(v)
        return -np.eye(3) + 2 * np.outer(v, v)
    skew = _skew_matrix(v)
    return np.eye(3) + skew + skew @ skew / (1.0 + c)


def _skew_matrix(v):
    return np.array([[0.0, -v[2], v[1]], [v[2], 0.0, -v[0]], [-v[1], v[0], 0.0]])


def face_view_projections(subject_position=None, near=1e-4, far=1000.0, orientation=None):
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


def faces_for_directions(directions, triangles=None):
    """Which cube faces a set of view directions actually lands on, in GL face order.

    A screen rarely fills the sphere. A bowl above the animal never sends a direction downwards, so
    the -Z face is rendered every frame and sampled by nothing; a screen covering only the front
    misses two. Rendering the scene into a face nothing samples costs a full scene draw for nothing.

    Faces are found by dominant axis, which is exactly how a cube map is sampled. Passing
    `triangles` also probes each triangle's edge midpoints and centroid: interpolation runs across
    a facet, so a facet straddling a face boundary can put fragments on a face none of its three
    vertices reached, and the cost of missing one is a black wedge on the screen. The extra probes
    are arithmetic on an array that already exists, so being conservative here is free.
    """
    directions = np.asarray(directions, dtype=float)
    if len(directions) == 0:
        return ()

    probes = [directions]
    if triangles is not None:
        corners = np.asarray(triangles, dtype=int).reshape(-1, 3)
        a, b, c = (directions[corners[:, i]] for i in range(3))
        probes += [(a + b) / 2, (b + c) / 2, (c + a) / 2, (a + b + c) / 3]

    found = set()
    for probe in probes:
        norms = np.linalg.norm(probe, axis=1, keepdims=True)
        unit = probe / np.where(norms == 0, 1.0, norms)
        axis = np.argmax(np.abs(unit), axis=1)
        negative = unit[np.arange(len(unit)), axis] < 0
        found.update((axis * 2 + negative).tolist())
    return tuple(sorted(found))


def faces_for_mesh(mesh):
    """The faces a ScreenMesh needs. See faces_for_directions."""
    return faces_for_directions(mesh.directions, getattr(mesh, 'triangles', None))


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
        1024 costs about 0.1 ms more per frame and 25 MB. This, not the screen tessellation, is
        what sets angular resolution: each fragment samples the cube along its own interpolated
        direction, so facets approximate the surface rather than the image.
    :param faces: which cube faces to render, by default only those the mesh actually samples --
        five for a bowl above the animal, four for a screen covering the front. Pass an iterable of
        indices to choose explicitly, or an integer N for the first N in GL order. The texture
        always has six faces; this decides how many times the scene is drawn.
    """

    def __init__(self, ctx, mesh, resolution=DEFAULT_CUBE_RESOLUTION, faces=None):
        from OpenGL import GL

        if int(resolution) < 1:
            raise ValueError(f'cube resolution must be at least 1 pixel, got {resolution}')
        if faces is None:
            face_indices = faces_for_mesh(mesh)
        elif isinstance(faces, (int, np.integer)):
            # The legacy spelling: a count, taken from the front of GL face order. Kept because it
            # is what the tests reach for, but it cannot express most real answers -- a front-facing
            # screen needs +X, -X, +Y and +Z, and no prefix of the order contains those four.
            if not 1 <= int(faces) <= 6:
                raise ValueError(f'a cube map has 6 faces; asked for {faces}')
            face_indices = tuple(range(int(faces)))
        else:
            face_indices = tuple(sorted({int(f) for f in faces}))
            if not face_indices or not all(0 <= f <= 6 - 1 for f in face_indices):
                raise ValueError(f'cube face indices must be 0..5; got {faces}')

        self.ctx = ctx
        self.resolution = int(resolution)
        self.face_indices = face_indices
        self.faces = len(face_indices)
        self._gl = GL

        self.cube = ctx.texture_cube((self.resolution, self.resolution), 4)
        self.cube.filter = (ctx.LINEAR, ctx.LINEAR)
        # Without this, sampling near a face boundary blends towards that face's border instead of
        # across into its neighbour, and the seams show up as lines on the screen.
        drain_gl_errors(GL)
        GL.glEnable(GL.GL_TEXTURE_CUBE_MAP_SEAMLESS)

        self._depth = ctx.depth_renderbuffer((self.resolution, self.resolution))
        # A placeholder colour attachment so moderngl will build complete framebuffers; the raw call
        # below re-points each at a cube face. A renderbuffer rather than a 2D texture on purpose: a
        # GL texture name keeps the target it was first bound to, so a reused name that had been 2D
        # cannot become a cube face, which made a second CubeMapRenderer in one context fail.
        self._color_placeholder = ctx.renderbuffer((self.resolution, self.resolution), 4)

        # One framebuffer per face, each attached once, here. Re-pointing a single framebuffer per
        # frame instead put a raw GL call on the render path, and inside the screen subprocess that
        # failed with GL_INVALID_OPERATION: whichever context PyOpenGL is talking to at paint time
        # is not reliably the one the cube belongs to, whereas at construction it is. Keeping raw GL
        # out of paintGL removes the question, and use_face becomes pure moderngl.
        # Keyed by face index, not positional: the set is sparse in general.
        self._face_fbos = {index: self._attach_face(index) for index in self.face_indices}

        self.program = ctx.program(vertex_shader=WARP_VERTEX_SHADER,
                                   fragment_shader=WARP_FRAGMENT_SHADER)
        self._vbo = ctx.buffer(mesh.interleaved().tobytes())
        self.vao = ctx.vertex_array(
            self.program, [(self._vbo, '2f 3f 1f', 'in_ndc', 'in_direction', 'in_gain')])
        self.n_vertices = mesh.n_triangles * 3

    def _attach_face(self, index):
        """Point a framebuffer at one cube face. Construction time only -- never per frame."""
        GL = self._gl
        fbo = self.ctx.framebuffer(color_attachments=[self._color_placeholder],
                                   depth_attachment=self._depth)
        fbo.use()

        drain_gl_errors(GL)
        GL.glFramebufferTexture2D(GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT0,
                                  GL.GL_TEXTURE_CUBE_MAP_POSITIVE_X + index, self.cube.glo, 0)

        # GL reports an incomplete framebuffer by flag rather than exception, so without this the
        # failure would be a black screen with no explanation anywhere.
        status = GL.glCheckFramebufferStatus(GL.GL_FRAMEBUFFER)
        if status != GL.GL_FRAMEBUFFER_COMPLETE:
            raise RuntimeError(f'cube-map framebuffer for face {index} is incomplete '
                               f'(status 0x{status:x})')
        return fbo

    def use_face(self, index, clear_color=(0.0, 0.0, 0.0, 1.0)):
        """Make one cube face the render target. Draw the scene, then move to the next face."""
        if index not in self._face_fbos:
            raise ValueError(
                f'face {index} is not attached: this renderer draws {list(self._face_fbos)}, the '
                f'faces its mesh samples. Pass faces= to render others.')
        fbo = self._face_fbos[index]
        fbo.use()
        self.ctx.viewport = (0, 0, self.resolution, self.resolution)
        fbo.clear(*clear_color)

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
        self._face_fbos = dict(getattr(self, '_face_fbos', {}))
        for owned in (*self._face_fbos.values(), self.vao, self._vbo, self.program,
                      self._color_placeholder, self._depth, self.cube):
            try:
                owned.release()
            except Exception:
                pass
