#!/usr/bin/env python3
from stimpack.visual_stim.stim_server import launch_stim_server
from stimpack.visual_stim.screen import Screen

from time import sleep


def main():
    stim_time = 4
    
    x_trajectory = {'name': 'TVPairs',
                    'tv_pairs': [(0, -2), (stim_time, 2)],
                    'kind': 'linear'}
    y_trajectory = {'name': 'TVPairs',
                    'tv_pairs': [(0, 4), (stim_time, 6)],
                    'kind': 'linear'}
    z_trajectory = {'name': 'TVPairs',
                    'tv_pairs': [(0, -2), (stim_time, 2)],
                    'kind': 'linear'}

    yaw_trajectory = {'name': 'TVPairs',
                        'tv_pairs': [(0, 0), (stim_time, 90*stim_time)],
                        'kind': 'linear'}
    pitch_trajectory   = {'name': 'TVPairs',
                        'tv_pairs': [(0, 0), (stim_time, 90*stim_time)],
                        'kind': 'linear'}
    roll_trajectory = {'name': 'TVPairs',
                        'tv_pairs': [(0, 0), (stim_time, 0)],
                        'kind': 'linear'}

    manager = launch_stim_server(Screen(fullscreen=False, server_number=0, id=0, vsync=False)) #,
                                 # other_stim_module_paths=[])

    manager.load_stim(name='ConstantBackground', color=[0.5, 0.5, 0.5, 1.0], side_length=100)

    manager.load_stim(name='MovingEllipsoid', x_length=2, y_length=1, z_length=1, color=None, 
                                        x=x_trajectory, y=y_trajectory, z=z_trajectory, 
                                        yaw=yaw_trajectory, pitch=pitch_trajectory, roll=roll_trajectory, 
                                        n_subdivisions=6, hold=True)

    sleep(1)

    manager.start_stim()
    sleep(stim_time)
 
    manager.stop_stim(print_profile=True)
    sleep(1)

if __name__ == '__main__':
    main()
