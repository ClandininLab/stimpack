# ref: https://github.com/cprogrammer1994/ModernGL/blob/master/examples/julia_fractal.py

import moderngl
import numpy as np


class SquareProgram:
    def __init__(self, screen, on_color=1.0, off_color=0.0):
        # save settings
        self.screen = screen
        self.on_color = on_color
        self.off_color = off_color

        # initialize settings
        self.on = False
        self.color = self.off_color
        self.toggle = True
        self.draw = True

    def initialize(self, ctx):
        """
        :param ctx: ModernGL context
        """

        # save context
        self.ctx = ctx

        # create OpenGL program
        self.prog = self.create_prog()

        # create VBO to represent vertex positions
        self.pts = np.array([-1, -1, 1, -1, -1, 1, 1, 1]).astype('f4').tobytes() # fill the viewport
        self.vbo = self.ctx.buffer(self.pts)

        # create vertex array object
        self.vao = self.ctx.vertex_array(program = self.prog, 
                                         content = [(self.vbo, '2f', 'pos')], 
                                         mode = moderngl.TRIANGLE_STRIP)

    def create_prog(self):
        return self.ctx.program(
            vertex_shader='''
                #version 330

                in vec2 pos;

                void main() {
                    // assign gl_Position
                    gl_Position = vec4(pos, 0.0, 1.0);
                }
            ''',
            fragment_shader='''
                #version 330

                uniform float color;

                out vec4 out_color;

                void main() {
                    // assign output color based on uniform input
                    out_color = vec4(color, color, color, 1.0);
                }
            '''
        )

    def set_viewport(self, display_width, display_height):
        """
        Sets viewport for display given desired square location and size (size given in NDC)
        :param display_width: Width in pixels of GL display device
        :param display_height: Height in pixels of GL display device

        """
        frac_width = self.screen.square_size[0]/2 # fraction of total window width
        frac_height = self.screen.square_size[1]/2

        # convert from ndc to viewport coordinates
        x = (1+self.screen.square_loc[0]) * display_width/2
        y = (1+self.screen.square_loc[1]) * display_height/2
        self.viewport = (x, y, frac_width*display_width, frac_height*display_height)

    def turn_on(self):
        self.on = True
        self.color = self.on_color

    def turn_off(self):
        self.on = False
        self.color = self.off_color
    
    def set_color(self, color):
        self.toggle = False
        self.on = False
        self.color = color

    def toggle_start(self):
        self.toggle = True

    def toggle_stop(self):
        self.toggle = False

    def paint(self):

        if self.draw:
            # Set viewport
            self.ctx.viewport = self.viewport

            # When using EGL, the context state needs to be reset. Temporary fix.
            if self.screen.use_egl:
                self.prog = self.create_prog()
                self.vbo = self.ctx.buffer(self.pts)
                self.vao = self.ctx.vertex_array(program = self.prog, 
                                        content = [(self.vbo, '2f', 'pos')], 
                                        mode = moderngl.TRIANGLE_STRIP)

            # write color
            self.prog['color'].value = self.color
                
            # render to screen
            self.vao.render(mode=moderngl.TRIANGLE_STRIP)
            
        if self.toggle:
            self.on = not self.on
            self.color = self.on_color if self.on else self.off_color
