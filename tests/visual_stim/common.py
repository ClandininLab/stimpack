import moderngl
import numpy as np
from PIL import Image
from PyQt5 import QtOpenGL, QtWidgets


class HeadlessDisplay:
    def __init__(self, width=512, height=512):
        # Create an OpenGL context
        self.ctx = moderngl.create_context(standalone=True, size=(width, height))
        self.ctx.enable(moderngl.DEPTH_TEST)
        self.ctx.enable(moderngl.BLEND)

        # Create a framebuffer for rendering
        self.fbo = self.ctx.simple_framebuffer((width, height))
        self.fbo.use()

        # Create an empty list of render actions
        self.render_objs = []
        self.render_actions = []

    def initializeGL(self):
        for render_obj in self.render_objs:
            render_obj.initialize(self)

    def paintGL(self):
        # First clear the entire viewport
        self.ctx.viewport = (0, 0, self.fbo.width, self.fbo.height)
        self.fbo.clear(0.0, 0.0, 0.0, 1.0)

        # Run each render action in sequence
        for render_action in self.render_actions:
            render_action()

        # Display a single frame
        return Image.frombytes('RGB', self.fbo.size, self.fbo.read(), 'raw', 'RGB', 0, -1)


class QtTestDisplay(QtOpenGL.QGLWidget):
    # adapted from https://github.com/moderngl/moderngl/blob/master/examples/old-examples/PyQt5/01_hello_world.py
    def __init__(self, width=512, height=512):
        # Set up OpenGL format
        fmt = QtOpenGL.QGLFormat()
        fmt.setVersion(3, 3)
        fmt.setProfile(QtOpenGL.QGLFormat.CoreProfile)
        fmt.setSampleBuffers(True)
        super(QtTestDisplay, self).__init__(fmt, None)

        # Set the window size and position
        self.resize(width, height)
        self.move(QtWidgets.QDesktopWidget().rect().center() - self.rect().center())

        # Create an empty list of render actions
        self.render_objs = []
        self.render_actions = []

    def initializeGL(self):
        # Create a context for OpenGL
        self.ctx = moderngl.create_context()
        self.ctx.enable(moderngl.DEPTH_TEST)
        self.ctx.enable(moderngl.BLEND)

        # Initialize render objects
        for render_obj in self.render_objs:
            render_obj.initialize(self)

    def paintGL(self):
        # clear the entire window
        self.ctx.viewport = (0, 0, self.width()*self.devicePixelRatio(), self.height()*self.devicePixelRatio())
        self.ctx.clear(0, 0, 0, 1)

        # run each render action in sequence
        for render_action in self.render_actions:
            render_action()

        # finish rendering
        self.ctx.finish()
        self.update()


def run_headless(*register_funcs):
    # create the display and register the stimuli
    display = HeadlessDisplay()
    for register_func in register_funcs:
        register_func(display)

    # initialize and paint
    display.initializeGL()
    image = display.paintGL()

    # return image
    return image


def run_qt(*register_funcs):
    # create Qt application
    app = QtWidgets.QApplication([])

    # create test display and move to the right place
    display = QtTestDisplay()

    # register the stimuli
    for register_func in register_funcs:
        register_func(display)

    # run the application
    display.show()
    app.exec_()


def get_img_err(img1, img2):
    diff = np.array(img1) - np.array(img2)
    error = np.linalg.norm(diff.flatten())
    return error
