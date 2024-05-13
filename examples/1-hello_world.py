#!/usr/bin/env python3
from stimpack.visual_stim.stim_server import launch_stim_server
from stimpack.visual_stim.screen import Screen

from time import sleep


def main():
    # Initialize your display canvas with the default a default screen server
    screen = Screen(fullscreen=False, vsync=True)
    
    # Launch the stim server
    manager = launch_stim_server(screen)

    # Set the background color of the screen
    manager.set_idle_background(0.5)

    # Present 5 epochs of the stimulus
    for i in range(5):
        # Load a stimulus
        manager.load_stim(name='Checkerboard')

        # Pre time: wait for 0.5 second
        sleep(1.5)

        # Start the stimulus
        manager.start_stim()

        # Stim time: client waits for 4 seconds while server shows the stimulus
        sleep(2)

        # Tail time: wait for 0.5 second at the end of the stimulus
        sleep(0.5)

        # Stop the stimulus
        manager.stop_stim(print_profile=True)


if __name__ == '__main__':
    main()
