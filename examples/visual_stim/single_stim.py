#!/usr/bin/env python3
from stimpack.visual_stim.stim_server import launch_stim_server
from stimpack.visual_stim.screen import Screen

from time import sleep

import sys


def main(stim_name):
    manager = launch_stim_server(Screen(fullscreen=False, server_number = 0, id = 0, vsync=False, square_loc=(-1.0, -1.0), square_size=(0.25, 0.25)))

    manager.load_stim(name=stim_name)

    sleep(0.5)

    manager.start_stim()
    sleep(4)

    manager.stop_stim(print_profile=True)
    sleep(0.5)

if __name__ == '__main__':
    stim_name = sys.argv[1]
    main(stim_name)
