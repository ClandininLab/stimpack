"""BaseManager: the module contract, hardened once and inherited by the method-dispatch modules.

DAQ, LocoManager and LocoClosedLoopManager carried byte-identical dispatch loops (and
LocoSocketManager a fourth, dead copy) that had already drifted in style; now one implementation
exists and these tests pin its behavior once. VisualStimServer deliberately does NOT inherit: it
is a transceiver whose __getattr__ turns missing attributes into RPC stubs bound for the screens,
and a no-op default from a base class would shadow that forwarding.
"""
import warnings

import pytest

from stimpack.module import BaseManager

pytestmark = pytest.mark.unit


class Valve(BaseManager):
    module_name = 'odor'

    def __init__(self):
        super().__init__()
        self.opened = []

    def open_valve(self, channel):
        self.opened.append(channel)

    def explode(self):
        raise RuntimeError('boom')


def _reports(module):
    seen = []
    module.error_reporter = lambda level, text: seen.append((level, text))
    return seen


def test_requests_dispatch_to_public_methods():
    v = Valve()
    v.handle_request_list([{'name': 'open_valve', 'args': [2], 'kwargs': {}}])
    assert v.opened == [2]


def test_a_failing_handler_is_isolated_and_reported_with_the_module_prefix():
    v = Valve()
    seen = _reports(v)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        v.handle_request_list([{'name': 'explode', 'args': [], 'kwargs': {}},
                               {'name': 'open_valve', 'args': [7], 'kwargs': {}}])
    assert v.opened == [7]                          # the batch survives the bad handler
    assert seen and seen[0][0] == 'error'
    assert seen[0][1].startswith('odor: explode:')  # module_name names the culprit


def test_an_unknown_name_is_reported_not_skipped():
    v = Valve()
    seen = _reports(v)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        v.handle_request_list([{'name': 'open_valv', 'args': [], 'kwargs': {}}])
    assert seen and "no such method 'open_valv'" in seen[0][1]


def test_a_broadcast_this_module_does_not_handle_stays_quiet():
    v = Valve()
    seen = _reports(v)
    v.handle_request_list([{'name': 'start_stim', 'target': 'all', 'args': [], 'kwargs': {}}])
    assert seen == []


def test_a_broken_reporter_cannot_take_dispatch_down():
    v = Valve()
    v.error_reporter = lambda level, text: 1 / 0
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        v.handle_request_list([{'name': 'explode', 'args': [], 'kwargs': {}}])   # must not raise
        v.handle_request_list([{'name': 'nope', 'args': [], 'kwargs': {}}])      # here too


def test_the_method_dispatch_modules_share_the_one_implementation():
    from stimpack.daq import DAQ
    from stimpack.locomotion import LocoManager, LocoClosedLoopManager

    assert issubclass(DAQ, BaseManager) and DAQ.module_name == 'daq'
    assert issubclass(LocoManager, BaseManager) and LocoManager.module_name == 'locomotion'
    # The point of the base class: no per-module copies left to drift.
    assert DAQ.handle_request_list is BaseManager.handle_request_list
    assert LocoManager.handle_request_list is BaseManager.handle_request_list
    assert LocoClosedLoopManager.handle_request_list is BaseManager.handle_request_list


def test_the_visual_server_does_not_inherit():
    # VisualStimServer forwards requests to screens via MyTransceiver.__getattr__ RPC stubs;
    # BaseManager's no-op lifecycle defaults would shadow that forwarding, so it implements the
    # contract natively (see stimpack/module.py's docstring).
    from stimpack.visual_stim.stim_server import VisualStimServer
    assert not issubclass(VisualStimServer, BaseManager)


def test_a_module_that_returns_none_is_advertised_as_unknown():
    from stimpack.experiment.server import BaseServer

    class Forwarder(BaseManager):
        def get_callable_names(self):
            return None                     # "I forward; I cannot enumerate myself"

    server = BaseServer.__new__(BaseServer)
    server.modules = {'relay': Forwarder(), 'odor': Valve()}
    server.functions_on_root = {}
    sent = []
    server.write_request_list = sent.append

    server.on_connection_open()

    functions = {r['name']: r['args'][0] for r in sent[0]}['report_server_functions']
    assert 'relay' not in functions          # declined -> unknown, not an empty list
    assert 'open_valve' in functions['odor']  # the sibling still enumerates
