"""Integration tests for BaseServer request routing, including the "hardware isn't there" cases.

A rig without opto hardware runs a server with no daq module. A protocol that asks for opto anyway
must not be silently ignored -- that is how a session gets recorded with no stimulation while the
metadata implies otherwise.
"""
import warnings

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def visual_only_server():
    """A server configured like a rig with no opto/locomotion hardware: visual module only."""
    from stimpack.experiment.server import BaseServer
    from stimpack.visual_stim.screen import Screen

    try:
        server = BaseServer(host='127.0.0.1', port=None,
                            visual_stim_kwargs={'screens': [Screen(fullscreen=False, vsync=False)]},
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

    with pytest.warns(UserWarning, match="no 'daq' module"):
        server.handle_request_list([{'target': 'daq', 'name': 'setup_pulse_wave_stream_out',
                                     'args': [], 'kwargs': {}}])

    assert server._reported, 'an opto call on a rig with no DAQ was silently dropped'
    level, text = server._reported[0]
    assert level == 'error'
    assert 'setup_pulse_wave_stream_out' in text and 'daq' in text


def test_locomotion_request_without_loco_hardware_is_reported(visual_only_server):
    server = visual_only_server
    with pytest.warns(UserWarning, match="no 'locomotion' module"):
        server.handle_request_list([{'target': 'locomotion', 'name': 'loop_start',
                                     'args': [], 'kwargs': {}}])
    assert server._reported and server._reported[0][0] == 'error'


def test_typo_in_target_name_is_reported(visual_only_server):
    server = visual_only_server
    with pytest.warns(UserWarning, match="no 'vizual' module"):
        server.handle_request_list([{'target': 'vizual', 'name': 'load_stim',
                                     'args': [], 'kwargs': {}}])
    assert server._reported and server._reported[0][0] == 'error'


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
