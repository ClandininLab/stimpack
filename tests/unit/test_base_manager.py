"""The module contract: BaseModule is the abstract form every module inherits; BaseManager the
behavior layer for modules that execute requests as their own methods.

DAQ, LocoManager and LocoClosedLoopManager carried byte-identical dispatch loops (and
LocoSocketManager a fourth, dead copy) that had already drifted in style; now one implementation
exists and these tests pin its behavior once. VisualStimServer inherits the FORM only: it is a
transceiver whose __getattr__ turns missing attributes into RPC stubs bound for the screens, so
a concrete default inherited from any base would shadow that forwarding -- which is why
BaseModule must stay behavior-free (pinned below) and why the visual server implements every
contract method explicitly.
"""
import warnings

import pytest

from stimpack.module import BaseModule, BaseManager

CONTRACT_METHODS = ('handle_request_list', 'get_callable_names', 'start', 'close',
                    'on_connection_close', 'set_save_directory')

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


def test_the_form_is_universal_and_the_behavior_is_not():
    from stimpack.daq import DAQ
    from stimpack.locomotion import LocoManager
    from stimpack.visual_stim.stim_server import VisualStimServer

    assert issubclass(DAQ, BaseModule)
    assert issubclass(LocoManager, BaseModule)
    assert issubclass(VisualStimServer, BaseModule)       # every module shares the form
    assert not issubclass(VisualStimServer, BaseManager)  # only executors share the behavior
    # Every contract method on the visual server is its OWN: a concrete method inherited from
    # any base would shadow its __getattr__ screen forwarding (see its class docstring).
    for name in CONTRACT_METHODS:
        assert name in vars(VisualStimServer), f'{name} must be explicit on VisualStimServer'


def test_the_form_stays_behavior_free():
    # The invariant that makes it safe for a forwarder to inherit BaseModule: nothing concrete,
    # ever. Concrete belongs in BaseManager. See stimpack/module.py's docstring.
    concrete = [name for name, attr in vars(BaseModule).items()
                if not name.startswith('_')
                and not getattr(attr, '__isabstractmethod__', False)]
    assert concrete == []


def test_an_incomplete_module_cannot_even_be_instantiated():
    # Abstractness is the enforcement: forgetting a contract method is a loud startup error,
    # not a silently wrong default.
    class Incomplete(BaseModule):
        def handle_request_list(self, request_list):
            pass

    with pytest.raises(TypeError, match='abstract'):
        Incomplete()


def test_visual_set_save_directory_translates_to_the_screens_vocabulary():
    # The screens' name for this setting is set_save_pos_history_dir; the explicit contract
    # method must translate, where __getattr__ would have forwarded the contract name to screens
    # that have never heard of it.
    from stimpack.visual_stim.stim_server import VisualStimServer

    server = VisualStimServer.__new__(VisualStimServer)
    server.functions_on_root = {}
    sent = []

    class FakeScreenManager:
        def write_request_list(self, request_list):
            sent.append(list(request_list))

        def process_queue(self):
            pass

    server.screen_managers = [FakeScreenManager()]
    server.set_save_directory('/data/run7')

    names = [r['name'] for rl in sent for r in rl]
    assert names == ['set_save_pos_history_dir']
    assert sent[0][0]['args'] == ['/data/run7']


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
