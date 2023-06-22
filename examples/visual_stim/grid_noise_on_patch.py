#!/usr/bin/env python3
from stimpack.visual_stim.stim_server import launch_stim_server
from stimpack.visual_stim.screen import Screen
import numpy as np

from time import sleep


def main():
    manager = launch_stim_server(Screen(fullscreen=False, vsync=False))

    manager.load_stim(name='ConstantBackground', color=[0.5, 0.5, 0.5, 1.0], side_length=100)

    distribution_data = {'name': 'Ternary',
                         'rand_min': 0.0,
                         'rand_max': 1.0}
    #
    # theta_trajectory = {'name': 'tv_pairs',
    #                     'tv_pairs': [(0, -45), (4, 45)],
    #                     'kind': 'linear'}

    manager.load_stim(name='RandomGridOnSphericalPatch', patch_width=5, patch_height=5, distribution_data=distribution_data, update_rate=0.0, start_seed=0,
                      width=60, height=60, sphere_radius=1.1, color=[1, 0, 1, 1], theta=0, phi=0, angle=0, hold=True, rgb_texture=True)

    # manager.set_global_fly_pos(0, -2, 0)

    # manager.load_stim(name='RandomGrid', patch_width=5, patch_height=5, cylinder_vertical_extent=80, cylinder_angular_extent=120,
    #                   distribution_data=distribution_data, update_rate=0, start_seed=0,
    #                   color=[1, 1, 1, 1], cylinder_radius=1.1, theta=90, phi=0, angle=0.0, hold=True, rgb_texture=False)

    # manager.load_stim(name='MovingSpot', radius=2.5, sphere_radius=1, color=[1, 0, 0, 1], theta=5, phi=-21.5, hold=True)
    #
    # manager.load_stim(name='MovingSpot', radius=2.5, sphere_radius=1, color=[1, 0, 0, 1], theta=5, phi=2.5, hold=True)

    sleep(1)

    manager.start_stim()
    sleep(10)

    manager.stop_stim(print_profile=True)
    sleep(1)

if __name__ == '__main__':
    main()
