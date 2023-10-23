import signal, sys
from math import radians

import numpy as np

from stimpack.visual_stim.screen import Screen
from stimpack.visual_stim.stim_server import VisualStimServer

from stimpack.device.locomotion.loco_managers import LocoManager, LocoClosedLoopManager
from stimpack.device.daq import DAQ

from stimpack.rpc.util import start_daemon_thread, find_free_port
from stimpack.rpc.transceiver import MySocketServer
from stimpack.rpc.launch import launch_server
from stimpack.rpc.util import get_kwargs, get_from_dict

class BaseServer(MySocketServer):
    def __init__(self, screens=[], host='127.0.0.1', port=60629, 
                    loco_class=None, loco_kwargs={}, daq_class=None, daq_kwargs={}, 
                    start_loop=False):

        self.host = host
        if port is None:
            self.port = find_free_port(host)
        else:
            self.port = port

        # call super constructor
        super().__init__(host=self.host, port=self.port, threaded=False, auto_stop=False)

        # Default aux screen
        if screens is None or len(screens) == 0:
            screens = [Screen(server_number=-1, id=-1, fullscreen=False, vsync=True, square_size=(0.25, 0.25))]

        # other_stim_module_paths=[] stops VisualStimServer from importing user stimuli modules from a txt file
        self.vis_stim_manager = VisualStimServer(screens=screens, host=None, port=None, auto_stop=False, other_stim_module_paths=[])

        if loco_class is not None:
            assert issubclass(loco_class, LocoManager)
            self.loco_manager = loco_class(fs_manager=self.vis_stim_manager, start_at_init=False, **loco_kwargs)
        else:
            self.loco_manager = None

        if daq_class is not None:
            assert issubclass(daq_class, DAQ)
            self.daq_manager = daq_class(**daq_kwargs)
        else:
            self.daq_manager = None

        self.module_managers = {'visual': self.vis_stim_manager}

        # set the subject position parameters
        self.set_global_subject_pos(0, 0, 0)
        self.set_global_theta_offset(0) # deg -> radians
        self.set_global_phi_offset(0) # deg -> radians

        # Register functions to be executed on the server's root node only, and not on the clients (i.e. screens).
        self.functions_on_root = {}
        # Print on server
        self.register_function_on_root(lambda x: print(x), "print_on_server")

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
        if self.daq_manager is not None:
            self.daq_manager.close()
        
        self.vis_stim_manager.shutdown_flag.set()

    def register_function_on_root(self, function, name=None):
        '''
        Register function to be executed on the server's root node only, and not on the clients (i.e. screens).
        '''
        if name is None:
            name = function.__name__

        assert name not in self.functions_on_root, 'Function "{}" already defined.'.format(name)
        self.functions_on_root[name] = function
    
    def handle_request_list_to_root(self, root_request_list):
        for request in root_request_list:
            # get function call parameters
            function = self.functions_on_root[request['name']]
            args = request.get('args', [])
            kwargs = request.get('kwargs', {})

            # call function
            # print(f"Server root node executing: {str(request)}")
            function(*args, **kwargs)

    def handle_request_list(self, request_list):
        # pre-process the request list as necessary
        for request in request_list:
            if isinstance(request, dict) and ('name' in request):
                if 'target' not in request:
                    request['target'] = 'root'
                if 'kwargs' not in request:
                    request['kwargs'] = {}

        # Pull out and process requests for root node of the stim server
        root_request_list = [request for request in request_list if request['target']=='root']
        self.handle_request_list_to_root(root_request_list)

        # Pull out and process requests for each module
        for module_name, manager in self.module_managers.items():
            module_request_list = [request for request in request_list if request['target']==module_name]
            manager.handle_request_list(module_request_list)

    def run_function_in_modules(self, function_name, *args, **kwargs):
        '''
        Run a function in each module manager, only if the function exists in the module manager.
        '''
        for manager in self.module_managers.values():
            if hasattr(manager, function_name):
                getattr(manager, function_name)(*args, **kwargs)
    

    ### Functions for setting global subject position parameters ###
    # the function calls also get forwarded to each module manager

    def set_global_subject_pos(self, x, y, z):
        self.global_subject_pos = np.array([x, y, z], dtype=float)
        self.run_function_in_modules('set_global_subject_pos', x, y, z)

    def set_global_subject_x(self, x):
        self.global_subject_pos[0] = float(x)
        self.run_function_in_modules('set_global_subject_x', x)

    def set_global_subject_y(self, y):
        self.global_subject_pos[1] = float(y)
        self.run_function_in_modules('set_global_subject_y', y)

    def set_global_subject_z(self, z):
        self.global_subject_pos[2] = float(z)
        self.run_function_in_modules('set_global_subject_z', z)

    def set_global_theta_offset(self, value):
        self.global_theta_offset = radians(value)
        self.run_function_in_modules('set_global_theta_offset', value)

    def set_global_phi_offset(self, value):
        self.global_phi_offset = radians(value)
        self.run_function_in_modules('set_global_phi_offset', value)
