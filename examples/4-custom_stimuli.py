#!/usr/bin/env python3
from stimpack.visual_stim.stim_server import launch_stim_server
from stimpack.visual_stim.screen import Screen, SubScreen

from time import sleep


def main():
    # This must contain a file called stimuli.py that defines the custom stimuli
    PATH_TO_CUSTOM_STIMULI = '/home/jblvn/Code/stimpack/examples/custom_visual_stimuli/'

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

    # Import the custom stimulus module
    manager.import_stim_module(PATH_TO_CUSTOM_STIMULI)

    # Set the background color of the screen
    manager.set_idle_background(0.5)

    # Present 5 epochs of the stimulus
    rotation = 0
    for i in range(200):
        # Load a stimulus
        manager.load_stim(name='ShowImage', image_path='/home/jblvn/Code/stimpack/examples/assets/cactus.png', vertical_extent=30, horizontal_extent=30, rotate=rotation)
        rotation+=10

        # Pre time: wait for 0.5 second

        # Start the stimulus
        manager.start_stim()

        # Stim time: client waits for 4 seconds while server shows the stimulus
        sleep(0.2)

        # Tail time: wait for 0.5 second at the end of the stimulus

        # Stop the stimulus
        manager.stop_stim(print_profile=True)


if __name__ == '__main__':
    main()
