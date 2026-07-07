import socket, atexit, traceback
from typing import Callable
from queue import Queue, Empty
from threading import Event, Lock
import warnings
from json.decoder import JSONDecodeError

from stimpack.rpc.util import start_daemon_thread, stream_is_binary, JSONCoderWithTuple

class MyTransceiver:
    """
    Base class for transceivers that can send and receive requests.
    """
    def __init__(self):
        # initialize variables
        self.functions = {}
        self.outfile = None
        self.queue = Queue()

        # set when an outbound write fails because the peer disconnected, so callers can detect a dead link
        self.connection_broken = False

        # serialize writes: the server can push messages back to the client from other threads (e.g. the
        # closed-loop thread), which could otherwise interleave with the main write on the same stream
        self._write_lock = Lock()

        # optional callback(level, text) used to bubble handler errors toward the client (set by owners)
        self.error_reporter = None

        # create shutdown flag
        self.shutdown_flag = Event()

        # create shutdown function
        def shutdown():
            self.shutdown_flag.set()

        # register shutdown function
        self.register_function(shutdown)

    def register_function(self, function, name=None):
        if name is None:
            name = function.__name__

        assert name not in self.functions, 'Function "{}" already defined.'.format(name)
        self.functions[name] = function

    def write_request_list(self, request_list: list) -> None:
        if self.outfile is None:
            return

        line = JSONCoderWithTuple.encode(request_list) + '\n'

        if stream_is_binary(self.outfile):
            line = line.encode('utf-8')

        try:
            with self._write_lock:
                self.outfile.write(line)
                self.outfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError) as e:
            # The other side disconnected. Mark the link as broken and warn loudly instead of
            # silently turning every subsequent request into a no-op. Note ConnectionResetError
            # is a sibling of BrokenPipeError under OSError, not a subclass, so it must be listed.
            self.connection_broken = True
            warnings.warn(f"RPC write failed ({type(e).__name__}: {e}); connection appears broken.")

    def handle_request_list(self, request_list: list) -> None:
        if not isinstance(request_list, list):
            warnings.warn("Request list is not a list.")
            return

        for request in request_list:
            if isinstance(request, dict) and ('name' in request):
                if request['name'] in self.functions:
                    # get function call parameters
                    function = self.functions[request['name']]
                    args = request.get('args', [])
                    kwargs = request.get('kwargs', {})

                    # Call the function, isolating handler errors. Without this, an exception here
                    # propagates out of the screen subprocess's paintGL (aborting it via qFatal) or
                    # out of the server's inline loop() (silently killing the request loop thread).
                    try:
                        function(*args, **kwargs)
                    except Exception as e:
                        warnings.warn(f"Error handling request '{request['name']}':\n{traceback.format_exc()}")
                        self._report_error(f"error handling '{request['name']}': {type(e).__name__}: {e}")
                else:
                    warnings.warn(f"Function '{request['name']}' not defined.")
            else:
                warnings.warn(f"Request '{request}' is not a valid request.")

    def _report_error(self, text):
        '''Bubble an error toward the client via error_reporter, if one is set. Best-effort.'''
        if self.error_reporter is not None:
            try:
                self.error_reporter('error', text)
            except Exception:
                pass

    def process_queue(self):
        while True:
            try:
                request_list = self.queue.get_nowait()
            except Empty:
                break

            self.handle_request_list(request_list)

    def parse_line(self, line: str | bytes) -> list:
        if isinstance(line, bytes):
            line = line.decode('utf-8')

        return JSONCoderWithTuple.decode(line)


class MySocketClient(MyTransceiver):
    def __init__(self, host=None, port=None):
        super().__init__()

        # set defaults
        if host is None:
            host = '127.0.0.1'

        assert port is not None, 'The port must be specified when creating a client.'

        conn = socket.create_connection((host, port))

        # make sure that connection is closed on
        def cleanup():
            try:
                conn.shutdown(socket.SHUT_RDWR)
                conn.close()
            except (OSError, ConnectionResetError):
                pass

        atexit.register(cleanup)

        self.infile = conn.makefile('r')
        self.outfile = conn.makefile('wb')

        start_daemon_thread(self.loop)

    def __getattr__(self, name: str) -> Callable[..., None]:
        def f(*args: list, **kwargs: dict) -> None:
            request = {'name': name, 'args': args, 'kwargs': kwargs}
            self.write_request_list([request])

        return f

    def target(self, target_name: str):
        """
        Directs all function calls to the remote module with target name.
        """
        outer_self = self
        class remote_module_target:
            def __getattr__(self, target_attr_name: str) -> Callable[..., None]:
                def g(*args, **kwargs) -> None:
                    request = {'target': target_name, 
                            'name': target_attr_name, 
                            'args': args, 
                            'kwargs': kwargs}
                    outer_self.write_request_list([request])
                return g
        return remote_module_target()

    def loop(self):
        try:
            for line in self.infile:
                try:
                    request_list = self.parse_line(line)
                except JSONDecodeError:
                    continue

                self.queue.put(request_list)
        except (OSError, ConnectionResetError):
            pass


class MySocketServer(MyTransceiver):
    def __init__(self, host=None, port=None, threaded=None, auto_stop=None, accept_timeout=None, name=None):
        super().__init__()

        # set defaults
        if host is None:
            host = '127.0.0.1'

        if port is None:
            port = 0

        if threaded is None:
            threaded = True

        if auto_stop is None:
            auto_stop = True

        if accept_timeout is None:
            if auto_stop:
                accept_timeout = 10

        if name is None:
            name = self.__class__.__name__

        # save settings
        self.threaded = threaded
        self.auto_stop = auto_stop
        self.name = name

        # create the listener
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.bind((host, port))
        self.listener.listen()
        self.listener.settimeout(accept_timeout)

        # print out socket information
        sockname = self.listener.getsockname()
        print('{} hostname: {}'.format(self.name, sockname[0]))
        print('{} port: {}'.format(self.name, sockname[1]))

        # launch the read thread
        if self.threaded:
            start_daemon_thread(self.loop)

    def __getattr__(self, name):
        '''
        Allow the server to execute function calls as client, assuming server isn't busy looping. 
        If loop is on a separate thread, it can execute calls.
        '''
        # If not a method of the server class, handle it as a request.
        def f(*args, **kwargs):
            request = {'name': name, 'args': args, 'kwargs': kwargs}
            self.handle_request_list([request])
        return f

    def target(self, target_name: str):
        """
        Directs all function calls to the local module with target name.
        """
        outer_self = self
        class remote_module_target:
            def __getattr__(self, target_attr_name: str) -> Callable[..., None]:
                def g(*args, **kwargs) -> None:
                    request = {'target': target_name, 
                            'name': target_attr_name, 
                            'args': args, 
                            'kwargs': kwargs}
                    outer_self.handle_request_list([request])
                return g
        return remote_module_target()

    def loop(self):
        while not self.shutdown_flag.is_set():
            # wait for connection
            try:
                conn, address = self.listener.accept()
            except socket.timeout:
                print('Server received no connection within timeout, shutting down...')
                break

            print(f'{self.name} accepted connection from {address}.')

            infile = conn.makefile('r')
            self.outfile = conn.makefile('wb')

            try:
                for line in infile:
                    try:
                        request_list = self.parse_line(line)
                    except JSONDecodeError:
                        continue

                    if self.threaded:
                        self.queue.put(request_list)
                    else:
                        self.handle_request_list(request_list)
            except (OSError, ConnectionResetError):
                pass

            print(f'{self.name} dropped connection from {address}.')
            self.on_connection_close()

            if self.auto_stop:
                self.shutdown_flag.set()

    def on_connection_close(self):
        '''
        This function is called when the connection is closed / dropped.
        Can serve as a hook for subclasses to implement custom behavior.
        '''
        pass