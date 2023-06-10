#!/usr/bin/env python3
from stimpack.visual_stim.stim_server import launch_stim_server
from stimpack.visual_stim.screen import Screen

from time import sleep


def main():
    manager = launch_stim_server(Screen(fullscreen=False, server_number=0, id=0, vsync=True))

    # manager.load_stim(name='ConstantBackground', color=[0.5, 0.5, 0.5, 1.0], side_length=100)

    # manager.load_stim(name='MovingDotField', n_points=200, point_size=20, sphere_radius=1, color=[0, 1, 0, 1],
    #                   speed=60, signal_direction=0, coherence=1.0, random_seed=0, sphere_pitch=45, hold=True)

    manager.load_stim(name='MovingDotField_Cylindrical', n_points=200, point_size=80, cylinder_radius=1, color=[1, 0, 0, 1],
                      speed=60, signal_direction=45, coherence=1.0, random_seed=0, cylinder_pitch=45, phi_limits=[45, 135], hold=True)

    # n_points = 50

    # x_locations = list(np.random.uniform(-2, 2, n_points))
    # y_locations = list(np.random.uniform(0, 8, n_points))
    # z_locations = list(np.random.uniform(-2, 2, n_points))
    #
    # point_locations = [x_locations, y_locations, z_locations]
    #
    # velocity_y = -0.5  # m/sec
    # y_offset = {'name': 'TVPairs',
    #             'tv_pairs': [(0, 0), (6, 6*velocity_y)],
    #             'kind': 'linear'}
    # manager.load_stim(name='ProgressiveStarfield', point_size=20, color=[0, 0, 0, 1],
    #                   point_locations=point_locations,
    #                   y_offset=y_offset, hold=True)
    #

    sleep(1)

    manager.start_stim()
    sleep(6)

    manager.stop_stim(print_profile=True)
    sleep(1)

if __name__ == '__main__':
    main()
