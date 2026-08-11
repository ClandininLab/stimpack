"""
The base class for server modules: the module contract, hardened once.

:class:`BaseModule` is for method-dispatch modules -- ones that execute requests as calls on
themselves, which is every module except one. The DAQ and the locomotion managers inherit it, a
labpack's own modules should (see the docs page ``writing_a_module``), and it carries the parts
of the contract that are easy to get subtly wrong: dispatch with each handler's errors isolated
and reported, unknown names reported rather than silently dropped, ``target('all')`` broadcasts
quietly skipped, and no-op defaults for the lifecycle hooks.

``VisualStimServer`` deliberately does NOT inherit this class. It forwards requests to screen
subprocesses instead of executing them, and it is a transceiver: ``MyTransceiver.__getattr__``
turns any *missing* attribute into an RPC stub bound for the screens, so a no-op default
inherited from here would shadow that forwarding. It implements the same contract natively --
which is the naming rule in code: a *Server* serves sockets, a *Manager* owns hardware.

The contract itself stays duck-typed: :class:`~stimpack.experiment.server.BaseServer` checks for
methods, never for this class, so a module may be any object with ``handle_request_list``.
"""
import traceback
import warnings

from stimpack.rpc.transceiver import is_broadcast


class BaseModule():
    #: Prefix on errors reported to the client ('daq: ...', 'locomotion: ...'); subclasses set it.
    module_name = 'module'

    def __init__(self, verbose=False):
        self.verbose = verbose
        self.error_reporter = None  # optional callback(level, text); set by BaseServer to reach the client

    def report(self, level, text):
        """Report to the connected client, if any. Never raises: a broken reporter must not take
        the dispatch loop down with it."""
        if self.error_reporter is not None:
            try:
                self.error_reporter(level, text)
            except Exception:
                pass

    def get_callable_names(self):
        """
        Names this module will answer to, for the server to advertise (see
        BaseServer.on_connection_open and BaseProtocol.has_server_function).

        Dispatch below is ``request['name'] in dir(self)``, so the surface is exactly the public
        attributes and this enumeration cannot be wrong for a module that keeps that dispatch. A
        module that cannot enumerate itself -- one that forwards its requests elsewhere -- should
        override this to **return None**: callers are then told the answer is unknown rather than
        given a wrong one. (Absence used to carry that meaning, and still does for modules that do
        not inherit this class; a base class makes absence impossible, so None says it instead.)
        """
        return sorted(name for name in dir(self)
                      if not name.startswith('_') and callable(getattr(self, name, None)))

    def handle_request_list(self, request_list):
        for request in request_list:
            if request['name'] in dir(self):
                # If the request is a method of this class, execute it, isolating handler errors:
                # one bad request must not kill the rest of the batch or the server loop.
                try:
                    getattr(self, request['name'])(*request.get('args', []), **request.get('kwargs', {}))
                except Exception as e:
                    warnings.warn(f"{self.__class__.__name__}: error handling '{request['name']}':\n{traceback.format_exc()}")
                    self.report('error', f"{self.module_name}: {request['name']}: {type(e).__name__}: {e}")
            else:
                # Silently skipping an unknown name is how a mis-named call (an old pre-target()
                # name, a camelCase typo) ends up never firing. Report it.
                if is_broadcast(request):
                    continue          # a target('all') broadcast this module simply doesn't handle
                msg = f"{self.__class__.__name__}: no such method '{request['name']}'"
                warnings.warn(msg)
                self.report('error', f'{self.module_name}: {msg}')

    # Lifecycle hooks, every one optional -- override the ones your hardware needs.
    # (See writing_a_module for when each is called.)
    def start(self):
        pass

    def close(self):
        pass

    def on_connection_close(self):
        pass

    def set_save_directory(self, save_directory):
        pass
