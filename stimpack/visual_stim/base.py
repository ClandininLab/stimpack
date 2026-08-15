"""
Base stimulus class.

Handles GL context, shader programs common to all stimpack.visual_stim stim classes.

See stimpack.visual_stim.stimuli for available child stimulus classes. Overwrite methods in child classes like:
    configure
    eval_at
    update

"""

import moderngl
import numpy as np


#: Where "opaque" stops, for splitting a frame into an opaque pass and a blended one.
#:
#: One half of an 8-bit step below 1.0, which is the point an 8-bit framebuffer stops being able to
#: tell the fragment from opaque. It has to be below 1.0 rather than equal to it: the shader tests
#: an interpolated varying, and perspective-correct interpolation divides by w, so an alpha that is
#: exactly 1.0 at every vertex still arrives a few ULPs under. The GLSL side keeps its own copy of
#: this number -- keep the two in step.
OPAQUE_ALPHA = 254.5 / 255.0

#: Triangles the vertex buffers start out holding. Small on purpose: they grow to fit whatever a
#: frame turns out to need, and growing jumps straight to that size when the gap is large, so
#: starting small costs at most one reallocation and starting large costs more than it saves.
INITIAL_TRIANGLE_RESERVATION = 500


def _frame_bytes(frame):
    """A shape's edge frame as the bytes a GLSL mat3 uniform wants.

    A frame is stored one axis per row in Python, because that is how it reads -- azimuth,
    elevation, forward. GLSL indexes a mat3 by *column* and takes its bytes column-major, so
    writing the rows out in order is what makes ``edge_frame[2]`` the forward axis in the shader.
    """
    return np.ascontiguousarray(frame, dtype='f4').tobytes()


def _draw_runs(stim_object, n_vertices):
    """Split a shape into (first, count, declaration) runs, one per edge equation to be applied.

    One run for the ordinary case. A composite gives one per declared component plus one for each
    gap between them, since undeclared geometry still has to be drawn -- just with no equation.
    Costs about 0.8 microseconds per extra draw call, which is 0.6% of a 360 Hz frame for the
    twenty-patch fields this exists for.
    """
    spans = getattr(stim_object, 'edge_spans', None)
    if not spans:
        return [(0, n_vertices, _packed_edge(stim_object))]

    runs, cursor = [], 0
    for span in spans:                       # add() appends in order, so these are already sorted
        if span.start > cursor:
            runs.append((cursor, span.start - cursor, None))
        runs.append((span.start, span.count, _packed_edge(span)))
        cursor = span.start + span.count
    if cursor < n_vertices:
        runs.append((cursor, n_vertices - cursor, None))
    return runs


def _packed_edge(declaration):
    """A declaration converted once into the exact forms the uniforms want, or None if there is none.

    Packing here rather than at the point of upload matters when a composite has many components:
    the runs are built once per frame but their uniforms are set once per subscreen, and the numpy
    conversions cost more than the draw call they precede.
    """
    if not getattr(declaration, 'edge_kind', 0):
        return None
    return (declaration.edge_kind,
            _frame_bytes(declaration.edge_frame),
            tuple(float(v) for v in declaration.edge_anchor),
            tuple(float(v) for v in declaration.edge_extent))


class BaseProgram:
    def __init__(self, screen, num_tri=None):
        """
        :param screen: Object containing screen size information
        :param num_tri: **ignored**, and accepted only so existing callers keep working.

            It used to reserve the vertex buffers, and had to be given here -- before configure has
            run, before anything knows how big the geometry will be -- so callers guessed. The
            guesses in the tree are thirteen identical 10000s, two 1000s, one 20000 and one 500,
            which is what a parameter looks like when nobody can compute its answer.

            The buffers now size themselves, and a wrong guess costs one reallocation of 0.005 ms
            rather than an error. Guessing *high* was measured to be worse than not guessing at all:
            reserving 20000 triangles for a stimulus that needs 10368 made its first frame 0.703 ms
            against 0.585 ms starting small, because the oversized allocation costs more than the
            one reallocation it saves.
        """
        # set screen
        self.screen = screen
        self.num_tri = INITIAL_TRIANGLE_RESERVATION
        self.use_texture = False
        self.rgb_texture = False
        self.texture = None
        self.draw_mode = 'TRIANGLES'  # TRIANGLES, POINTS
        self.point_size = 2  # pixels on screen, only for POINTS draw_mode

    def initialize(self, ctx):
        """
        :param ctx: ModernGL context
        """
        # save context
        self.ctx = ctx
        self.prog = self.ctx.program(vertex_shader=self.get_vertex_shader(), fragment_shader=self.get_fragment_shader())

        self.allocate_vertex_buffers(INITIAL_TRIANGLE_RESERVATION)

        # Default texture booleans for the shader program
        self.prog['use_texture'].value = False
        self.prog['rgb_texture'].value = False
        self.prog['sharp_texels'].value = False

        # Draw everything unless a caller splits the frame into passes.
        self.prog['pass_kind'].value = 0

        # No analytic edge unless a shape asks for one, so an unconverted stimulus renders exactly
        # as it did. The other two are never read while this is 0, but GL wants them initialized.
        self.prog['edge_kind'].value = 0
        self.prog['edge_frame'].write(_frame_bytes(np.eye(3)))
        self.prog['edge_anchor'].value = (0.0, 0.0, 0.0)
        self.prog['edge_extent'].value = (0.0, 0.0)

    def allocate_vertex_buffers(self, num_tri):
        """(Re)serve vertex buffers for `num_tri` triangles and rebuild the vertex array.

        3 points per triangle; 3 floats for position, 4 for color, 2 for texture coordinates.
        """
        for name in ('vao', 'vbo_vert', 'vbo_color', 'vbo_texture'):
            existing = getattr(self, name, None)
            if existing is not None:
                existing.release()
                setattr(self, name, None)

        self.num_tri = int(num_tri)
        self.vbo_vert    = self.ctx.buffer(reserve=self.num_tri*3*3*4)
        self.vbo_color   = self.ctx.buffer(reserve=self.num_tri*3*4*4)
        vao_content  = [(self.vbo_vert,  '3f', 'in_vert'),
                        (self.vbo_color, '4f', 'in_color')]
        if self.use_texture:
            self.vbo_texture = self.ctx.buffer(reserve=self.num_tri*3*2*4)
            vao_content.append((self.vbo_texture, '2f', 'in_tex_coord'))
        self.vao = self.ctx.vertex_array(program = self.prog, content = vao_content)

    def ensure_vertex_capacity(self, n_vertices):
        """Grow the vertex buffers if this frame's geometry does not fit in them.

        This is what replaced the reservation a caller used to have to guess at construction.
        Guessing low failed at the first frame with `out of range offset`, which is how Forest's
        1000 stopped it at 31 faces per tree for 16 trees; guessing high reserved GPU memory
        nothing wrote to.

        Doubling rather than fitting exactly, so a stimulus whose geometry creeps upward -- a loom
        rebuilt each frame, a field gaining points -- reallocates a handful of times rather than
        every frame.
        """
        if n_vertices <= self.num_tri * 3:
            return
        self.allocate_vertex_buffers(max(-(-n_vertices // 3), self.num_tri * 2))

    def configure(self, *args, **kwargs):
        """
        Set this stimulus's parameters. Called once, before the trial starts.

        Subclasses override this. Anything expensive -- building geometry that does not change,
        generating and uploading a texture -- belongs here rather than in :meth:`eval_at`, which
        runs every frame. Parameters accepted here are what a protocol passes to ``load_stim``,
        and what is saved with the data.
        """
        pass

    def update(self, *args, **kwargs):
        """Update parameters mid-trial, in response to a ``update_stim`` call from the client."""
        pass

    def destroy(self):
        """Release GL resources. Called when the stimulus is unloaded."""
        pass

    def may_blend(self):
        """Whether this stimulus can produce a fragment with alpha below 1.

        Lets a caller splitting the frame skip the blended pass for stimuli that cannot contribute
        to it -- a grating, a background, any opaque geometry with no declared edge. Worth the check
        because the skipped pass is not free: it still runs the vertex stage, rasterizes everything
        and executes the fragment shader up to the discard. On the curved path, where that happens
        once per cube face, a full-field grating paid 0.70 ms for a pass that drew nothing.

        Conservative in every uncertain case. Skipping a stimulus that did need the pass would drop
        its edges from the frame entirely, which is far worse than drawing one that did not.

        Only meaningful after the stimulus has been evaluated: it reads the shape eval_at built.
        """
        stim_object = getattr(self, 'stim_object', None)
        if stim_object is None:
            return True
        if getattr(stim_object, 'edge_kind', 0) or getattr(stim_object, 'edge_spans', None):
            return True                       # a declared edge means partial coverage at its rim
        colors = getattr(stim_object, 'colors', None)
        if colors is None:
            return True
        try:
            return bool(np.min(np.asarray(colors)[3]) < OPAQUE_ALPHA)
        except Exception:
            return True                       # unreadable colors: assume it blends

    def paint_at(self, t, viewports, perspectives, subject_position={'x':0, 'y':0, 'z':0, 'theta':0, 'phi':0},
                 prepare=True, pass_kind=0):
        """
        :param t: current time in seconds
        :param viewports: list of viewport arrays for each subscreen - (xmin, ymin, width, height) in display device pixels
        :param perspectives: list of perspective matrices for each subscreen, generated using perspective.GenPerspective and subscreen corners
        :param subject_position: x, y, z position of subject (meters)
        :param prepare: whether to evaluate this stimulus and upload its geometry first. Pass
            ``False`` when the caller has already done that for this frame and is drawing the same
            geometry again from another viewpoint -- which is what the cube-map path does, since it
            has to bind a different framebuffer per face and so cannot hand over every "viewport"
            in one call the way the planar path does.

            Both halves have to be per frame, for different reasons.

            **Evaluation, because a stimulus is entitled to exactly one per displayed frame.**
            Several are stateful -- they integrate since the last call, or pop from a schedule --
            and evaluating one twice at the same t advances it twice. Whether that shows depends on
            the stimulus: one integrating ``t - t_prev`` sees zero elapsed and is unharmed, while
            one testing ``t % period <= t_prev % period`` fires again, because after the first call
            those are equal and the comparison is not strict. A labpack dot field popping one
            refresh time per evaluation ran out of them five times faster than it should and raised
            IndexError mid-trial.

            **Upload, because it is the expensive part of this method** and the geometry is the
            same for every face. Re-sending it per face made the cube pass scale with face count in
            vertices as well as in draw calls, which is exactly what turning the cube is meant to
            avoid.
        :param pass_kind: which fragments to draw. ``0`` draws everything, which is the behavior
            this had before the option existed. ``1`` draws only fully opaque fragments and ``2``
            only blended ones, which is how a caller splits a frame so that blending stops
            depending on draw order -- see ``Screen(split_blended_pass=True)``.
        """
        self.prog['pass_kind'].value = int(pass_kind)

        if prepare:
            self.eval_at(t, subject_position=subject_position) # update any stim objects that depend on subject position

        # get data from stim object
        vert_coords = self.stim_object.vertices  # x, y, z

        n_vertices = vert_coords.shape[1]

        if prepare:
            # Grow before writing, and only when writing: growing replaces the buffers, so doing it
            # on a pass that is drawing geometry someone else uploaded would discard that geometry.
            self.ensure_vertex_capacity(n_vertices)

            # write data to VBO
            self.vbo_vert.write(vert_coords.flatten(order='F').astype('f4'))
            self.vbo_color.write(self.stim_object.colors.flatten(order='F').astype('f4'))
            if self.use_texture:
                self.vbo_texture.write(self.stim_object.tex_coords.flatten(order='F').astype('f4'))

        if self.use_texture:
            # Bind this stimulus's texture immediately before drawing it, always to unit 0.
            #
            # Every call, not only when uploading: the next stimulus in the list binds its own
            # texture to the same unit, so by the time this one is drawn into the following cube
            # face someone else's is current.
            #
            # Each stimulus owns its own shader program and draws on its own, so no draw call ever
            # needs more than one texture bound -- one unit is enough for any number of stimuli.
            # Binding once at load instead gave every stimulus a permanent unit of its own, which
            # capped an trial at GL_MAX_TEXTURE_IMAGE_UNITS textured stimuli (32 on the development
            # GPU, 16 on some). Past that, drivers observed here bind and render with no GL error at
            # all, so the stimulus is simply wrong on screen with nothing to say so.
            #
            # Benchmarked at 16-100 stimuli and 1-4 viewports on Mesa/Intel, an RTX A4500 and an
            # RTX 2080 Ti: between 8% faster (Mesa, which apparently validates less sampler state
            # per draw with one unit live) and 3% slower (2080 Ti). Every case is a fraction of a
            # millisecond against a 16.7 ms budget at 60 Hz, so the cap is not worth keeping to
            # save it.
            self.texture.use(0)

        # What to draw, and with which edge equation. Usually one run with the object's own -- but
        # a shape built by merging others carries one declaration per component, and those have to
        # be drawn separately because a draw call has only one set of uniforms.
        runs = _draw_runs(self.stim_object, n_vertices)

        # Render to each subscreen
        for v_ind, vp in enumerate(viewports):
            # set the perspective matrix
            self.prog['Mvp'].write(perspectives[v_ind])
            # set the viewport
            self.ctx.viewport = vp

            for first, count, packed in runs:
                self._set_edge_uniforms(packed)
                # render the object
                if self.draw_mode == 'POINTS':
                    self.vao.render(mode=moderngl.POINTS, vertices=count, first=first)
                    self.ctx.point_size=self.point_size
                elif self.draw_mode == 'TRIANGLES':
                    self.vao.render(mode=moderngl.TRIANGLES, vertices=count, first=first)

    def _set_edge_uniforms(self, packed):
        """Hand the shader one edge equation, or none. `packed` comes from :func:`_packed_edge`.

        Read off the shape rather than configured per stimulus: converting a shape converts every
        stimulus that draws it, and one that declares nothing keeps the geometry-defined edge.
        """
        if packed is None:
            self.prog['edge_kind'].value = 0
            return
        kind, frame, anchor, extent = packed
        self.prog['edge_kind'].value = kind
        self.prog['edge_frame'].write(frame)
        self.prog['edge_anchor'].value = anchor
        self.prog['edge_extent'].value = extent

    def add_texture_gl(self, texture_image, texture_interpolation='LINEAR'):
        """
        Upload a texture for this stimulus.

        :param texture_image: 2D array for monochrome, or x-by-y-by-3 for RGB
        :param texture_interpolation: ``'LINEAR'`` to smooth between texels, ``'NEAREST'`` to keep
            hard edges -- the right choice for checkerboards and random grids, where interpolation
            would blur the pattern. ``'NEAREST'`` keeps the edge hard but antialiases where it
            falls, so a drifting pattern's edges move smoothly rather than snapping to the pixel
            grid; it does not blur the pattern.
        """
        # Update the texture booleans for the shader program
        self.prog['rgb_texture'].value = self.rgb_texture
        self.prog['use_texture'].value = self.use_texture

        if self.rgb_texture:
            # RGB texture, shape = x, y, 3 (rgb)
            components = 3
        else:
            # Monochromatic texture, shape = x, y
            components = 1

        self.texture = self.ctx.texture(size=(texture_image.shape[1], texture_image.shape[0]),
                                        components=components,
                                        data=texture_image.tobytes())  # size = (width, height)

        # Both modes filter LINEAR. 'NEAREST' asks for hard texel edges, and the shader delivers
        # them by moving the sample point onto the texel center everywhere except within one pixel
        # of a boundary -- which keeps the hard edge and antialiases it, where the NEAREST filter
        # keeps the hard edge and aliases it. See sample_texture in the fragment shader.
        self.sharp_texels = (texture_interpolation == 'NEAREST')
        self.prog['sharp_texels'].value = self.sharp_texels

        if self.sharp_texels:
            self.texture.filter = (moderngl.LINEAR, moderngl.LINEAR)
        else:
            # A smooth texture can end up finer than a screen pixel -- a ground plane running to the
            # horizon always does, and a grating does whenever it is generated at more texels than
            # the projector has pixels. One sample per pixel of a texture that fine is aliasing, and
            # no amount of filtering at the base level fixes it. Mipmaps do, and they cost a third
            # again of the texture's memory. Measured on a drifting square grating at 2048 texels:
            # 12 of 29 frames had a frozen edge without them and none with.
            #
            # Not for the sharp-texel path: those textures are magnified, their texels ARE the datum
            # -- a checker square, a noise cell -- and a mipmap would blur exactly what they encode.
            self.texture.build_mipmaps()
            self.texture.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)

        # Every stimulus samples from unit 0; paint_at binds this texture there before drawing.
        # This uniform belongs to this stimulus's own program, so it never needs to change again.
        self.prog['texture_matrix'].value = 0

    def update_texture_gl(self, texture_image):
        """Replace the texture's contents, keeping the same GL texture object. For stimuli whose
        texture changes every frame."""
        # Hand the array straight to GL when its memory is already contiguous, rather than copying
        # the whole frame through .tobytes() first. A non-contiguous array has no usable buffer, so
        # it still needs the copy.
        #
        # Tidiness rather than a speed-up, and measured so nobody re-opens the question: at the
        # texture sizes these stimuli actually use (256x256 mono gratings and bars) this saves about
        # 1 microsecond per frame. It reaches 0.3 ms only at full-HD RGB, where the upload itself
        # costs 1.6 ms and dominates anyway.
        data = texture_image if texture_image.flags['C_CONTIGUOUS'] else texture_image.tobytes()
        self.texture.write(data=data)
        if not getattr(self, 'sharp_texels', True):
            self.texture.build_mipmaps()      # else the smaller levels still hold the old frame

    def eval_at(self, t, subject_position={'x':0, 'y':0, 'z':0, 'theta':0, 'phi':0, 'roll':0}):
        """
        :param t: current time in seconds
        """

        pass

    def get_vertex_shader(self):
        """The vertex shader source. Override to change how vertices are transformed."""
        vertex_shader = '''
            #version 330

            in vec3 in_vert;
            in vec4 in_color;
            in vec2 in_tex_coord;

            out vec4 v_color;
            out vec2 v_tex_coord;
            // The vertex before projection. gl_Position has been flattened onto the screen and
            // cannot say which direction this point lies in from the subject, which is what an
            // angular edge test needs.
            out vec3 v_world;

            uniform mat4 Mvp;

            void main() {
                v_color = in_color;
                v_tex_coord = in_tex_coord;
                v_world = in_vert;
                gl_Position = Mvp * vec4(in_vert, 1.0);
            }
        '''
        return vertex_shader

    def get_fragment_shader(self):
        """The fragment shader source. Override to change how fragments are colored."""
        fragment_shader = '''
            #version 330

            in vec4 v_color;
            in vec2 v_tex_coord;
            in vec3 v_world;

            uniform bool use_texture;
            uniform bool rgb_texture;
            uniform sampler2D texture_matrix;
            // Whether this texture's texels are meant to read as hard-edged -- what a caller asks
            // for with texture_interpolation='NEAREST'. See sample_texture below.
            uniform bool sharp_texels;

            // A shape may hand the shader an equation for its true boundary instead of relying on
            // its triangles to describe it. edge_kind 0 means it has not, which is every shape
            // that has not opted in -- the geometry defines the edge, exactly as it always has.
            uniform int edge_kind;
            // Rows: the shape's azimuth axis, elevation axis, and forward direction. A disc needs
            // only the last; a rectangle needs all three, because "20 degrees wide" is a statement
            // about a frame, not about a point.
            uniform mat3 edge_frame;
            uniform vec2 edge_extent;
            // Where the declaration is measured from. Carrying this rather than assuming the origin
            // is what lets a shape be moved without invalidating what it declared.
            uniform vec3 edge_anchor;

            // Which fragments this draw is for. 0 draws everything, as it always did. 1 keeps
            // only fully opaque fragments and 2 only blended ones -- see paint_at's `pass_kind`.
            uniform int pass_kind;

            // Where "opaque" stops, one half of an 8-bit step below 1.0. See the split in main().
            const float OPAQUE_ALPHA = 254.5 / 255.0;

            out vec4 f_color;

            // A texture sample that keeps hard texel edges without letting them alias.
            //
            // NEAREST filtering exists so a checkerboard stays a checkerboard rather than being
            // blurred into a gradient, and that is the right intent. What it costs is exactly what
            // an unantialiased polygon costs: a texel boundary cannot sit between pixels, so it
            // stays on one and then jumps. On a square grating drifting at 10 deg/s the edge is
            // frozen for 17 frames in 19.
            //
            // So filter LINEAR and move the sample point instead. Everywhere but within one pixel
            // of a boundary this lands exactly on a texel center, which is what NEAREST would have
            // returned; across the boundary it ramps, and the hardware's own interpolation then
            // mixes the two texels in the proportion the pixel is covered by each. Same
            // covered-fraction rule as the shape edges, reached through the filter rather than
            // through alpha. See shapes.sharp_texel_coord for the reference implementation.
            vec4 sample_texture() {
                if (!sharp_texels) return texture(texture_matrix, v_tex_coord);
                vec2 size = vec2(textureSize(texture_matrix, 0));
                vec2 texel = v_tex_coord * size;
                // clamped to one texel: past that the texture is minified, there is no single
                // boundary to antialias, and this becomes ordinary bilinear filtering -- which is
                // the right thing to become.
                vec2 pixel = clamp(fwidth(texel), 1e-6, 1.0);
                vec2 boundary = floor(texel + 0.5);
                vec2 across = clamp((texel - boundary) / pixel + 0.5, 0.0, 1.0);
                return texture(texture_matrix, (boundary - 0.5 + across) / size);
            }

            // How far outside the shape this fragment is. Negative is inside, zero on the
            // boundary. Each kind picks its own units -- the coverage step below divides by
            // fwidth of this same value, so the units cancel and only the shape matters.
            float edge_excess() {
                vec3 offset = v_world - edge_anchor;

                // A metric kind asks how FAR away a fragment is; an angular one asks WHICH WAY it
                // lies. That is the whole difference between them, and it is one branch.
                if (edge_kind == 3) {
                    // A flat disc's fragments all lie in the disc's plane, so this distance in
                    // three dimensions is the radius in two.
                    return length(offset) - edge_extent.x;
                }

                vec3 dir = normalize(offset);
                float across = dot(dir, edge_frame[0]);
                float up     = dot(dir, edge_frame[1]);
                float ahead  = dot(dir, edge_frame[2]);

                if (edge_kind == 1) {
                    // Cone: the shape is a flat ellipse projected outward, so divide out the
                    // forward component to get that flat card's own coordinates and ask how far
                    // out on it this fragment lands. 1.0 is exactly on the boundary.
                    //
                    // A disc is the equal-extent case, which is why there is no separate branch
                    // for it -- and why an ellipse with equal axes really is a disc.
                    if (ahead <= 0.0) return 1.0;                 // behind the shoulder, so outside
                    float u = across / (ahead * tan(edge_extent.x));
                    float v = up     / (ahead * tan(edge_extent.y));
                    return sqrt(u*u + v*v) - 1.0;
                }

                // Rectangle: the exact distance outside an axis-aligned box. Taking max() of the
                // two axes instead would be the Chebyshev distance, which past a corner reports
                // the longer leg where the truth is the hypotenuse -- under-reporting by up to
                // sqrt(2), so corners would read as extended by 0.4 of a pixel.
                vec2 d = abs(vec2(atan(across, ahead), asin(clamp(up, -1.0, 1.0)))) - edge_extent;
                return length(max(d, 0.0)) + min(max(d.x, d.y), 0.0);
            }

            // What fraction of this pixel the shape covers.
            //
            // fwidth is the change in a value between neighboring pixels -- GPUs shade in 2x2
            // quads so that derivative exists -- so dividing by it converts `excess` into a
            // distance in pixels, right here, without anyone having to know the projector's
            // resolution, the screen's shape, or whether this is drawn through a cube face.
            //
            // It also means each kind may answer in whatever units suit it: numerator and
            // denominator scale together, so the ratio is always "how many pixels outside".
            //
            // Linear rather than smoothstep: see shapes.edge_coverage for why. A pixel 30% covered
            // must emit 30% of the light, and the mapping from edge position to intensity has to
            // stay linear or a constant-velocity edge stalls and hurries once per pixel.
            float edge_coverage() {
                if (edge_kind == 0) return 1.0;
                float excess = edge_excess();
                float pixel = fwidth(excess);
                if (pixel <= 0.0) return excess <= 0.0 ? 1.0 : 0.0;
                return clamp(0.5 - excess / pixel, 0.0, 1.0);
            }

            void main() {
                if (use_texture) {
                    vec4 texFrag = sample_texture();
                    if (rgb_texture) {
                        f_color.rgb = texFrag.rgb * v_color.rgb;
                    } else {
                        f_color.rgb = texFrag.r * v_color.rgb;
                    }

                    f_color.a = v_color.a;
                } else {
                    f_color.rgb = v_color.rgb;
                    f_color.a = v_color.a;
                }
                // Multiplied in, not assigned: a shape may already be translucent (GlCylinder's
                // alpha_by_face), and coverage composes with that rather than overwriting it.
                f_color.a *= edge_coverage();

                // Split by the FINAL alpha, so a deliberately translucent shape goes the same way
                // an antialiased edge does. Both have to blend without writing depth, and nothing
                // else about them differs here.
                //
                // Against OPAQUE, not against 1.0. v_color.a is an interpolated varying, and
                // perspective-correct interpolation divides by w, so an attribute that is exactly
                // 1.0 at every vertex still arrives a few ULPs under it. Comparing against 1.0
                // exactly made pass 1 discard every opaque fragment -- and since may_blend() reports
                // False for those same stimuli, they were dropped from pass 2 as well and never drawn
                // at all. An opaque background rendered as nothing.
                //
                // 254.5/255 is the point where an 8-bit framebuffer can no longer tell the fragment
                // from opaque, which makes it the honest place to put the boundary: anything that
                // would round to 255 is opaque as far as the display is concerned.
                if (pass_kind == 1 && f_color.a < OPAQUE_ALPHA) discard;
                if (pass_kind == 2 && f_color.a >= OPAQUE_ALPHA) discard;
            }
        '''

        return fragment_shader
