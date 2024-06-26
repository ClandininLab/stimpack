#!/usr/bin/env python3
from stimpack.visual_stim.stim_server import launch_stim_server
from stimpack.visual_stim.screen import Screen

from time import sleep


def main():
    manager = launch_stim_server(Screen(fullscreen=False, vsync=False))

    manager.load_stim(name='ConstantBackground', color=[0.5, 0.5, 0.5, 1.0], side_length=100)

    loom_trajectory = {'name': 'Loom',
                       'rv_ratio': 0.08,
                       'stim_time': 4,
                       'start_size': 3,
                       'end_size': 90}

    color_trajectory = {'name': 'Sinusoid',
                        'temporal_frequency': 2,
                        'amplitude': 1,
                        'offset': 1}

    manager.load_stim(name='MovingSpot', radius=loom_trajectory, sphere_radius=1, color=color_trajectory, theta=0, phi=0, hold=True)

    sleep(1)

    manager.start_stim()
    sleep(4)

    manager.stop_stim(print_profile=True)
    sleep(1)

if __name__ == '__main__':
    main()
