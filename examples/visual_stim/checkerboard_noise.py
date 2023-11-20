#!/usr/bin/env python3
from stimpack.visual_stim.stim_server import launch_stim_server
from stimpack.visual_stim.screen import Screen

from time import sleep

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import matplotlib.pyplot as plt
from stimpack.visual_stim.screen import Screen, SubScreen
from base_server import BaseServer
from stimpack.device.locomotion.loco_managers import LocoClosedLoopManager


class VoltronServer(BaseServer):
    def __init__(self, visual_stim_kwargs={}, loco_class=None, loco_kwargs={}, daq_class=None, daq_kwargs={}):
        super().__init__(visual_stim_kwargs=visual_stim_kwargs, 
                         loco_class=loco_class, loco_kwargs=loco_kwargs, 
                         daq_class=daq_class, daq_kwargs=daq_kwargs)

    def get_subscreens(dir):
        if dir == 'l':
            viewport_ll = (-1.0, -1.0)
            viewport_width  = 2
            viewport_height = 2
            pa = (-13.5, -7.5, -2.5)
            pb = (0.0, 9.0, -2.5)
            pc = (-13.5, -7.5, 9.5)

        elif dir == 'r':
            viewport_ll = (-1.0, -1.0)
            viewport_width  = 2
            viewport_height = 2
            pa = (0, 9, -2.5)
            pb = (13.5, -7.5, -2.5)
            pc = (0, 9, 9.5)
            # pc = (0, 10, 10)
        elif dir == 'aux':
            viewport_ll = (-1.0, -1.0)
            viewport_width  = 2
            viewport_height = 2
            pa = (-4, -2, -2)
            pb = (0, 4, -2)
            pc = (-4, -2, 2)
        else:
            raise ValueError('Invalid direction.')
        return SubScreen(pa=pa, pb=pb, pc=pc, viewport_ll=viewport_ll, viewport_width=viewport_width, viewport_height=viewport_height)

def main():
    server= 0
    left_screen  = Screen(subscreens=[VoltronServer.get_subscreens('l')],   
                          server_number=0, id=1, fullscreen=True, vsync=True,
                          name='Left', horizontal_flip=False)
    right_screen = Screen(subscreens=[VoltronServer.get_subscreens('r')], 
                          server_number=0, id=2, fullscreen=True, vsync=True, 
                          name='Right', horizontal_flip=False)
    aux_screen   = Screen(subscreens=[VoltronServer.get_subscreens('aux')], 
                          server_number=0, id=0, fullscreen=False, vsync=False,
                          name='Aux', horizontal_flip=False)
    screens = [left_screen, right_screen, aux_screen]
    visual_stim_kwargs = {'screens': screens}
    
    loco_class = LocoClosedLoopManager 
    loco_kwargs = {
        'host':          '127.0.0.1', 
        'port':          33335
    }
    server = VoltronServer(visual_stim_kwargs=visual_stim_kwargs, loco_class=loco_class, loco_kwargs=loco_kwargs)
    server.loop()


if __name__ == '__main__':
    main()

def main():
    manager = launch_stim_server(Screen(fullscreen=False, vsync=True))

    manager.load_stim(name='ConstantBackground', color=[0.5, 0.5, 0.5, 1.0], side_length=100, hold=True)

    distribution_data = {'name': 'Ternary',
                         'rand_min': 0,
                         'rand_max': 1}
    
    # manager.load_stim(name='RandomGrid', patch_width=5, patch_height=5, cylinder_vertical_extent=80, cylinder_angular_extent=120,
    #                   distribution_data=distribution_data, update_rate=1.0, start_seed=0,
    #                   color=[1, 1, 1, 1], cylinder_radius=1, theta=90, phi=0, angle=0.0, hold=True)
    manager.load_stim(name='UniformWhiteNoise', width=10, height=10, sphere_radius=1, distribution_data=distribution_data,
                      theta=0, phi=0, angle=0, update_rate=10.0, start_seed=0, hold=True)
    # manager.load_stim(name='MovingSpot', radius=2.5, sphere_radius=1, color=[1, 0, 0, 1], theta=0, phi=21.5, hold=True)

    sleep(1)

    manager.start_stim()
    sleep(4)

    manager.stop_stim(print_profile=True)
    sleep(1)

if __name__ == '__main__':
    main()
