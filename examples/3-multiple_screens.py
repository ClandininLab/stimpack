#!/usr/bin/env python3
import numpy as np
from stimpack.visual_stim.stim_server import launch_stim_server
from stimpack.visual_stim.screen import Screen, SubScreen

from time import sleep


def main():
    # Make two subscreen / screen objects at 90 degrees to one another
    monitor_id = 1
    subscreen_1 = SubScreen(pa=(-1, 1, -1),
                          pb=(1, 1, -1),
                          pc=(-1, 1, 1 ),

                          viewport_ll=(-1, -1),
                          viewport_width=2,
                          viewport_height=2)
    
    screen_1 = Screen(subscreens=[subscreen_1],
                    display_index=monitor_id,
                    fullscreen=True,
                    vsync=True)

    # Now let's make a second screen looking to the left of the first screen monitor_id = 1
    monitor_id = 0
    subscreen_2 = SubScreen(pa=(-1, -1, -1),
                          pb=(-1, 1, -1),
                          pc=(-1, -1, 1 ),

                          viewport_ll=(-1, -1),
                          viewport_width=2,
                          viewport_height=2)
    
    screen_2 = Screen(subscreens=[subscreen_2],
                    display_index=monitor_id,
                    fullscreen=True,
                    vsync=True)


    screens = [screen_1, screen_2]

    # Launch the stim server
    manager = launch_stim_server(screens)
    sleep(2)

    # Set the background color of the screen
    manager.set_idle_background(0.5)
    
    r=0
    # Present 5 epochs of the stimulus
    for i in range(100):
        # Load a stimulus
        manager.load_stim(name='MovingSpot', theta = r) 
        r += 5

        # Pre time: wait for 0.5 second
        # sleep(0.1)

        # Start the stimulus
        manager.start_stim()


        # Stim time: client waits for 4 seconds while server shows the stimulus
        sleep(0.1)

        # Tail time: wait for 0.5 second at the end of the stimulus
        # sleep(0.1)

        # Stop the stimulus
        manager.stop_stim(print_profile=True)


if __name__ == '__main__':
    main()
