#!/usr/bin/env python3
from stimpack.visual_stim.stim_server import launch_stim_server
from stimpack.visual_stim.screen import Screen
from stimpack.visual_stim.draw import draw_screens

from time import sleep


def main():
    
    stim_duration = 2
    iti = 2
    
    screen = Screen(fullscreen=False, server_number=0, id=0, vsync=False)

    # draw_screens(screen)

    manager = launch_stim_server(screen)


    for i in range(2):
        manager.load_stim(name='RandomBars', period=20, width=5, vert_extent=80, theta_offset=0, background=0.5,
                          distribution_data=None, update_rate=4.0, start_seed=10,
                          color=[1, 1, 1, 1], cylinder_radius=1, theta=0, phi=0, angle=0.0, cylinder_location=(0, 0, 0), hold=True)

        sleep(iti)

        manager.start_stim()
        sleep(stim_duration)

        manager.stop_stim(print_profile=True)
        sleep(iti)

if __name__ == '__main__':
    main()
