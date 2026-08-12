"""
The module contract, stated once and enforced by the class hierarchy.

A *module* is an entry in ``BaseServer.modules``: one capability -- screens, a tracker, a DAQ, a
lab's own hardware -- reached by ``target(name)``. Two classes carry the contract, with two
different guarantees and two different mechanisms:

- :class:`BaseModule` guarantees **form**. It is abstract and holds no behavior; every module
  inherits it, stimpack's own included. Abstractness is the enforcement: a module that misses a
  contract method cannot even be instantiated, so adding a method to the contract turns every
  missing implementation into a loud startup error rather than a silently wrong default.
- :class:`BaseManager` guarantees **behavior**. It implements the contract for the *manager*
  kind of module -- one that executes requests as calls on itself and owns the hardware behind
  them, which is every module except the forwarding kind (see below).

INVARIANT: ``BaseModule`` must never gain a concrete method or attribute; concrete belongs in
``BaseManager``. The reason is ``VisualStimServer`` (and any future module that forwards its
requests elsewhere): it relays calls to screen subprocesses via ``MyTransceiver.__getattr__``,
which fires only when normal attribute lookup *fails*. A concrete default inherited from a base
class would be found by that lookup and silently swallow calls meant for the screens -- a
success-shaped no-op, the worst failure mode this codebase knows. An abstract method is safe
precisely because the forwarder is forced to override it explicitly. A test pins this invariant.
"""
from abc import ABC, abstractmethod
import traceback
import warnings

from stimpack.rpc.transceiver import is_broadcast


class BaseModule(ABC):
    """The form of a module: what every module implements, with no behavior attached.

    Managers get all of this from :class:`BaseManager`. A module that *forwards* its requests
    somewhere else (as the visual module does, to its screen subprocesses) inherits this class
    directly and implements each method explicitly -- including explicit, name-translating
    forwarding where a hook's real handler lives remotely. See ``writing_a_module`` in the docs
    for each method's semantics and when the server calls it.
    """

    @abstractmethod
    def handle_request_list(self, request_list):
        """Execute or route a batch of requests, each a dict of ``name``, ``args``, ``kwargs``."""

    @abstractmethod
    def get_callable_names(self):
        """The names this module answers to, for the server to advertise -- or ``None`` for
        "cannot enumerate myself" (honest for a forwarder whose surface lives elsewhere)."""

    @abstractmethod
    def start(self):
        """Claim hardware / begin operating; construction in ``__init__`` should not."""

    @abstractmethod
    def close(self):
        """Release hardware and child processes. The server closes every module at shutdown."""

    @abstractmethod
    def on_connection_close(self):
        """A client disconnected: stop anything that should not outlive the session."""

    @abstractmethod
    def set_save_directory(self, save_directory):
        """Where to write files that accompany the data file (a tracker's log, a screen's
        position history, ...)."""


class BaseManager(BaseModule):
    """The standard implementation of the module contract, for modules that execute requests as
    their own methods and own hardware. Subclass it, set ``module_name``, and write the methods
    your hardware needs -- see ``writing_a_module`` in the docs."""

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
        subclass that forwards its requests elsewhere should override this to return None: callers
        are then told the answer is unknown rather than given a wrong one.
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

    # Lifecycle hooks, no-ops by default -- override the ones your hardware needs.
    # (See writing_a_module for when each is called.)
    def start(self):
        pass

    def close(self):
        pass

    def on_connection_close(self):
        pass

    def set_save_directory(self, save_directory):
        pass
