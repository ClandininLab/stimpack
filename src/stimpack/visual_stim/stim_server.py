import platform
from time import time

import stimpack.visual_stim.framework
from stimpack.visual_stim.screen import Screen
from stimpack import util

from stimpack.rpc.transceiver import MySocketServer
from stimpack.rpc.launch import launch_server
from stimpack.rpc.util import get_kwargs, get_from_dict

from stimpack.visual_stim.shared_pixmap import SharedPixMapStimulus

def launch_screen(screen, **kwargs):
    """
    This function launches a subprocess to display stimuli on a given screen.  In general, this function should
    be called once for each screen.
    :param screen: Screen object (from stimpack.visual_stim.screen) that contains screen ID, dimensions, etc.
    :return: Subprocess object corresponding to the stimuli display program.
    """

    # set the arguments as necessary
    new_env_vars = {}
    if platform.system() in ['Linux', 'Darwin']:
        if screen.server_number == -1 and screen.id == -1:
            print('Initializing screen with default X display server.')
        elif screen.server_number == -1:
            new_env_vars['DISPLAY'] = ':{}'.format(screen.id)
        elif screen.id == -1:
            new_env_vars['DISPLAY'] = ':{}.0'.format(screen.server_number)
        else:
            new_env_vars['DISPLAY'] = ':{}.{}'.format(screen.server_number, screen.id)
    # launch the server and return the resulting client
    return launch_server(stimpack.visual_stim.framework, screen=screen.serialize(), new_env_vars=new_env_vars, **kwargs)

class VisualStimServer(MySocketServer):
    time_stamp_commands = ['start_stim', 'pause_stim', 'update_stim']

    def __init__(self, screens=[], host=None, port=None, auto_stop=None, other_stim_module_paths=None, **kwargs):
        # call super constructor
        super().__init__(host=host, port=port, threaded=False, auto_stop=auto_stop)

        # If other_stim_module_paths specified in kwargs, use that.
        if other_stim_module_paths is None:
            other_stim_module_paths = []
        if not isinstance(other_stim_module_paths, list):
            other_stim_module_paths = [other_stim_module_paths]
        
        self.functions_on_root = {}
        self.register_function_on_root(self.close)

        # Shared memory PixMap stim functions to be run on the root node of visual stim server
        self.spms = None
        self.register_function_on_root(self.load_shared_pixmap_stim)
        self.register_function_on_root(self.start_shared_pixmap_stim)
        self.register_function_on_root(self.clear_shared_pixmap_stim)

        # If no screens are specified, create a default screen
        if screens is None or len(screens) == 0:
            screens = [Screen(server_number=-1, id=-1, fullscreen=False, vsync=True, square_size=(0.25, 0.25))]
        
        # launch screens
        self.screen_clients = [launch_screen(screen=screen, other_stim_module_paths=other_stim_module_paths, **kwargs) for screen in screens]

        self.corner_square_toggle_stop()
        self.corner_square_off()
        self.set_idle_background(0)

    def __getattr__(self, name):
        '''
        Allow the server to execute function calls as client, assuming server isn't busy looping. 
        If loop is on a separate thread, it can execute calls.
        '''
        if name in dir(self):
            return self.name
        
        # If not a method of the server class, handle it as a request.
        def f(*args, **kwargs):
            request = {'name': name, 'args': args, 'kwargs': kwargs}
            self.handle_request_list([request])
        return f

    def register_function_on_root(self, function, name=None):
        '''
        Register function to be executed on the server's root node only, and not on the clients (i.e. screens).
        '''
        if name is None:
            name = function.__name__

        assert name not in self.functions_on_root, 'Function "{}" already defined.'.format(name)
        self.functions_on_root[name] = function

    def handle_request_list(self, request_list):
        # make sure that request list is actually a list...
        if not isinstance(request_list, list):
            print("Request list is not a list and thus cannot be handled.")
            return

        # pull out requests that are meant for server root node and not the screen clients
        root_request_list = [req for req in request_list if isinstance(req, dict) and 'name' in req and req['name'] in self.functions_on_root]
        request_list[:] = [req for req in request_list if not (isinstance(req, dict) and 'name' in req and req['name'] in self.functions_on_root)]

        # handle requests for the root server without sending to client screens
        for request in root_request_list:
            # get function call parameters
            function = self.functions_on_root[request['name']]
            args = request.get('args', [])
            kwargs = request.get('kwargs', {})

            # call function
            # print(f"Server root node executing: {str(request)}")
            function(*args, **kwargs)

        # pre-process the request list as necessary
        for request in request_list:
            if isinstance(request, dict) and ('name' in request) and (request['name'] in self.time_stamp_commands):
                if 'kwargs' not in request:
                    request['kwargs'] = {}
                request['kwargs']['t'] = time()

        # send modified request list to clients
        for screen_client in self.screen_clients:
            screen_client.write_request_list(request_list)

    def close(self):
        self.shutdown_flag.set()

    ### Shared memory pixmap stim functions ###
    def load_shared_pixmap_stim(self, **kwargs):
        '''
        '''
        self.spms = util.make_as(kwargs, parent_class=SharedPixMapStimulus)
    
    def start_shared_pixmap_stim(self):
        if self.spms is not None:
            self.spms.start_stream()

    def clear_shared_pixmap_stim(self):
        if self.spms is not None:
            self.spms.close()
    ### Shared memory pixmap stim functions ###
        
def launch_stim_server(screen_or_screens=None, **kwargs):
    # set defaults
    if screen_or_screens is None:
        screen_or_screens = []

    # make list from single screen if necessary
    screens = util.listify(screen_or_screens, Screen)

    # serialize the Screen objects
    screens = [screen.serialize() for screen in screens]

    # run the server
    return launch_server(__file__, screens=screens, **kwargs)

def run_stim_server(host=None, port=None, auto_stop=None, screens=None, **kwargs):
    # set defaults
    if screens is None:
        screens = []

    # instantiate the server
    server = VisualStimServer(screens=screens, host=host, port=port, auto_stop=auto_stop, **kwargs)

    # launch the server
    server.loop()

def main():
    # get the startup arguments
    kwargs = get_kwargs()
    screens, host, port, auto_stop = get_from_dict(kwargs, ['screens', 'host', 'port', 'auto_stop'], remove=True)
    
    # get list of screens
    if screens is None:
        screens = []
    screens = [Screen.deserialize(screen) for screen in screens]

    # run the server
    run_stim_server(host=host, port=port, auto_stop=auto_stop, screens=screens, **kwargs)

if __name__ == '__main__':
    main()
