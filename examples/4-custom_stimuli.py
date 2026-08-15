#!/usr/bin/env python3
from stimpack.visual_stim.stim_server import launch_stim_server
from stimpack.visual_stim.screen import Screen, SubScreen

import os.path
from time import sleep

# Absolute paths: the server resolves relative paths against the configured labpack (if one is
# configured), not against this script -- so relative paths break the moment a machine has a
# labpack set up.
HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    # This must contain a file called stimuli.py that defines the custom stimuli
    PATH_TO_CUSTOM_STIMULI = os.path.join(HERE, 'example_custom_module')

    # Initialize your display canvas
    subscreen = SubScreen(pa=(-1, 1, -1),
                          pb=(1, 1, -1),
                          pc=(-1, 1, 1 ),

                          viewport_ll=(-1, -1),
                          viewport_width=2,
                          viewport_height=2)


    screen = Screen(subscreens=[subscreen],
                    display_index=0,
                    fullscreen=True,
                    vsync=True)

    # Launch the stim server
    manager = launch_stim_server(screen)
    sleep(2)

    # Import the custom stimulus module
    manager.import_stim_module(PATH_TO_CUSTOM_STIMULI)

    # Set the background color of the screen
    manager.set_idle_background(0.5)

    # Present 200 trials, rotating the image a little each time
    rotation = 0
    for i in range(200):
        # Load a stimulus - here ShowImage is a new stimulus class found within the custom module directory
        manager.load_stim(name='ShowImage', image_path=os.path.join(HERE, 'assets', 'cactus.png'), vertical_extent=30, horizontal_extent=30, rotate=rotation)
        rotation+=15

        # Start the stimulus
        manager.start_stim()

        # Stim time: client waits 0.1 seconds while the server shows the stimulus
        sleep(0.1)

        # Stop the stimulus
        manager.stop_stim(print_profile=True)


if __name__ == '__main__':
    main()
