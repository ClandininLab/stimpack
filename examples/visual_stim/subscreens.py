#!/usr/bin/env python3
from stimpack.visual_stim.stim_server import launch_stim_server
from stimpack.visual_stim.screen import Screen, SubScreen, TriSubScreen, ScreenPoint
from stimpack.visual_stim.draw import draw_screens
from stimpack.rpc.multicall import MyMultiCall

from time import sleep

def get_subscreen(dir):
    w = 3.0e-2 #meters
    h = 3.0e-2
    viewport_width = 0.6 #ndc
    viewport_height = 0.6
    if dir == 'w':
        viewport_ll = (-0.8, -0.6)
        # pa = (-w/2, +w/2, -h/2)
        # pb = (+w/2, +w/2, -h/2)
        # pc = (-w/2, +w/2, +h/2)
        # return SubScreen(pa=pa, pb=pb, pc=pc, viewport_ll=viewport_ll, viewport_width=viewport_width, viewport_height=viewport_height)
        pa = (+w/2, +w/2, -h/2)
        pb = (+w/2, -w/2, -h/2)
        pc = (+w/2, +w/2, +h/2)
        return SubScreen(pa=pa, pb=pb, pc=pc, viewport_ll=viewport_ll, viewport_width=viewport_width, viewport_height=viewport_height)
    elif dir == 'n':
        viewport_ll = (-0.3, 0.0)
        # pa = (-w/2, +w/2, -h/2)
        # pb = (+w/2, +w/2, -h/2)
        # pc = (-w/2, +w/2, +h/2)
        # return SubScreen(pa=pa, pb=pb, pc=pc, viewport_ll=viewport_ll, viewport_width=viewport_width, viewport_height=viewport_height)
        p1 = ScreenPoint(viewport_ll, (-w/2, +w/2, -h/2))
        p2 = ScreenPoint((viewport_ll[0] + viewport_width, viewport_ll[1]), (+w/2, +w/2, -h/2))
        p3 = ScreenPoint((viewport_ll[0] + viewport_width/2, viewport_ll[1] + viewport_height), (0, +w/2, +h/2))
        return TriSubScreen(p1, p2, p3)

    elif dir == 'e':
        viewport_ll = (+0.2, -0.6)
        pa = (+w/2, +w/2, -h/2)
        pb = (+w/2, -w/2, -h/2)
        pc = (+w/2, +w/2, +h/2)
        # return SubScreen(pa=pa, pb=pb, pc=pc, viewport_ll=viewport_ll, viewport_width=viewport_width, viewport_height=viewport_height)
        p1 = ScreenPoint(viewport_ll, pa)
        p2 = ScreenPoint((viewport_ll[0] + viewport_width, viewport_ll[1]), pb)
        p3 = ScreenPoint((viewport_ll[0], viewport_ll[1] + viewport_height), pc)
        return TriSubScreen(p1, p2, p3)

    else:
        raise ValueError('Invalid direction.')



def main():

    # Set stimulus parameters
    n_trials = 3
    pre_time = 1 #sec
    stim_time = 4 #sec
    tail_time = 1 #sec
    idle_background = (0.5, 0.5, 0.5, 1.0) #RGBA

    # Initialize screens
    subscreens = [get_subscreen('w'), get_subscreen('n'), get_subscreen('e')]
    screen = Screen(subscreens=subscreens, fullscreen=False, square_loc=(0.75, -1.0), square_size=(0.25, 0.25), vsync=True, horizontal_flip=True)
    #draw_screens(screen)

    # Initialize stim server
    manager = launch_stim_server(screen)
    manager.set_idle_background(idle_background)

    for _ in range(n_trials):
        # (1) LOAD STIMS
        multicall_load = MyMultiCall(manager)
        multicall_load.load_stim(name='ConstantBackground', color=idle_background, side_length=100)

        multicall_load.load_stim(name='RotatingGrating', rate=25, period=30, mean=0.5, contrast=1.0, offset=0.0, profile='square',
                        color=[1, 1, 1, 1], cylinder_radius=1.1, cylinder_height=10, theta=0, phi=0, angle=90, hold=True)

        tv_pairs = [(0, 0), (4, 360)]
        theta_traj = {'name': 'TVPairs',
                    'tv_pairs': tv_pairs,
                    'kind': 'linear'}

        multicall_load.load_stim(name='MovingPatch', width=30, height=30, phi=0, color=[1, 0, 0, 1], theta=theta_traj, hold=True, angle=0)

        multicall_load()
        sleep(pre_time)

        # (2) START STIMS, FLICKER CORNER
        multicall_start = MyMultiCall(manager)
        multicall_start.start_stim()
        multicall_start.corner_square_toggle_start()
        multicall_start() #start stims
        sleep(stim_time)

        # (3) STOP STIMS, SET CORNER TO BLACK
        multicall_stop = MyMultiCall(manager)
        multicall_stop.stop_stim(print_profile=True)
        multicall_stop.corner_square_toggle_stop()
        multicall_stop.corner_square_off()
        multicall_stop()
        sleep(tail_time)

if __name__ == '__main__':
    main()
