"""
The visual module: manages screen subprocesses and forwards requests to them.

:class:`VisualStimServer` launches one subprocess per :class:`~stimpack.visual_stim.screen.Screen`
so that one display stalling cannot stall another, and fans each request out to all of them.
Some calls are handled on the server itself rather than forwarded -- see ``register_function_on_root``.
"""
import platform, os, subprocess, warnings, traceback
from time import time, sleep

import stimpack.visual_stim.framework
from stimpack.visual_stim.screen import Screen
from stimpack import util

from stimpack.rpc.transceiver import MySocketServer
from stimpack.rpc.launch import launch_server
from stimpack.rpc.util import get_kwargs, get_from_dict, start_daemon_thread

from stimpack.visual_stim.shared_pixmap import SharedPixMapStimulus

def launch_screen(screen, **kwargs):
    """
    This function launches a subprocess to display stimuli on a given screen.  In general, this function should
    be called once for each screen.
    :param screen: Screen object (from stimpack.visual_stim.screen) that contains screen ID, dimensions, etc.
    :return: Client object that can be used to send commands to the screen server.
    """

    # set the arguments as necessary
    new_env_vars = {}

    session_type = os.environ.get('XDG_SESSION_TYPE', "unknown")
    qt_platform_type = os.environ.get('QT_QPA_PLATFORM', "unknown")
    print(f"Display session type: {session_type}")
    print(f"QT platform type: {qt_platform_type}")

    if platform.system() == 'Linux':
        if screen.x_display is not None:
            if session_type != 'x11':
                print("Host session type is not X11 but attempting to use X11.")
            screen.name += f" (X11 {screen.x_display})"
            new_env_vars['DISPLAY'] = screen.x_display
            new_env_vars['QT_QPA_PLATFORM'] = 'xcb'
        else:
            if session_type == 'x11' or qt_platform_type == 'xcb':
                print("No X display specified, using default X11 settings.")
                screen.name += f" (X11 {os.environ.get('DISPLAY', '')})"
                new_env_vars['QT_QPA_PLATFORM'] = 'xcb'
            elif session_type == 'wayland' or 'wayland' in qt_platform_type:
                screen.name += " (Wayland)"
                new_env_vars['QT_QPA_PLATFORM'] = 'wayland'
                screen.use_egl = True
            else:
                print(f"Unknown session type: {session_type}")

    # launch the server and return the resulting client
    screen_client, proc = launch_server(stimpack.visual_stim.framework, screen=screen.serialize(), new_env_vars=new_env_vars, **kwargs)
    # Return the process handle too: a screen only auto-stops when its client disconnects, which
    # happens when the stim server PROCESS exits. When VisualStimServer is constructed in-process
    # (BaseServer does this), the parent keeps running, so without this handle the screen
    # subprocesses would outlive close() and pile up.
    return screen_client, proc

class VisualStimServer(MySocketServer):
    '''
    This class manages multiple screens and sends commands to them.
    It can also execute certain commands on the server itself ("root"), rather than sending them to the screens.
    '''
    time_stamp_commands = ['start_stim', 'pause_stim', 'update_stim']

    def __init__(self, screens=None, host=None, port=None, auto_stop=None, **kwargs):
        # call super constructor
        super().__init__(host=host, port=port, threaded=False, auto_stop=auto_stop)

        # Removed in 0.3.0. Left as an explicit error rather than swallowed by **kwargs: the
        # modules it loaded were dropped the moment a client disconnected and never re-imported, so
        # anyone passing it had custom stimuli for exactly one session. Silently accepting it now
        # would reproduce that, without even the first session working.
        if 'other_stim_module_paths' in kwargs:
            raise TypeError(
                "other_stim_module_paths was removed in stimpack 0.3.0. Import stimulus modules "
                "from the client instead: manager.target('visual').import_stim_module(path), or "
                "name them under module_paths.visual_stim in your config. Re-importing is safe -- "
                "it reloads rather than duplicating.")

        # Screen-side errors reach whoever is connected, even with no BaseServer wrapping this one.
        # Without this default the reporter stayed None and every error a screen bubbled up was
        # dropped here -- so a script driving launch_stim_server directly, which is what the
        # examples do, saw a failing stimulus do nothing at all and say nothing about it.
        self.error_reporter = self.report_to_client

        self.functions_on_root = {}
        self.register_function_on_root(self.close)

        # Shared memory PixMap stim functions to be run on the root node of visual stim server
        self.spms = None
        self.register_function_on_root(self.load_shared_pixmap_stim)
        self.register_function_on_root(self.start_shared_pixmap_stim)
        self.register_function_on_root(self.clear_shared_pixmap_stim)

        # If no screens are specified, create a default screen
        # screens=None means "you did not say", and gets a default aux screen, as it always has.
        # screens=[] means "none", and gets none -- a rig that outputs voltage or reads a tracker
        # but drives no display should not open a window, and neither should a test that only
        # exercises those. Every screen is a subprocess with its own GL context, so the difference
        # is not free.
        if screens is None:
            screens = [Screen(x_display=None, display_index=0, fullscreen=False, vsync=True, square_size=(0.25, 0.25))]
        
        # launch screens
        launched = [launch_screen(screen=screen, **kwargs) for screen in screens]
        self.screen_managers = [client for client, _ in launched]
        self.screen_processes = [proc for _, proc in launched]

        # Let each screen subprocess bubble its errors up to us (and thence to the client). The screen
        # pushes a 'report_server_message' back on its socket, which we drain below.
        for screen_manager in self.screen_managers:
            screen_manager.register_function(self._forward_screen_message, name='report_server_message')

        # Screen replies arrive asynchronously, so draining only when a new request comes in would
        # strand a message (forever, if no further requests follow). Pump the screen queues on a
        # background thread so screen-side errors propagate promptly regardless of traffic.
        start_daemon_thread(self._pump_screen_messages)

        self.corner_square_toggle_stop()
        self.corner_square_off()
        self.set_idle_background(0)

    def report_to_client(self, level, text):
        '''
        Push a message back to the connected client, which surfaces it and, for level='error',
        aborts the run. Best-effort: no-ops when nothing is connected.

        A BaseServer replaces this with its own reporter when it owns this module, so messages
        reach the experiment client rather than stopping here.
        '''
        self.write_request_list([{'name': 'report_server_message', 'args': [level, str(text)], 'kwargs': {}}])

    def get_callable_names(self):
        """
        Names target('visual') answers to: this server's own root functions, plus the ones each
        screen subprocess registers.

        The screen half comes from framework.SCREEN_FUNCTION_NAMES rather than from asking a
        screen. The link to a screen is fire-and-forget like every other, so there is nothing to
        ask over -- but there is also no need, since what a screen registers is fixed in stimpack's
        own source and known here at import time.
        """
        from stimpack.visual_stim.framework import SCREEN_FUNCTION_NAMES
        return sorted(set(SCREEN_FUNCTION_NAMES) | set(self.functions_on_root))

    def register_function_on_root(self, function, name=None):
        '''
        Register function to be executed on the server's root node only, and not on the screens.
        '''
        if name is None:
            name = function.__name__

        assert name not in self.functions_on_root, 'Function "{}" already defined.'.format(name)
        self.functions_on_root[name] = function

    def handle_request_list(self, request_list):
        '''
        Handle a list of requests. 
        Requests that are meant for the server's root node
        (i.e. registered with register_function_on_root) are executed on the server.
        Other requests are sent to the screens.

        This function overrides the one in MyTransceiver.
        '''

        # make sure that request list is actually a list...
        if not isinstance(request_list, list):
            print("Request list is not a list and thus cannot be handled.")
            return

        # pull out requests that are meant for server root node and not the screens
        root_request_list = [req for req in request_list if isinstance(req, dict) and 'name' in req and req['name'] in self.functions_on_root]
        screen_request_list = [req for req in request_list if not (isinstance(req, dict) and 'name' in req and req['name'] in self.functions_on_root)]

        # handle requests for the root server without sending to screens
        for request in root_request_list:
            # get function call parameters
            function = self.functions_on_root[request['name']]
            args = request.get('args', [])
            kwargs = request.get('kwargs', {})

            # call function, isolating handler errors so one bad root request cannot kill the server loop
            # print(f"Server root node executing: {str(request)}")
            try:
                function(*args, **kwargs)
            except Exception as e:
                warnings.warn(f"Error handling root request '{request['name']}':\n{traceback.format_exc()}")
                self._report_error(f"visual: {request['name']}: {type(e).__name__}: {e}")

        # Stamp the screen-bound requests with the current time, copying rather than editing in
        # place. Under target='all' the server hands the SAME dict objects to every module, and this
        # module runs first, so mutating one here would deliver a stray 't' kwarg to locomotion and
        # voltage_out as well. That is invisible today only because neither implements any of
        # time_stamp_commands; the first one that does would get a TypeError on a signature that
        # looks correct. 't' is a screen frame timestamp and should not leave this module.
        screen_request_list = [
            {**request, 'kwargs': {**request.get('kwargs', {}), 't': time()}}
            if isinstance(request, dict) and request.get('name') in self.time_stamp_commands
            else request
            for request in screen_request_list
        ]

        # send modified request list to screens
        for screen_manager in self.screen_managers:
            screen_manager.write_request_list(screen_request_list)

        # Drain any messages the screens pushed back (e.g. handler errors) and forward them upward.
        for screen_manager in self.screen_managers:
            screen_manager.process_queue()

    def _pump_screen_messages(self, interval=0.05):
        '''Continuously drain the screen subprocesses' inbound queues (see __init__).'''
        while not self.shutdown_flag.is_set():
            for screen_manager in self.screen_managers:
                try:
                    screen_manager.process_queue()
                except Exception:
                    pass
            sleep(interval)

    def _forward_screen_message(self, level, text):
        '''Forward a message a screen subprocess pushed back up toward the client.'''
        if self.error_reporter is not None:
            try:
                self.error_reporter(level, f"[screen] {text}")
            except Exception:
                pass

    def close(self):
        self.shutdown_flag.set()

        # Shut the screen subprocesses down rather than leaving them running. Ask nicely first (the
        # auto-registered 'shutdown' makes paintGL quit the Qt app), then insist.
        for manager in self.screen_managers:
            try:
                manager.shutdown()
            except Exception:
                pass

        for proc in getattr(self, 'screen_processes', []):
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()

        # Close our end of each screen socket too. The subprocess is gone, but our reader thread is
        # still parked on the connection; only close() unblocks and joins it.
        for manager in self.screen_managers:
            try:
                manager.close()
            except Exception:
                pass

    def on_connection_close(self):
        '''
        Clean up the loaded "other stim modules".
        '''
        # Unload all the stim modules from the screen managers
        for screen_manager in self.screen_managers:
            screen_manager.unload_stim_module(barcodes=None)
        return

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

    # run the server and return the resulting client handle (ignore the process handle)
    client_handle, _ = launch_server(__file__, screens=screens, **kwargs)
    return client_handle

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
