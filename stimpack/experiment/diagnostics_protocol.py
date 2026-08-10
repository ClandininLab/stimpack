"""Commissioning and diagnostic protocols: for checking a rig, not for running experiments.

None of these presents an experiment. Each one exercises a specific piece of rig plumbing and is
meant to be run while setting a rig up or hunting a fault:

- ``ServerErrorDemo``     the error path: a stimulus that cannot load must abort the run visibly
- ``SubframeTimingCheck`` subframe multiplexing order and timing, with a photodiode
- ``ScreenAlignmentCheck``where screens meet: rings and rulers for aligning physical displays
- ``ProjectorCenterBeam`` a projector's optical axis, for measuring a rig's geometry

They are not loaded by default, so a fresh install's protocol dropdown shows only experiments.
To use them, add this module to a config's protocol paths -- the ``stimpack:`` prefix resolves
against wherever stimpack is installed::

    module_paths:
      protocol:
        - stimpack:experiment/diagnostics_protocol.py

"""
import warnings

import numpy as np

from stimpack.experiment.protocol import BaseProtocol


class ServerErrorDemo(BaseProtocol):
    """
    Deliberately triggers a server-side error, to demonstrate server -> client error reporting.

    Each trial asks the display server to load a stimulus class that does not exist, so load_stim
    raises on the server. The error bubbles back to the client: it shows up in the GUI status label
    (tagged [screen], since it originates in a screen subprocess), the run aborts instead of running
    to completion, and — when recording — the series group is written with run_status='error' and
    abort_reason set. Nothing renders; this is a diagnostics/demo protocol, not a real stimulus.
    """
    def get_run_parameter_defaults(self):
        return {'num_trials': 3, 'idle_color': 0.5}

    def get_protocol_parameter_defaults(self):
        return {'pre_time': 0.5, 'stim_time': 1.0, 'tail_time': 0.5}

    def get_trial_parameters(self):
        super().get_trial_parameters()
        # A stimulus class name that does not exist -> load_stim raises ValueError on the server.
        self.trial_stim_parameters = {'name': 'NoSuchStimulus_ServerErrorDemo'}


class SubframeTimingCheck(BaseProtocol):
    """
    Commissioning stimulus: is the display really showing every subframe, in the right order?

    The subframe path packs up to three timepoints into a frame's color channels for a projector
    that unpacks them as successive patterns -- 360 Hz from a 120 Hz video link. Whether that
    happens depends on the projector being in pattern mode, on the channel order matching, and on
    every subframe reaching the screen. None of it can be checked from the client, and the unit
    tests cannot check it either: they read pixels back from an offscreen buffer, which says the
    packing is right and nothing about the display.

    This puts the spot at a *different azimuth in each subframe*, cycling once per video frame, so
    the answer is visible rather than inferred:

    - **all subframes displayed** -- ``n_subframes`` spots, evenly spaced by ``separation``, and
      with a high-speed camera they appear in order left to right
    - **only one channel reaching the screen** -- a single spot, not ``n_subframes`` of them
    - **channel order wrong** -- the right number of spots, in the wrong sequence, which a camera
      sees and the eye does not

    Alongside it the corner square toggles once per subframe (see StimDisplay.paint_subframe), so a
    photodiode on the square reports the rate directly: transitions at ``subframe_rate``, not at the
    video frame rate. That is the measurement to trust; the spots say what is wrong when the rate is
    not what it should be.

    ``subframe_rate`` and ``n_subframes`` are parameters rather than read from the screen, because
    this is the stimulus you run when you do not yet believe the screen is doing what it was told.
    Set them to what the rig's configuration asks for, and see whether the display agrees.

    It also *switches the rig*, on rigs that can be switched: a labpack registering ``set_subframes``
    on root -- see the "Subframe multiplexing" page -- gets the whole check in one run rather than a
    server edit either side of it. Where no such function is registered, this runs at whatever the
    server was started with, which on most rigs means one subframe and one spot.
    """
    def __init__(self, cfg):
        super().__init__(cfg)

        self.run_parameters = self.get_run_parameter_defaults()
        self.protocol_parameters = self.get_protocol_parameter_defaults()

    def n_subframes(self):
        """The count this run asks the rig for, as an int.

        Refused as a list: a list is stimpack's notation for a parameter that varies across trials,
        and a screen cannot change its temporal structure part-way through a run -- StimDisplay
        refuses mid-stimulus, and nothing in the data file would record that trial 1 differed from
        trial 2. Better said before the run starts than discovered afterwards.
        """
        value = self.protocol_parameters['n_subframes']
        if isinstance(value, (list, tuple)):
            raise ValueError(f'n_subframes must be a single value, not {value}: the screen cannot '
                             f'change how many subframes it carries between trials of one run.')
        return int(value)

    def prepare_run(self, manager, recompute_epoch_parameters=True):
        super().prepare_run(manager, recompute_epoch_parameters)

        # After super(), so a run that fails its parameter checks does not leave the rig switched.
        if self.has_server_function('set_subframes'):
            manager.target('root').set_subframes(self.n_subframes())
        elif self.n_subframes() != 1:
            warnings.warn(f'This rig registers no set_subframes, so the display stays as the server '
                          f'started it while the stimulus is drawn for {self.n_subframes()} '
                          f'subframes. Expect a single spot unless the server was started '
                          f'multiplexing.')

    def on_run_finish(self, manager, multicall=None):
        super().on_run_finish(manager, multicall)

        # Back to ordinary rendering. Called from the run loop's finally block, so a stopped or
        # errored run leaves the rig as it was found -- and a rig left multiplexing is not an error
        # anyone would see, since the next protocol's color channels are simply reinterpreted as
        # slices of time.
        if self.has_server_function('set_subframes'):
            manager.target('root').set_subframes(1)

    def subframe_positions(self, stim_time, n_subframes, subframe_rate, separation, center):
        """A staircase in azimuth, one step per subframe, cycling every video frame.

        Held rather than interpolated: each subframe must land on one position, not slide between
        two. The step boundaries sit half an interval early so that a subframe rendered at exactly
        k / subframe_rate samples the middle of step k rather than its edge, where floating point
        could put it on either side.
        """
        interval = 1.0 / subframe_rate
        steps = int(np.ceil(stim_time * subframe_rate)) + 2
        return [((k - 0.5) * interval, center + separation * (k % n_subframes))
                for k in range(steps)]

    def get_trial_parameters(self):
        super().get_trial_parameters()

        center = self.adjust_center(self.trial_protocol_parameters['center'])
        theta = self.subframe_positions(
            stim_time=self.trial_protocol_parameters['stim_time'],
            n_subframes=int(self.trial_protocol_parameters['n_subframes']),
            subframe_rate=float(self.trial_protocol_parameters['subframe_rate']),
            separation=float(self.trial_protocol_parameters['separation']),
            center=center[0])

        self.trial_stim_parameters = {'name': 'MovingSpot',
                                      'radius': self.trial_protocol_parameters['radius'],
                                      'sphere_radius': 1,
                                      'color': self.trial_protocol_parameters['color'],
                                      'theta': {'name': 'TVPairs',
                                                'tv_pairs': theta,
                                                'kind': 'previous'},
                                      'phi': center[1]}

    def get_protocol_parameter_defaults(self):
        return {'pre_time': 1.0,
                'stim_time': 4.0,
                'tail_time': 1.0,

                'n_subframes': 3,        # match the screen's `subframes`
                'subframe_rate': 360.0,  # Hz; the video rate times n_subframes
                'separation': 10.0,      # degrees between consecutive subframe positions
                'radius': 2.5,
                'color': 1.0,
                'center': (0, 0),
                }

    def get_run_parameter_defaults(self):
        return {'num_trials': 5,
                'idle_color': 0.0,       # dark, so a photodiode sees only the corner square
                'pre_run_time': 0,
                'post_run_time': 0,
                'all_combinations': True,
                'randomize_order': False}


class ScreenAlignmentCheck(BaseProtocol):
    """
    Commissioning stimulus: concentric rings of equal angular width, to check the warp and the
    screen's centering.

    Two questions, one pattern.

    **Is the warp right?** Every band subtends the same angle at the subject. On a screen that is a
    sphere centered on the subject, equal angle is equal arc, so every band is the same *physical*
    width on the surface -- a ruler laid across the screen, or a photograph of it, answers directly,
    with no model of the rig needed to interpret the reading. Look at the projector image instead
    and the same bands are visibly unequal, crowding towards the rim. That difference *is* the warp;
    seeing it is how you know the screen mesh is being used rather than bypassed.

    **Is the screen centered on the projector?** The rings are concentric about
    ``center``, which defaults to the rig's own ``screen_center`` -- on a rig whose screen has an
    axis of symmetry, that is the axis, and the rings should come out concentric with the rim. An
    offset shows up as rings crowding one side, and every ring is a fresh chance to see it, which
    beats eyeballing a single edge. If they are eccentric, either the screen is off the projector's
    axis or ``screen_center`` does not describe this rig.

    Static and non-random on purpose: this is a target to photograph and measure, so nothing here
    varies across trials, and one trial is enough. It is left up for ``stim_time``, so make that as
    long as you need to take the picture.

    Run :class:`ProjectorCenterBeam` alongside it. The beam marks the center of the projector image;
    the rings should be concentric about that mark, which turns "is it centered" into a comparison of
    two things on the same photograph rather than a judgment about one.
    """
    def __init__(self, cfg):
        super().__init__(cfg)

        self.run_parameters = self.get_run_parameter_defaults()
        self.protocol_parameters = self.get_protocol_parameter_defaults()

    def get_trial_parameters(self):
        super().get_trial_parameters()

        center = self.adjust_center(self.trial_protocol_parameters['center'])

        # Two scalars rather than one 'colors' pair, because a list in a protocol parameter is
        # stimpack's notation for a value that varies across trials -- so a color pair written as
        # a list would be read as two trials, each with one color, and the pattern would come out
        # a flat disc.
        colors = (self.trial_protocol_parameters['bright'],
                  self.trial_protocol_parameters['dark'])

        self.trial_stim_parameters = {'name': 'AlternatingAnnuli',
                                      'band_width': self.trial_protocol_parameters['band_width'],
                                      'max_radius': self.trial_protocol_parameters['max_radius'],
                                      'sphere_radius': 1,
                                      'colors': colors,
                                      'theta': center[0],
                                      'phi': center[1],
                                      'n_azimuth': self.trial_protocol_parameters['n_azimuth']}

    def get_protocol_parameter_defaults(self):
        return {'pre_time': 0.5,
                'stim_time': 60.0,       # long: this is a target to photograph, not a trial
                'tail_time': 0.5,

                'band_width': 5.0,       # degrees; the quantity the whole check is about
                # Past the edge of the screen on purpose. A ring that runs off the screen shows
                # where the edge is; one that stops short of it does not.
                'max_radius': 60.0,
                'bright': 1.0,
                'dark': 0.0,
                'center': (0, 0),        # relative to screen_center -- see the class docstring
                'n_azimuth': 128,
                }

    def get_run_parameter_defaults(self):
        return {'num_trials': 1,
                'idle_color': 0.0,       # dark, so the rings are the only thing on the screen
                'pre_run_time': 0,
                'post_run_time': 0,
                'all_combinations': True,
                'randomize_order': False}


class ProjectorCenterBeam(BaseProtocol):
    """
    Commissioning stimulus: a narrow spot at the center of the projector image, for aligning the
    projector against the subject.

    Drawn in *projector* coordinates, after the warp, on an otherwise black screen -- so it marks a
    known position in the image rather than a direction in the world, and no part of the rendering
    geometry can move it. That is what makes it an independent reference: everything else on the
    screen has been through the mesh, and this has not.

    On a rig whose projector is aimed at the subject, the center ray goes from the projector, through
    the screen, to the subject. So with ``ndc`` at the default (0, 0) the beam should land on the
    subject itself. Watch it on the behavior camera and move the projector until it does.

    The beam stays lit for the whole run rather than per trial, because what you do with it is
    physically adjust the rig while looking at it. Press Stop when you are done -- it is taken down
    from the run loop's finally block, so a stopped or errored run does not leave the screen black
    with a dot on it.

    Two things it deliberately does: it blacks out the rest of the screen (see
    :class:`~stimpack.visual_stim.calibration.CalibrationSpot` -- the same mechanism the brightness
    calibration uses), and while it is up the corner square is suppressed, so a photodiode sees
    nothing during this protocol. Neither matters for alignment, and both would matter if you tried
    to use this while recording.
    """
    def __init__(self, cfg):
        super().__init__(cfg)

        self.run_parameters = self.get_run_parameter_defaults()
        self.protocol_parameters = self.get_protocol_parameter_defaults()

    def on_run_start(self, manager, multicall=None):
        super().on_run_start(manager, multicall)

        if not self.has_server_function('show_calibration_spot', target='visual'):
            warnings.warn('This screen server does not answer to show_calibration_spot, so no beam '
                          'will appear. It is stimpack 1.0+; check the server version.')
            return

        manager.target('visual').show_calibration_spot(
            ndc_x=self.protocol_parameters['ndc_x'],
            ndc_y=self.protocol_parameters['ndc_y'],
            radius=self.protocol_parameters['radius'],
            intensity=self.protocol_parameters['intensity'])

    def on_run_finish(self, manager, multicall=None):
        super().on_run_finish(manager, multicall)

        # From the run loop's finally block, so Stop and an error both take the beam down. A screen
        # left showing nothing but a dot is not an error anyone would recognize as one.
        if self.has_server_function('hide_calibration_spot', target='visual'):
            manager.target('visual').hide_calibration_spot()

    def get_trial_parameters(self):
        super().get_trial_parameters()

        # No stimulus: the beam is not drawn through the rendering path at all. The trial exists
        # only to hold the run open while the projector is being moved.
        self.trial_stim_parameters = None

    def get_protocol_parameter_defaults(self):
        return {'pre_time': 0.0,
                'stim_time': 300.0,      # long: you are adjusting hardware. Stop when done.
                'tail_time': 0.0,

                # Projector image coordinates, [-1, +1] in each axis. (0, 0) is the center of the
                # image, which is the point this protocol exists to find.
                'ndc_x': 0.0,
                'ndc_y': 0.0,
                # Radius as a fraction of the image half-width, corrected to be round in the image
                # rather than in NDC. 0.01 is about 9 px across a 912 px panel.
                'radius': 0.01,
                'intensity': 1.0,
                }

    def get_run_parameter_defaults(self):
        return {'num_trials': 1,
                'idle_color': 0.0,
                'pre_run_time': 0,
                'post_run_time': 0,
                'all_combinations': True,
                'randomize_order': False}
