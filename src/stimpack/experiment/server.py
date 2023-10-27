import signal, sys
from math import radians

import numpy as np

from stimpack.visual_stim.screen import Screen
from stimpack.visual_stim.stim_server import VisualStimServer

from stimpack.device.locomotion.loco_managers import LocoManager
from stimpack.device.daq import DAQ

from stimpack.rpc.util import start_daemon_thread, find_free_port
from stimpack.rpc.transceiver import MySocketServer

class BaseServer(MySocketServer):
    def __init__(self, host='127.0.0.1', port=60629, 
                    visual_stim_kwargs={},
                    loco_class=None, loco_kwargs={}, 
                    daq_class=None,  daq_kwargs={}, 
                    start_loop=False):

        self.host = host
        if port is None:
            self.port = find_free_port(host)
        else:
            self.port = port

        # call super constructor
        super().__init__(host=self.host, port=self.port, threaded=False, auto_stop=False)

        self.modules = {}
        
        ### Visual stim manager ###
        # Default aux screen
        if 'screens' not in visual_stim_kwargs:
            visual_stim_kwargs['screens'] = [Screen(server_number=-1, id=-1, fullscreen=False, vsync=True, square_size=(0.25, 0.25))]
        
        self.modules['visual'] = VisualStimServer(**visual_stim_kwargs) # auto_stop=False, other_stim_module_paths=[]
        ### Visual stim manager ###

        ### Locomotion manager ###
        if loco_class is not None:
            assert issubclass(loco_class, LocoManager)
            self.modules['locomotion'] = loco_class(stim_server=self, start_at_init=False, **loco_kwargs)
        ### Locomotion manager ###

        ### DAQ manager ###
        if daq_class is not None:
            assert issubclass(daq_class, DAQ)
            self.modules['daq'] = daq_class(**daq_kwargs)
        ### DAQ manager ###

        # Register functions to be executed on the server's root node, and not in modules.
        self.functions_on_root = {}
        self.register_function_on_root(lambda x: print(x), "print_on_server")
        self.register_function_on_root(self.set_global_subject_pos)
        self.register_function_on_root(self.set_global_subject_x)
        self.register_function_on_root(self.set_global_subject_y)
        self.register_function_on_root(self.set_global_subject_z)
        self.register_function_on_root(self.set_global_theta_offset)
        self.register_function_on_root(self.set_global_phi_offset)

        def signal_handler(sig, frame):
            print('Closing server after Ctrl+C...')
            self.close()
            sys.exit(0)
        signal.signal(signal.SIGINT, signal_handler)
        
        # set the subject position parameters
        self.set_global_subject_pos(0, 0, 0)
        self.set_global_theta_offset(0) # deg -> radians
        self.set_global_phi_offset(0) # deg -> radians

        if start_loop:
            start_daemon_thread(self.loop)

    def __getattr__(self, name):
        '''
        Allow the server to execute function calls as client, assuming server isn't busy looping. 
        If loop is on a separate thread, it can execute calls.
        '''
        
        # If call is for an attribute / method of the server class, return it.
        if name in dir(self):
            return self.name

        # If call is target('module_name'), return the module object.
        elif name == 'target':
            def f(module_name):
                class dummy_module:
                    def __getattr__(module_self, module_attr_name):
                        def g(*args, **kwargs):
                            request = {'target': module_name, 
                                       'name': module_attr_name, 
                                       'args': args, 
                                       'kwargs': kwargs}
                            self.handle_request_list([request])                            
                        return g
                return dummy_module()
            return f
        
        # If not a method of the server class and target not specified, 
        #   handle it as a request to the root nodoe.
        else:
            # print(f"Server does not have attribute {name}; call must be for either module or an attribute or method of BaseServer.")            
            def f(*args, **kwargs):
                request = {'target': 'root',
                           'name': name, 
                           'args': args, 
                           'kwargs': kwargs}
                self.handle_request_list([request])
            return f
    
    # def loop(self):
    #     self.run_function_in_all_modules('loop')

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
            if request['name'] not in self.functions_on_root:
                print(f"Warning: function '{request['name']}' not registered on root node.")
                continue
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
        for module_name, module in self.modules.items():
            module_request_list = [request for request in request_list if request['target'] in [module_name, 'all']]
            if len(module_request_list) > 0:
                module.handle_request_list(module_request_list)

    def run_function_in_module(self, module, function_name, *args, **kwargs):
        '''
        Run a function in specified module, only if the function exists in the module.
        '''
        if hasattr(module, function_name):
            getattr(module, function_name)(*args, **kwargs)
    
    def run_function_in_all_modules(self, function_name, *args, **kwargs):
        '''
        Run a function in each module manager, only if the function exists in the module manager.
        '''
        for module in self.modules.values():
            self.run_function_in_module(module, function_name, *args, **kwargs)    

    def close(self):
        self.run_function_in_all_modules('close')

    ### Functions for setting global subject position parameters ###
    # the function calls also get forwarded to each module manager

    def set_global_subject_pos(self, x, y, z):
        self.global_subject_pos = np.array([x, y, z], dtype=float)
        self.run_function_in_all_modules('set_global_subject_pos', x, y, z)

    def set_global_subject_x(self, x):
        self.global_subject_pos[0] = float(x)
        self.run_function_in_all_modules('set_global_subject_x', x)

    def set_global_subject_y(self, y):
        self.global_subject_pos[1] = float(y)
        self.run_function_in_all_modules('set_global_subject_y', y)

    def set_global_subject_z(self, z):
        self.global_subject_pos[2] = float(z)
        self.run_function_in_all_modules('set_global_subject_z', z)

    def set_global_theta_offset(self, value):
        self.global_theta_offset = radians(value)
        self.run_function_in_all_modules('set_global_theta_offset', value)

    def set_global_phi_offset(self, value):
        self.global_phi_offset = radians(value)
        self.run_function_in_all_modules('set_global_phi_offset', value)
