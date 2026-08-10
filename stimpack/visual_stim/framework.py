"""
The screen subprocess: a Qt window holding a GL context, driven over RPC.

:class:`StimDisplay` is one screen. Its ``paintGL`` is the heartbeat -- it drains the RPC queue,
evaluates every loaded stimulus at the current time, draws it once per subscreen through that
subscreen's perspective matrix, and finally draws the corner square used as a photodiode timing
signal.

Because the queue is drained in ``paintGL``, a screen whose render loop has stopped still accepts
every command and does nothing with it. ``report_frame_count`` is how a client tells those two
states apart.
"""
import os
import sys
import warnings

import time
import signal
from math import radians
import moderngl

import numpy as np
import pandas as pd
from skimage.transform import downscale_local_mean
from PyQt6 import QtCore, QtWidgets, QtGui
from PyQt6.QtOpenGLWidgets import QOpenGLWidget

from stimpack.util import get_all_subclasses, ICON_PATH

from stimpack.visual_stim import stimuli
from stimpack.visual_stim import util
from stimpack.visual_stim.trajectory import make_as_trajectory, return_for_time_t

from stimpack.visual_stim.perspective import GenPerspective
from stimpack.visual_stim.square import SquareProgram
from stimpack.visual_stim.calibration import CalibrationSpot
from stimpack.visual_stim.screen import Screen
from stimpack.visual_stim.curved_screen import CurvedScreen

from stimpack.rpc.transceiver import MySocketServer
from stimpack.rpc.util import get_kwargs

# Names a screen subprocess answers to, i.e. what target('visual') can call.
#
# Fixed in this source rather than discovered at runtime: main() registers exactly these, and
# VisualStimServer advertises them so a protocol can ask has_server_function(..., target='visual')
# without a round trip to a subprocess it cannot query. A test asserts every name is a real
# StimDisplay method, so the list cannot rot.
SCREEN_FUNCTION_NAMES = (
    'set_subject_trajectory',
    'load_stim',
    'start_stim',
    'stop_stim',
    'update_stim',
    'clear_profile',
    'print_profile',
    'save_rendered_movie',
    'corner_square_toggle_start',
    'corner_square_toggle_stop',
    'corner_square_on',
    'corner_square_off',
    'set_corner_square',
    'show_corner_square',
    'hide_corner_square',
    'set_idle_background',
    'set_subject_state',
    'set_save_pos_history_flag',
    'set_save_pos_history_dir',
    'save_pos_history_to_file',
    'import_stim_module',
    'unload_stim_module',
    'report_frame_count',
    'set_subframes',
    'show_calibration_spot',
    'hide_calibration_spot',
)


class StimDisplay(QOpenGLWidget):
    """
    Class that controls the stimulus display on one screen.  It contains the pyglet window object for that screen,
    and also controls rendering of the stimulus, toggling corner square, and/or debug information.
    """

    def __init__(self, screen, server, app, debug=False):
        """
        Initialize the StimDisplay obect.

        :param screen: Screen object (from stimpack.visual_stim.screen) corresponding to the screen on which the stimulus will
        be displayed.
        """
        # call super constructor
        super().__init__()
        self.setFormat(make_qt_format(vsync=screen.vsync))

        self.setWindowTitle(f'Stimpack visual_stim screen: {screen.name}' + (" (EGL)" if screen.use_egl else ""))
        self.setWindowIcon(QtGui.QIcon(ICON_PATH))

        self.debug = debug
        if self.debug:
            print('Debug mode enabled')

        # Get the correct QScreen object for the display hardware
        qscreens = app.screens()
        if len(qscreens) == 0:
            raise ValueError('ERROR: No screens detected.')
        elif len(qscreens) == 1: 
            # If only one screen is detected, use that screen
            qscreen = qscreens[0]
        else:
            # If multiple screens are detected, index the screen with screen.display_index
            assert len(qscreens) > screen.display_index, f'ERROR: Display index ({screen.display_index}) must be less than # of screens ({len(qscreens)} detected).'
            qscreen = qscreens[screen.display_index]

        # The video link rate, which decides how far apart in time the subframes are. Taken from
        # the display rather than from configuration: it is a number the system already knows, and
        # one an experimenter can get wrong. An explicitly configured value still wins, but says so
        # when it disagrees -- a config claiming 120 on a 60 Hz link gives subtly wrong timing and
        # no error.
        reported = qscreen.refreshRate()
        if screen.refresh_rate is None:
            screen.refresh_rate = reported
        elif reported and abs(screen.refresh_rate - reported) > 1.0:
            warnings.warn(f'Screen {screen.name}: configured refresh_rate '
                          f'{screen.refresh_rate} Hz, but the display reports {reported} Hz. '
                          f'Subframe timing follows the configured value.')

        if screen.fullscreen:
            screen_geometry = qscreen.geometry() # Get hardware display size
            self.move(screen_geometry.left(), screen_geometry.top())
            # Explicitly resize to device size because sometimes self.width/height stays at default
            self.resize(screen_geometry.width(), screen_geometry.height())
        else:
            screen_geometry = qscreen.availableGeometry() # Get available display size
            self.move(screen_geometry.left(), screen_geometry.top())

            # Set window size such that neither heignt nor width exceeds half that of the display, 
            #   while maintaining aspect ratio
            window_aspect_ratio = screen.width / screen.height
            display_aspect_ratio = screen_geometry.width() / screen_geometry.height()

            # Maximum allowed size (half of the display's size)
            max_window_width = screen_geometry.width() // 2
            max_window_height = screen_geometry.height() // 2

            # Determine the scaling factor based on aspect ratios and maximum allowed dimensions
            if window_aspect_ratio > display_aspect_ratio:
                # Window is wider in aspect than the display. Width is the constraining dimension.
                window_width = max_window_width
                window_height = int(window_width / window_aspect_ratio)
            else:
                # Window is taller in aspect than the display, or both have the same aspect ratio. Height is the constraining dimension.
                window_height = max_window_height
                window_width = int(window_height * window_aspect_ratio)

            # Set window size
            self.resize(window_width, window_height)

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
        self.calibration_spot = CalibrationSpot()

        # initialize background color
        self.idle_background = (0.5, 0.5, 0.5, 1.0)
        
        # initialize subject state (e.g. position)
        self.subject_position = {}
        self.set_subject_state({'x': 0, 'y': 0, 'z': 0, 'theta': 0, 'phi': 0, 'roll': 0}) # meters and degrees

        self.use_subject_trajectory = False
        self.subject_x_trajectory = None
        self.subject_y_trajectory = None
        self.subject_theta_trajectory = None
        
        # Imported stimulus modules, and the class registry load_stim resolves against.
        #
        # Resolution used to be a scan of BaseProgram.__subclasses__(), which is process-global,
        # keyed only by class name, and cannot be pruned: a class stays registered for as long as
        # anything references it, and a loaded stimulus instance does. Re-importing the same module
        # -- which every client does on connect -- therefore produced two classes of the same name
        # and load_stim refused to choose. An explicit registry makes the choice ours.
        self.imported_stim_module_names = []          # barcodes, in import order
        self.imported_stim_module_paths = {}          # barcode -> the path it came from
        self.imported_stim_module_classes = {}        # barcode -> {class name: class}
        self.stim_classes = {}                        # name -> class; later imports shadow earlier
        self._rebuild_stim_registry()

    def show_calibration_spot(self, ndc_x, ndc_y, radius=0.05, intensity=1.0):
        """Put a spot at a known place in the projector image, on an otherwise black screen.

        For measuring the rig's brightness falloff: aim a photometer at it from where the animal
        sits. See stimpack.visual_stim.calibration, which also picks where to put them.
        """
        self.calibration_spot.show(ndc_x, ndc_y, radius=radius, intensity=intensity)

    def hide_calibration_spot(self):
        self.calibration_spot.hide()

    def report_frame_count(self):
        """Push this screen's rendered-frame count back to the client.

        The RPC link is fire-and-forget, so a client has no way to ask a screen anything -- it can
        only send. That makes "is this screen actually rendering?" unanswerable from the client, and
        it is exactly the question that matters when a screen stops: paintGL is what drains the RPC
        queue, so a screen whose render loop has died accepts every command and silently does
        nothing. Reported over the same channel screen errors use.
        """
        reporter = getattr(self.server, 'error_reporter', None)
        if reporter is not None:
            reporter('info', f'frame_count={self.frame_count}')

    def set_subframes(self, subframes, refresh_rate=None, channel_order=None):
        """Change how many subframes a frame carries, between trials.

        Takes effect on the next frame: paintGL asks the screen for its masks and interval every
        frame and caches neither, so there is no framebuffer to resize and no GL state to reset.

        Refused while a stimulus is running. Changing part-way through would leave some frames of a
        trial carrying one timepoint and some three, which nothing downstream reports and no
        analysis could recover. Under multiplexing each color channel is a slice of time rather
        than a color, so a loaded color stimulus would also be silently reinterpreted.

        This changes stimpack's half only. The projector has to be told the matching pattern count
        separately -- stimpack cannot see it -- so a labpack wanting to switch at run time should
        register one function that does both, in the manner of set_dlpc_current. Pass that function
        one permutation and let it derive the projector's half with screen.channel_names, rather
        than writing the order out twice in two vocabularies.
        """
        if self.stim_started:
            raise RuntimeError('cannot change subframes while a stimulus is running: the trial '
                               'would carry two different temporal structures')
        self.screen.set_subframes(subframes, refresh_rate=refresh_rate,
                                  channel_order=channel_order)
        self.report_subframe_mode()

    def report_subframe_mode(self):
        """Say whether this screen is multiplexing, and at what rate.

        Printed because it is a claim about hardware that software cannot check. subframes=3 packs
        three timepoints into the color channels for a projector configured to unpack them; if the
        projector is in ordinary video mode instead, the result is a plausible-looking color image
        rather than an error. Saying it out loud at start-up is the only warning available, and it
        is what a commissioning run (see SubframeTimingCheck) is checked against.
        """
        if self.screen.subframes <= 1:
            print(f'Screen {self.screen.name}: 1 subframe per frame (ordinary rendering)')
            return
        order = ''.join(name[0].upper() for name in self.screen.subframe_channel_names())
        print(f'Screen {self.screen.name}: {self.screen.subframes} subframes per frame, '
              f'channel order {order}, {self.screen.refresh_rate} Hz video -> '
              f'{self.screen.refresh_rate * self.screen.subframes} Hz')
        print(f'Screen {self.screen.name}: this assumes the projector is in a matching pattern '
              f'mode -- stimpack cannot verify it. Check with SubframeTimingCheck.')

    def report_surface_format(self):
        """Say what the GL surface actually granted, next to what make_qt_format asked for.

        A driver silently downgrades a surface format it cannot provide, so a request is not a
        setting. Print requested and granted side by side so the difference is visible rather than
        assumed -- this is how the alpha channel that made stimuli see-through on Mesa, and not on
        NVIDIA/XWayland, was found.

        make_qt_format used to ask for 24 samples here too and was granted 0 on every GPU measured,
        because QOpenGLWidget renders into its own FBO where the surface sample count does not
        apply. That request has been removed rather than left as a claim the code cannot deliver;
        samples is still reported, so a driver that grants some anyway would show up.
        """
        try:
            granted = self.context().format()
        except Exception:
            return                                    # not a QOpenGLWidget (render-movie / EGL path)

        requested = make_qt_format(self.screen.vsync)
        for label, want, got in (('samples', requested.samples(), granted.samples()),
                                 ('alpha bits', requested.alphaBufferSize(), granted.alphaBufferSize()),
                                 ('depth bits', requested.depthBufferSize(), granted.depthBufferSize())):
            # -1 is Qt's "unset": nothing was requested, so nothing can have been denied.
            if want < 0:
                print(f'OpenGL {label}: not requested, got {got}')
            elif want == got:
                print(f'OpenGL {label}: requested {want}, got {got}')
            elif got > want:
                # More than asked for is not a denial -- but for alpha it is the one that bites:
                # a compositor can see through whatever alpha the driver granted unasked. paintGL
                # scrubs alpha to 1 at the end of every frame on exactly this condition.
                print(f'OpenGL {label}: requested {want}, got {got}   <-- more than requested')
            else:
                print(f'OpenGL {label}: requested {want}, got {got}   <-- not granted')

    def initializeGL(self):
         # get OpenGL context
        if self.screen.use_egl:
            # Get EGL context with PyOpenGL then hand it over to moderngl
            from OpenGL import EGL, GL

            def create_egl_context():
                # Get an EGL display connection
                display = EGL.eglGetDisplay(EGL.EGL_DEFAULT_DISPLAY)
                if display == EGL.EGL_NO_DISPLAY:
                    raise RuntimeError("Failed to get EGL display")

                # Initialize the EGL display connection
                major, minor = EGL.EGLint(), EGL.EGLint()
                if not EGL.eglInitialize(display, major, minor):
                    raise RuntimeError("Unable to initialize EGL")
                
                # Specify the minimum configuration attributes
                config_attribs = [
                    EGL.EGL_SURFACE_TYPE, EGL.EGL_PBUFFER_BIT,
                    EGL.EGL_BLUE_SIZE, 8,
                    EGL.EGL_GREEN_SIZE, 8,
                    EGL.EGL_RED_SIZE, 8,
                    EGL.EGL_ALPHA_SIZE, 24,
                    EGL.EGL_DEPTH_SIZE, 24,
                    EGL.EGL_RENDERABLE_TYPE, EGL.EGL_OPENGL_BIT,
                    EGL.EGL_NONE
                ]
                config_attribs = (EGL.EGLint * len(config_attribs))(*config_attribs)

                # Choose a configuration
                num_configs = EGL.EGLint()
                config = EGL.EGLConfig()
                if not EGL.eglChooseConfig(display, config_attribs, config, 1, num_configs):
                    raise RuntimeError("Failed to choose config")

                # Context attributes for specifying OpenGL version
                context_attribs = [
                    EGL.EGL_CONTEXT_MAJOR_VERSION, 3,
                    EGL.EGL_CONTEXT_MINOR_VERSION, 3,
                    EGL.EGL_CONTEXT_OPENGL_PROFILE_MASK, EGL.EGL_CONTEXT_OPENGL_CORE_PROFILE_BIT,
                    EGL.EGL_NONE
                ]
                context_attribs = (EGL.EGLint * len(context_attribs))(*context_attribs)

                # Create an EGL context
                ctx = EGL.eglCreateContext(display, config, EGL.EGL_NO_CONTEXT, context_attribs)
                if ctx == EGL.EGL_NO_CONTEXT:
                    raise RuntimeError("Failed to create EGL context")
                
                GL.glEnable(GL.GL_DEPTH_TEST)         # Enable depth testing
                GL.glDepthFunc(GL.GL_LESS)            # Specify depth comparison function

                return display, ctx, config

            display, ctx, config = create_egl_context()

            # Make the context current
            if not EGL.eglMakeCurrent(display, EGL.EGL_NO_SURFACE, EGL.EGL_NO_SURFACE, ctx):
                raise RuntimeError("Failed to make the EGL context current")

            # Grab the EGL context with moderngl
            self.ctx = moderngl.get_context()
        
        else: 
            # Use moderngl context creation
            self.ctx = moderngl.create_context(require=330) # TODO: can we make this run headless in render_movie_mode?

        print(f"OpenGL version: {self.ctx.info['GL_VERSION']}")
        print(f"OpenGL vendor: {self.ctx.info['GL_VENDOR']}")
        print(f"OpenGL renderer: {self.ctx.info['GL_RENDERER']}")
        self.report_surface_format()
        self.report_subframe_mode()

        self.ctx.enable(moderngl.BLEND) # enable alpha blending
        self.ctx.enable(moderngl.DEPTH_TEST) # enable depth test

        # Blend colour normally, but never let alpha be blended DOWN. The default blend function
        # applies (SRC_ALPHA, ONE_MINUS_SRC_ALPHA) to all four channels, so an analytic edge with
        # coverage a leaves the framebuffer at a*a + (1-a)*1, which is 0.75 at a = 0.5. On a
        # compositing window manager that is a hole: the desktop behind the window shows through
        # the rim of every stimulus. Measured before this line existed, a 15-degree MovingSpot left
        # 228 pixels below full opacity.
        #
        # dst_a = 1*src_a + (1-src_a)*dst_a, so a framebuffer cleared opaque stays opaque exactly,
        # while one cleared transparent still accumulates coverage correctly. Colour is untouched:
        # the rendered image is byte-identical either way, anti-aliased edges included.
        self.ctx.blend_func = (moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA,
                               moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA)

        # Keep sRGB encoding off, so what a shader writes is what lands in the framebuffer. The
        # default framebuffer here IS sRGB-capable (measured: its color encoding reports GL_SRGB),
        # so the enable bit genuinely matters -- it just happens to default to off.
        #
        # disable_direct, not disable. ctx.disable() takes moderngl's own flag bitmask, not a raw
        # GL enum: GL_FRAMEBUFFER_SRGB is 0x8DB9 = 36281, and 36281 & moderngl.BLEND == 1, so
        # ctx.disable(0x8DB9) was read as "disable BLEND" and switched off alpha blending on the
        # line after it was switched on -- while leaving sRGB untouched. Every stimulus with
        # alpha < 1 composited wrongly from 2026-05-18 until this was fixed. It went unnoticed
        # because alpha = 1 renders identically either way (src*1 + dst*0 == src).
        #
        # tests/gl/test_render_smoke.py asserts the resulting GL state; a rendered-image test
        # cannot catch this.
        GL_FRAMEBUFFER_SRGB = 0x8DB9
        self.ctx.disable_direct(GL_FRAMEBUFFER_SRGB)

        # Initialize attribute storage for the context
        self.ctx.extra = {}

        # Whether the window surface ended up with an alpha channel, requested or not. Decided by
        # what was GRANTED, not what was asked for -- see the scrub in paintGL. Outside a Qt window
        # (offscreen render paths) there is no compositor and nothing to scrub for.
        try:
            self._surface_has_alpha = self.context().format().alphaBufferSize() > 0
        except Exception:
            self._surface_has_alpha = False

        # A curved screen renders through a cube map instead of one frustum per flat subscreen.
        self.cube_renderer = None
        if isinstance(self.screen, CurvedScreen):
            from stimpack.visual_stim.cubemap import CubeMapRenderer
            mesh = self.screen.build_mesh()
            self.cube_renderer = CubeMapRenderer(self.ctx, mesh,
                                                 resolution=self.screen.cube_resolution,
                                                 orientation=self.screen.resolve_cube_orientation(mesh))
            coverage = mesh.coverage()
            print(f'Curved screen: {mesh.n_triangles} triangles, '
                  f'{coverage["fraction"]:.0%} of the surface lit by the projector')

        # clear the whole screen
        # self.clear_viewports(color=(0, 0, 0, 1), viewports=None)
        self.ctx.fbo.clear(0, 0, 0, 1)

        # initialize square program
        self.square_program.initialize(self.ctx)
        self.calibration_spot.initialize(
            self.ctx, aspect_ratio=getattr(self.screen, 'projector', None)
            and self.screen.projector.aspect_ratio or 1.0)

        self.frame_count = 0

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
            self.ctx.fbo.clear(red=color[0], green=color[1], blue=color[2], alpha=color[3], viewport=viewport)
        
    def paint_through_cube_map(self, stim_time, display_width, display_height):
        """Draw the scene into a cube map, then warp it onto the curved screen.

        Both passes happen inside this one frame, deliberately. Rendering the cube on one frame and
        warping it on the next would be easier to arrange and would add a whole frame of latency to
        the closed loop -- 8 to 16 ms, against the ~0.3 ms the passes themselves cost. That is the
        only part of this worth being careful about performance-wise.
        """
        from stimpack.visual_stim.cubemap import face_matrices

        renderer = self.cube_renderer
        matrices = face_matrices(self.subject_position, orientation=renderer.orientation)
        face_viewport = [(0, 0, renderer.resolution, renderer.resolution)]

        # Grab the display framebuffer now, before the face loop rebinds anything. It cannot be
        # recovered afterwards: ctx.detect_framebuffer() with no argument reports whatever is bound
        # at the moment it is called, which by the end of the loop is the last cube face -- so the
        # warp went into a cube face, the display kept the black it had been cleared to, and so did
        # everything drawn after this (the photodiode square, the calibration spot). Nor is the
        # display glo 0: a QOpenGLWidget renders into a framebuffer of its own.
        #
        # ctx.fbo rather than a fresh detect_framebuffer of the same glo, because this is the very
        # object paintGL set color_mask on for this subframe, and moderngl re-applies a
        # framebuffer's stored mask on use(). A fresh wrapper carries the default all-channels mask
        # and would quietly undo subframe multiplexing.
        display_fbo = self.ctx.fbo

        # Only the faces the screen samples. A bowl above the animal never looks down, so -Z would
        # be a whole scene draw feeding a face nothing reads.
        #
        # The first face drawn prepares each stimulus -- evaluates it and uploads its geometry --
        # and the rest only draw. The planar path gets that for free by handing paint_at every
        # subscreen in one call; here each face needs its own framebuffer bound, so paint_at is
        # called per face, and it used to redo both every time.
        #
        # Evaluation must be once per frame because a stimulus is entitled to that: stateful ones
        # advance N times too fast otherwise, and it is luck whether that shows. One integrating
        # (t - t_prev) sees zero elapsed the second time; one testing t % period against
        # t_prev % period fires again, since those are equal after the first call. A labpack dot
        # field popping one refresh time per evaluation exhausted its schedule and raised
        # IndexError mid-trial.
        #
        # Upload wants to be once per frame because it is the expensive part and the geometry does
        # not differ between faces -- only the matrix does. Hoisting it out is what keeps the cube
        # pass from scaling with face count in vertices as well as in draw calls.
        for order, face in enumerate(renderer.face_indices):
            matrix = matrices[face]
            renderer.use_face(face, clear_color=self.idle_background)
            if not self.stim_started:
                continue
            self.draw_stimuli(stim_time, face_viewport, [matrix], prepare=(order == 0),
                              framebuffer=renderer.face_framebuffer(face))

        # Back to the display, then the screen mesh in one draw call. No horizontal flip here even
        # for a rear-projected screen: the mesh already says where each direction lands on the
        # projector, worked out from the physical geometry, so the handedness is built in.
        display_fbo.use()
        self.ctx.viewport = (0, 0, display_width, display_height)
        renderer.render_warp()

    def paintGL(self):
        # t0 = time.time() # benchmarking
        self.frame_count += 1

        # Qt uses this GL context between paintGL calls (QOpenGLWidget composits through it) and
        # documents that state is NOT preserved -- and moderngl cannot know what Qt changed, so
        # setting state once in initializeGL is setting it for the first frame only. Re-assert
        # everything the render depends on, every frame.
        self.ctx.enable(moderngl.BLEND)
        self.ctx.enable(moderngl.DEPTH_TEST)
        self.ctx.blend_func = (moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA,
                               moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA)

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

        target = self.ctx.detect_framebuffer()
        framebuffer = self.multisample_framebuffer(display_width, display_height) or target
        framebuffer.use()

        # One pass per subframe. With subframes=1 this runs once with every channel writable, which
        # is ordinary rendering; with 3 it draws three timepoints, each masked into one color
        # channel, for a projector that reads them back as successive patterns. glClear respects the
        # write mask, so each pass clears only its own channel -- the other two keep what the earlier
        # passes put there.
        masks = self.screen.subframe_color_masks()
        interval = self.screen.subframe_interval
        for subframe, mask in enumerate(masks):
            framebuffer.color_mask = mask
            self.paint_subframe(subframe * interval, display_width, display_height)
        framebuffer.color_mask = (True, True, True, True)

        if framebuffer is not target:
            # Resolve the samples down into the widget's own framebuffer. Everything after this --
            # grabFramebuffer, the photodiode square, presentation -- sees an ordinary image.
            self.ctx.copy_framebuffer(target, framebuffer)
            target.use()

        # Force the frame opaque, whatever was drawn into it. The separate alpha blend above keeps
        # coverage from thinning the framebuffer, but it only governs OUR draws -- and the surface
        # can have an alpha channel whether we want one or not (measured: Mesa grants 8 bits
        # against a request for 0; macOS and NVIDIA/XWayland grant the 0 requested, and skip
        # this block entirely; see report_surface_format). A compositor composites the window with
        # whatever alpha is left here, so the only guarantee that holds everywhere is written after
        # the last draw: clear alpha to 1 with the color channels masked off. glClear respects the
        # write mask, as the subframe passes above already rely on.
        #
        # Only where it can matter, because it is not free: a color-masked clear takes a slow path
        # on Mesa, measured at 0.49 ms per 1920x1080 frame against 0.09 for an unmasked clear (the
        # per-frame state re-assert above is measurement-noise free). A surface with no alpha
        # channel gives a compositor nothing to read, so those rigs skip the cost entirely.
        if self._surface_has_alpha:
            target.color_mask = (False, False, False, True)
            target.clear(0.0, 0.0, 0.0, 1.0)
            target.color_mask = (True, True, True, True)

        # Once per displayed frame, not per subframe: presenting, capturing and logging all describe
        # the frame the display will actually show, which is the packed one.
        if self.debug:
            error = self.ctx.error
            if error != 'GL_NO_ERROR' and self.frame_count < 5:
                print(f'{self.frame_count} OpenGL Error: {error}')

        # update the window
        self.ctx.finish()
        self.update()

        if self.stim_started:
            # print('paintGL {:.2f} ms'.format((time.time()-t0)*1000)) #benchmarking

            if self.save_pos_history:
                self.pos_history.append([self.subject_position['x'], self.subject_position['y'], self.subject_position['z'], self.subject_position['theta'], self.subject_position['phi']])

            if self.append_stim_frames:
                # NOTE: with subframes > 1 this captures the packed frame, in which each channel is
                # a different moment -- not one image. Taking the blue channel gives whichever
                # subframe landed there, which is a third of the frames at a third of the rate.
                self.stim_frames.append(util.qimage2ndarray(self.grabFramebuffer())[:, :, 2])
                self.current_time_index += 1

    def multisample_framebuffer(self, width, height):
        """A multisampled framebuffer to draw this frame into, or None to draw straight to the widget.

        Kept and reused across frames, and rebuilt only when the display size changes -- allocating
        a multisampled color and depth buffer every frame would cost far more than the sampling.

        Returns None when the screen asks for no multisampling, which is the default, so the
        ordinary path is unchanged: same framebuffer, same draws, no copy.
        """
        samples = getattr(self.screen, 'msaa_samples', 0)
        if not samples:
            return None

        want = (int(width), int(height), int(samples))
        if getattr(self, '_msaa_key', None) != want:
            self._msaa_fbo = self.ctx.framebuffer(
                color_attachments=[self.ctx.renderbuffer((want[0], want[1]), samples=want[2])],
                depth_attachment=self.ctx.depth_renderbuffer((want[0], want[1]), samples=want[2]))
            self._msaa_key = want
            granted = self._msaa_fbo.color_attachments[0].samples
            if granted != samples:
                print(f'Screen {self.screen.name}: asked for {samples}x multisampling, '
                      f'the driver granted {granted}x.')
        return self._msaa_fbo

    def draw_stimuli(self, stim_time, viewports, perspectives, prepare=True, framebuffer=None):
        """Draw every loaded stimulus, in one pass or split into opaque and blended ones.

        The split is what makes blending stop depending on draw order. Blending against a depth
        buffer is order-dependent: a partly covered fragment still writes depth as though it were
        opaque, so whatever is behind it is rejected and it blends against the background instead.
        Drawing all the opaque fragments first, then the blended ones with depth writes off, fixes
        that -- the far surface is already in the color buffer when the near edge blends over it,
        and the edge no longer hides anything.

        It has to be all stimuli, not each stimulus in turn: interleaving them would put one
        stimulus's edges down before the next stimulus's interior, which is the same bug again.

        What it does not fix is two blended fragments overlapping each other; both are in the second
        pass, neither writes depth, and they still composite in order. Measured on 100 overlapping
        dots, reversing the draw order moved 3519 pixels in one pass and 22 in two.

        :param framebuffer: whose depth mask to toggle. The cube path draws into a face's
            framebuffer rather than the one paintGL bound, and toggling the wrong one silently
            leaves depth writes on for the blended pass, which is the unsplit behavior again.
        """
        if not self.screen.split_blended_pass:
            for stim in self.stim_list:
                stim.paint_at(stim_time, viewports, perspectives,
                              subject_position=self.subject_position, prepare=prepare)
            return

        for stim in self.stim_list:
            stim.paint_at(stim_time, viewports, perspectives,
                          subject_position=self.subject_position, prepare=prepare, pass_kind=1)

        # Which stimuli can contribute to the blended pass at all. Asked after the opaque pass,
        # because it reads the shape eval_at built and that is where evaluation happens.
        #
        # Worth asking: the second pass is not free even when it draws nothing. It still rasterizes
        # everything and runs the fragment shader up to the discard, once per cube face -- a
        # full-field grating, entirely opaque, paid 0.70 ms on the curved path for a pass with no
        # output. Skipping the stimuli that cannot blend takes that back.
        blended = [stim for stim in self.stim_list
                   if getattr(stim, 'may_blend', None) is None or stim.may_blend()]
        if not blended:
            return

        target = framebuffer if framebuffer is not None else self.ctx.fbo
        target.depth_mask = False
        try:
            for stim in blended:
                # prepare=False always: the opaque pass above has already evaluated and uploaded
                # this frame, and evaluating again would advance a stateful stimulus twice.
                stim.paint_at(stim_time, viewports, perspectives,
                              subject_position=self.subject_position, prepare=False, pass_kind=2)
        finally:
            target.depth_mask = True

    def paint_subframe(self, time_offset, display_width, display_height):
        """Draw one timepoint into whichever channels are currently writable.

        time_offset is how far into the future this subframe will be shown: 0 for ordinary
        rendering, and 0, 1/360, 2/360 when three are packed into a 120 Hz frame. It matters because
        the three are displayed at different moments, so evaluating all of them at the same stimulus
        time would throw away exactly the temporal resolution this mode exists to gain.
        """
        # clear the previous frame across the whole display
        self.clear_viewports(color=(0,0,0,1), viewports=None)

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
            t += time_offset
            if self.use_subject_trajectory:
                self.set_subject_state({'x': return_for_time_t(self.subject_x_trajectory, self.get_stim_time(t)),
                                        'y': return_for_time_t(self.subject_y_trajectory, self.get_stim_time(t)),
                                        'theta': return_for_time_t(self.subject_theta_trajectory, self.get_stim_time(t)) # deg -> radians
                                        })

            if self.cube_renderer is not None:
                self.paint_through_cube_map(self.get_stim_time(t), display_width, display_height)
            else:
                # For each subscreen associated with this screen: get the perspective matrix
                perspectives = [get_perspective(self.subject_position, x.pa, x.pb, x.pc, self.screen.horizontal_flip) for x in self.screen.subscreens]

                if self.stim_started:
                    self.draw_stimuli(self.get_stim_time(t), self.subscreen_viewports, perspectives)
                else: # Clear when there is stim loaded but not started (pre-time for the most part)
                    self.clear_viewports(color=self.idle_background, viewports=self.subscreen_viewports)

            # Only while the stimulus is running. This used to accumulate from load_stim onward, so
            # pre-time frames were folded into the frame-time statistics print_profile reports --
            # anyone reading those to check for dropped frames was reading polluted numbers. It also
            # grew for as long as a loaded-but-never-started stimulus sat there.
            if self.stim_started:
                self.profile_frame_times.append(t)
        elif self.cube_renderer is not None:
            # Standby and tail-time go through the cube map too, with nothing drawn into the faces.
            #
            # Only the warp knows where the screen is. Clearing the window directly lights the whole
            # projector image -- including the parts that miss the screen entirely, which on a bowl
            # is nearly half the frame -- and skips the mesh's per-vertex brightness gain. So the
            # background a subject saw between trials differed from the one the same idle_color
            # produced during them, in extent and, with brightness_correction on, in level.
            #
            # A CurvedScreen still inherits a full-viewport SubScreen it never uses, so the branch
            # below would happily paint through it and look like it was working.
            self.paint_through_cube_map(0.0, display_width, display_height)
        else: # Clear when there is no stim loaded (tail-time and when on standby)
            self.clear_viewports(color=self.idle_background, viewports=self.subscreen_viewports)

        # A calibration spot owns the whole frame: black everywhere else, and no corner square,
        # because a photometer aimed at the spot collects whatever else the screen is showing.
        if self.calibration_spot.visible:
            self.ctx.clear(0.0, 0.0, 0.0, 1.0)
            self.calibration_spot.paint()
        else:
            # Drawn per subframe, not per frame. The photodiode is what says when a frame appeared,
            # so under multiplexing it has to mark the subframes -- otherwise it reports 120 Hz for
            # a display running at 360 and there is no way to check the timing that matters.
            self.square_program.paint()


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
            # Release before dropping the references: nothing else will. stop_stim used to be the
            # only path that freed these, so replacing a loaded stimulus without stopping it first
            # -- View pressed twice, a readiness probe, anything interactive -- leaked every buffer,
            # program and texture it held.
            self.release_stims()
            self.stim_list = []

        # Resolved from the registry rather than by scanning BaseProgram.__subclasses__(), which
        # is global and cannot distinguish two same-named classes left by successive imports.
        chosen_stim_class = self.stim_classes.get(name)

        if chosen_stim_class is None:
            # Fall back to the global scan, for stimuli registered by some other route than
            # import_stim_module -- a labpack importing its own module, say.
            candidates = [x for x in get_all_subclasses(stimuli.BaseProgram) if x.__name__ == name]
            if not candidates:
                available = ', '.join(sorted(self.stim_classes)) or '(none)'
                # An explicit exception rather than assert: asserts are stripped under `python -O`,
                # which would let this silently pick the wrong stimulus class.
                raise ValueError(f"ERROR: no stimulus named '{name}'. Available: {available}")
            # Newest last: if several share the name, prefer the most recently defined, and say so.
            chosen_stim_class = candidates[-1]
            if len(candidates) > 1:
                warnings.warn(f"{len(candidates)} classes named '{name}' are registered; using the "
                              f"most recent, from {getattr(chosen_stim_class, '__module__', '?')}.")
        stim = chosen_stim_class(screen=self.screen)
        stim.initialize(self.ctx)
        stim.kwargs = kwargs
        stim.configure(**stim.kwargs) # Configure stim on load
        self.stim_list.append(stim)
        
    def start_stim(self, t, append_stim_frames=False, pre_render=False, pre_render_timepoints=None):
        """
        Start the stimulus animation, using the given time as t=0.

        :param t: Time corresponding to t=0 of the animation
        :param append_stim_frames: bool, append frames to stim_frames list, for saving stim movie. May affect performance.
        """
        self.clear_profile()

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

    def release_stims(self):
        """Free the GL objects held by the currently loaded stimuli.

        moderngl's default gc_mode does not free these when the Python objects are collected, so
        dropping stim_list without calling this leaks buffers, programs and textures on the GPU.
        """
        for stim in self.stim_list:
            stim.vbo_vert.release()
            stim.vbo_color.release()
            if stim.use_texture:
                stim.vbo_texture.release()
                # clear_samplers() only unbinds the texture; release it so the memory goes back.
                if getattr(stim, 'texture', None) is not None:
                    stim.texture.release()
                    stim.texture = None
            stim.vao.release()
            stim.prog.release()
            stim.destroy()

    def stop_stim(self, print_profile=False):
        """
        Stops the stimulus animation and removes it from the display.
        """
        # clear texture
        self.ctx.clear_samplers()

        self.release_stims()

        # print profiling information if applicable
        if print_profile:
            self.print_profile()
        self.clear_profile()

        # reset stim variables
        self.stim_list = []

        self.stim_started = False
        self.stim_start_time = None
        self.current_time_index = 0

        self.use_subject_trajectory = False
        self.subject_x_trajectory = None
        self.subject_y_trajectory = None
        self.subject_theta_trajectory = None
        
        self.set_subject_state({'x': 0, 'y': 0, 'z': 0, 'theta': 0, 'phi': 0, 'roll': 0})
        self.perspective = get_perspective(self.subject_position, self.screen.subscreens[0].pa, self.screen.subscreens[0].pb, self.screen.subscreens[0].pc, self.screen.horizontal_flip)

    def update_stim(self, t, **kwargs):
        for stim in self.stim_list:
            stim.update(**kwargs)
        
    def clear_profile(self):
        """
        Clear profiling information for the last stimulus.
        """
        self.profile_frame_times = []

    def print_profile(self):
        """
        Print profiling information for the last stimulus.
        """
        # filter out frame times of duration zero
        fps_data = np.diff(np.array(self.profile_frame_times))
        fps_data = fps_data[fps_data != 0]

        if len(fps_data) > 0:
            fps_data = pd.Series(1.0/fps_data)
            stim_names = ', '.join([type(stim).__name__ for stim in self.stim_list])
            print(f'*** {self.screen.name}: {stim_names} ***')
            print(fps_data.describe(percentiles=[0.01, 0.05, 0.1, 0.9, 0.95, 0.99]))
            print('*** end of statistics ***')
        
    def save_rendered_movie(self, file_path, downsample_xy=4):
        """
        Save rendered stim frames from stim_frames as 3D np array
        Must be used with append_stim_frames in start_stim

        :param file_path: full file path of saved array
        """
        stack = np.stack(self.stim_frames, axis=2)  # stack once (was built twice)
        pre_size = stack.shape
        mov = downscale_local_mean(stack, factors=(downsample_xy, downsample_xy, 1)).astype('uint8')
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
            else:
                if self.debug:
                    print(f'WARNING: Invalid key {k} in subject state update. Valid keys are x, y, z, theta, phi, roll.')
        
    def import_stim_module(self, path):
        '''
        Make the stimuli in a directory available to load_stim.

        The directory must contain a ``stimuli.py`` defining subclasses of
        :class:`~stimpack.visual_stim.base.BaseProgram`; ``trajectory.py`` and ``distribution.py``
        are picked up too if present.

        Re-importing a path that is already loaded **reloads** it: the previous import is dropped
        first, so the code on disk now is the code that runs, and no duplicate classes accumulate.
        That is what makes it safe for every client to import its labpack's stimuli on connect,
        and what makes an edited stimulus take effect on reconnect.

        A stimulus whose name is already taken -- by a built-in, or by a module imported earlier --
        shadows it, and the shadowing is reported so it is not silent.
        '''
        full_path = os.path.realpath(util.convert_labpack_relative_path_to_full_path(path))

        # Reload rather than add: see the docstring. Without this the same class name ends up
        # registered twice and resolution becomes ambiguous.
        for existing in [b for b, p in self.imported_stim_module_paths.items() if p == full_path]:
            print(f'Reloading stim module {path} (was key {existing})')
            self.unload_stim_module([existing])

        barcode = util.generate_lowercase_barcode(length=10, existing_barcodes=self.imported_stim_module_names)
        util.load_stim_module_from_path(path, barcode)

        # Take the classes from the module objects just created, rather than asking
        # BaseProgram.__subclasses__() what appeared: that is global, so it cannot tell this
        # module's classes from any other's, nor from ones left behind by an earlier import.
        classes = {}
        for submodule_name, module in list(sys.modules.items()):
            if not submodule_name.startswith(barcode + '.') or module is None:
                continue
            for attr in vars(module).values():
                if (isinstance(attr, type) and issubclass(attr, stimuli.BaseProgram)
                        and attr.__module__ == submodule_name):
                    classes[attr.__name__] = attr

        shadowed = [n for n in classes if n in self.stim_classes]
        self.imported_stim_module_names.append(barcode)
        self.imported_stim_module_paths[barcode] = full_path
        self.imported_stim_module_classes[barcode] = classes
        self._rebuild_stim_registry()

        print(f'Loaded stim module from {path} with key {barcode}'
              + (f' ({len(classes)} stimuli)' if classes else ' (no stimuli found)'))
        for name in shadowed:
            warnings.warn(f"Stimulus '{name}' from {full_path} shadows an existing one; "
                          f"the newly imported one will be used.")

    def _rebuild_stim_registry(self):
        '''
        Rebuild the name -> class map: stimpack's own stimuli first, then each imported module in
        the order it was imported, so a later import shadows an earlier one and unloading a module
        restores whatever it had been covering.
        '''
        registry = {cls.__name__: cls for cls in get_all_subclasses(stimuli.BaseProgram)
                    if getattr(cls, '__module__', '').startswith('stimpack.')}
        for barcode in self.imported_stim_module_names:
            registry.update(self.imported_stim_module_classes.get(barcode, {}))
        self.stim_classes = registry
    
    def unload_stim_module(self, barcodes=None):
        '''
        barcodes: list of keys for the stim modules to be unloaded. If None, all loaded stim modules will be unloaded.
        '''
        # Copy the list: the loop below removes from self.imported_stim_module_names, so iterating the
        # same object (the None case aliases it, and a caller may pass it in) would skip every other item.
        if barcodes is None:
            barcodes = list(self.imported_stim_module_names)
        else:
            barcodes = list(barcodes)

        for barcode in barcodes:
            if barcode not in self.imported_stim_module_names:
                print(f'Error: stim module with key {barcode} not found in loaded visual stim modules.')
                continue
            else:
                # Unload the submodules associated with each barcode from sys.modules
                submodule_names = [x for x in sys.modules.keys() if x.startswith(barcode)]
                [util.unload_module(x) for x in submodule_names]
                self.imported_stim_module_names.remove(barcode)
                self.imported_stim_module_paths.pop(barcode, None)
                self.imported_stim_module_classes.pop(barcode, None)
                print(f'Unloaded stim module with key {barcode}')

        # Rebuild once, after all removals: a module that was shadowing another now stops doing so,
        # and whatever it covered -- including a built-in of the same name -- comes back.
        self._rebuild_stim_registry()
        
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

    # No multisampling is requested here, and asking for it would not get it: QOpenGLWidget renders
    # into its own FBO, where the surface sample count does not apply. This asked for 24 samples for
    # years and was granted 0 on every GPU measured -- see report_surface_format, which prints what
    # was actually granted at start-up. Multisampling that works has to be an explicit multisampled
    # framebuffer resolved with copy_framebuffer; docs/design/analytic-edges.md has the costs.
    format.setDepthBufferSize(24)

    # No alpha channel in the window surface, deliberately. This asked for 24 (not even a valid
    # alpha depth -- 8 is) under a comment claiming alpha was "needed to enable transparency".
    # Nothing here wants a transparent window, and what it actually bought was the opposite of a
    # feature: on a compositor that honours it, the window is composited against the desktop using
    # whatever alpha the stimulus left behind, so analytic edges -- which carry coverage in alpha --
    # made the rim of every stimulus see-through. Mesa grants 8 bits here, NVIDIA/XWayland grants 0,
    # which is why the symptom followed the GPU rather than the code.
    #
    # StimDisplay also blends alpha separately so the framebuffer stays opaque (see initializeGL);
    # that is the correct-by-construction half. This is the belt: with no alpha in the surface, a
    # compositor has nothing to make a hole with even if something later writes alpha < 1.
    format.setAlphaBufferSize(0)

    return format

def main():
    # get the configuration parameters
    kwargs = get_kwargs()

    # get the screen
    screen = Screen.deserialize(kwargs.get('screen', {}))

    # launch the server
    server = MySocketServer(host=kwargs['host'], port=kwargs['port'], threaded=True, auto_stop=True, name=screen.name)

    # Bubble this screen's handler errors up to the visual stim server (which forwards to the client).
    server.error_reporter = lambda level, text: server.write_request_list(
        [{'name': 'report_server_message', 'args': [level, str(text)], 'kwargs': {}}])

    # set default format with OpenGL context
    format = QtGui.QSurfaceFormat()
    format.setVersion(3, 3)
    format.setProfile(QtGui.QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    QtGui.QSurfaceFormat.setDefaultFormat(format)

    # launch application
    app = QtWidgets.QApplication([])
    app.setWindowIcon(QtGui.QIcon(ICON_PATH))
    app.setApplicationName(f'Stimpack visual_stim screen: {screen.name}')

    # create the StimDisplay object
    screen = Screen.deserialize(kwargs.get('screen', {}))
    debug = kwargs.get('debug', False)
    stim_display = StimDisplay(screen=screen, server=server, app=app, debug=debug)

    # register functions -- from SCREEN_FUNCTION_NAMES, so the advertised surface and the
    # registered one cannot drift apart
    for function_name in SCREEN_FUNCTION_NAMES:
        server.register_function(getattr(stim_display, function_name))
    
    # A new window normally activates itself and takes the keyboard. Screens are shown without
    # taking focus by default instead; set STIMPACK_NO_FOCUS=0 for the old behavior.
    #
    # This used to be opt-in, on the reasoning that taking focus "is right on a rig" and only a
    # desktop needs protecting from it. On a rig with more than one screen it is the opposite. The
    # windows compete for focus, the window manager flashes the one that lost, and each flash costs
    # the fullscreen screen a whole vsync. Measured on BrukerJr, 6-second trials at 120 Hz:
    #
    #     bowl alone                     720 frames of 720
    #     bowl + operator window         707 frames of 720   (13 dropped, ~2 per second)
    #     bowl + operator window, no focus   720 frames of 720
    #
    # It did not depend on scene complexity -- a plain background lost as many frames as 400 towers
    # -- which is what marks it as a window-manager artifact rather than GPU load. Reported first
    # from the rig as "the aux window blinks and we drop frames", which is exactly what it was.
    #
    # Honored under X11/XWayland, where Qt maps it to _NET_WM_USER_TIME=0 and the window manager
    # respects that. NOT honored under the wayland platform plugin: Wayland has no such hint, the
    # compositor alone decides focus, and mutter activates new toplevels regardless (measured, not
    # assumed). To get this under a Wayland session, run the screen on XWayland instead --
    # Screen(x_display=os.environ['DISPLAY']) selects the xcb platform. See tests/conftest.py.
    # Two mechanisms, applied to different screens because they do different jobs:
    #
    #     WA_ShowWithoutActivating   do not take focus when shown       every screen
    #     WindowDoesNotAcceptFocus   never accept focus at all          fullscreen only
    #
    # The dropped frames below came from the screens competing for focus. What settles it is the
    # fullscreen screen refusing focus outright, so the operator window can hold it; see the block
    # below for why that is the way round it is, and for what the flag costs if applied naively.
    if os.environ.get('STIMPACK_NO_FOCUS', '1') != '0':
        stim_display.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        if screen.fullscreen:
            # Frameless as well as no-focus, and both only here. Measured on a 1920x1080 fluxbox
            # screen with showFullScreen():
            #
            #     no-focus                    1920x1080+0+22   refuses focus
            #     frameless                   1920x1080+0+0    accepts focus
            #     no-focus + frameless        1920x1080+0+0    refuses focus
            #
            # The no-focus flag alone gets the window placed as though it were decorated, so the
            # client area starts a title bar down -- on this rig that shifted the projected image
            # 22 px down the bowl while Qt still reported WindowFullScreen, so nothing in software
            # could tell. Removing the decoration removes the offset, and a fullscreen stimulus
            # window has no business being decorated anyway.
            #
            # It is the *fullscreen* screen that has to refuse focus, which is the opposite of the
            # obvious guess. The operator window flashes when it wants focus and cannot keep it, so
            # what stops the flashing is the projector never taking it away. Setting the flag on
            # the operator window instead makes things worse twice over: it still flashes, and it
            # can no longer be clicked to settle. Observed at the rig in all three configurations.
            stim_display.setWindowFlag(QtCore.Qt.WindowType.WindowDoesNotAcceptFocus, True)
            stim_display.setWindowFlag(QtCore.Qt.WindowType.FramelessWindowHint, True)

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
