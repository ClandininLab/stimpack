"""probe_default_output must say WHY there is no audio, not just that there is none.

The failure this prevents: pyaudio missing -> probe returns None -> the local server builds no
audio module -> the first symptom is a "no audio module on this rig" warning at stimulus-load
time, minutes later, pointing at the rig instead of at pip. Three causes, three reasons, each
naming its own fix.
"""
import sys
import types

import pytest

from stimpack.audio import util

pytestmark = pytest.mark.unit


def _fake_pyaudio(monkeypatch, pa_class):
    fake = types.ModuleType('pyaudio')
    fake.PyAudio = pa_class
    monkeypatch.setitem(sys.modules, 'pyaudio', fake)


def test_missing_pyaudio_names_the_extra(monkeypatch):
    monkeypatch.setitem(sys.modules, 'pyaudio', None)   # makes `import pyaudio` raise ImportError
    rate, channels, reason = util.probe_default_output()
    assert rate is None and channels is None
    assert 'stimpack[audio]' in reason                  # the fix, not just the fact


def test_portaudio_failure_is_a_different_reason(monkeypatch):
    class Boom:
        def __init__(self):
            raise RuntimeError('no host API')

    _fake_pyaudio(monkeypatch, Boom)
    rate, channels, reason = util.probe_default_output()
    assert rate is None and channels is None
    assert 'PortAudio could not start' in reason
    assert 'stimpack[audio]' not in reason              # installing again would not fix this


def test_no_output_device_is_a_different_reason(monkeypatch):
    class NoDevice:
        def get_default_output_device_info(self):
            raise OSError('no default output device')

        def terminate(self):
            pass

    _fake_pyaudio(monkeypatch, NoDevice)
    rate, channels, reason = util.probe_default_output()
    assert rate is None and channels is None
    assert 'no default output device' in reason


def test_a_working_device_reports_rate_channels_and_no_reason(monkeypatch):
    class Fine:
        def get_default_output_device_info(self):
            return {'defaultSampleRate': 48000.0, 'maxOutputChannels': 2}

        def terminate(self):
            pass

    _fake_pyaudio(monkeypatch, Fine)
    assert util.probe_default_output() == (48000, 2, None)
    assert util.default_output_sample_rate() == 48000   # the thin wrapper agrees


def test_channels_cap_at_stereo_and_floor_at_mono(monkeypatch):
    """A '7.1' chipset must not cost six interleaved lanes of silence, and a device that
    reports nothing about channels still plays mono. Without the cap-and-pass-through, every
    auto-built server ran mono and stereo panning could never engage."""
    def device(report):
        class Dev:
            def get_default_output_device_info(self):
                return {'defaultSampleRate': 44100.0, **report}

            def terminate(self):
                pass
        return Dev

    _fake_pyaudio(monkeypatch, device({'maxOutputChannels': 8}))
    assert util.probe_default_output()[1] == 2
    _fake_pyaudio(monkeypatch, device({'maxOutputChannels': 1}))
    assert util.probe_default_output()[1] == 1
    _fake_pyaudio(monkeypatch, device({}))
    assert util.probe_default_output()[1] == 1
