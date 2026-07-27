"""
The RPC link: newline-delimited JSON over a socket.

Both ends are transceivers. A request is ``{'name', 'args', 'kwargs', 'target'}``, and calls are
**fire-and-forget** -- there is no reply and no return value, so a call naming something the far
end does not have is accepted, sent, and silently dropped.

Missing attributes become remote calls through ``__getattr__``, which is what lets a protocol
write ``manager.target('visual').load_stim(...)``. The same mechanism means ``getattr(obj, 'x',
default)`` never falls back and ``hasattr`` is always true, so neither is a safe way to ask
whether the far end supports something.
"""
import socket, atexit, traceback
from typing import Any, Callable
from queue import Queue, Empty
from threading import Event, Lock
import warnings
from json.decoder import JSONDecodeError

from stimpack.rpc.util import start_daemon_thread, stream_is_binary, JSONCoderWithTuple


def is_broadcast(request):
    """True for a target='all' request.

    Broadcasts are delivered to every module and each takes only the calls it knows -- e.g.
    target('all').start_stim() is meant for the screens, and the daq/locomotion modules ignoring it
    is normal. So an unknown name is only worth reporting when the caller addressed a specific
    target; reporting broadcasts would fire on every run.
    """
    return isinstance(request, dict) and request.get('target') == 'all'


def reject_private_attribute(name):
    """Raise AttributeError for private/dunder names instead of turning them into an RPC call.

    The __getattr__ proxies below make any unknown attribute a remote call. Without this guard,
    routine introspection becomes network traffic and silently succeeds: copy/pickle probe
    __deepcopy__/__getstate__, IPython probes _repr_html_, and -- most confusingly --
    getattr(manager, 'foo', default) never falls back to the default, it returns an RPC stub.
    Nothing legitimately calls a remote _private method.
    """
    if name.startswith('_'):
        raise AttributeError(name)


def _warn_undecodable_line(line, error):
    """Report a line that could not be parsed, instead of dropping it silently.

    A line only fails to decode if something is genuinely wrong -- a truncated write, two writers
    interleaving on one socket, a non-stimpack client. Dropping it without a word means the caller's
    request simply never happens, which is the same invisible failure as an unknown function name.
    Truncated because a corrupted line can be arbitrarily long.
    """
    excerpt = line.decode('utf-8', 'replace') if isinstance(line, bytes) else line
    excerpt = excerpt.strip()
    if len(excerpt) > 200:
        excerpt = f'{excerpt[:200]}... ({len(excerpt)} chars)'
    warnings.warn(f'Discarding an RPC line that could not be decoded ({error}): {excerpt!r}')


def _disable_nagle(sock):
    """Disable Nagle's algorithm (TCP_NODELAY) so small RPC messages are sent immediately instead of
    being buffered for up to ~40 ms waiting for an ACK. Best-effort: ignore sockets that don't support it."""
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except OSError:
        pass


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
        """
        Make a function callable from the other end of the link.

        :param function: the callable to expose
        :param name: the name remote callers use; defaults to the function's own. Registering a
            name twice is an error, so collisions surface at startup rather than at run time.
        """
        if name is None:
            name = function.__name__

        assert name not in self.functions, 'Function "{}" already defined.'.format(name)
        self.functions[name] = function

    def write_request_list(self, request_list: list) -> None:
        """
        Send a batch of requests. Returns as soon as they are written -- there is no reply.

        A no-op when nothing is connected, which is why a call made before the far end is up
        disappears without complaint.
        """
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
                    # An unknown name is the classic silent failure of this RPC style: the attribute
                    # access succeeded, the request was sent, and it lands nowhere. Report it back so
                    # the caller finds out instead of the call simply having no effect.
                    warnings.warn(f"Function '{request['name']}' not defined.")
                    if not is_broadcast(request):
                        self._report_error(f"no such function '{request['name']}' "
                                           f"(target={request.get('target', 'root')})")
            else:
                warnings.warn(f"Request '{request}' is not a valid request.")
                self._report_error(f"malformed request: {request!r}")

    def _report_error(self, text):
        '''Bubble an error toward the client via error_reporter, if one is set. Best-effort.'''
        if self.error_reporter is not None:
            try:
                self.error_reporter('error', text)
            except Exception:
                pass

    def process_queue(self):
        """
        Run every request received since the last call, on the calling thread.

        Requests arrive on a reader thread and are queued rather than executed there, so the
        owner decides when they run -- a screen does it once per rendered frame, in ``paintGL``.
        Handler errors are caught and reported rather than killing the loop.
        """
        while True:
            try:
                request_list = self.queue.get_nowait()
            except Empty:
                break

            self.handle_request_list(request_list)

    def parse_line(self, line: str | bytes) -> list:
        """Decode one newline-delimited JSON request list, preserving tuples."""
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

        # Set before connecting so close() is well-defined even if create_connection below raises.
        # Real attributes, so __getattr__ can't turn them into RPC stubs.
        self.conn = None
        self._reader_thread = None

        # Modules the server advertised on connect (a set), or None if it never told us -- e.g. an
        # older server. A real attribute, so __getattr__ can't turn it into an RPC stub.
        self.available_modules = None
        # Only a client receives this, so handle it here rather than on every transceiver. Doing so
        # means any client -- not just BaseClient -- accepts the advertisement instead of treating
        # it as an unknown function.
        self.register_function(self._set_available_modules, name='report_server_modules')

        # Keep the socket and the reader thread: close() needs both, and without them the reader is
        # unstoppable -- it parks in `for line in self.infile` and only ever exits when the peer
        # happens to drop the connection.
        self.conn = socket.create_connection((host, port))
        _disable_nagle(self.conn)

        atexit.register(self.close)

        self.infile = self.conn.makefile('r')
        self.outfile = self.conn.makefile('wb')

        self._reader_thread = start_daemon_thread(self.loop)

    def close(self, timeout=2.0):
        '''
        Close the connection and stop the reader thread. Idempotent.

        socket.shutdown() -- not close() -- is what unblocks the reader. It is parked in a blocking
        read inside `for line in self.infile`; shutdown makes that read return EOF, so the loop ends
        on its own and the thread can be joined. Closing the file object out from under a blocked
        reader does NOT reliably wake it and can hang instead.
        '''
        self.shutdown_flag.set()

        if self.conn is not None:
            try:
                self.conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass                              # already shut down, or never fully connected

        if self._reader_thread is not None:
            self._reader_thread.join(timeout=timeout)
            self._reader_thread = None

        # Drop outfile before closing it: write_request_list() treats None as "no link" and returns
        # quietly, whereas writing to a *closed* file raises ValueError, which it does not catch.
        infile, outfile, conn = self.infile, self.outfile, self.conn
        self.infile = self.outfile = self.conn = None
        for closeable in (infile, outfile, conn):
            if closeable is not None:
                try:
                    closeable.close()
                except OSError:
                    pass

    def _set_available_modules(self, modules):
        '''Record the modules the server advertised (see BaseServer.on_connection_open).'''
        self.available_modules = set(modules)

    def __getattr__(self, name: str) -> Callable[..., None]:
        reject_private_attribute(name)
        def f(*args: Any, **kwargs: Any) -> None:
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
                reject_private_attribute(target_attr_name)
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
                except JSONDecodeError as e:
                    _warn_undecodable_line(line, e)
                    continue

                self.queue.put(request_list)
        except (OSError, ConnectionResetError, ValueError):
            # ValueError: close() got the file out from under us (iterating a closed file). That is
            # a normal shutdown race, not an error.
            pass
        finally:
            # The reader loop only ends when the connection drops (EOF or error), so flag the link
            # broken here too. This detects a dead server even during a quiet stretch with no sends.
            self.connection_broken = True


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
        reject_private_attribute(name)
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
                reject_private_attribute(target_attr_name)
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
            _disable_nagle(conn)

            infile = conn.makefile('r')
            self.outfile = conn.makefile('wb')

            # outfile is now live, so the server can push to this client (e.g. advertise its modules)
            self.on_connection_open()

            try:
                for line in infile:
                    try:
                        request_list = self.parse_line(line)
                    except JSONDecodeError as e:
                        _warn_undecodable_line(line, e)
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

    def on_connection_open(self):
        '''
        Called once a client has connected and self.outfile is live, so the server can push
        something to it immediately. Hook for subclasses (BaseServer advertises its modules here).
        '''
        pass

    def on_connection_close(self):
        '''
        This function is called when the connection is closed / dropped.
        Can serve as a hook for subclasses to implement custom behavior.
        '''
        pass