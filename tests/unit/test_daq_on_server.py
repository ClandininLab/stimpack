"""DAQonServer must either queue a call in a multicall or send it immediately -- never both.

Both branches used to run: a caller passing a multicall got the hardware call twice, once at the
call and again when the batch dispatched. For a trigger channel that is two TTL edges; for a
reward or opto step, a doubled output. The multicall branch returns the multicall, so callers can
chain the way the labpack subclasses established.
"""
import pytest

from stimpack.daq import DAQonServer
from stimpack.rpc.multicall import MyMultiCall

pytestmark = pytest.mark.unit


class RecordingTransceiver:
    """Stands in for the socket client behind a MyMultiCall: records dispatched batches."""
    def __init__(self):
        self.dispatched = []

    def write_request_list(self, request_list):
        self.dispatched.append(list(request_list))


class RecordingManager:
    """Stands in for DAQonServer's manager: records what would be sent immediately."""
    def __init__(self):
        self.calls = []

    def target(self, target_name):
        manager = self

        class Target:
            def __getattr__(self, name):
                def call(*args, **kwargs):
                    manager.calls.append({'target': target_name, 'name': name, 'kwargs': kwargs})
                return call

        return Target()


@pytest.fixture
def daq():
    d = DAQonServer()
    d.set_manager(RecordingManager())
    return d


@pytest.mark.parametrize('method', ['send_trigger', 'output_step'])
def test_a_batched_call_is_queued_once_and_not_also_sent(daq, method):
    transceiver = RecordingTransceiver()
    multicall = MyMultiCall(transceiver)

    returned = getattr(daq, method)(multicall=multicall, output_channel='DAC0')

    assert len(multicall.request_list) == 1                  # queued exactly once
    assert multicall.request_list[0]['target'] == 'voltage_out'
    assert multicall.request_list[0]['name'] == method
    assert daq.manager.calls == []                           # nothing sent immediately
    assert returned is multicall                             # chainable, like the labpack subclasses

    multicall()
    assert len(transceiver.dispatched) == 1                  # the batch delivers it exactly once


@pytest.mark.parametrize('method', ['send_trigger', 'output_step'])
def test_an_unbatched_call_is_sent_immediately_exactly_once(daq, method):
    getattr(daq, method)(output_channel='DAC0')

    assert len(daq.manager.calls) == 1
    assert daq.manager.calls[0]['target'] == 'voltage_out'
    assert daq.manager.calls[0]['name'] == method
