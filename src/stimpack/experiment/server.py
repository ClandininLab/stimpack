import signal, sys

from stimpack.visual_stim.screen import Screen
from stimpack.visual_stim.stim_server import StimServer

from stimpack.device.locomotion.loco_managers import LocoManager, LocoClosedLoopManager
from stimpack.device.daq import DAQ

from stimpack.rpc.util import start_daemon_thread, find_free_port

class BaseServer():
    def __init__(self, screens=[], host='127.0.0.1', port=60629, 
                    loco_class=None, loco_kwargs={}, daq_class=None, daq_kwargs={}, 
                    start_loop=False):

        # Default aux screen
        if screens is None or len(screens) == 0:
            screens = [Screen(server_number=-1, id=-1, fullscreen=False, vsync=True, square_size=(0.25, 0.25))]

        self.host = host
        if port is None:
            self.port = find_free_port(host)
        else:
            self.port = port

        # other_stim_module_paths=[] stops StimServer from importing user stimuli modules from a txt file
        self.vis_stim_manager = StimServer(screens=screens, host=self.host, port=self.port, auto_stop=False, other_stim_module_paths=[])

        self.loco_manager = None
        self.daq_device = None

        if loco_class is not None:
            assert issubclass(loco_class, LocoManager)
            self.__set_up_loco__(loco_class, **loco_kwargs)
        if daq_class is not None:
            assert issubclass(daq_class, DAQ)
            self.__set_up_daq__(daq_class, **daq_kwargs)

        self.vis_stim_manager.corner_square_toggle_stop()
        self.vis_stim_manager.corner_square_off()
        self.vis_stim_manager.set_idle_background(0)

        def signal_handler(sig, frame):
            print('Closing server after Ctrl+C...')
            self.close()
            sys.exit(0)
        signal.signal(signal.SIGINT, signal_handler)
    
        if start_loop:
            start_daemon_thread(self.loop)

    def loop(self):
        self.vis_stim_manager.loop()

    def close(self):
        if self.loco_manager is not None:
            self.loco_manager.close()
        if self.daq_device is not None:
            self.daq_device.close()
        self.vis_stim_manager.shutdown_flag.set()

    def __set_up_loco__(self, loco_class, **kwargs):
        self.loco_manager = loco_class(fs_manager=self.vis_stim_manager, start_at_init=False, **kwargs)
        self.vis_stim_manager.register_function_on_root(self.loco_manager.set_save_directory, "loco_set_save_directory")
        self.vis_stim_manager.register_function_on_root(self.loco_manager.start, "loco_start")
        self.vis_stim_manager.register_function_on_root(self.loco_manager.close, "loco_close")
        
        if issubclass(loco_class, LocoClosedLoopManager):
            self.vis_stim_manager.register_function_on_root(self.loco_manager.set_pos_0, "loco_set_pos_0")
            self.vis_stim_manager.register_function_on_root(self.loco_manager.write_to_log, "loco_write_to_log")
            self.vis_stim_manager.register_function_on_root(self.loco_manager.loop_start, "loco_loop_start")
            self.vis_stim_manager.register_function_on_root(self.loco_manager.loop_stop, "loco_loop_stop")
            self.vis_stim_manager.register_function_on_root(self.loco_manager.loop_start_closed_loop, "loco_loop_start_closed_loop")
            self.vis_stim_manager.register_function_on_root(self.loco_manager.loop_stop_closed_loop, "loco_loop_stop_closed_loop")
            self.vis_stim_manager.register_function_on_root(self.loco_manager.loop_update_closed_loop_vars, "loco_loop_update_closed_loop_vars")

    def __set_up_daq__(self, daq_class, **kwargs):
        self.daq_device = daq_class(**kwargs)
        self.vis_stim_manager.register_function_on_root(self.daq_device.send_trigger, "daq_send_trigger")
        self.vis_stim_manager.register_function_on_root(self.daq_device.output_step, "daq_output_step")
