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
        manager.load_stim(name='RotatingGrating', rate=60, hold_duration=1, period=60, mean=0.5, contrast=1.0, offset=0.0, profile='square',
                        color=[1, 1, 1, 1], cylinder_radius=1.1, cylinder_height=10, theta=0, phi=0, angle=0, hold=True)

        sleep(iti)

        manager.start_stim()
        sleep(stim_duration)

        manager.stop_stim(print_profile=True)
        sleep(iti)

if __name__ == '__main__':
    main()
