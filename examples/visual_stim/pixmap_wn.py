#!/usr/bin/env python3
from stimpack.visual_stim.stim_server import launch_stim_server
from stimpack.visual_stim.screen import Screen
from stimpack.visual_stim.util import generate_lowercase_barcode
from time import sleep

def main():
    memname = generate_lowercase_barcode(10)
    frame_shape = (200, 100, 3)
    nominal_frame_rate = 10
    duration = 2
    seed = 37

    manager = launch_stim_server(Screen(fullscreen=False, vsync=True))
    # manager = init_screens()

    manager.load_shared_pixmap_stim(name='WhiteNoise', memname=memname, 
                                    frame_shape=frame_shape, nominal_frame_rate=nominal_frame_rate, 
                                    dur=duration, seed=seed, coverage='full')


    manager.load_stim(name='PixMap', memname=memname, frame_size=frame_shape, rgb_texture=True, 
                        width=180, radius=1, n_steps=32, surface='spherical', hold=True)

    sleep(1)

    manager.start_shared_pixmap_stim()
    manager.start_stim()
    sleep(duration)

    manager.stop_stim(print_profile=True)
    manager.clear_shared_pixmap_stim()

    sleep(1)

    

if __name__ == '__main__':
    main()
