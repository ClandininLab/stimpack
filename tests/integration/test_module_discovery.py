"""Integration tests for module discovery, target aliasing, and server-message dedupe.

These let ONE protocol run on rigs with different hardware: the server says which modules it has,
and the protocol adapts, rather than the framework knowing about any particular capability.
"""
import pytest

from fakes import FakeManager
from helpers import unobtrusive_screen

pytestmark = pytest.mark.integration


class _Protocol:
    """A BaseProtocol built without a config, to test has_module() in isolation."""
    def __new__(cls):
        from stimpack.experiment.protocol import BaseProtocol
        p = BaseProtocol.__new__(BaseProtocol)
        p.available_modules = None
        return p


# --- has_module ---------------------------------------------------------------------------------

def test_has_module_is_permissive_when_the_server_never_advertised():
    # An older server doesn't report its modules; protocols must behave exactly as before.
    p = _Protocol()
    assert p.available_modules is None
    assert p.has_module('voltage_out') is True
    assert p.has_module('anything') is True


def test_has_module_reflects_what_the_server_advertised():
    p = _Protocol()
    p.available_modules = {'visual', 'locomotion'}      # a behavior rig: no voltage out
    assert p.has_module('visual') is True
    assert p.has_module('voltage_out') is False         # so a shared protocol skips its opto calls


def test_prepare_run_picks_up_the_modules_from_the_manager():
    from stimpack.experiment.protocol import BaseProtocol

    class Tiny(BaseProtocol):
        def get_run_parameter_defaults(self):
            return {'num_epochs': 1, 'idle_color': 0.5, 'do_loco': False}
        def get_protocol_parameter_defaults(self):
            return {'pre_time': 0.0, 'stim_time': 0.0, 'tail_time': 0.0}
        def get_epoch_parameters(self):
            super().get_epoch_parameters()
            self.epoch_stim_parameters = {'name': 'FakeStim'}

    manager = FakeManager()
    manager.available_modules = {'visual', 'voltage_out'}
    protocol = Tiny(cfg={})
    protocol.prepare_run(manager=manager)

    # available before precompute runs, so has_module() is usable inside get_epoch_parameters too
    assert protocol.available_modules == {'visual', 'voltage_out'}
    assert protocol.has_module('voltage_out') is True
    assert protocol.has_module('locomotion') is False


# --- target aliasing ----------------------------------------------------------------------------

def test_daq_target_is_aliased_to_voltage_out(visual_only_server_with_voltage_out):
    """Existing labpack protocols calling target('daq') keep working."""
    server, module = visual_only_server_with_voltage_out
    assert 'voltage_out' in server.modules and 'daq' not in server.modules

    with pytest.warns(UserWarning, match="deprecated"):
        server.handle_request_list([{'target': 'daq', 'name': 'send_trigger',
                                     'args': [], 'kwargs': {}}])
    assert module.triggered == 1                       # routed to the voltage_out module

    # ...and the canonical name works without any deprecation warning
    server.handle_request_list([{'target': 'voltage_out', 'name': 'send_trigger',
                                 'args': [], 'kwargs': {}}])
    assert module.triggered == 2


def test_alias_deprecation_warns_once_not_per_call(visual_only_server_with_voltage_out):
    server, _ = visual_only_server_with_voltage_out
    with pytest.warns(UserWarning, match='deprecated'):
        server.handle_request_list([{'target': 'daq', 'name': 'send_trigger', 'args': [], 'kwargs': {}}])
    # a second call must not warn again (per-epoch opto would otherwise flood the console)
    import warnings as w
    with w.catch_warnings():
        w.simplefilter('error')
        server.handle_request_list([{'target': 'daq', 'name': 'send_trigger', 'args': [], 'kwargs': {}}])


@pytest.fixture
def visual_only_server_with_voltage_out():
    from stimpack.device.daq import DAQ
    from stimpack.experiment.server import BaseServer
    class CountingDAQ(DAQ):
        triggered = 0
        def send_trigger(self, *args, **kwargs):
            CountingDAQ.triggered += 1

    CountingDAQ.triggered = 0
    try:
        server = BaseServer(host='127.0.0.1', port=None,
                            visual_stim_kwargs={'screens': [unobtrusive_screen()]},
                            daq_class=CountingDAQ, start_loop=False)
    except Exception as e:
        pytest.skip(f'could not construct a server here: {type(e).__name__}: {e}')
    yield server, CountingDAQ
    server.close()


# --- message dedupe -----------------------------------------------------------------------------

def test_repeated_server_messages_are_reported_once_per_run(client):
    """A per-epoch condition must not emit the same line hundreds of times."""
    surfaced = []
    client.on_server_message = lambda level, text: surfaced.append((level, text))

    for _ in range(200):
        client.report_server_message('warning', "no 'voltage_out' module on this server")

    assert len(surfaced) == 1                          # surfaced once...
    assert len(client.server_messages) == 1            # ...and server_messages doesn't grow unbounded
    assert client._message_counts[('warning', "no 'voltage_out' module on this server")] == 200


def test_distinct_messages_are_each_reported(client):
    surfaced = []
    client.on_server_message = lambda level, text: surfaced.append((level, text))
    client.report_server_message('warning', 'first')
    client.report_server_message('warning', 'second')
    assert len(surfaced) == 2


def test_a_repeated_error_still_aborts_the_run(client):
    client.report_server_message('error', 'boom')
    client.server_error = None                          # pretend the run loop consumed it
    client.report_server_message('error', 'boom')       # a repeat must still mark the run for abort
    assert client.server_error == 'boom'
