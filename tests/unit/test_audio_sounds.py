"""Sound waveforms, and the two defects inherited from multistim that are pinned rather than fixed.

The songs were ported from ``flystim/audio.py`` so that recordings made before and after the port
compare. That means reproducing arithmetic that is questionable in two places, and the tests below
are what stop somebody "tidying" either one without knowing what it costs. The one behaviour that
did change -- the overflowing int16 cast -- is pinned too, in both directions.
"""
import numpy as np
import pytest

from stimpack.audio.sounds import BaseSound, PulseSong, Silence, SineSong, WhiteNoise, make_as_sound
from stimpack.audio.util import to_int16

pytestmark = pytest.mark.unit

SR = 44100


def multistim_pulse_song(sr, volume=1.0, duration=1.0, freq=125.0, pcycle=0.016, ncycle=0.020):
    """`flystim/audio.py:pulse_song`, verbatim, as the reference to match."""
    cycles = round(duration / (pcycle + ncycle))
    sigm = pcycle / 4
    K = 0.5 * sigm ** 2
    seg = int((pcycle + ncycle) * sr)
    t = np.linspace(0, (seg - 1) / sr, seg)
    t = t - np.mean(t)
    y = np.exp(-t ** 2 / K) * np.cos(2 * np.pi * freq * t)
    samples = np.zeros(seg * cycles)
    for i in range(cycles):
        samples[seg * i:seg * (i + 1)] = y
    samples = np.delete(samples, slice(0, int(seg / 4)))
    return volume * samples


def multistim_sine_song(sr, volume=1.0, duration=1.0, freq=225.0):
    """`flystim/audio.py:sine_song`, verbatim."""
    t = np.linspace(0, duration, round(duration * sr))
    return volume * np.sin(2 * np.pi * freq * t)


# # # Bit-exactness with the implementation these were ported from # # #

def test_pulse_song_matches_multistim_sample_for_sample():
    np.testing.assert_array_equal(PulseSong().generate(SR), multistim_pulse_song(SR))


def test_sine_song_matches_multistim_sample_for_sample():
    np.testing.assert_array_equal(SineSong().generate(SR), multistim_sine_song(SR))


def test_pulse_song_matches_multistim_at_non_default_parameters_too():
    kwargs = dict(volume=0.4, duration=2.5, freq=200.0, pcycle=0.02, ncycle=0.03)
    np.testing.assert_array_equal(PulseSong(**kwargs).generate(SR), multistim_pulse_song(SR, **kwargs))


# # # The inherited defects, pinned so nobody removes them by accident # # #

def test_pulse_song_duration_is_not_the_requested_duration():
    """Quantised to whole cycles, then a quarter-segment trimmed off the front. 1.0 s -> 0.9986 s.

    A protocol that needs the sound and the visual stimulus to end together has to ask
    duration_at() rather than trust the parameter it passed in.
    """
    song = PulseSong(duration=1.0)
    realised = song.duration_at(SR)
    assert realised != pytest.approx(1.0)
    assert realised == pytest.approx(0.998639, abs=1e-6)


def test_pulse_song_puts_exactly_one_point_zero_at_the_centre_of_every_pulse():
    """The sample that used to overflow int16. Odd segment length + a mean-centred grid == exact 1.0.

    Pinned because it is the precondition for the clipping test below being worth anything: if the
    waveform ever stops touching 1.0, that test silently stops testing.
    """
    song = PulseSong(volume=1.0, duration=1.0)
    samples = song.generate(SR)
    assert samples.max() == 1.0
    assert np.count_nonzero(samples == 1.0) == 28      # one per pulse, 28 pulses in ~1 s


# # # The behaviour that did change # # #

def test_full_scale_samples_clip_instead_of_wrapping():
    converted = to_int16(PulseSong(volume=1.0).generate(SR))
    assert converted.max() == 32767
    assert not (converted == -32768).any(), 'a full-scale sample wrapped to the negative rail'


def test_legacy_flag_reproduces_the_multistim_overflow_exactly():
    """`np.floor(x * 2**15).astype(np.int16)` wrapped 1.0 to -32768: a click on every pulse.

    Kept behind a flag so a stimulus can be regenerated as an older recording actually heard it.
    """
    samples = PulseSong(volume=1.0).generate(SR)
    legacy = to_int16(samples, legacy_overflow=True)
    reference = np.floor(multistim_pulse_song(SR) * 2 ** 15).astype(np.int16)

    np.testing.assert_array_equal(legacy, reference)
    assert np.count_nonzero(legacy == -32768) == 28
    assert legacy.max() == 32760        # the wrapped samples were the only full-scale ones


def test_quiet_sounds_are_unaffected_by_the_clipping_change():
    """Clipping must only touch samples that were out of range; everything else round-trips."""
    samples = SineSong(volume=0.5).generate(SR)
    converted = to_int16(samples)
    np.testing.assert_allclose(converted / 32767.0, samples, atol=1e-4)


# # # The rest of the catalogue # # #

def test_silence_is_silent_and_the_right_length():
    samples = Silence(duration=0.25).generate(SR)
    assert len(samples) == round(0.25 * SR)
    assert not samples.any()


def test_white_noise_is_reproducible_by_default_and_stays_in_range():
    a = WhiteNoise(duration=0.1).generate(SR)
    b = WhiteNoise(duration=0.1).generate(SR)
    np.testing.assert_array_equal(a, b)             # a fixed seed, so a trial can be reconstructed
    assert a.min() >= -1.0 and a.max() <= 1.0

    c = WhiteNoise(duration=0.1, seed=1).generate(SR)
    assert not np.array_equal(a, c)


def test_a_duration_shorter_than_one_pulse_cycle_gives_silence_not_a_crash():
    assert PulseSong(duration=0.001).generate(SR).size == 0


# # # Name resolution # # #

def test_sounds_resolve_by_name_from_a_descriptor_dict():
    sound = make_as_sound({'name': 'SineSong', 'freq': 300.0, 'duration': 0.1})
    assert isinstance(sound, SineSong) and sound.freq == 300.0


def test_an_unknown_sound_name_raises_rather_than_resolving_to_something():
    with pytest.raises(AssertionError):
        make_as_sound({'name': 'NoSuchSong', 'duration': 0.1})


def test_a_labpack_subclass_becomes_resolvable_with_no_registration_step():
    """The same mechanism custom stimuli use: subclass, and the name works."""
    class CourtshipSong(BaseSound):
        def __init__(self, duration=1.0):
            self.duration = duration

        def generate(self, sample_rate):
            return np.zeros(round(self.duration * sample_rate))

    assert isinstance(make_as_sound({'name': 'CourtshipSong', 'duration': 0.1}), CourtshipSong)
