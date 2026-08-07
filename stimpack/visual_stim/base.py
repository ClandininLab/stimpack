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


def _frame_bytes(frame):
    """A shape's edge frame as the bytes a GLSL mat3 uniform wants.

    A frame is stored one axis per row in Python, because that is how it reads -- azimuth,
    elevation, forward. GLSL indexes a mat3 by *column* and takes its bytes column-major, so
    writing the rows out in order is what makes ``edge_frame[2]`` the forward axis in the shader.
    """
    return np.ascontiguousarray(frame, dtype='f4').tobytes()


class BaseProgram:
    def __init__(self, screen, num_tri=500):
        """
        :param screen: Object containing screen size information
        """
        # set screen
        self.screen = screen
        self.num_tri = num_tri
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

        # Initialize vertex objects
        # 3 points, (3 for vert, 4 for color, 2 for tex_coords), 4 bytes per value
        self.vbo_vert    = self.ctx.buffer(reserve=self.num_tri*3*3*4)
        self.vbo_color   = self.ctx.buffer(reserve=self.num_tri*3*4*4)
        vao_content  = [(self.vbo_vert,  '3f', 'in_vert'),
                        (self.vbo_color, '4f', 'in_color')]
        if self.use_texture:
            self.vbo_texture = self.ctx.buffer(reserve=self.num_tri*3*2*4)
            vao_content.append((self.vbo_texture, '2f', 'in_tex_coord'))
        self.vao = self.ctx.vertex_array(program = self.prog, content = vao_content)

        # Default texture booleans for the shader program
        self.prog['use_texture'].value = False
        self.prog['rgb_texture'].value = False

        # No analytic edge unless a shape asks for one, so an unconverted stimulus renders exactly
        # as it did. The other two are never read while this is 0, but GL wants them initialised.
        self.prog['edge_kind'].value = 0
        self.prog['edge_frame'].write(_frame_bytes(np.eye(3)))
        self.prog['edge_extent'].value = (0.0, 0.0)
        self.prog['subject_position'].value = (0.0, 0.0, 0.0)

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

    def paint_at(self, t, viewports, perspectives, subject_position={'x':0, 'y':0, 'z':0, 'theta':0, 'phi':0}):
        """
        :param t: current time in seconds
        :param viewports: list of viewport arrays for each subscreen - (xmin, ymin, width, height) in display device pixels
        :param perspectives: list of perspective matrices for each subscreen, generated using perspective.GenPerspective and subscreen corners
        :param subject_position: x, y, z position of subject (meters)
        """
        self.eval_at(t, subject_position=subject_position) # update any stim objects that depend on subject position

        # get data from stim object
        vert_coords = self.stim_object.vertices  # x, y, z
        colors   = self.stim_object.colors       # r, g, b, a        
        tex_coords = self.stim_object.tex_coords # texture x, texture y

        n_vertices = vert_coords.shape[1]

        # write data to VBO
        self.vbo_vert.write(vert_coords.flatten(order='F').astype('f4'))
        self.vbo_color.write(colors.flatten(order='F').astype('f4'))
        if self.use_texture:
            self.vbo_texture.write(tex_coords.flatten(order='F').astype('f4'))
            # Bind this stimulus's texture immediately before drawing it, always to unit 0.
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

        # Hand the shader this shape's own edge equation, if it has one. Read off the object
        # rather than configured per stimulus: converting a shape converts every stimulus that
        # draws it, and one that declares nothing keeps the geometry-defined edge.
        edge_kind = getattr(self.stim_object, 'edge_kind', 0)
        self.prog['edge_kind'].value = edge_kind
        if edge_kind:
            self.prog['edge_frame'].write(_frame_bytes(self.stim_object.edge_frame))
            self.prog['edge_extent'].value = tuple(float(v) for v in self.stim_object.edge_extent)
            self.prog['subject_position'].value = (float(subject_position['x']),
                                                   float(subject_position['y']),
                                                   float(subject_position['z']))

        # Render to each subscreen
        for v_ind, vp in enumerate(viewports):
            # set the perspective matrix
            self.prog['Mvp'].write(perspectives[v_ind])
            # set the viewport
            self.ctx.viewport = vp

            # render the object
            if self.draw_mode == 'POINTS':
                self.vao.render(mode=moderngl.POINTS, vertices=n_vertices)
                self.ctx.point_size=self.point_size
            elif self.draw_mode == 'TRIANGLES':
                self.vao.render(mode=moderngl.TRIANGLES, vertices=n_vertices)

    def add_texture_gl(self, texture_image, texture_interpolation='LINEAR'):
        """
        Upload a texture for this stimulus.

        :param texture_image: 2D array for monochrome, or x-by-y-by-3 for RGB
        :param texture_interpolation: ``'LINEAR'`` to smooth between texels, ``'NEAREST'`` to keep
            hard edges -- the right choice for checkerboards and random grids, where interpolation
            would blur the pattern
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

        if texture_interpolation == 'NEAREST':
            self.texture.filter = (moderngl.NEAREST, moderngl.NEAREST)
        elif texture_interpolation == 'LINEAR':
            self.texture.filter = (moderngl.LINEAR, moderngl.LINEAR)
        else:
            self.texture.filter = (moderngl.LINEAR, moderngl.LINEAR)

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
        """The fragment shader source. Override to change how fragments are coloured."""
        fragment_shader = '''
            #version 330

            in vec4 v_color;
            in vec2 v_tex_coord;
            in vec3 v_world;

            uniform bool use_texture;
            uniform bool rgb_texture;
            uniform sampler2D texture_matrix;

            // A shape may hand the shader an equation for its true boundary instead of relying on
            // its triangles to describe it. edge_kind 0 means it has not, which is every shape
            // that has not opted in -- the geometry defines the edge, exactly as it always has.
            uniform int edge_kind;
            // Rows: the shape's azimuth axis, elevation axis, and forward direction. A disc needs
            // only the last; a rectangle needs all three, because "20 degrees wide" is a statement
            // about a frame, not about a point.
            uniform mat3 edge_frame;
            uniform vec2 edge_extent;
            uniform vec3 subject_position;

            out vec4 f_color;

            // How far outside the shape this fragment is, in radians. Negative is inside. Every
            // kind answers in the same currency, so the coverage arithmetic below is shared.
            float edge_excess(vec3 dir) {
                float across = dot(dir, edge_frame[0]);
                float up     = dot(dir, edge_frame[1]);
                float ahead  = dot(dir, edge_frame[2]);

                if (edge_kind == 1) {
                    // Cone: the shape is a flat ellipse projected outward from the subject, so
                    // divide out the forward component to get that flat card's own coordinates and
                    // ask how far out on it this fragment lands. 1.0 is exactly on the boundary.
                    //
                    // A disc is the equal-extent case, which is why there is no separate branch
                    // for it -- and why an ellipse with equal axes really is a disc.
                    if (ahead <= 0.0) return 1.0;                 // behind the shoulder, so outside
                    float u = across / (ahead * tan(edge_extent.x));
                    float v = up     / (ahead * tan(edge_extent.y));
                    return sqrt(u*u + v*v) - 1.0;
                }

                // Rectangle: azimuth and elevation in the shape's own frame, whichever is worse.
                float azimuth   = atan(across, ahead);
                float elevation = asin(clamp(up, -1.0, 1.0));
                return max(abs(azimuth) - edge_extent.x, abs(elevation) - edge_extent.y);
            }

            // What fraction of this pixel the shape covers.
            //
            // fwidth is the change in a value between neighbouring pixels -- GPUs shade in 2x2
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
                vec3 dir = normalize(v_world - subject_position);
                float excess = edge_excess(dir);
                float pixel = fwidth(excess);
                if (pixel <= 0.0) return excess <= 0.0 ? 1.0 : 0.0;
                return clamp(0.5 - excess / pixel, 0.0, 1.0);
            }

            void main() {
                if (use_texture) {
                    vec4 texFrag = texture(texture_matrix, v_tex_coord);
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
            }
        '''

        return fragment_shader
