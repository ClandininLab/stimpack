"""
Base stimulus class.

Handles GL context, shader programs common to all stimpack.visual_stim stim classes.

See stimpack.visual_stim.stimuli for available child stimulus classes. Overwrite methods in child classes like:
    configure
    eval_at
    update

"""

import moderngl


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

    def configure(self, *args, **kwargs):
        pass

    def update(self, *args, **kwargs):
        pass

    def destroy(self):
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

        self.prog['texture_matrix'].value = self.prog.ctx.extra['n_textures_loaded']
        self.texture.use(self.prog.ctx.extra['n_textures_loaded'])

        self.prog.ctx.extra['n_textures_loaded'] += 1

    def update_texture_gl(self, texture_image):
        self.texture.write(data=texture_image.tobytes())

    def eval_at(self, t, subject_position={'x':0, 'y':0, 'z':0, 'theta':0, 'phi':0, 'roll':0}):
        """
        :param t: current time in seconds
        """

        pass

    def get_vertex_shader(self):
        vertex_shader = '''
            #version 330

            in vec3 in_vert;
            in vec4 in_color;
            in vec2 in_tex_coord;

            out vec4 v_color;
            out vec2 v_tex_coord;

            uniform mat4 Mvp;

            void main() {
                v_color = in_color;
                v_tex_coord = in_tex_coord;
                gl_Position = Mvp * vec4(in_vert, 1.0);
            }
        '''
        return vertex_shader

    def get_fragment_shader(self):
        fragment_shader = '''
            #version 330

            in vec4 v_color;
            in vec2 v_tex_coord;

            uniform bool use_texture;
            uniform bool rgb_texture;
            uniform sampler2D texture_matrix;

            out vec4 f_color;

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
            }
        '''

        return fragment_shader
