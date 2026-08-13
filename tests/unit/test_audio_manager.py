"""The audio manager: rendering, mixing, the trial lifecycle, and the software stand-in.

The point most worth protecting is that the module needs no protocol changes. A protocol's trial
loop already sends ``target('all').start_stim(...)`` and ``target('all').stop_stim(...)``, along
with several calls meant for other modules; an audio module has to answer the first two and ignore
the rest without complaining. ``test_the_protocols_broadcast_drives_audio_unchanged`` is that.
"""
import time
import warnings

import numpy as np
import pytest

from stimpack.audio import AudioManager, NullAudioManager
from stimpack.module import BaseManager

pytestmark = pytest.mark.unit

SR = 8000       # low, so a test's waveforms are small; nothing here plays


def manager(**kwargs):
    kwargs.setdefault('sample_rate', SR)
    m = NullAudioManager(**kwargs)
    m.start()
    return m


def reports(module):
    seen = []
    module.error_reporter = lambda level, text: seen.append((level, text))
    return seen


# # # The module contract # # #

def test_it_is_a_manager_sharing_the_one_dispatch_implementation():
    assert issubclass(AudioManager, BaseManager)
    assert AudioManager.module_name == 'audio'
    assert AudioManager.handle_request_list is BaseManager.handle_request_list


def test_the_base_class_refuses_to_pretend_it_has_a_device():
    """Silence from a misconfigured rig is the failure mode this module exists to avoid."""
    with pytest.raises(NotImplementedError, match='PyAudioManager|NullAudioManager'):
        AudioManager(sample_rate=SR).start()


def test_callable_names_advertise_the_trial_lifecycle():
    """What has_server_function() will answer from, once the server passes it to the client."""
    names = manager().get_callable_names()
    assert {'load_stim', 'start_stim', 'stop_stim'} <= set(names)


# # # Loading and mixing # # #

def test_load_stim_renders_the_named_sound():
    m = manager()
    m.load_stim('SineSong', duration=0.1, freq=200.0)
    assert m._frame_count() == round(0.1 * SR)


def test_hold_layers_sounds_by_summing_them():
    m = manager()
    m.load_stim('SineSong', duration=0.1, freq=200.0, volume=0.25)
    m.load_stim('SineSong', duration=0.1, freq=200.0, volume=0.25, hold=True)
    both = m._buffer.astype(np.float64)

    m2 = manager()
    m2.load_stim('SineSong', duration=0.1, freq=200.0, volume=0.5)
    np.testing.assert_allclose(both, m2._buffer.astype(np.float64), atol=1)


def test_loading_without_hold_replaces_rather_than_layers():
    m = manager()
    m.load_stim('SineSong', duration=0.2)
    m.load_stim('SineSong', duration=0.1)
    assert m._frame_count() == round(0.1 * SR)


def test_layered_sounds_of_different_lengths_are_padded_to_the_longest():
    m = manager()
    m.load_stim('SineSong', duration=0.2, volume=0.3)
    m.load_stim('SineSong', duration=0.05, volume=0.3, hold=True)
    assert m._frame_count() == round(0.2 * SR)


def test_a_mono_sound_is_spread_across_every_output_channel():
    m = manager(channels=2)
    m.load_stim('SineSong', duration=0.1, volume=0.5)
    interleaved = m._buffer.reshape(-1, 2)
    np.testing.assert_array_equal(interleaved[:, 0], interleaved[:, 1])


def test_an_unknown_sound_name_is_reported_as_an_error_not_dropped():
    m = manager()
    seen = reports(m)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        m.handle_request_list([{'name': 'load_stim', 'args': [], 'kwargs': {'name': 'NoSuchSong'}}])
    assert seen and seen[0][0] == 'error' and seen[0][1].startswith('audio:')


# # # The trial lifecycle # # #

def test_start_stim_returns_immediately_rather_than_waiting_out_the_sound():
    """The whole reason this is a callback and not stream.write(): BaseServer runs handlers inline
    on its accept loop, so a handler that blocks for the length of a sound stops the server."""
    m = manager()
    m.load_stim('SineSong', duration=5.0)

    began = time.monotonic()
    m.start_stim()
    assert time.monotonic() - began < 0.1, 'start_stim blocked for the length of the sound'


def test_stopping_early_reports_the_truncation_as_a_warning():
    m = manager()
    seen = reports(m)
    m.load_stim('SineSong', duration=5.0)
    m.start_stim()
    m.stop_stim()

    assert seen and seen[0][0] == 'warning'     # a protocol may cut a sound off on purpose
    assert 'of a 5.000 s sound' in seen[0][1]


def test_losing_the_output_latency_off_the_end_is_not_called_truncation():
    """The common case: a protocol sets the sound's duration to stim_time, so the last few
    milliseconds are always cut. Warning on that would fire every trial of every audio protocol.

    The stand-in derives how far playback got from the clock, so backdating the start is how a
    trial of a known length is simulated without sleeping through one. Tolerance here is
    4 * 256 frames == 0.128 s at this sample rate.
    """
    m = manager(frames_per_buffer=256)
    seen = reports(m)
    m.load_stim('SineSong', duration=1.0)       # 8000 frames at SR=8000
    m.start_stim()
    m._started_at = time.monotonic() - 0.95     # 0.05 s short: inside the tolerance
    m.stop_stim()
    assert seen == []


def test_a_sound_far_longer_than_the_trial_is_still_reported():
    m = manager(frames_per_buffer=256)
    seen = reports(m)
    m.load_stim('SineSong', duration=1.0)
    m.start_stim()
    m._started_at = time.monotonic() - 0.1      # 0.9 s unplayed: well past the tolerance
    m.stop_stim()
    assert seen and seen[0][0] == 'warning'
    assert 'of a 1.000 s sound' in seen[0][1]


def test_the_real_manager_takes_its_tolerance_from_the_devices_reported_latency():
    """A fixed block count sat within a millisecond of the actual latency on real hardware, so the
    truncation warning fired on jitter. Asking the stream makes it scale with the device."""
    from stimpack.audio import PyAudioManager

    m = PyAudioManager(sample_rate=48000, frames_per_buffer=256)
    assert m._truncation_tolerance() == 4 * 256          # no stream yet: the base-class estimate

    class FakeStream:
        def get_output_latency(self):
            return 0.0227

    m._stream = FakeStream()
    assert m._truncation_tolerance() == int(0.0227 * 48000) + 2 * 256

    class BrokenStream:
        def get_output_latency(self):
            raise OSError('device went away')

    m._stream = BrokenStream()
    assert m._truncation_tolerance() == 4 * 256          # falls back rather than raising


def test_a_sound_that_finishes_within_the_trial_reports_nothing():
    m = manager()
    seen = reports(m)
    m.load_stim('SineSong', duration=0.005)
    m.start_stim()
    time.sleep(0.05)                            # 10x the sound, so this is not timing-sensitive
    m.stop_stim()
    assert seen == []


def test_playing_before_the_device_is_open_is_an_error_naming_the_real_cause():
    """The failure this module exists to prevent, and one it briefly had.

    Nothing calls start() for you unless the client does, and without this branch a rig whose
    audio module was never started played nothing and reported a *truncated sound* -- true, but
    naming the wrong cause, and easy to spend an afternoon on.
    """
    m = NullAudioManager(sample_rate=SR)         # deliberately not started
    seen = reports(m)
    m.load_stim('SineSong', duration=0.1)
    m.start_stim()
    m.stop_stim()

    assert not m._playing
    assert seen and seen[0][0] == 'error'
    assert 'before the device was opened' in seen[0][1]
    assert len(seen) == 1, 'the misleading truncation warning is still being reported too'


def test_a_trial_with_no_sound_loaded_is_a_silent_no_op():
    """Broadcast start_stim/stop_stim reach audio on every trial of every protocol, including the
    ones with no sound. Those must not report, and must not put a row in the log."""
    m = manager()
    seen = reports(m)
    m.start_stim()
    m.stop_stim()
    assert seen == []
    assert m.played == []


def test_stopping_releases_the_loaded_sound_so_trials_do_not_accumulate():
    """Mirrors the visual module, whose stop_stim releases its stimuli. It is what makes
    load_stimuli safe to pass hold=True for every descriptor."""
    m = manager()
    m.load_stim('SineSong', duration=0.1)
    m.start_stim()
    m.stop_stim()

    assert m.sound_list == [] and m._buffer is None

    # A second trial layering with hold=True gets only its own sound, not the last trial's too.
    m.load_stim('SineSong', duration=0.05, hold=True)
    assert m._frame_count() == round(0.05 * SR)


def test_stop_without_start_is_quiet():
    """stop_stim arrives on every trial via target('all'), including trials with no sound."""
    m = manager()
    seen = reports(m)
    m.stop_stim()
    assert seen == []


def test_a_disconnecting_client_does_not_leave_a_sound_playing():
    m = manager()
    m.load_stim('SineSong', duration=5.0)
    m.start_stim()
    m.on_connection_close()
    assert not m._playing


# # # Dropping into the existing trial loop # # #

def test_the_protocols_broadcast_drives_audio_unchanged():
    """Exactly what BaseProtocol.start_stimuli puts on the wire, replayed at the audio module.

    The audio calls must land and the locomotion ones must be ignored in silence -- otherwise every
    trial of every existing protocol would report an error the moment a rig gained a sound card.
    """
    m = manager()
    seen = reports(m)
    m.load_stim('SineSong', duration=0.005)

    m.handle_request_list([
        {'name': 'set_save_pos_history_flag', 'target': 'all', 'args': [False], 'kwargs': {}},
        {'name': 'start_stim', 'target': 'all', 'args': [], 'kwargs': {'append_stim_frames': False}},
    ])
    assert m._playing, 'the broadcast start_stim did not reach the audio module'

    time.sleep(0.05)
    m.handle_request_list([
        {'name': 'stop_stim', 'target': 'all', 'args': [], 'kwargs': {'print_profile': True}},
        {'name': 'save_pos_history_to_file', 'target': 'all', 'args': [], 'kwargs': {'epoch_id': '001'}},
        {'name': 'set_subject_state', 'target': 'all', 'args': [{'x': 0}], 'kwargs': {}},
    ])
    assert not m._playing
    assert seen == [], f'a broadcast meant for another module was reported: {seen}'


# # # Logging # # #

def test_a_trial_writes_one_row_to_the_audio_log(tmp_path):
    m = manager()
    m.set_save_directory(str(tmp_path))
    m.load_stim('SineSong', duration=0.005)
    m.start_stim()
    time.sleep(0.05)
    m.stop_stim()
    m.close()

    rows = (tmp_path / 'audio_log.txt').read_text().strip().split('\n')
    assert len(rows) == 1
    assert 'SineSong' in rows[0]


def test_no_save_directory_means_no_log_and_no_complaint(tmp_path):
    m = manager()
    m.load_stim('SineSong', duration=0.005)
    m.start_stim()
    m.stop_stim()
    m.close()
    assert not list(tmp_path.iterdir())


# # # The stand-in # # #

def test_the_stand_in_records_what_it_would_have_played():
    """What makes an audio protocol developable with no sound card, and testable in CI."""
    m = manager()
    m.load_stim('SineSong', duration=0.005)
    m.start_stim()
    time.sleep(0.05)
    m.stop_stim()

    assert len(m.played) == 1
    names, requested_at, played_seconds = m.played[0]
    assert names == ('SineSong',)
    assert requested_at is not None
    assert played_seconds == pytest.approx(0.005, abs=0.001)


def test_the_stand_in_opens_no_device_and_needs_no_audio_library():
    m = NullAudioManager(sample_rate=SR)
    m.start()
    assert m.started
    m.close()
    assert not m.started


def test_the_generated_buffer_is_the_int16_a_card_wants():
    m = manager()
    m.load_stim('SineSong', duration=0.01, volume=1.0)
    assert m._buffer.dtype == np.int16
    assert m._buffer.max() <= 32767 and m._buffer.min() >= -32768


def test_chunks_handed_to_the_device_are_always_a_full_block():
    """A short final block would tell PortAudio the stream had finished."""
    m = manager(channels=2)
    m.load_stim('SineSong', duration=0.001)     # 8 frames at SR=8000
    m.start_stim()
    chunk = m._next_chunk(256)
    assert len(chunk) == 256 * 2 * 2            # frames * channels * 2 bytes per int16


# # # Event sounds # # #

def test_an_event_sound_plays_with_no_trial_running():
    m = manager()
    m.play_event_sound(name='SineSong', duration=0.01, freq=1000.0, volume=1.0)
    chunk = np.frombuffer(m._next_chunk(80), dtype=np.int16)
    assert np.abs(chunk).max() > 0


def test_an_event_sound_survives_stop_stim():
    """The whole point: a catch chime fires in the same breath as end_trial, and the stop_stim
    that trial teardown broadcasts moments later must not silence it."""
    m = manager()
    m.load_stim(name='SineSong', duration=0.01)
    m.start_stim()
    m.play_event_sound(name='SineSong', duration=0.01, freq=1000.0, volume=1.0)
    m.stop_stim()
    chunk = np.frombuffer(m._next_chunk(80), dtype=np.int16)
    assert np.abs(chunk).max() > 0


def test_an_event_ends_when_its_samples_run_out():
    m = manager()
    m.play_event_sound(name='SineSong', duration=0.01, freq=1000.0)   # 80 frames at SR
    m._next_chunk(80)
    silence = np.frombuffer(m._next_chunk(80), dtype=np.int16)
    assert np.abs(silence).max() == 0
    assert m._active_events == []


def test_an_event_over_a_full_scale_trial_sound_clips_rather_than_wraps():
    """Two full-scale sines sum past int16; int32 mixing plus a clip saturates. An int16
    accumulator would wrap 32767+32767 to -2, and the maximum would collapse."""
    m = manager()
    m.load_stim(name='SineSong', duration=0.01, freq=1000.0, volume=1.0)
    m.start_stim()
    m.play_event_sound(name='SineSong', duration=0.01, freq=1000.0, volume=1.0)
    chunk = np.frombuffer(m._next_chunk(80), dtype=np.int16)
    assert chunk.max() == 32767


def test_an_event_before_the_device_opens_warns_and_queues_nothing():
    m = NullAudioManager(sample_rate=SR)          # never start()ed
    seen = reports(m)
    m.play_event_sound(name='SineSong', duration=0.01)
    assert any('play_event_sound' in text for _, text in seen)
    assert m._pending_events == []


# # # Sources: continuous sounds with live per-channel gains # # #

def _rms(chunk):
    return float(np.sqrt(np.mean(chunk.astype(np.float64) ** 2)))


def _source_manager(**kwargs):
    m = manager(**kwargs)
    m.load_stim(name='SineSong', source_id='src', loop=True, gains=1.0,
                duration=0.01, freq=1000.0, volume=1.0)
    m.start_stim()
    return m


def test_a_looping_source_keeps_playing_past_its_length():
    m = _source_manager()                                   # 0.01 s of samples at SR
    for _ in range(4):                                      # 4 x 80 frames = 4 lengths
        chunk = np.frombuffer(m._next_chunk(80), dtype=np.int16)
    assert np.abs(chunk).max() > 0


def test_a_source_is_silent_until_start_stim():
    m = manager()
    m.load_stim(name='SineSong', source_id='src', loop=True, duration=0.01)
    chunk = np.frombuffer(m._next_chunk(80), dtype=np.int16)
    assert np.abs(chunk).max() == 0


def test_a_gain_step_ramps_across_one_block_instead_of_clicking():
    m = _source_manager()
    loud = _rms(np.frombuffer(m._next_chunk(80), dtype=np.int16))
    m.set_source_gains('src', 0.0)
    ramp = _rms(np.frombuffer(m._next_chunk(80), dtype=np.int16))
    after = _rms(np.frombuffer(m._next_chunk(80), dtype=np.int16))
    assert 0.1 * loud < ramp < 0.9 * loud, 'the transition block carries the ramp'
    assert after == 0.0, 'the block after the ramp sits at the target'


def test_per_channel_gains_reach_their_channels():
    m = manager(channels=2)
    m.load_stim(name='SineSong', source_id='src', loop=True, gains=[1.0, 0.0],
                duration=0.01, freq=1000.0, volume=1.0)
    m.start_stim()
    m._next_chunk(80)                                       # ramp-in block
    chunk = np.frombuffer(m._next_chunk(80), dtype=np.int16)
    left, right = chunk[0::2], chunk[1::2]
    assert np.abs(left).max() > 0 and np.abs(right).max() == 0


def test_stop_stim_removes_the_source():
    m = _source_manager()
    m._next_chunk(80)
    m.stop_stim()
    assert not m.has_source('src')
    chunk = np.frombuffer(m._next_chunk(80), dtype=np.int16)
    assert np.abs(chunk).max() == 0


def test_a_non_looping_source_ends_on_its_own():
    m = manager()
    m.load_stim(name='SineSong', source_id='src', loop=False, duration=0.01)
    m.start_stim()
    m._next_chunk(80)                                       # exactly the sound's length
    chunk = np.frombuffer(m._next_chunk(80), dtype=np.int16)
    assert np.abs(chunk).max() == 0


def test_retargeting_an_unknown_source_is_reported_not_dropped():
    m = manager()
    seen = reports(m)
    with pytest.warns(UserWarning, match="no source named 'nope'"):
        m.handle_request_list([{'name': 'set_source_gains', 'args': [],
                                'kwargs': {'source_id': 'nope', 'gains': 1.0}}])
    assert any('nope' in text for _, text in seen)


def test_a_source_mixes_over_the_trial_sound():
    m = _source_manager()
    m.load_stim(name='SineSong', duration=0.01, freq=500.0, volume=0.25, hold=True)
    m.start_stim()
    solo = _rms(np.frombuffer(m._next_chunk(80), dtype=np.int16))
    m.set_source_gains('src', 0.0)
    m._next_chunk(80)                                       # ramp out
    m._cursor = 0                                           # replay the trial sound alone
    duo = _rms(np.frombuffer(m._next_chunk(80), dtype=np.int16))
    assert solo > duo > 0


# # # constant-power pan # # #

def test_constant_power_pan_holds_loudness_across_the_sweep():
    from stimpack.audio.util import constant_power_gains
    for bearing in (-90, -45, 0, 30, 90):
        left, right = constant_power_gains(bearing, channels=2)
        assert left ** 2 + right ** 2 == pytest.approx(1.0)


def test_pan_extremes_and_centre():
    from stimpack.audio.util import constant_power_gains
    assert constant_power_gains(-90, 2) == pytest.approx([1.0, 0.0], abs=1e-9)
    assert constant_power_gains(90, 2)[0] == pytest.approx(0.0, abs=1e-9)
    centre = constant_power_gains(0, 2)
    assert centre[0] == pytest.approx(centre[1])


def test_pan_behind_collapses_to_the_nearest_side():
    from stimpack.audio.util import constant_power_gains
    assert constant_power_gains(135, 2) == pytest.approx(constant_power_gains(90, 2))


def test_pan_on_a_mono_device_is_just_the_gain():
    from stimpack.audio.util import constant_power_gains
    assert constant_power_gains(42.0, channels=1, gain=0.5) == [0.5]
