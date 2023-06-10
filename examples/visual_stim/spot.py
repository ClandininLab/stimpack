from PyQt5 import QtOpenGL, QtWidgets, QtCore

import sys
import signal
import moderngl
import numpy as np
from argparse import ArgumentParser

class SpotProgram:
    def __init__(self, color=1.0):
        self.color = color

    def initialize(self, ctx):
        """
        :param ctx: ModernGL context
        """
        # save context
        self.ctx = ctx

        # create OpenGL program
        self.prog = self.create_prog()

        # create VBO to represent vertex positions
        self.vbo = self.ctx.buffer(self.make_vert_data())

        # create vertex array object
        self.vao = self.ctx.simple_vertex_array(self.prog, self.vbo, 'pos')
        self.prog['color'].value = self.color

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

    def make_vert_data(self, x=0, y=0, scale=0.01):
        """
        Returns a numpy array of the vertex coordinates in NDC space of the photodiode square
        """

        # determine rectangular bounds
        x_min = x-scale
        x_max = x+scale
        y_min = y-scale
        y_max = y+scale

        # format vertex point data
        data = np.array([x_min, y_min, x_max, y_min, x_min, y_max, x_max, y_max])
        data = data.astype('f4').tobytes()

        # return the data
        return data

    def paint(self, x, y, scale):
        # write new vertex information to VBO
        self.vbo.write(self.make_vert_data(x=x, y=y, scale=scale))

        # render to screen
        self.vao.render(mode=moderngl.TRIANGLE_STRIP)

class SpotDisplay(QtOpenGL.QGLWidget):
    """
    Class that controls the stimulus display on one screen.  It contains the pyglet window object for that screen,
    and also controls rendering of the stimulus, toggling corner square, and/or debug information.
    """

    def __init__(self, app):
        # call super constructor
        super().__init__(self.make_qt_format())

        self.app = app
        self.spot_program = SpotProgram()
        self.x = 0
        self.y = 0
        self.delta = 0.01
        self.scale = 0.01

    def initializeGL(self):
        # get OpenGL context
        self.ctx = moderngl.create_context()

        # initialize program
        self.spot_program.initialize(self.ctx)

    def paintGL(self):
        # set the viewport to fill the window
        # ref: https://github.com/pyqtgraph/pyqtgraph/issues/422
        self.ctx.viewport = (0, 0, self.width()*self.devicePixelRatio(), self.height()*self.devicePixelRatio())

        # clear the display
        self.ctx.clear(0, 0, 0, 1)
        self.ctx.enable(moderngl.BLEND)

        # draw the spot
        self.spot_program.paint(x=self.x, y=self.y, scale=self.scale)

        # update the window
        self.update()

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape:
            self.app.quit()

        if event.key() == QtCore.Qt.Key_Left:
            self.x = max(-1, self.x-self.delta)
        elif event.key() == QtCore.Qt.Key_Right:
            self.x = min(+1, self.x+self.delta)

        if event.key() == QtCore.Qt.Key_Down:
            self.y = max(-1, self.y-self.delta)
        elif event.key() == QtCore.Qt.Key_Up:
            self.y = min(+1, self.y+self.delta)

        if event.key() == QtCore.Qt.Key_L:
            self.scale /= 1.3
        elif event.key() == QtCore.Qt.Key_M:
            self.scale *= 1.3

        if event.key() == QtCore.Qt.Key_S:
            self.delta /= 2
        elif event.key() == QtCore.Qt.Key_F:
            self.delta *= 2

        if event.key() == QtCore.Qt.Key_Space:
            print(f'({self.x}, {self.y})')

    @classmethod
    def make_qt_format(cls, vsync=True):
        """
        Initializes the Qt OpenGL format.
        :param vsync: If True, use VSYNC, otherwise update as fast as possible
        """

        # create format with default settings
        format = QtOpenGL.QGLFormat()

        # use OpenGL 3.3
        format.setVersion(3, 3)
        format.setProfile(QtOpenGL.QGLFormat.CoreProfile)

        # use VSYNC
        if vsync:
            format.setSwapInterval(1)
        else:
            format.setSwapInterval(0)

        # TODO: determine what these lines do and whether they are necessary
        format.setSampleBuffers(True)
        format.setDepthBufferSize(24)

        # needed to enable transparency
        format.setAlpha(True)

        return format


def main():
    parser = ArgumentParser()
    parser.add_argument('--windowed', action='store_true')
    args = parser.parse_args()

    # launch application
    app = QtWidgets.QApplication([])

    stim_display = SpotDisplay(app=app)

    # display the stimulus
    if not args.windowed:
        stim_display.showFullScreen()
    else:
        stim_display.show()

    ####################################
    # Run QApplication
    ####################################

    # Use Ctrl+C to exit.
    # ref: https://stackoverflow.com/questions/2300401/qapplication-how-to-shutdown-gracefully-on-ctrl-c
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
