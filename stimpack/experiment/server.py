import signal, sys, os
from math import radians

import numpy as np

from stimpack.visual_stim.screen import Screen
from stimpack.visual_stim.stim_server import VisualStimServer

from stimpack.device.locomotion.loco_managers import LocoManager
from stimpack.device.daq import DAQ

from stimpack.rpc.util import start_daemon_thread, find_free_port
from stimpack.rpc.transceiver import MySocketServer

from stimpack.experiment.util import config_tools

from stimpack.util import ROOT_DIR

class BaseServer(MySocketServer):
    def __init__(self, host='', port=60629, 
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
        self.register_function_on_root(self.set_subject_state, "set_subject_state")
        self.register_function_on_root(self.load_server_side_state_dependent_control, "load_server_side_state_dependent_control")
        self.register_function_on_root(self.unload_server_side_state_dependent_control, "unload_server_side_state_dependent_control")

        def signal_handler(sig, frame):
            print('Closing server after Ctrl+C...')
            self.close()
            sys.exit(0)
        signal.signal(signal.SIGINT, signal_handler)

        # Custom state-dependent control function, initialized to None        
        self.loaded_custom_state_dependent_control = None

        # set the subject position parameters
        self.subject_state = {}
        self.set_subject_state({'x': 0, 'y': 0, 'z': 0, 'theta': 0, 'phi': 0, 'roll':0}) # meters and degrees

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

        # If call is target('module_name'), return a dummy module object that will handle the request.
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

    def close(self):
        self.target('all').close()

    def on_connection_close(self):
        '''
        This function is called when the connection is closed / dropped.
        Overrides the function in MySocketServer.
        It calls on_connection_close() for each module.
        '''
        [module.on_connection_close() for module in self.modules.values()]
        
    ### Functions for setting subject state ###
    def set_subject_state(self, state_update:dict={'x': 0, 'y': 0, 'z': 0, 'theta': 0, 'phi': 0, 'roll':0}) -> None:
        # Perform custom closed-loop control and get an updated state update
        if self.loaded_custom_state_dependent_control is not None:
            state_update = self.loaded_custom_state_dependent_control(self, self.subject_state, state_update)

        # Update the subject state
        for k,v in state_update.items():
            self.subject_state[k] = v
        
        # Forward state information to each module manager
        self.target('all').set_subject_state(state_update)
    
    def load_server_side_state_dependent_control(self, protocol_module_path, protocol_name):
        '''
        Load a custom state-dependent control function.
        '''
        if protocol_module_path is None: # No user-specified protocol module, use Stimpack protocol
            protocol_module_full_path = os.path.join(ROOT_DIR, 'experiment', 'example_protocol.py')
        else:
            protocol_module_full_path = config_tools.convert_labpack_relative_path_to_full_path(protocol_module_path)
        protocol_module = config_tools.load_user_module_from_path(protocol_module_full_path, 'client_protocol')
        if protocol_module is not None:
            self.loaded_custom_state_dependent_control = getattr(protocol_module, protocol_name).server_side_state_dependent_control
        else:
            print(f"Failed to load custom state-dependent control function from {protocol_module_path}.")

    def unload_server_side_state_dependent_control(self):
        '''
        Unload custom state-dependent control function.
        '''
        self.loaded_custom_state_dependent_control = None