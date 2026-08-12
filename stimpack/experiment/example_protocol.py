#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import functools
import time

import numpy as np


def _wander(rng, n, dt, sigma, tau=0.5, bound=60.0):
    """A velocity random walk that forgets its speed over ~tau seconds, integrated to position.

    The momentum is what makes it read as an animal moving rather than as noise: velocity decays
    toward zero while being kicked, so the path has smooth swerves and pauses instead of jitter.
    Deterministic for a given rng state, which ChaseTheTower depends on: the server regenerates
    the exact path from the seed alone.
    """
    velocity = np.zeros(n)
    for i in range(1, n):
        velocity[i] = velocity[i - 1] * (1 - dt / tau) + rng.normal(0, sigma) * np.sqrt(dt)
    position = np.cumsum(velocity) * dt
    return np.clip(position, -bound, +bound)

from stimpack.rpc.transceiver import MySocketClient
from stimpack.rpc.multicall import MyMultiCall
from stimpack.experiment.protocol import BaseProtocol

# %% Some simple visual stimulus protocol classes

class DriftingSquareGrating(BaseProtocol):
    """
    Drifting square wave grating, painted on a cylinder
    """
    def __init__(self, cfg):
        super().__init__(cfg)

        self.run_parameters = self.get_run_parameter_defaults()
        self.protocol_parameters = self.get_protocol_parameter_defaults()

    def get_trial_parameters(self):
        super().get_trial_parameters()
        
        center = self.adjust_center(self.trial_protocol_parameters['center'])
        centerX = center[0]
        centerY = center[1]

        self.trial_stim_parameters = {'name': 'RotatingGrating',
                                      'period': self.trial_protocol_parameters['period'],
                                      'rate': self.trial_protocol_parameters['rate'],
                                      'color': [1, 1, 1, 1],
                                      'mean': self.trial_protocol_parameters['mean'],
                                      'contrast': self.trial_protocol_parameters['contrast'],
                                      'angle': self.trial_protocol_parameters['angle'],
                                      'offset': 0.0,
                                      'cylinder_radius': 1,
                                      'cylinder_height': 10,
                                      'profile': 'square',
                                      'theta': centerX,
                                      'phi': centerY}

    def get_protocol_parameter_defaults(self):
        return {'pre_time': 1.0,
                'stim_time': 4.0,
                'tail_time': 1.0,
                
                'period': 20.0,
                'rate': 20.0,
                'contrast': 1.0,
                'mean': 0.5,
                'angle': [0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0],
                'center': (0, 0),
                }

    def get_run_parameter_defaults(self):
        return {'num_trials': 40,
                'idle_color': 0.5,
                'pre_run_time': 0,  # seconds to wait before starting the run
                'post_run_time': 0,  # seconds to wait after the run
                'all_combinations': True,
                'randomize_order': True}

# %%

class MovingPatch(BaseProtocol):
    """
    Moving patch, either rectangular or elliptical. Moves along a spherical or cylindrical trajectory
    """
    def __init__(self, cfg):
        super().__init__(cfg)

        self.run_parameters = self.get_run_parameter_defaults()
        self.protocol_parameters = self.get_protocol_parameter_defaults()

    def get_moving_patch_parameters(self, center=None, angle=None, speed=None, width=None, height=None, color=None, distance_to_travel=None, ellipse=None, render_on_cylinder=None):
        if center is None: center = self.trial_protocol_parameters['center']
        if angle is None: angle = self.trial_protocol_parameters['angle']
        if speed is None: speed = self.trial_protocol_parameters['speed']
        if width is None: width = self.trial_protocol_parameters['width']
        if height is None: height = self.trial_protocol_parameters['height']
        if color is None: color = self.trial_protocol_parameters['color']
        if ellipse is None: ellipse = self.trial_protocol_parameters['ellipse'] if 'ellipse' in self.trial_protocol_parameters else False
        if render_on_cylinder is None: render_on_cylinder = self.trial_protocol_parameters['render_on_cylinder'] if 'render_on_cylinder' in self.trial_protocol_parameters else False

        center = self.adjust_center(center)

        centerX = center[0]
        centerY = center[1]
        stim_time = self.trial_protocol_parameters['stim_time']
        if distance_to_travel is None:  # distance_to_travel is set by speed and stim_time
            distance_to_travel = speed * stim_time
            # trajectory just has two points, at time=0 and time=stim_time
            startX = (0, centerX - np.cos(np.radians(angle)) * distance_to_travel/2)
            endX = (stim_time, centerX + np.cos(np.radians(angle)) * distance_to_travel/2)
            startY = (0, centerY - np.sin(np.radians(angle)) * distance_to_travel/2)
            endY = (stim_time, centerY + np.sin(np.radians(angle)) * distance_to_travel/2)
            x = [startX, endX]
            y = [startY, endY]

        else:  # distance_to_travel is specified, so only go that distance at the defined speed. Hang pre- and post- for any extra stim time
            travel_time = np.abs(distance_to_travel / speed)
            distance_to_travel = np.sign(speed) * distance_to_travel
            if travel_time > stim_time:
                print('Warning: stim_time is too short to show whole trajectory at this speed!')
                hang_time = 0
            else:
                hang_time = (stim_time - travel_time)/2

            # split up hang time in pre and post such that trajectory always hits centerX,centerY at stim_time/2
            x_1 = (0, centerX - np.cos(np.radians(angle)) * distance_to_travel/2)
            x_2 = (hang_time, centerX - np.cos(np.radians(angle)) * distance_to_travel/2)
            x_3 = (stim_time-hang_time, centerX + np.cos(np.radians(angle)) * distance_to_travel/2)
            x_4 = (stim_time, centerX + np.cos(np.radians(angle)) * distance_to_travel/2)

            y_1 = (0, centerY - np.sin(np.radians(angle)) * distance_to_travel/2)
            y_2 = (hang_time, centerY - np.sin(np.radians(angle)) * distance_to_travel/2)
            y_3 = (stim_time-hang_time, centerY + np.sin(np.radians(angle)) * distance_to_travel/2)
            y_4 = (stim_time, centerY + np.sin(np.radians(angle)) * distance_to_travel/2)

            x = [x_1, x_2, x_3, x_4]
            y = [y_1, y_2, y_3, y_4]

        x_trajectory = {'name': 'TVPairs',
                        'tv_pairs': x,
                        'kind': 'linear'}
        y_trajectory = {'name': 'TVPairs',
                        'tv_pairs': y,
                        'kind': 'linear'}

        if render_on_cylinder:
            flystim_stim_name = 'MovingEllipseOnCylinder' if ellipse else 'MovingPatchOnCylinder'
        else:
            flystim_stim_name = 'MovingEllipse' if ellipse else 'MovingPatch'
        
        patch_parameters = {'name': flystim_stim_name,
                            'width': width,
                            'height': height,
                            'color': color,
                            'theta': x_trajectory,
                            'phi': y_trajectory,
                            'angle': angle}
        return patch_parameters

    def get_trial_parameters(self):
        super().get_trial_parameters()

        # Create stimpack.visual_stim trial parameters dictionary
        self.trial_stim_parameters = self.get_moving_patch_parameters(center=self.trial_protocol_parameters['center'],
                                                                angle=self.trial_protocol_parameters['angle'],
                                                                speed=self.trial_protocol_parameters['speed'],
                                                                width=self.trial_protocol_parameters['width_height'][0],
                                                                height=self.trial_protocol_parameters['width_height'][1],
                                                                color=self.trial_protocol_parameters['intensity'])

    def get_protocol_parameter_defaults(self):
        return {'pre_time': 0.5,
                'stim_time': 3.0,
                'tail_time': 1.0,
                
                'ellipse': True,
                'width_height': [(5, 5), (10, 10), (15, 15), (20, 20), (25, 25), (30, 30)],
                'intensity': 0.0,
                'center': (0, 0),
                'speed': 80.0,
                'angle': 0.0,
                'render_on_cylinder': False,
                }

    def get_run_parameter_defaults(self):
        return {'num_trials': 40,
                'idle_color': 0.5,
                'pre_run_time': 0,  # seconds to wait before starting the run
                'post_run_time': 0,  # seconds to wait after the run
                'all_combinations': True,
                'randomize_order': True}

#%%

# %%

class WanderingSpot(BaseProtocol):
    """A spot that wanders like an animal rather than sweeping like a stimulus.

    Each trial synthesizes a smooth, meandering path -- a random walk with momentum in azimuth and
    elevation -- and hands it to the renderer as an ordinary time-value trajectory. ``seed`` is an
    ordinary protocol parameter, so it sweeps like any other: the default run presents five
    different walks, and the same seed always produces the same path, on this rig or any other.
    That is what makes a naturalistic stimulus replayable and comparable across setups.

    The same mechanism replays a RECORDED path. Load times and positions from a file instead of
    synthesizing them, and keep the trajectory dict the same::

        t, theta = np.load('my_trajectory.npy')      # or pd.read_pickle, ...
        {'name': 'TVPairs', 'tv_pairs': list(zip(t, theta)), 'kind': 'linear'}

    That is exactly how measured courtship trajectories are presented (Coen et al. 2014); the
    recordings themselves belong in a labpack, not in stimpack.
    """
    def __init__(self, cfg):
        super().__init__(cfg)

        self.run_parameters = self.get_run_parameter_defaults()
        self.protocol_parameters = self.get_protocol_parameter_defaults()

    def get_trial_parameters(self):
        super().get_trial_parameters()
        params = self.trial_protocol_parameters

        rng = np.random.default_rng(int(params['seed']))
        dt = 1.0 / 60.0
        n = int(params['stim_time'] / dt) + 1
        t = np.arange(n) * dt

        center = self.adjust_center(params['center'])
        theta = center[0] + _wander(rng, n, dt, sigma=params['wander_speed'], bound=60)
        phi = center[1] + _wander(rng, n, dt, sigma=params['wander_speed'] / 2, bound=30)

        self.trial_stim_parameters = {
            'name': 'MovingSpot',
            'radius': params['radius'],
            'sphere_radius': 1,
            'color': params['color'],
            'theta': {'name': 'TVPairs', 'tv_pairs': list(zip(t, theta)), 'kind': 'linear'},
            'phi': {'name': 'TVPairs', 'tv_pairs': list(zip(t, phi)), 'kind': 'linear'},
        }

    def get_protocol_parameter_defaults(self):
        return {'pre_time': 0.5,
                'stim_time': 6.0,
                'tail_time': 0.5,

                'radius': 5.0,
                'color': [0, 0, 0, 1],
                'center': (0, 0),
                'wander_speed': 20.0,           # sets typical speed (~10 deg/s); larger wanders faster
                'seed': [0, 1, 2, 3, 4]}        # a list, so seeds sweep like any parameter

    def get_run_parameter_defaults(self):
        return {'num_trials': 5,
                'idle_color': 0.5,
                'pre_run_time': 0,
                'post_run_time': 0,
                'all_combinations': True,
                'randomize_order': True}


class ReachTheGoal(BaseProtocol):
    """A trial that ends when the subject arrives, not when a timer says so.

    A red tower stands at a goal location ahead. Arrive within ``GOAL_RADIUS`` of it and the trial
    ends immediately, with ``trial_end_reason='reached_goal'`` recorded; stand still -- or walk
    straight past it -- and ``stim_time`` ends the trial as usual, so the run cannot hang on an
    unwilling subject and cannot be finished by wandering anywhere sufficiently far forward. This is the runnable version of the
    docs' "Trials that end when the animal does something".

    To try it without hardware: on a config with ``loco_available: True`` (the built-in default
    config qualifies; the GUI's local server runs KeyTrac, a keyboard stand-in tracker), tick
    ``do_loco`` in the run parameters, press View, focus the KeyTrac window and hold the Up arrow.
    The scene approaches the tower, and the trial ends as you reach it.

    The condition cannot be checked in this class's own methods: they run on the CLIENT, which
    never sees subject state and cannot ask for it (requests carry no reply). So the check lives
    in server_side_state_dependent_control below, which stimpack calls on the SERVER on every
    tracker update.

    This is the MINIMAL behavior-ended trial, and the one to copy when writing your own: the
    control function is a distance check and an end_trial call. ChaseTheTower is the same task
    with the goal in motion, and carries the extra machinery a moving, client-defined target
    needs -- start there only if your condition needs it.
    """

    # The goal, in meters -- deliberately class attributes, not protocol parameters.
    # server_side_state_dependent_control runs in the server process, which imports this module
    # and reads the *class*; it never sees the protocol object, so a value edited in the GUI would
    # move the tower (below) without moving the finish line. Keeping the numbers here means the
    # stimulus and the trial-ending condition cannot disagree.
    GOAL_LOCATION = (0.0, 0.10)   # (x, y): 10 presses of the Up arrow at KeyTrac's 0.01 m step
    GOAL_RADIUS = 0.02            # arrive within two presses of the tower, in any direction

    def __init__(self, cfg):
        super().__init__(cfg)

        self.run_parameters = self.get_run_parameter_defaults()
        self.protocol_parameters = self.get_protocol_parameter_defaults()

        # Ask stimpack to load server_side_state_dependent_control onto the server for the
        # duration of the run. Without this flag the function below is never called.
        self.use_server_side_state_dependent_control = True

    @staticmethod
    def server_side_state_dependent_control(server, previous_state, state_update):
        """Runs ON THE SERVER, once per tracker update. Must return a state_update; modifying it
        is the closed-loop part (a gain, an offset) -- ending the trial is an extra thing it may
        do along the way. This one leaves the update untouched.
        """
        # Read fresh values from state_update first, and only fall back to previous_state.
        # state_update holds what the tracker just reported (only the keys that changed);
        # previous_state is the accumulated state as it was BEFORE this update. A condition
        # written against previous_state alone fires one update late -- and if the subject
        # arrives on the run's last update, never.
        x = state_update.get('x', previous_state.get('x', 0))
        y = state_update.get('y', previous_state.get('y', 0))
        goal_x, goal_y = ReachTheGoal.GOAL_LOCATION
        if (x - goal_x) ** 2 + (y - goal_y) ** 2 <= ReachTheGoal.GOAL_RADIUS ** 2:
            # Ends only the trial in progress, as if its timer had elapsed; the run goes on to
            # the next trial, which re-zeroes the subject at the start line (set_pos_0).
            server.end_trial(reason='reached_goal')
        return state_update

    def get_trial_parameters(self):
        super().get_trial_parameters()

        self.trial_stim_parameters = [
            # A floor, so walking is visible as motion even before the tower grows.
            {'name': 'CheckerboardFloor',
             'mean': 0.3, 'contrast': 0.5, 'center': (0, self.GOAL_LOCATION[1] / 2, -0.05),
             'side_length': (0.25, self.GOAL_LOCATION[1] + 0.25), 'patch_width': 0.02},
            # The goal itself, at the same location the server-side condition tests, sized to the
            # radius that counts as arrival.
            {'name': 'Tower',
             'color': [1, 0, 0, 1], 'cylinder_radius': self.GOAL_RADIUS / 2,
             'cylinder_height': 0.1,
             'cylinder_location': (self.GOAL_LOCATION[0], self.GOAL_LOCATION[1], 0),
             'n_faces': 16},
        ]

    def get_protocol_parameter_defaults(self):
        return {'pre_time': 0.5,
                'stim_time': 30.0,             # a timeout, not the expected duration
                'tail_time': 0.5,
                'loco_pos_closed_loop': 1}     # the scene follows the subject within the trial

    def get_run_parameter_defaults(self):
        return {'num_trials': 5,
                'idle_color': 0.5,
                'pre_run_time': 0,
                'post_run_time': 0,
                'all_combinations': True,
                'randomize_order': False,
                # This protocol only means anything in closed loop, so tracking
                # comes pre-checked; untick it in the GUI to rehearse open loop.
                'do_loco': True}


@functools.lru_cache(maxsize=32)
def _tower_path(seed, n):
    """The tower's (x, y) path over the trial, in meters, as tuples so it can be cached.

    One function, called from BOTH processes: the protocol (client) builds the stimulus
    trajectories from it, and server_side_state_dependent_control (server) regenerates it to know
    where the tower is now. Same seed, same path -- determinism is the channel. Cached because the
    server half runs at tracker rate. The two walks draw from one rng in a fixed order, which is
    part of the contract: reordering them would change every path.
    """
    rng = np.random.default_rng(int(seed))
    dt = ChaseTheTower.DT
    x = ChaseTheTower.TOWER_START[0] + _wander(rng, n, dt, sigma=ChaseTheTower.WANDER_SIGMA,
                                               bound=ChaseTheTower.WANDER_BOUND)
    y = ChaseTheTower.TOWER_START[1] + _wander(rng, n, dt, sigma=ChaseTheTower.WANDER_SIGMA,
                                               bound=ChaseTheTower.WANDER_BOUND)
    return tuple(x), tuple(y)


class ChaseTheTower(BaseProtocol):
    """ReachTheGoal, except the goal will not stay put: chase a drifting tower and catch it.

    A short translucent red pillar wanders slowly around the arena. Walk to it -- steer with the
    Left/Right arrows, walk forward with the Up arrow in the KeyTrac window -- and the trial ends
    the moment you are within ``CATCH_RADIUS`` of it, with ``trial_end_reason='caught'``
    recorded. The tower drifts far slower than you walk, so every chase is winnable; stand still
    and it stays out of reach, and ``stim_time`` ends the trial as a timeout.

    What this adds over ReachTheGoal is the architectural point: the server-side condition needs
    to know where the TOWER is, and the tower's path is defined on the client. No position is ever
    sent. The client arms each trial with the path's seed (ordinary ``set_subject_state`` keys),
    and the server regenerates the identical path from that seed -- _tower_path above is one
    function called from both processes. Reproducibility is not just for replaying trials; it is
    what lets two processes agree about a stimulus without talking about it.

    Timing honesty: the server measures trial time from the first tracker update after arming, on
    its own clock -- within one tracker interval of stimulus onset, which is ample here. A
    condition needing frame-accurate stimulus time should be designed around the photodiode
    record instead.
    """

    # All class attributes, not protocol parameters, for ReachTheGoal's reason: the server
    # imports the class and never sees the protocol object.
    CATCH_RADIUS = 0.02          # arrive within two KeyTrac presses of the tower, any direction
    TOWER_START = (0.0, 0.08)    # meters ahead at trial start
    TOWER_HEIGHT = 0.04
    FLOOR_Z = -0.05
    # The tower's base sits 2 mm BELOW the floor plane, never on it. Coplanar surfaces z-fight:
    # which one wins the depth test varies per pixel with the lowest bits of interpolation, so a
    # translucent tower resting exactly on the floor shimmers with blinking lines as it moves --
    # driver-dependent, seen on rig hardware and not reproducible on Mesa offscreen. Sinking the
    # base also keeps the box's bottom face below the floor, where the depth test removes it,
    # instead of drawing edge-on as a moving line.
    TOWER_SINK = 0.002
    WANDER_SIGMA = 0.02          # typical drift ~0.01 m/s: far slower than walking
    WANDER_BOUND = 0.03          # the tower stays within this of its start, so a stationary
                                 # subject is never handed a catch (0.08 - 0.03 > CATCH_RADIUS)
    DT = 1.0 / 60.0

    def __init__(self, cfg):
        super().__init__(cfg)

        self.run_parameters = self.get_run_parameter_defaults()
        self.protocol_parameters = self.get_protocol_parameter_defaults()

        self.use_server_side_state_dependent_control = True

    @staticmethod
    def server_side_state_dependent_control(server, previous_state, state_update):
        def fresh(key, default):
            return state_update.get(key, previous_state.get(key, default))

        if not fresh('chase_armed', 0):
            return state_update

        # First update after arming: stamp the trial's clock and wait for the next update.
        t0 = fresh('chase_t0', 0.0)
        now = time.time()
        if t0 <= 0.0:
            state_update['chase_t0'] = now
            return state_update

        t = now - t0
        n = int(fresh('chase_n', 0))
        if n <= 0 or t > n * ChaseTheTower.DT:     # past the timeout; the clock ends this trial
            return state_update

        xs, ys = _tower_path(int(fresh('chase_seed', 0)), n)
        i = min(int(t / ChaseTheTower.DT), n - 1)
        dx = fresh('x', 0.0) - xs[i]
        dy = fresh('y', 0.0) - ys[i]
        if dx * dx + dy * dy <= ChaseTheTower.CATCH_RADIUS ** 2:
            server.end_trial(reason='caught')
            state_update['chase_armed'] = 0        # one catch per arming
        return state_update

    def get_trial_parameters(self):
        super().get_trial_parameters()
        params = self.trial_protocol_parameters

        n = int(params['stim_time'] / self.DT) + 1
        xs, ys = _tower_path(int(params['seed']), n)
        t = np.arange(n) * self.DT

        self.trial_stim_parameters = [
            # The same floor as ReachTheGoal, so walking is visible as motion.
            {'name': 'CheckerboardFloor',
             'mean': 0.3, 'contrast': 0.5, 'center': (0, self.TOWER_START[1] / 2, self.FLOOR_Z),
             'side_length': (0.3, 0.3), 'patch_width': 0.02},
            # The quarry: a short translucent pillar whose x/y follow the wandering path. Sized
            # to CATCH_RADIUS so what you see is what the condition tests; based below the floor
            # plane so no face is coplanar with it (see TOWER_SINK).
            {'name': 'MovingBox',
             'x_length': self.CATCH_RADIUS / 2, 'y_length': self.CATCH_RADIUS / 2,
             'z_length': self.TOWER_HEIGHT,
             'color': [1, 0, 0, 0.6],
             'x': {'name': 'TVPairs', 'tv_pairs': list(zip(t, xs)), 'kind': 'linear'},
             'y': {'name': 'TVPairs', 'tv_pairs': list(zip(t, ys)), 'kind': 'linear'},
             'z': self.FLOOR_Z + self.TOWER_HEIGHT / 2 - self.TOWER_SINK},
        ]

    def load_stimuli(self, manager, multicall=None):
        # Arm the server side: the seed is the whole description of the path, and resetting
        # chase_t0 makes the control function stamp a fresh clock for this trial. An untargeted
        # call goes to the server's root node, where set_subject_state lives.
        manager.set_subject_state({'chase_armed': 1, 'chase_t0': 0.0,
                                   'chase_seed': int(self.trial_protocol_parameters['seed']),
                                   'chase_n': int(self.trial_protocol_parameters['stim_time']
                                                  / self.DT) + 1})
        super().load_stimuli(manager, multicall)

    def get_protocol_parameter_defaults(self):
        return {'pre_time': 0.5,
                'stim_time': 30.0,             # a timeout: catches usually come much sooner
                'tail_time': 0.5,
                'loco_pos_closed_loop': 1,

                'seed': [0, 1, 2, 3, 4]}

    def get_run_parameter_defaults(self):
        return {'num_trials': 5,
                'idle_color': 0.5,
                'pre_run_time': 0,
                'post_run_time': 0,
                'all_combinations': True,
                'randomize_order': True,
                # This protocol only means anything in closed loop, so tracking
                # comes pre-checked; untick it in the GUI to rehearse open loop.
                'do_loco': True}


class LinearTrackWithTowers(BaseProtocol):
    """
    Linear track with towers. Towers can be rotating or stationary, and can be sine or square wave gratings.
    """
    def __init__(self, cfg):
        super().__init__(cfg)

        self.run_parameters = self.get_run_parameter_defaults()
        self.protocol_parameters = self.get_protocol_parameter_defaults()

        self.use_server_side_state_dependent_control = True

    def process_input_parameters(self):
        super().process_input_parameters()

    def start_stimuli(self, manager, append_stim_frames=False, print_profile=True, multicall=None):
        # self.sleep, not time.sleep: a bare sleep cannot be interrupted, so Stop is not noticed
        # until the trial ends -- on a long track that is a long wait, and the same delay applies
        # to an error the server reports mid-trial. See BaseProtocol.sleep.

        # locomotion setting variables
        do_loco = self.run_parameters.get('do_loco', False)
        do_loco_closed_loop = do_loco and self.trial_protocol_parameters.get('loco_pos_closed_loop', False)
        save_pos_history = do_loco_closed_loop and self.save_metadata_flag
        
        manager.set_subject_state(state_update={'y_pos_modulo': self.trial_protocol_parameters['y_pos_modulo'], 
                                                'y_pos_offset': self.trial_protocol_parameters['y_pos_offset']})

        ### pre time
        self.sleep(self.trial_protocol_parameters['pre_time'])
        
        if multicall is None:
            multicall = MyMultiCall(manager)

        ### stim time
        # locomotion / closed loop
        if do_loco:
            multicall.target('locomotion').set_pos_0(loco_pos = {'x': None, 'y': None, 'z': None, 'theta': None, 'phi': None, 'roll': None}, 
                                                                  use_data_prev=True, write_log=self.save_metadata_flag)
        if do_loco_closed_loop:
            multicall.target('locomotion').loop_update_closed_loop_vars(update_x=True, update_y=True, update_z=True, update_theta=True, update_phi=True, update_roll=True)
            multicall.target('locomotion').loop_start_closed_loop()
        
        multicall.target('all').set_save_pos_history_flag(save_pos_history)
        multicall.target('all').start_stim(append_stim_frames=append_stim_frames)
        multicall.target('visual').corner_square_toggle_start()
        multicall()
        self.sleep(self.trial_protocol_parameters['stim_time'])

        ### tail time
        multicall = MyMultiCall(manager)
        multicall.target('all').stop_stim(print_profile=print_profile)
        multicall.target('visual').corner_square_toggle_stop()
        multicall.target('visual').corner_square_off()

        # locomotion / closed loop
        if do_loco_closed_loop:
            multicall.target('locomotion').loop_stop_closed_loop()
        if save_pos_history:
            multicall.target('all').save_pos_history_to_file(epoch_id=f'{self.num_trials_completed:03d}')

        multicall()

        self.sleep(self.trial_protocol_parameters['tail_time'])

    def get_trial_parameters(self):
        super().get_trial_parameters()

        # assert that all tower parameters are the same length
        if not (len(self.trial_protocol_parameters['tower_radius']) \
            == len(self.trial_protocol_parameters['tower_top_z']) \
            == len(self.trial_protocol_parameters['tower_bottom_z']) \
            == len(self.trial_protocol_parameters['tower_y_pos']) \
            == len(self.trial_protocol_parameters['tower_period']) \
            == len(self.trial_protocol_parameters['tower_angle']) \
            == len(self.trial_protocol_parameters['tower_mean']) \
            == len(self.trial_protocol_parameters['tower_contrast']) \
            == len(self.trial_protocol_parameters['tower_profile_sine']) \
            == len(self.trial_protocol_parameters['tower_rotating']) \
            == len(self.trial_protocol_parameters['tower_on_left'])):
            print('Error: tower parameters are not the same length.')
        
        n_repeat_track = int(self.trial_protocol_parameters['n_repeat_track'])
        n_towers = len(self.trial_protocol_parameters['tower_radius'])

        track_width = float(self.trial_protocol_parameters['track_width']) / 100 # m
        track_patch_width = float(self.trial_protocol_parameters['track_patch_width']) / 100 # m
        track_length = float(self.trial_protocol_parameters['track_length']) / 100 # m
        track_z_level = float(self.trial_protocol_parameters['track_z_level']) / 100 # m
        
        tower_radius = np.array(self.trial_protocol_parameters['tower_radius'], dtype=float) / 100 # m
        tower_top_z = np.array(self.trial_protocol_parameters['tower_top_z'], dtype=float) / 100 # m
        tower_bottom_z = np.array(self.trial_protocol_parameters['tower_bottom_z'], dtype=float) / 100 # m
        tower_y_pos = np.array(self.trial_protocol_parameters['tower_y_pos'], dtype=float) / 100 # m
        tower_period = np.array(self.trial_protocol_parameters['tower_period'], dtype=float) # deg
        tower_angle = np.array(self.trial_protocol_parameters['tower_angle'], dtype=float) # deg

        tower_height = tower_top_z - tower_bottom_z
        tower_z_pos = tower_top_z/2 + tower_bottom_z/2
        tower_x_pos_l = -track_width/2 - tower_radius
        tower_x_pos_r = +track_width/2 + tower_radius

        # Create stimpack.visual_stim trial parameters dictionary

        track = {'name':  'CheckerboardFloor',
                'mean': self.trial_protocol_parameters['track_color_mean'],
                'contrast': self.trial_protocol_parameters['track_color_contrast'],
                'center': (0, track_length * n_repeat_track / 2, track_z_level),
                'side_length': (track_width, track_length * n_repeat_track),
                'patch_width': track_patch_width}
        
        self.trial_stim_parameters = [track]

        for r in range(n_repeat_track):
            for i in range(n_towers):
                tower_x_pos = tower_x_pos_l[i] if self.trial_protocol_parameters['tower_on_left'][i] else tower_x_pos_r[i]
                tower_y_pos_r = tower_y_pos[i] + r * track_length
                tower = {'name': 'CylindricalGrating' if not self.trial_protocol_parameters['tower_rotating'][i] else 'RotatingGrating',
                        'period': tower_period[i],
                        'mean': self.trial_protocol_parameters['tower_mean'][i], 
                        'contrast': self.trial_protocol_parameters['tower_contrast'][i],
                        'offset': 0.0,
                        'grating_angle': tower_angle[i],
                        'profile': 'sine' if self.trial_protocol_parameters['tower_profile_sine'][i] else 'square',
                        'color': [1, 1, 1, 1],
                        'cylinder_radius': tower_radius[i],
                        'cylinder_location': (tower_x_pos, tower_y_pos_r, tower_z_pos[i]),
                        'cylinder_height': tower_height[i],
                        'theta': 0,
                        'phi': 0,
                        'angle': 0}
                if self.trial_protocol_parameters['tower_rotating'][i]:
                    tower['rate'] = tower_period[i]
                self.trial_stim_parameters.append(tower)

    @staticmethod
    def server_side_state_dependent_control(server, previous_state:dict, state_update:dict) -> dict:
        y = state_update.get('y', previous_state.get('y', 0))
        y_pos_modulo = state_update.get('y_pos_modulo', previous_state.get('y_pos_modulo', 400)) / 100  # cm -> meters
        y_pos_offset = state_update.get('y_pos_offset', previous_state.get('y_pos_offset', 400)) / 100  # cm -> meters
        
        state_update['y'] = (y % y_pos_modulo) + y_pos_offset

        return state_update

    def load_stimuli(self, manager:MySocketClient, multicall:MyMultiCall|None=None):
        if multicall is None:
            multicall = MyMultiCall(manager)
        
        params_to_print = {k:self.trial_protocol_parameters[k] for k in self.persistent_parameters['variable_protocol_parameter_names']}
        multicall.print_on_server(f'{params_to_print}')

        super().load_stimuli(manager, multicall)

    def get_protocol_parameter_defaults(self):
        return {'pre_time': 1.0,
                'stim_time': 10.0,
                'tail_time': 1.0,
                'loco_pos_closed_loop': 1,

                'track_z_level': -5,
                'track_length': 400,
                'track_width': 40,
                'track_patch_width': 5,
                'track_color_mean': 0.3,
                'track_color_contrast': 1.0,

                'tower_radius':       ( 15,  15,   5,   5,  10,  10,  10,  10,   8,   8),
                'tower_bottom_z':     (-10, -10, -10, -10, -10, -10, -10, -10, -10, -10),
                'tower_top_z':        ( 30,  30,  40,  40,  20,  20,  40,  40,  50,  50),
                'tower_y_pos':        ( 80,  80, 160, 160, 240, 240, 320, 320, 400, 400),
                'tower_on_left':      (   1,  0,   1,   0,   1,   0,   1,   0,   1,   0),
                'tower_angle':        (   0,180,  45, -45,  90,  90,  60, -60, -30,  30),
                'tower_period':       ( 30,  30,  60,  60,  45,  45,  30,  30,  60,  60),
                'tower_mean':         (0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5),
                'tower_contrast':     (  1,   1,   1,   1, 0.6, 0.6,   1,   1,   1,   1),
                'tower_profile_sine': (  0,   0,   1,   1,   1,   1,   0,   0,   1,   1),
                'tower_rotating':     (  0,   0,   1,   1,   0,   0,   1,   1,   0,   0),

                'n_repeat_track': 3,
                'y_pos_modulo': 400,
                'y_pos_offset': 400
                }

    def get_run_parameter_defaults(self):
        return {'num_trials': 40,
                'idle_color': 0.5,
                'pre_run_time': 0,  # seconds to wait before starting the run
                'post_run_time': 0,  # seconds to wait after the run
                'all_combinations': True,
                'randomize_order': True,
                # This protocol only means anything in closed loop, so tracking
                # comes pre-checked; untick it in the GUI to rehearse open loop.
                'do_loco': True}


# %% Auditory and audiovisual protocol classes
#
# These need a server with an audio module. On a rig without one, each load is reported back as a
# warning and the run continues in silence -- the same way a protocol that asks for opto behaves on
# a rig with no DAQ. The client deduplicates those messages, so it is one line per run, not per
# trial.
#
# The waveforms are ported from the multistim project (flystim/audio.py, via yh_audio_protocol);
# the default volumes here are lower than its 1.0, because these are demonstrations that somebody
# will run on a laptop.

class SineSong(BaseProtocol):
    """
    A constant-frequency tone: Drosophila sine song.

    The simplest audio protocol there is, and the one to copy when writing your own. Note that the
    stimulus descriptor is the same shape a visual protocol builds -- it just names a target.
    """
    def __init__(self, cfg):
        super().__init__(cfg)

        self.run_parameters = self.get_run_parameter_defaults()
        self.protocol_parameters = self.get_protocol_parameter_defaults()

    def get_trial_parameters(self):
        super().get_trial_parameters()

        # 'target' is what sends this to the audio module rather than the screens. Without it a
        # descriptor goes to 'visual', which is what every descriptor meant before targets existed.
        self.trial_stim_parameters = {'name': 'SineSong',
                                      'target': 'audio',
                                      'duration': self.trial_protocol_parameters['stim_time'],
                                      'freq': self.trial_protocol_parameters['freq'],
                                      'volume': self.trial_protocol_parameters['volume']}

    def get_protocol_parameter_defaults(self):
        return {'pre_time': 0.5,
                'stim_time': 1.0,
                'tail_time': 1.0,

                'freq': [225.0, 120.0, 450.0, 900.0],
                'volume': 0.5,
                }

    def get_run_parameter_defaults(self):
        return {'num_trials': 40,
                'idle_color': 0.5,
                'pre_run_time': 0,  # seconds to wait before starting the run
                'post_run_time': 0,  # seconds to wait after the run
                'all_combinations': True,
                'randomize_order': True}

# %%

class PulseSong(BaseProtocol):
    """
    A train of Gaussian-windowed pulses: Drosophila pulse song.

    ``pcycle`` is the pulse and ``ncycle`` the gap after it, so the inter-pulse interval -- the
    feature the fly actually discriminates -- is their sum. The realised trial length is quantised
    to a whole number of those cycles, so it is a little short of ``stim_time``; the audio module
    logs what was really played.
    """
    def __init__(self, cfg):
        super().__init__(cfg)

        self.run_parameters = self.get_run_parameter_defaults()
        self.protocol_parameters = self.get_protocol_parameter_defaults()

    def get_trial_parameters(self):
        super().get_trial_parameters()

        self.trial_stim_parameters = {'name': 'PulseSong',
                                      'target': 'audio',
                                      'duration': self.trial_protocol_parameters['stim_time'],
                                      'freq': self.trial_protocol_parameters['freq'],
                                      'volume': self.trial_protocol_parameters['volume'],
                                      'pcycle': self.trial_protocol_parameters['pcycle'],
                                      'ncycle': self.trial_protocol_parameters['ncycle']}

    def get_protocol_parameter_defaults(self):
        return {'pre_time': 0.5,
                'stim_time': 1.0,
                'tail_time': 1.0,

                'freq': [225.0, 120.0],
                'volume': 0.5,
                'pcycle': 0.016,
                'ncycle': [0.020, 0.035, 0.050],   # inter-pulse interval, the discriminated feature
                }

    def get_run_parameter_defaults(self):
        return {'num_trials': 40,
                'idle_color': 0.5,
                'pre_run_time': 0,  # seconds to wait before starting the run
                'post_run_time': 0,  # seconds to wait after the run
                'all_combinations': True,
                'randomize_order': True}

# %%

class AudiovisualPairing(BaseProtocol):
    """
    A pulse song and a moving patch, loaded together and started together.

    What a list-valued ``trial_stim_parameters`` is for once descriptors can name a target: the two
    stimuli go to different modules, in one batch, and are started by the same
    ``target('all').start_stim()`` -- so they share a trial without either protocol knowing about
    the other. Both sets of parameters are saved on the trial, under ``stim0_`` and ``stim1_``.
    """
    def __init__(self, cfg):
        super().__init__(cfg)

        self.run_parameters = self.get_run_parameter_defaults()
        self.protocol_parameters = self.get_protocol_parameter_defaults()

    def get_trial_parameters(self):
        super().get_trial_parameters()

        center = self.adjust_center(self.trial_protocol_parameters['center'])
        stim_time = self.trial_protocol_parameters['stim_time']
        speed = self.trial_protocol_parameters['speed']
        angle = self.trial_protocol_parameters['angle']

        # Sweep the patch across the visual field over the trial, centered on the rig's own center.
        start_theta = center[0] - speed * stim_time / 2
        end_theta = center[0] + speed * stim_time / 2

        self.trial_stim_parameters = [
            {'name': 'MovingPatch',
             'width': 10.0,
             'height': 10.0,
             'sphere_radius': 1.0,
             'color': self.trial_protocol_parameters['intensity'],
             'theta': {'name': 'TVPairs',
                       'tv_pairs': [(0, start_theta), (stim_time, end_theta)],
                       'kind': 'linear'},
             'phi': center[1],
             'angle': angle},

            {'name': 'PulseSong',
             'target': 'audio',
             'duration': stim_time,
             'freq': self.trial_protocol_parameters['freq'],
             'volume': self.trial_protocol_parameters['volume']},
        ]

    def get_protocol_parameter_defaults(self):
        return {'pre_time': 0.5,
                'stim_time': 2.0,
                'tail_time': 1.0,

                'intensity': 0.0,
                'center': (0, 0),
                'speed': 60.0,
                'angle': 0.0,

                'freq': [225.0, 120.0],
                'volume': 0.5,
                }

    def get_run_parameter_defaults(self):
        return {'num_trials': 40,
                'idle_color': 0.5,
                'pre_run_time': 0,  # seconds to wait before starting the run
                'post_run_time': 0,  # seconds to wait after the run
                'all_combinations': True,
                'randomize_order': True}
