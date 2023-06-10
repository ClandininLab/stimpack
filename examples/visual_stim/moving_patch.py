#!/usr/bin/env python3
from stimpack.visual_stim.stim_server import launch_stim_server
from stimpack.visual_stim.screen import Screen
from time import sleep


def main():
    manager = launch_stim_server(Screen(fullscreen=False, server_number=0, id=0, vsync=False))

    manager.load_stim(name='ConstantBackground', color=[0.5, 0.5, 0.5, 1.0], side_length=100)

    theta_trajectory = {'name': 'TVPairs',
                        'tv_pairs': [(0, -45), (4, 45)],
                        'kind': 'linear'}

    # color_trajectory = {'name': 'Sinusoid',
    #                     'temporal_frequency': 2,
    #                     'amplitude': 1,
    #                     'offset': 1}

    color_trajectory = {'name': 'TVPairs',
                        'tv_pairs': [(0, (0, 0, 0, 1)), (1, (0, 0, 0, 0)), (2, (0, 0, 0, 1))],
                        'kind': 'linear'}


    manager.load_stim(name='MovingSpot', radius=5, sphere_radius=1, color=color_trajectory, theta=theta_trajectory, phi=0, hold=True)


    sleep(1)

    manager.start_stim()
    sleep(4)

    manager.stop_stim(print_profile=True)
    sleep(1)

if __name__ == '__main__':
    main()
