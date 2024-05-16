#!/usr/bin/env python3
from stimpack.visual_stim.stim_server import launch_stim_server
from stimpack.visual_stim.screen import Screen, SubScreen

from time import sleep


def main():
    # Each available display is assigned a unique monitor_id, in ascending order
    monitor_id = 0

    # Create the subscreen object which controls the viewport and perspective of the stimulus
    # pa, pb, pc are physical screen coordinates, relative to viewer (see README.md for more details)
    # ll, width, height are viewport coordinates
    # These coordinates provide a 60 degree visual angle checkerboard stimulus
    subscreen = SubScreen(pa=(-1, 1.73, -1),
                          pb=(1, 1.73, -1),
                          pc=(-1, 1.73, 1 ),

                          viewport_ll=(-1, -1),
                          viewport_width=2,
                          viewport_height=2)
    
    # Initialize the screen object with the subscreen, which is handled
    # asynchronously by the stim server
    screen = Screen(subscreens=[subscreen],
                    display_index=monitor_id,
                    fullscreen=True,
                    vsync=True)


    # Launch the stim server
    manager = launch_stim_server(screen)
    sleep(2)

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
