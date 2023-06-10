#!/usr/bin/env python3

# Example client program that walks through all available stimuli.

from stimpack.visual_stim.stim_server import launch_stim_server
from stimpack.visual_stim.screen import Screen

from time import sleep


def main():
    manager = launch_stim_server(Screen(fullscreen=False, server_number=0, id=0, vsync=True))

    stims = ['ConstantBackground', 'Floor', 'MovingSpot', 'MovingPatch', 'CylindricalGrating',
             'RotatingGrating', 'RandomBars', 'RandomGrid', 'Checkerboard', 'Tower', 'TexturedGround', 'HorizonCylinder', 'Forest',
             'MovingDotField']

    for stim in stims:
        manager.load_stim(stim)
        sleep(500e-3)

        manager.start_stim()
        sleep(2.5)

        manager.stop_stim(print_profile=True)
        sleep(500e-3)

if __name__ == '__main__':
    main()
