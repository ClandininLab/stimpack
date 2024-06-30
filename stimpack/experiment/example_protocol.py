#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import numpy as np
from time import sleep
import stimpack.rpc.multicall
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

    def get_epoch_parameters(self):
        super().get_epoch_parameters()
        
        center = self.adjust_center(self.epoch_protocol_parameters['center'])
        centerX = center[0]
        centerY = center[1]

        self.epoch_stim_parameters = {'name': 'RotatingGrating',
                                      'period': self.epoch_protocol_parameters['period'],
                                      'rate': self.epoch_protocol_parameters['rate'],
                                      'color': [1, 1, 1, 1],
                                      'mean': self.epoch_protocol_parameters['mean'],
                                      'contrast': self.epoch_protocol_parameters['contrast'],
                                      'angle': self.epoch_protocol_parameters['angle'],
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
        return {'num_epochs': 40,
                'idle_color': 0.5,
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
        if center is None: center = self.epoch_protocol_parameters['center']
        if angle is None: angle = self.epoch_protocol_parameters['angle']
        if speed is None: speed = self.epoch_protocol_parameters['speed']
        if width is None: width = self.epoch_protocol_parameters['width']
        if height is None: height = self.epoch_protocol_parameters['height']
        if color is None: color = self.epoch_protocol_parameters['color']
        if ellipse is None: ellipse = self.epoch_protocol_parameters['ellipse'] if 'ellipse' in self.epoch_protocol_parameters else False
        if render_on_cylinder is None: render_on_cylinder = self.epoch_protocol_parameters['render_on_cylinder'] if 'render_on_cylinder' in self.epoch_protocol_parameters else False

        center = self.adjust_center(center)

        centerX = center[0]
        centerY = center[1]
        stim_time = self.epoch_protocol_parameters['stim_time']
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

    def get_epoch_parameters(self):
        super().get_epoch_parameters()

        # Create stimpack.visual_stim epoch parameters dictionary
        self.epoch_stim_parameters = self.get_moving_patch_parameters(center=self.epoch_protocol_parameters['center'],
                                                                angle=self.epoch_protocol_parameters['angle'],
                                                                speed=self.epoch_protocol_parameters['speed'],
                                                                width=self.epoch_protocol_parameters['width_height'][0],
                                                                height=self.epoch_protocol_parameters['width_height'][1],
                                                                color=self.epoch_protocol_parameters['intensity'])

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
        return {'num_epochs': 40,
                'idle_color': 0.5,
                'all_combinations': True,
                'randomize_order': True}

#%%

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
        
        # locomotion setting variables
        do_loco = self.run_parameters.get('do_loco', False)
        do_loco_closed_loop = do_loco and self.epoch_protocol_parameters.get('loco_pos_closed_loop', False)
        save_pos_history = do_loco_closed_loop and self.save_metadata_flag
        
        manager.set_subject_state(state_update={'y_pos_modulo': self.epoch_protocol_parameters['y_pos_modulo'], 
                                                'y_pos_offset': self.epoch_protocol_parameters['y_pos_offset']})

        ### pre time
        sleep(self.epoch_protocol_parameters['pre_time'])
        
        if multicall is None:
            multicall = stimpack.rpc.multicall.MyMultiCall(manager)

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
        sleep(self.epoch_protocol_parameters['stim_time'])

        ### tail time
        multicall = stimpack.rpc.multicall.MyMultiCall(manager)
        multicall.target('all').stop_stim(print_profile=print_profile)
        multicall.target('visual').corner_square_toggle_stop()
        multicall.target('visual').corner_square_off()

        # locomotion / closed loop
        if do_loco_closed_loop:
            multicall.target('locomotion').loop_stop_closed_loop()
        if save_pos_history:
            multicall.target('all').save_pos_history_to_file(epoch_id=f'{self.num_epochs_completed:03d}')

        multicall()

        sleep(self.epoch_protocol_parameters['tail_time'])

    def get_epoch_parameters(self):
        super().get_epoch_parameters()

        # assert that all tower parameters are the same length
        if not (len(self.epoch_protocol_parameters['tower_radius']) \
            == len(self.epoch_protocol_parameters['tower_top_z']) \
            == len(self.epoch_protocol_parameters['tower_bottom_z']) \
            == len(self.epoch_protocol_parameters['tower_y_pos']) \
            == len(self.epoch_protocol_parameters['tower_period']) \
            == len(self.epoch_protocol_parameters['tower_angle']) \
            == len(self.epoch_protocol_parameters['tower_mean']) \
            == len(self.epoch_protocol_parameters['tower_contrast']) \
            == len(self.epoch_protocol_parameters['tower_profile_sine']) \
            == len(self.epoch_protocol_parameters['tower_rotating']) \
            == len(self.epoch_protocol_parameters['tower_on_left'])):
            print('Error: tower parameters are not the same length.')
        
        n_repeat_track = int(self.epoch_protocol_parameters['n_repeat_track'])
        n_towers = len(self.epoch_protocol_parameters['tower_radius'])

        track_width = float(self.epoch_protocol_parameters['track_width']) / 100 # m
        track_patch_width = float(self.epoch_protocol_parameters['track_patch_width']) / 100 # m
        track_length = float(self.epoch_protocol_parameters['track_length']) / 100 # m
        track_z_level = float(self.epoch_protocol_parameters['track_z_level']) / 100 # m
        
        tower_radius = np.array(self.epoch_protocol_parameters['tower_radius'], dtype=float) / 100 # m
        tower_top_z = np.array(self.epoch_protocol_parameters['tower_top_z'], dtype=float) / 100 # m
        tower_bottom_z = np.array(self.epoch_protocol_parameters['tower_bottom_z'], dtype=float) / 100 # m
        tower_y_pos = np.array(self.epoch_protocol_parameters['tower_y_pos'], dtype=float) / 100 # m
        tower_period = np.array(self.epoch_protocol_parameters['tower_period'], dtype=float) # deg
        tower_angle = np.array(self.epoch_protocol_parameters['tower_angle'], dtype=float) # deg

        tower_height = tower_top_z - tower_bottom_z
        tower_z_pos = tower_top_z/2 + tower_bottom_z/2
        tower_x_pos_l = -track_width/2 - tower_radius
        tower_x_pos_r = +track_width/2 + tower_radius

        # Create stimpack.visual_stim epoch parameters dictionary

        track = {'name':  'CheckerboardFloor',
                'mean': self.epoch_protocol_parameters['track_color_mean'],
                'contrast': self.epoch_protocol_parameters['track_color_contrast'],
                'center': (0, track_length * n_repeat_track / 2, track_z_level),
                'side_length': (track_width, track_length * n_repeat_track),
                'patch_width': track_patch_width}
        
        self.epoch_stim_parameters = [track]

        for r in range(n_repeat_track):
            for i in range(n_towers):
                tower_x_pos = tower_x_pos_l[i] if self.epoch_protocol_parameters['tower_on_left'][i] else tower_x_pos_r[i]
                tower_y_pos_r = tower_y_pos[i] + r * track_length
                tower = {'name': 'CylindricalGrating' if not self.epoch_protocol_parameters['tower_rotating'][i] else 'RotatingGrating',
                        'period': tower_period[i],
                        'mean': self.epoch_protocol_parameters['tower_mean'][i], 
                        'contrast': self.epoch_protocol_parameters['tower_contrast'][i],
                        'offset': 0.0,
                        'grating_angle': tower_angle[i],
                        'profile': 'sine' if self.epoch_protocol_parameters['tower_profile_sine'][i] else 'square',
                        'color': [1, 1, 1, 1],
                        'cylinder_radius': tower_radius[i],
                        'cylinder_location': (tower_x_pos, tower_y_pos_r, tower_z_pos[i]),
                        'cylinder_height': tower_height[i],
                        'theta': 0,
                        'phi': 0,
                        'angle': 0}
                if self.epoch_protocol_parameters['tower_rotating'][i]:
                    tower['rate'] = tower_period[i]
                self.epoch_stim_parameters.append(tower)

    def server_side_state_dependent_control(manager, previous_state:dict, state_update:dict) -> dict:
        y = state_update.get('y', previous_state.get('y', 0))
        y_pos_modulo = state_update.get('y_pos_modulo', previous_state.get('y_pos_modulo', 400)) / 100  # cm -> meters
        y_pos_offset = state_update.get('y_pos_offset', previous_state.get('y_pos_offset', 400)) / 100  # cm -> meters
        
        state_update['y'] = (y % y_pos_modulo) + y_pos_offset

        return state_update

    def load_stimuli(self, client, multicall=None):
        if multicall is None:
            multicall = stimpack.rpc.multicall.MyMultiCall(client)
        
        params_to_print = {k:self.epoch_protocol_parameters[k] for k in self.persistent_parameters['variable_protocol_parameter_names']}
        multicall.print_on_server(f'{params_to_print}')

        super().load_stimuli(client, multicall)

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
        return {'num_epochs': 40,
                'idle_color': 0.5,
                'all_combinations': True,
                'randomize_order': True}

