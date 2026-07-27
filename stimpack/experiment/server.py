"""
The server side of an experiment: owns the hardware and routes requests to it.

:class:`BaseServer` holds one module per capability -- ``visual`` (screens), ``locomotion`` (a
tracker), ``voltage_out`` (a DAQ) -- and dispatches each incoming request by its ``target``. It
usually runs on the rig machine while the client runs wherever the experimenter is sitting.

The routing rule that most often catches people out: a request with no target goes to the
server's own ``root`` registry, **not** to the modules. Use ``target('all')`` for "whichever
module handles this". See :meth:`BaseServer.handle_request_list`.
"""
import signal, sys, os, warnings, traceback

from stimpack.visual_stim.screen import Screen
from stimpack.visual_stim.stim_server import VisualStimServer

from stimpack.device.locomotion.loco_managers import LocoManager
from stimpack.device.daq import DAQ

from stimpack.rpc.util import start_daemon_thread, find_free_port
from stimpack.rpc.transceiver import MySocketServer, reject_private_attribute

from stimpack.experiment.util import config_tools

from stimpack.util import ROOT_DIR

# Retired module target names -> the canonical name. 'daq' named the device category; 'voltage_out'
# names the capability (optogenetics, odor, reward, shock, ... are all voltage out), which is how the
# architecture is described. Requests using an old name are still routed, so existing labpack
# protocols calling target('daq') keep working.
MODULE_ALIASES = {'daq': 'voltage_out'}

# Names BaseServer executes on its root node instead of forwarding to a module.
#
# Untargeted requests default to 'root', so this set is what separates a legitimate untargeted call
# from one that lands nowhere -- which is how mis-migrated daq_* calls silently stopped firing. The
# labpack checker uses it for exactly that. An e2e test asserts it matches a live server, so it
# cannot drift from the registrations in __init__.
ROOT_FUNCTION_NAMES = frozenset({
    'print_on_server',
    'set_subject_state',
    'set_current_epoch',
    'load_server_side_state_dependent_control',
    'unload_server_side_state_dependent_control',
})

# Targets a request may name. Modules present depend on the rig (a rig with no voltage-out hardware
# has no such module), so this is the set of *spellings* stimpack understands, not a claim about
# what any given server has.
KNOWN_TARGETS = frozenset(MODULE_ALIASES) | {'visual', 'locomotion', 'voltage_out', 'all', 'root'}


class BaseServer(MySocketServer):
    def __init__(self,
                 host: str = '127.0.0.1',
                 port: int|None = 60629,
                 visual_stim_kwargs: dict = {},
                 loco_class: type|None = None,
                 loco_kwargs: dict = {},
                 daq_class: type|None = None,
                 daq_kwargs: dict = {},
                 start_loop: bool = False):
        '''
        host: interface to bind the (unauthenticated) RPC server to. Defaults to loopback
              ('127.0.0.1') so the control channel is not exposed to the network. To accept
              connections from other machines, pass host='0.0.0.0' explicitly and firewall the
              port to the trusted rig network.
        '''

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
            visual_stim_kwargs['screens'] = [Screen(x_display=None, display_index=0, fullscreen=False, vsync=True, square_size=(0.25, 0.25))]
        
        self.modules['visual'] = VisualStimServer(**visual_stim_kwargs)  # auto_stop=False
        ### Visual stim manager ###

        ### Locomotion manager ###
        if loco_class is not None:
            assert issubclass(loco_class, LocoManager)
            self.modules['locomotion'] = loco_class(stim_server=self, start_at_init=False, **loco_kwargs)
        ### Locomotion manager ###

        ### Voltage out manager (a DAQ device: opto, odor, reward, trigger, ...) ###
        if daq_class is not None:
            assert issubclass(daq_class, DAQ)
            self.modules['voltage_out'] = daq_class(**daq_kwargs)
        ### Voltage out manager ###

        self._warned_module_aliases = set()   # so a retired target name warns once, not per call

        # Let each module bubble its handler errors back to the client (surfaced in the GUI; aborts the run).
        for module in self.modules.values():
            module.error_reporter = self.report_to_client

        # Register functions to be executed on the server's root node, and not in modules.
        # Keep this in step with ROOT_FUNCTION_NAMES above; an e2e test asserts they match.
        self.functions_on_root = {}
        self.register_function_on_root(lambda x: print(x), "print_on_server")
        self.register_function_on_root(self.set_subject_state, "set_subject_state")
        self.register_function_on_root(self.set_current_epoch, "set_current_epoch")
        self.register_function_on_root(self.load_server_side_state_dependent_control, "load_server_side_state_dependent_control")
        self.register_function_on_root(self.unload_server_side_state_dependent_control, "unload_server_side_state_dependent_control")

        def signal_handler(sig, frame):
            print('Closing server after Ctrl+C...')
            self.close()
            sys.exit(0)
        signal.signal(signal.SIGINT, signal_handler)

        # Custom state-dependent control function, initialized to None        
        self.loaded_custom_state_dependent_control = None

        # Which epoch the client is running, set by the client as each one starts. Used to stamp
        # end_epoch() so a request cannot arrive late and cut short the epoch after the one it was
        # meant for. None between epochs, when there is nothing to end.
        self.current_epoch_index = None

        # set the subject position parameters
        self.subject_state = {}
        self.set_subject_state({'x': 0, 'y': 0, 'z': 0, 'theta': 0, 'phi': 0, 'roll':0}) # meters and degrees

        if start_loop:
            start_daemon_thread(self.loop)

    def __getattr__(self, name: str):
        '''
        Allow the server to execute function calls as a client. Any attribute access
        that is not a standard attribute of the server will be forwarded as an
        RPC request to the 'root' target.
        '''
        # print(f"Server does not have attribute {name}; call must be for either module or an attribute or method of BaseServer.")
        reject_private_attribute(name)
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
                if request.get('_untargeted'):
                    # An untargeted call landed here by default, not by choice, and found nothing.
                    # That is the classic silent failure of this RPC style, and how mis-migrated
                    # daq_* calls stopped firing: an error, because the call was meant for
                    # something and reached nothing.
                    msg = (f"no such function '{request['name']}' on the server root node. "
                           f"Untargeted calls go to root -- if you meant a module, use "
                           f"target('all') or target('<module>').")
                    level = 'error'
                else:
                    # The caller explicitly said target('root'), so they knew where they were
                    # aiming; this rig simply has not registered that function. Labs register
                    # rig-specific functions on root (a projector's LED current, a shutter), and a
                    # protocol written for one rig should degrade on another rather than refuse to
                    # run -- the same reasoning as a request for a module this server lacks, which
                    # is likewise a warning.
                    msg = (f"no function '{request['name']}' is registered on this server's root "
                           f"node (registered: {sorted(self.functions_on_root)}); "
                           f"request was dropped")
                    level = 'warning'
                warnings.warn(msg)
                self.report_to_client(level, msg)
                continue
            function = self.functions_on_root[request['name']]
            args = request.get('args', [])
            kwargs = request.get('kwargs', {})

            # call function, isolating handler errors so one bad root request cannot kill the server loop
            # print(f"Server root node executing: {str(request)}")
            try:
                function(*args, **kwargs)
            except Exception as e:
                warnings.warn(f"Error handling root request '{request['name']}':\n{traceback.format_exc()}")
                self.report_to_client('error', f"error handling '{request['name']}': {type(e).__name__}: {e}")

    def on_connection_open(self):
        '''
        Tell the freshly-connected client which modules this server has, so protocols can adapt to
        the rig instead of assuming its hardware (see BaseProtocol.has_module). Generic on purpose:
        it reports whatever modules exist, rather than any particular capability flag.
        '''
        # Also advertise the callable names, so a protocol can ask whether this rig has a
        # lab-registered function rather than calling it and reading the warning afterwards.
        # Only targets that can enumerate themselves are listed: the visual module forwards to
        # screen subprocesses, so a list built here would be wrong, and being absent means
        # "unknown", which has_server_function answers True to.
        functions = {'root': sorted(self.functions_on_root)}
        for module_name, module in self.modules.items():
            # Asked of the CLASS, not the instance. A module may be a transceiver, whose
            # __getattr__ turns any missing attribute into an RPC stub -- so
            # getattr(module, 'get_callable_names', None) never returns None, and calling the stub
            # sends the question down the wire to a screen that has never heard of it.
            if getattr(type(module), 'get_callable_names', None) is None:
                continue
            try:
                functions[module_name] = sorted(module.get_callable_names())
            except Exception:
                pass          # a module that cannot say is simply not listed

        self.write_request_list([
            {'name': 'report_server_modules', 'args': [sorted(self.modules)], 'kwargs': {}},
            {'name': 'report_server_functions', 'args': [functions], 'kwargs': {}},
        ])

    def report_to_client(self, level, text):
        '''
        Push a message (e.g. an error) back to the connected client, which surfaces it in the GUI and,
        for level='error', aborts the run. Best-effort: no-ops if no client is connected (outfile is None).
        '''
        self.write_request_list([{'name': 'report_server_message', 'args': [level, str(text)], 'kwargs': {}}])

    def handle_request_list(self, request_list):
        '''
        Route each request by its ``target``::

            (absent) / 'root'   the server's own functions_on_root registry ONLY. An untargeted
                                call does NOT reach the modules; if the name is not registered on
                                root, nothing happens (and it is reported back to the client).
            '<module name>'     that module only ('visual', 'locomotion', 'voltage_out').
            'all'               broadcast to every module; each acts only on the names it
                                defines, so target('all').start_stim() is handled by the screens
                                and ignored by the others, which is expected.

        Use ``target('all')`` when you mean "whichever module handles this" -- writing the call
        untargeted instead sends it to root, where it will not be found.

        Note that ``'all'`` covers the modules but NOT root, deliberately: root's
        ``set_subject_state`` itself fans out via ``target('all')``, so including root would
        recurse forever.
        '''
        # pre-process the request list as necessary
        for request in request_list:
            if isinstance(request, dict) and ('name' in request):
                if 'target' not in request:
                    request['target'] = 'root'
                    # Remember that root was the default rather than the caller's choice: the two
                    # cases mean opposite things when the name turns out not to be registered.
                    request['_untargeted'] = True
                if 'kwargs' not in request:
                    request['kwargs'] = {}

                # Normalize retired target names (e.g. 'daq' -> 'voltage_out'), warning once each.
                target = request['target']
                if target in MODULE_ALIASES:
                    request['target'] = MODULE_ALIASES[target]
                    if target not in self._warned_module_aliases:
                        self._warned_module_aliases.add(target)
                        warnings.warn(f"target('{target}') is deprecated; use "
                                      f"target('{MODULE_ALIASES[target]}').")

        # A request addressed to a module this server doesn't have (e.g. an opto call on a rig with
        # no daq_class, or a typo'd target) matches nothing in the loop below, and would otherwise be
        # dropped without a trace.
        #
        # Reported as a WARNING, not an error: running one protocol across rigs with different
        # hardware is legitimate and common, and the server cannot tell "this rig simply has no
        # opto" from "opto was expected here". So make it visible without aborting the run, and let
        # the protocol decide -- it knows whether opto was actually requested. Guard those calls with
        # `if self.daq_available and <opto requested>:` (see config_tools.get_daq_available) and set
        # `daq_available: False` for rigs without the hardware, and this warning won't fire at all.
        known_targets = set(self.modules) | {'root', 'all'}
        for request in request_list:
            if isinstance(request, dict) and request.get('target') not in known_targets:
                msg = (f"no '{request.get('target')}' module on this server "
                       f"(configured: {sorted(self.modules)}); "
                       f"request '{request.get('name')}' was dropped")
                warnings.warn(msg)
                self.report_to_client('warning', msg)

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
        
    def set_current_epoch(self, epoch_index):
        """
        Told by the client as each epoch begins, and set to None when it ends.

        Only used to stamp :meth:`end_epoch`; the server does not otherwise care which epoch is
        running.
        """
        self.current_epoch_index = epoch_index

    def end_epoch(self, reason=None):
        """
        Ask the client to end the epoch in progress early, and go on to the next one.

        For trials whose length is decided by what the animal does rather than by the clock: a
        fixation held long enough, a virtual goal reached, a choice made. The condition has to be
        evaluated here rather than on the client, because the client never sees subject state and
        could not ask for it if it wanted to -- requests carry no reply.

        Call it from a labpack's server-side closed-loop function, which runs on every tracker
        update with the full subject state::

            def server_side_state_dependent_control(server, subject_state, state_update):
                if subject_state['x'] > 0.5:
                    server.end_epoch(reason='reached_goal')
                return state_update

        :param reason: recorded with the epoch, so a trial that ended early can be told apart
            from one that ran its full length. Worth setting: once duration depends on behaviour,
            the protocol's stim_time describes the intent rather than the trial.

        Does nothing between epochs -- there is nothing to end, and ending the next one because a
        criterion was met just after the last is a bug that would be hard to see in the data.

        This ends one epoch. To stop the whole run, report an error instead
        (:meth:`report_to_client`), which aborts it and records why.
        """
        if self.current_epoch_index is None:
            return
        self.write_request_list([{'name': 'stop_epoch',
                                  'args': [], 'kwargs': {'epoch_index': self.current_epoch_index,
                                                         'reason': reason}}])

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