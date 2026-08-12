"""The audio module reached through a real BaseServer, by target.

Built with ``visual_stim_kwargs=None`` -- a rig with a sound card and no displays -- so these run
without launching screen subprocesses. The stand-in manager means no sound card is needed either.
"""
import warnings

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def audio_server():
    from stimpack.audio import NullAudioManager
    from stimpack.experiment.server import BaseServer

    server = BaseServer(host='127.0.0.1', port=None,
                        visual_stim_kwargs=None,              # no displays on this rig
                        audio_class=NullAudioManager,
                        audio_kwargs={'sample_rate': 8000},
                        start_loop=False)
    server._reported = []
    server.report_to_client = lambda level, text: server._reported.append((level, text))
    # BaseServer wires error_reporter over the modules it built; re-point it at the capturing one.
    for module in server.modules.values():
        module.error_reporter = server.report_to_client
    server.modules['audio'].start()
    yield server
    server.close()


def test_the_audio_module_is_registered_under_its_target_name(audio_server):
    assert 'audio' in audio_server.modules


def test_a_targeted_audio_request_reaches_the_module(audio_server):
    audio_server.handle_request_list([
        {'target': 'audio', 'name': 'load_stim', 'args': [], 'kwargs': {'name': 'SineSong', 'duration': 0.01}},
    ])
    assert audio_server.modules['audio']._frame_count() == 80      # 0.01 s at 8000 Hz


def test_a_broadcast_starts_and_stops_audio_with_everything_else(audio_server):
    audio = audio_server.modules['audio']
    audio_server.handle_request_list([
        {'target': 'audio', 'name': 'load_stim', 'args': [], 'kwargs': {'name': 'SineSong', 'duration': 0.01}},
    ])
    audio_server.handle_request_list([
        {'target': 'all', 'name': 'start_stim', 'args': [], 'kwargs': {'append_stim_frames': False}},
    ])
    assert audio._playing
    audio_server.handle_request_list([
        {'target': 'all', 'name': 'stop_stim', 'args': [], 'kwargs': {'print_profile': False}},
    ])
    assert not audio._playing


def test_audio_is_advertised_to_a_connecting_client(audio_server):
    """What has_module('audio') and has_server_function('load_stim', target='audio') answer from."""
    sent = []
    audio_server.write_request_list = lambda request_list: sent.extend(request_list)
    audio_server.on_connection_open()

    modules = next(r for r in sent if r['name'] == 'report_server_modules')['args'][0]
    functions = next(r for r in sent if r['name'] == 'report_server_functions')['args'][0]
    assert 'audio' in modules
    assert 'load_stim' in functions['audio'] and 'start_stim' in functions['audio']


def test_an_audio_call_on_a_rig_without_a_sound_card_warns_rather_than_aborting():
    """A protocol should run on rigs with and without audio. Same treatment as a missing DAQ."""
    from stimpack.experiment.server import BaseServer

    server = BaseServer(host='127.0.0.1', port=None, visual_stim_kwargs=None, start_loop=False)
    server._reported = []
    server.report_to_client = lambda level, text: server._reported.append((level, text))
    try:
        assert 'audio' not in server.modules
        with pytest.warns(UserWarning, match="no 'audio' module"):
            server.handle_request_list([{'target': 'audio', 'name': 'load_stim',
                                         'args': [], 'kwargs': {'name': 'SineSong'}}])
        assert server._reported and server._reported[0][0] == 'warning'
    finally:
        server.close()


def test_audio_is_a_known_target_so_the_labpack_checker_does_not_call_it_a_typo():
    from stimpack.experiment.server import KNOWN_TARGETS
    assert 'audio' in KNOWN_TARGETS


def test_the_normal_paths_stay_quiet(audio_server):
    with warnings.catch_warnings():
        warnings.simplefilter('error')                   # any warning here fails the test
        audio_server.handle_request_list([
            {'target': 'audio', 'name': 'load_stim', 'args': [], 'kwargs': {'name': 'Silence', 'duration': 0.01}},
            {'target': 'all', 'name': 'start_stim', 'args': [], 'kwargs': {}},
            {'target': 'all', 'name': 'stop_stim', 'args': [], 'kwargs': {}},
        ])
    assert audio_server._reported == []
