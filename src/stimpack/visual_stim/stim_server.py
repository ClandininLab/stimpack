import platform
from time import time
from queue import Queue
from json.decoder import JSONDecodeError

import stimpack.visual_stim.framework
from stimpack.visual_stim.screen import Screen
from stimpack.util import make_as, listify

import socket
import atexit
from stimpack.rpc.transceiver import MySocketServer, MySocketClient, MyTransceiver
from stimpack.rpc.launch import launch_server
from stimpack.rpc.util import get_kwargs, get_from_dict, start_daemon_thread

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
    return launch_server(stimpack.visual_stim.framework, 
                         screen=screen.serialize(), 
                         new_env_vars=new_env_vars, 
                         client_class=ScreenClient, 
                         **kwargs)

class ScreenClient(MySocketClient):
    def __init__(self, host=None, port=None, stim_server_host=None, stim_server_port=None):
        MyTransceiver().__init__()

        # set defaults
        if host is None:
            host = '127.0.0.1'

        assert port is not None, 'The port must be specified when creating a client.'

        conn = socket.create_connection((host, port))
        conn_ss = socket.create_connection((stim_server_host, stim_server_port))

        # make sure that connection is closed on
        def cleanup():
            try:
                conn.shutdown(socket.SHUT_RDWR)
                conn.close()
                conn_ss.shutdown(socket.SHUT_RDWR)
                conn_ss.close()
            except (OSError, ConnectionResetError):
                pass

        atexit.register(cleanup)

        self.infile = conn.makefile('r')
        self.outfile = conn.makefile('wb')
        self.outfile_stimserver = conn_ss.makefile('wb')

        start_daemon_thread(self.loop)

    def loop(self):
        try:
            for line in self.infile:
                print('ScreenClient.loop: ' + str(line))
                self.outfile.write(line.encode('utf-8'))
        except (OSError, ConnectionResetError):
            pass


class StimClient(MySocketClient):
    def __init__(self, host=None, port=None):
        super().__init__(host=host, port=port)

        self.alert_queue = Queue()
        print(f'initialized StimClient with port {port}')

        self.register_function(self.alert, 'alert_client')

    def alert(self, title, text):
        print('StimClient.alert: ' + str(title) + ' ' + str(text))
        self.alert_queue.put((title, text))

    def loop(self):
        try:
            for line in self.infile:
                print('StimClient.loop: ' + str(line))
                try:
                    request_list = self.parse_line(line)
                except JSONDecodeError:
                    continue
                
                self.handle_request_list(request_list)
        except (OSError, ConnectionResetError):
            pass

class StimServer(MySocketServer):
    time_stamp_commands = ['start_stim', 'pause_stim', 'update_stim']

    def __init__(self, screens, host=None, port=None, auto_stop=None, other_stim_module_paths=None, **kwargs):
        # call super constructor
        super().__init__(host=host, port=port, threaded=False, auto_stop=auto_stop, start_loop=False)

        # create the listener
        self.screen_client_listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.screen_client_listener.bind((host, port))
        self.screen_client_listener.listen()
        self.screen_client_listener.settimeout(accept_timeout)

        # print out socket information
        sockname = self.screen_client_listener.getsockname()
        print('{} hostname: {}'.format(self.name, sockname[0]))
        print('{} port: {}'.format(self.name, sockname[1]))

        self.functions_on_root = {}

        # Print on server
        self.register_function_on_root(lambda x: print(x), "print_on_server")

        # Shared PixMap Memory stim
        self.spms = None
        self.register_function_on_root(self.load_shared_pixmap_stim, "load_shared_pixmap_stim")
        self.register_function_on_root(self.start_shared_pixmap_stim, "start_shared_pixmap_stim")
        self.register_function_on_root(self.clear_shared_pixmap_stim, "clear_shared_pixmap_stim")
        
        # If other_stim_module_paths specified in kwargs, use that.
        if other_stim_module_paths is None:
            other_stim_module_paths = []
        if not isinstance(other_stim_module_paths, list):
            other_stim_module_paths = [other_stim_module_paths]
        
        # launch screens
        self.clients = [launch_screen(screen=screen, other_stim_module_paths=other_stim_module_paths, **kwargs) for screen in screens]

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
    
    def load_shared_pixmap_stim(self, **kwargs):
        '''
        '''
        self.spms = make_as(kwargs, parent_class=SharedPixMapStimulus)
    
    def start_shared_pixmap_stim(self):
        if self.spms is not None:
            self.spms.start_stream()

    def clear_shared_pixmap_stim(self):
        if self.spms is not None:
            self.spms.close()

    def handle_request_list(self, request_list):
        # make sure that request list is actually a list...
        if not isinstance(request_list, list):
            print("Request list is not a list and thus cannot be handled.")
            return
        
        if any([not isinstance(req, dict) for req in request_list]):
            print("Request list contains non-dictionary elements and thus cannot be handled.")
            return

        # pull out requests to StimClient
        reqs_for_stim_client = [req for req in request_list if 'StimClient' in req.get('to', '')]
        request_list[:] = [req for req in request_list if not ('StimClient' in req.get('to', ''))]

        # pull out requests that are meant for server root node and not the screen clients
        root_request_list = [req for req in request_list if 'name' in req and req['name'] in self.functions_on_root]
        request_list[:] = [req for req in request_list if not ('name' in req and req['name'] in self.functions_on_root)]

        # send requests to StimClient
        if len(reqs_for_stim_client) > 0:
            print('reqs for stim client')
            self.write_request_list(reqs_for_stim_client)

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
        for client in self.clients:
            client.write_request_list(request_list)

def launch_stim_server(screen_or_screens=None, **kwargs):
    # set defaults
    if screen_or_screens is None:
        screen_or_screens = []

    # make list from single screen if necessary
    screens = listify(screen_or_screens, Screen)

    # serialize the Screen objects
    screens = [screen.serialize() for screen in screens]

    # run the server
    return launch_server(__file__, screens=screens, client_class=StimClient, **kwargs)

def run_stim_server(host=None, port=None, auto_stop=None, screens=None, **kwargs):
    # set defaults
    if screens is None:
        screens = []

    # instantiate the server
    server = StimServer(screens=screens, host=host, port=port, auto_stop=auto_stop, **kwargs)

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
