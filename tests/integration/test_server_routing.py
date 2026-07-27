"""Integration tests for BaseServer request routing, including the "hardware isn't there" cases.

A rig without opto hardware runs a server with no daq module. A protocol that asks for opto anyway
must not be silently ignored -- that is how a session gets recorded with no stimulation while the
metadata implies otherwise.
"""
import warnings

import pytest

from helpers import unobtrusive_screen

pytestmark = pytest.mark.integration


@pytest.fixture
def visual_only_server():
    """A server configured like a rig with no opto/locomotion hardware: visual module only."""
    from stimpack.experiment.server import BaseServer

    try:
        server = BaseServer(host='127.0.0.1', port=None,
                            visual_stim_kwargs={'screens': [unobtrusive_screen()]},
                            start_loop=False)
    except Exception as e:
        pytest.skip(f'could not construct a server here: {type(e).__name__}: {e}')

    server._reported = []
    server.report_to_client = lambda level, text: server._reported.append((level, text))
    yield server
    server.close()


def test_opto_request_without_daq_hardware_is_reported(visual_only_server):
    server = visual_only_server
    assert 'daq' not in server.modules                      # this rig has no opto hardware

    # target('daq') is normalized to the canonical 'voltage_out' before routing, so that is the
    # name reported back.
    with pytest.warns(UserWarning, match="no 'voltage_out' module"):
        server.handle_request_list([{'target': 'voltage_out', 'name': 'setup_pulse_wave_stream_out',
                                     'args': [], 'kwargs': {}}])

    assert server._reported, 'an opto call on a rig with no DAQ was silently dropped'
    level, text = server._reported[0]
    # A warning, not an error: one protocol legitimately runs on rigs with and without opto, so this
    # must be visible without aborting the run (the protocol decides, via daq_available).
    assert level == 'warning'
    assert 'setup_pulse_wave_stream_out' in text and 'voltage_out' in text


def test_locomotion_request_without_loco_hardware_is_reported(visual_only_server):
    server = visual_only_server
    with pytest.warns(UserWarning, match="no 'locomotion' module"):
        server.handle_request_list([{'target': 'locomotion', 'name': 'loop_start',
                                     'args': [], 'kwargs': {}}])
    assert server._reported and server._reported[0][0] == 'warning'


def test_typo_in_target_name_is_reported(visual_only_server):
    server = visual_only_server
    with pytest.warns(UserWarning, match="no 'vizual' module"):
        server.handle_request_list([{'target': 'vizual', 'name': 'load_stim',
                                     'args': [], 'kwargs': {}}])
    assert server._reported and server._reported[0][0] == 'warning'


def test_configured_module_and_broadcast_are_not_reported(visual_only_server):
    """The normal paths must stay quiet: a configured target, a broadcast, and root."""
    server = visual_only_server
    with warnings.catch_warnings():
        warnings.simplefilter('error')                      # any warning here fails the test
        server.handle_request_list([
            {'target': 'visual', 'name': 'set_idle_background', 'args': [0.5], 'kwargs': {}},
            {'target': 'all', 'name': 'start_stim', 'args': [], 'kwargs': {}},
            {'target': 'root', 'name': 'print_on_server', 'args': ['hi'], 'kwargs': {}},
        ])
    assert server._reported == []
