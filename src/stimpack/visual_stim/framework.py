import os
import sys

import time
import signal
from math import radians
import moderngl
import numpy as np
import pandas as pd
from skimage.transform import downscale_local_mean
from PyQt6 import QtWidgets, QtGui
from PyQt6.QtOpenGLWidgets import QOpenGLWidget

from stimpack.util import get_all_subclasses, ICON_PATH

from stimpack.visual_stim import stimuli
from stimpack.visual_stim import util
from stimpack.visual_stim.trajectory import make_as_trajectory, return_for_time_t

from stimpack.visual_stim.perspective import GenPerspective
from stimpack.visual_stim.square import SquareProgram
from stimpack.visual_stim.screen import Screen

from stimpack.rpc.transceiver import MySocketServer
from stimpack.rpc.util import get_kwargs

class StimDisplay(QOpenGLWidget):
    """
    Class that controls the stimulus display on one screen.  It contains the pyglet window object for that screen,
    and also controls rendering of the stimulus, toggling corner square, and/or debug information.
    """

    def __init__(self, screen, server, app):
        """
        Initialize the StimDisplay obect.

        :param screen: Screen object (from stimpack.visual_stim.screen) corresponding to the screen on which the stimulus will
        be displayed.
        """
        # call super constructor
        super().__init__()
        self.setFormat(make_qt_format(vsync=screen.vsync))

        self.setWindowTitle(f'Stimpack visual_stim screen: {screen.name}')
        self.setWindowIcon(QtGui.QIcon(ICON_PATH))

        # Set window size and position for fullscreen
        if screen.fullscreen:
            rect_screen = app.primaryScreen().geometry()
            self.move(rect_screen.left(), rect_screen.top())
            self.resize(rect_screen.width(), rect_screen.height())

        # stimulus initialization
        self.stim_list = []

        # stimulus state
        self.stim_started = False
        self.stim_start_time = None

        # profiling information
        self.profile_frame_times = []

        # save handles to screen and server
        self.screen = screen
        self.server = server
        self.app = app

        # Initialize stuff for rendering & saving stim frames
        self.stim_frames = []
        self.append_stim_frames = False
        self.pre_render = False
        self.current_time_index = None

        # Initalize stuff for saving position history
        self.save_pos_history = False
        self.save_pos_history_dir = None
        self.pos_history = []

        # make program for rendering the corner square
        self.square_program = SquareProgram(screen=screen)

        # initialize background color
        self.idle_background = (0.5, 0.5, 0.5, 1.0)
        
        # flag indicating whether to clear the viewports on the next paintGL call
        self.clear_viewports_flag = False

        # initialize subject state (e.g. position)
        self.subject_position = {}
        self.set_subject_state({'x': 0, 'y': 0, 'z': 0, 'theta': 0, 'phi': 0, 'roll': 0}) # meters and degrees

        self.use_subject_trajectory = False
        self.subject_x_trajectory = None
        self.subject_y_trajectory = None
        self.subject_theta_trajectory = None
        
        # imported stimuli module names
        self.imported_stim_module_names = []

    def initializeGL(self):
        # get OpenGL context
        self.ctx = moderngl.create_context() # TODO: can we make this run headless in render_movie_mode?
        self.ctx.enable(moderngl.BLEND) # enable alpha blending
        self.ctx.enable(moderngl.DEPTH_TEST) # enable depth test

        # Initialize attribute storage for the context
        self.ctx.extra = {}
        self.ctx.extra['n_textures_loaded'] = 0

        # clear the whole screen
        self.clear_viewports(color=(0, 0, 0, 1), viewports=None)

        # initialize square program
        self.square_program.initialize(self.ctx)

    def get_stim_time(self, t):
        stim_time = 0

        if self.stim_started:
            stim_time += t - self.stim_start_time

        return stim_time

    def clear_viewports(self, color=None, viewports=None):
        if color is None:
            color = self.idle_background
        assert len(color) == 4, 'ERROR: color must be a tuple of length 4 (RGBA)'
        
        if not isinstance(viewports, list):
            viewports = [viewports]
        
        for viewport in viewports:
            self.ctx.clear(red=color[0], green=color[1], blue=color[2], alpha=color[3], viewport=viewport)
        
        # doneCurrent() and makeCurrent() are necessary to allow painting over the cleared viewport
        self.doneCurrent()
        self.makeCurrent()

    def paintGL(self):
        # t0 = time.time() # benchmarking

        # quit if desired
        if self.server.shutdown_flag.is_set():
            self.app.quit()

        # handle RPC input
        self.server.process_queue()

        # get display size and set viewports
        display_width = self.width()*self.devicePixelRatio()
        display_height = self.height()*self.devicePixelRatio()

        self.subscreen_viewports = [sub.get_viewport(display_width, display_height) for sub in self.screen.subscreens]
        # Get viewport for corner square
        self.square_program.set_viewport(display_width, display_height)

        # clear the viewports if clear_viewports_flag is set, and reset the flag
        if self.clear_viewports_flag:
            self.clear_viewports(color=self.idle_background, viewports=self.subscreen_viewports)
            self.clear_viewports_flag = False
        
        # draw the stimulus
        if self.stim_list:
            if self.pre_render:
                if self.current_time_index < len(self.pre_render_timepoints):
                    t = self.pre_render_timepoints[self.current_time_index]
                else:
                    t = self.pre_render_timepoints[-1]
                    self.stop_stim()
            else:  # real-time generation
                t = time.time()
            if self.use_subject_trajectory:
                self.set_subject_state({'x': return_for_time_t(self.subject_x_trajectory, self.get_stim_time(t)),
                                        'y': return_for_time_t(self.subject_y_trajectory, self.get_stim_time(t)),
                                        'theta': return_for_time_t(self.subject_theta_trajectory, self.get_stim_time(t)) # deg -> radians
                                        })

            # For each subscreen associated with this screen: get the perspective matrix
            perspectives = [get_perspective(self.subject_position, x.pa, x.pb, x.pc, self.screen.horizontal_flip) for x in self.screen.subscreens]

            for stim in self.stim_list:
                if self.stim_started:
                    stim.paint_at(self.get_stim_time(t),
                                  self.subscreen_viewports,
                                  perspectives,
                                  subject_position=self.subject_position)
            self.profile_frame_times.append(t)

        # draw the corner square
        self.square_program.paint()

        # update the window
        self.ctx.finish()
        self.update()

        # clear the buffer objects
        for stim in self.stim_list:
            if self.stim_started:
                stim.vbo.release()
                stim.vao.release()

        if self.stim_started:
            # print('paintGL {:.2f} ms'.format((time.time()-t0)*1000)) #benchmarking

            if self.save_pos_history:
                self.pos_history.append([self.subject_position['x'], self.subject_position['y'], self.subject_position['z'], self.subject_position['theta'], self.subject_position['phi']])

            if self.append_stim_frames:
                # grab frame buffer, convert to array, grab blue channel, append to list of stim_frames
                self.stim_frames.append(util.qimage2ndarray(self.grabFrameBuffer())[:, :, 2])
                self.current_time_index += 1

    ###########################################
    # control functions
    ###########################################

    def set_subject_trajectory(self, x_trajectory, y_trajectory, theta_trajectory):
        """
        :param x_trajectory: meters, dict from Trajectory including time, value pairs
        :param y_trajectory: meters, dict from Trajectory including time, value pairs
        :param theta_trajectory: degrees on the azimuthal plane, dict from Trajectory including time, value pairs
        """
        self.use_subject_trajectory = True
        self.subject_x_trajectory = make_as_trajectory(x_trajectory)
        self.subject_y_trajectory = make_as_trajectory(y_trajectory)
        self.subject_theta_trajectory = make_as_trajectory(theta_trajectory)

    def load_stim(self, name, hold=False, **kwargs):
        """
        Load the stimulus with the given name, using the given params.

        After the stimulus is loaded, the background color is changed to the one specified in the stimulus, and the stimulus is evaluated at time 0.
        :param name: Name of the stimulus (should be a class name)
        """
        if hold is False:
            self.stim_list = []

        stim_classes = get_all_subclasses(stimuli.BaseProgram)
        stim_class_candidates = [x for x in stim_classes if x.__name__ == name]
        num_candidates = len(stim_class_candidates)
        
        assert num_candidates == 1, 'ERROR: {} stimulus candidates found with name {}. There should be exactly one'.format(num_candidates, name)

        chosen_stim_class = stim_class_candidates[0]
        stim = chosen_stim_class(screen=self.screen)
        stim.initialize(self.ctx)
        stim.kwargs = kwargs
        stim.configure(**stim.kwargs) # Configure stim on load
        self.stim_list.append(stim)
        
        # clear the viewports
        self.clear_viewports_flag = True

    def start_stim(self, t, append_stim_frames=False, pre_render=False, pre_render_timepoints=None):
        """
        Start the stimulus animation, using the given time as t=0.

        :param t: Time corresponding to t=0 of the animation
        :param append_stim_frames: bool, append frames to stim_frames list, for saving stim movie. May affect performance.
        """
        self.profile_frame_times = []
        self.stim_frames = []
        self.append_stim_frames = append_stim_frames
        self.pre_render = pre_render
        self.current_time_index = 0
        self.pre_render_timepoints = pre_render_timepoints

        if self.save_pos_history:
            self.pos_history = []

        self.stim_started = True
        if pre_render:
            self.stim_start_time = 0
        else:
            self.stim_start_time = t

    def stop_stim(self, print_profile=False):
        """
        Stops the stimulus animation and removes it from the display.
        """
        # clear texture
        self.ctx.clear_samplers()
        self.ctx.extra['n_textures_loaded'] = 0

        # clear the viewports
        self.clear_viewports_flag = True

        for stim in self.stim_list:
            stim.prog.release()
            stim.destroy()

        # print profiling information if applicable
        if (print_profile):
            # filter out frame times of duration zero
            fps_data = np.diff(np.array(self.profile_frame_times))
            fps_data = fps_data[fps_data != 0]

            if len(fps_data) > 0:
                fps_data = pd.Series(1.0/fps_data)
                stim_names = ', '.join([type(stim).__name__ for stim in self.stim_list])
                if print_profile:
                    print(f'*** {self.screen.name}: {stim_names} ***')
                    print(fps_data.describe(percentiles=[0.01, 0.05, 0.1, 0.9, 0.95, 0.99]))
                    print('*** end of statistics ***')


        # reset stim variables
        self.stim_list = []

        self.stim_started = False
        self.stim_start_time = None
        self.current_time_index = 0

        self.profile_frame_times = []

        self.use_subject_trajectory = False
        self.subject_x_trajectory = None
        self.subject_y_trajectory = None
        self.subject_theta_trajectory = None
        
        self.set_subject_state({'x': 0, 'y': 0, 'z': 0, 'theta': 0, 'phi': 0, 'roll': 0})
        self.perspective = get_perspective(self.subject_position, self.screen.subscreens[0].pa, self.screen.subscreens[0].pb, self.screen.subscreens[0].pc, self.screen.horizontal_flip)

    def save_rendered_movie(self, file_path, downsample_xy=4):
        """
        Save rendered stim frames from stim_frames as 3D np array
        Must be used with append_stim_frames in start_stim

        :param file_path: full file path of saved array
        """
        print('shape is {}'.format(len(self.stim_frames)))
        pre_size = np.stack(self.stim_frames, axis=2).shape
        mov = downscale_local_mean(np.stack(self.stim_frames, axis=2), factors=(downsample_xy, downsample_xy, 1)).astype('uint8')
        np.save(file_path, mov)
        print('Downsampled from {} to {} and saved to {}'.format(pre_size, mov.shape, file_path), flush=True)

    def set_save_pos_history_flag(self, flag=True):
        self.save_pos_history = flag
        
    def set_save_pos_history_dir(self, save_dir):
        self.save_pos_history_dir = os.path.join(save_dir, '_'.join(['screen', self.screen.name]))
        os.makedirs(self.save_pos_history_dir, exist_ok=True)

    def save_pos_history_to_file(self, epoch_id):
        '''
        Save the position history for the stim to a text file.
        '''
        if self.save_pos_history_dir is not None:
            file_path = os.path.join(self.save_pos_history_dir, '_'.join(['epoch', epoch_id])+'.out')
            np.savetxt(file_path, np.asarray(self.pos_history))

    def corner_square_toggle_start(self):
        """
        Start toggling the corner square.
        """

        self.square_program.toggle_start()

    def corner_square_toggle_stop(self):
        """
        Stop toggling the corner square.
        """

        self.square_program.toggle_stop()

    def corner_square_on(self):
        """
        Stop the corner square from toggling, then make it white.
        """

        self.square_program.turn_on()

    def corner_square_off(self):
        """
        Stop the corner square from toggling, then make it black.
        """

        self.square_program.turn_off()

    def set_corner_square(self, color):
        """
        Stop the corner square from toggling, then set it to the desired color.
        """

        self.corner_square_toggle_stop()
        self.square_program.color = color

    def show_corner_square(self):
        """
        Show the corner square.
        """

        self.square_program.draw = True

    def hide_corner_square(self):
        """
        Hide the corner square.  Note that it will continue to toggle if self.should_toggle_square is True,
        even though nothing will be displayed.
        """

        self.square_program.draw = False

    def set_idle_background(self, color):
        """
        Sets the (monochrome, RGB, or RGBA) color of the background when there is no stimulus being displayed 
        (sometimes called the interleave period).
        """
        self.idle_background = util.get_rgba(color)

    def set_subject_state(self, state_update):
        # Update the subject state (only position for this module)
        for k,v in state_update.items():
            if k in ['x', 'y', 'z', 'theta', 'phi', 'roll']:
                self.subject_position[k] = float(v)
        
    def import_stim_module(self, path):
        # Load other stim modules from paths containing subclasses of stimpack.visual_stim.stimuli.BaseProgram
        barcode = util.generate_lowercase_barcode(length=10, existing_barcodes=self.imported_stim_module_names)
        util.load_stim_module_from_path(path, barcode)
        self.imported_stim_module_names.append(barcode)
        print(f'Loaded stim module from {path} with key {barcode}')
        
def get_perspective(subject_pos, pa, pb, pc, horizontal_flip):
    """
    :param subject_pos: {'x', 'y', 'z', 'theta', 'phi', 'roll'}
        - x, y, z = position of subject, meters
        - theta = heading angle along azimuth, degrees
        - phi = heading angle along elevation, degrees
        - roll = roll angle, degrees
    :params (pa, pb, pc): xyz coordinates of screen corners, meters
    :param horizontal_flip: Boolean, apply horizontal flip to image, for rear-projection displays
    """
    x, y, z = subject_pos['x'], subject_pos['y'], subject_pos['z']
    perspective = GenPerspective(pa=pa, pb=pb, pc=pc, 
                                 subject_xyz=(x,y,z), 
                                 horizontal_flip=horizontal_flip)

    """
    With (theta, phi, roll) = (0, 0, 0): subject looks down +y axis, +x is to the right, and +z is above the subject's head
        +theta rotates view ccw around z axis / -theta is cw around z axis (looking down at xy plane)
        +phi tilts subject view up towards the sky (+z) / -phi tilts down towards the ground (-z)
        +roll rotates subject view cw around y axis / -roll rotates ccw around y axis

    theta = yaw around z
    phi = pitch around x
    roll = roll around y

    """
    theta, phi, roll = subject_pos['theta'], subject_pos['phi'], subject_pos.get('roll', 0)
    return perspective.rotz(radians(theta)).rotx(radians(phi)).roty(radians(roll)).matrix


def make_qt_format(vsync):
    """
    Initializes the Qt OpenGL format.
    :param vsync: If True, use VSYNC, otherwise update as fast as possible
    """

    # create format with default settings
    format = QtGui.QSurfaceFormat()

    # use OpenGL 3.3
    format.setVersion(3, 3)
    format.setProfile(QtGui.QSurfaceFormat.OpenGLContextProfile.CoreProfile)

    # use VSYNC
    if vsync:
        format.setSwapInterval(1)
    else:
        format.setSwapInterval(0)

    # TODO: determine what these lines do and whether they are necessary
    format.setSamples(24)
    format.setDepthBufferSize(24)

    # needed to enable transparency
    format.setAlphaBufferSize(24)

    return format


def main():
    # get the configuration parameters
    kwargs = get_kwargs()

    # get the screen
    screen = Screen.deserialize(kwargs.get('screen', {}))

    # launch the server
    server = MySocketServer(host=kwargs['host'], port=kwargs['port'], threaded=True, auto_stop=True, name=screen.name)

    # set default format with OpenGL context
    format = QtGui.QSurfaceFormat()
    format.setVersion(3, 3)
    format.setProfile(QtGui.QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    QtGui.QSurfaceFormat.setDefaultFormat(format)

    # launch application
    app = QtWidgets.QApplication([])
    app.setWindowIcon(QtGui.QIcon(ICON_PATH))
    app.setApplicationName('Stimpack visual_stim screen: {screen.name}')

    # create the StimDisplay object
    screen = Screen.deserialize(kwargs.get('screen', {}))
    stim_display = StimDisplay(screen=screen, server=server, app=app)

    # register functions
    server.register_function(stim_display.set_subject_trajectory)
    server.register_function(stim_display.load_stim)
    server.register_function(stim_display.start_stim)
    server.register_function(stim_display.stop_stim)
    server.register_function(stim_display.save_rendered_movie)
    server.register_function(stim_display.corner_square_toggle_start)
    server.register_function(stim_display.corner_square_toggle_stop)
    server.register_function(stim_display.corner_square_on)
    server.register_function(stim_display.corner_square_off)
    server.register_function(stim_display.set_corner_square)
    server.register_function(stim_display.show_corner_square)
    server.register_function(stim_display.hide_corner_square)
    server.register_function(stim_display.set_idle_background)
    server.register_function(stim_display.set_subject_state)
    server.register_function(stim_display.set_save_pos_history_flag)
    server.register_function(stim_display.set_save_pos_history_dir)
    server.register_function(stim_display.save_pos_history_to_file)
    server.register_function(stim_display.import_stim_module)
    
    # Load other stimuli from paths given in kwargs.
    # These modules contain subclasses of stimpack.visual_stim.stimuli.BaseProgram
    other_stim_module_paths = kwargs.get('other_stim_module_paths', [])
    for stim_module_path in other_stim_module_paths:
        stim_display.import_stim_module(stim_module_path)

    # display the stimulus
    if screen.fullscreen:
        stim_display.showFullScreen()
    else:
        stim_display.show()

    ####################################
    # Run QApplication
    ####################################

    # Use Ctrl+C to exit.
    # ref: https://stackoverflow.com/questions/2300401/qapplication-how-to-shutdown-gracefully-on-ctrl-c
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
