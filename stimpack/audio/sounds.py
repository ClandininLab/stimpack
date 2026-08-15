"""
Sound classes: what an auditory stimulus is, as a waveform.

A sound is a class, resolved by name through :func:`~stimpack.util.get_all_subclasses` -- the same
mechanism :mod:`stimpack.visual_stim.stimuli` uses -- so a labpack adds its own by subclassing
:class:`BaseSound` and needs no registration step. ``make_as_sound`` hydrates the descriptor dict a
protocol puts on the wire into the object that generates samples, exactly as ``make_as_trajectory``
does for a moving parameter.

Sounds generate **float** samples in [-1, 1] and know nothing about the output device. Conversion to
whatever the sound card wants happens in :mod:`stimpack.audio.util`, which is also where the int16
clipping lives -- see the note on ``volume=1.0`` there.

The two songs ported from the ``multistim`` project (``flystim/audio.py``) reproduce its arithmetic
sample for sample in float, so a recording made before the port and one made after are comparable.
Where that arithmetic is questionable the comment says so rather than the code silently improving
it; the one place the behaviour does change is the int16 cast, which used to overflow.
"""
import numpy as np

from stimpack.util import make_as


def make_as_sound(parameter):
    """Return parameter as a BaseSound object if it is a dictionary."""
    return make_as(parameter, parent_class=BaseSound)


class BaseSound:
    """
    Base class for auditory stimuli.

    A subclass takes its parameters in ``__init__`` and implements :meth:`generate`. Parameters are
    plain numbers, not trajectories: a waveform is generated once, whole, at load time, because the
    audio callback runs on a real-time thread and must not compute anything (see
    :class:`~stimpack.audio.managers.AudioManager`).
    """

    def generate(self, sample_rate):
        """
        Return the waveform as float samples in [-1, 1].

        :param sample_rate: samples per second the manager will play at. Passed in rather than
            stored on the sound, so the same descriptor plays correctly on rigs whose sound cards
            differ.
        :returns: a 1-D array for mono, or ``(n_samples, n_channels)`` for multichannel. The manager
            accepts either and spreads mono across the channels it opened.
        """
        raise NotImplementedError

    def duration_at(self, sample_rate):
        """
        The realised duration in seconds, which is not always the requested one.

        Worth asking rather than assuming: :class:`PulseSong` quantises to a whole number of pulse
        cycles, so a 1.0 s request yields 0.9986 s. A protocol that needs the sound and the visual
        stimulus to end together should read this rather than trust ``duration``.
        """
        return len(self.generate(sample_rate)) / sample_rate


class Silence(BaseSound):
    """
    Nothing, for the requested duration.

    Not a no-op: a trial whose condition is "no sound" should still say so in its descriptor, so the
    saved parameters distinguish it from a trial where the audio module was absent.
    """

    def __init__(self, duration=1.0):
        self.duration = duration

    def generate(self, sample_rate):
        return np.zeros(round(self.duration * sample_rate))


class SineSong(BaseSound):
    """
    A constant-frequency sine tone. *Drosophila* sine song, and a general-purpose pure tone.

    :param volume: peak amplitude, 0 to 1
    :param duration: seconds
    :param freq: Hz
    """

    def __init__(self, volume=1.0, duration=1.0, freq=225.0):
        self.volume = volume
        self.duration = duration
        self.freq = freq

    def generate(self, sample_rate):
        # linspace over a closed interval, so the step is duration/(n-1) rather than 1/sample_rate
        # and the tone is high by a factor n/(n-1) -- 0.005 Hz at 225 Hz over a second. Kept because
        # multistim generated it this way and matching it exactly costs nothing audible; a sound
        # that needed the exact frequency would pass endpoint=False, and none of these do.
        t = np.linspace(0, self.duration, round(self.duration * sample_rate))
        return self.volume * np.sin(2 * np.pi * self.freq * t)


class PulseSong(BaseSound):
    """
    A train of Gaussian-windowed cosine pulses. *Drosophila* pulse song.

    Each pulse is ``exp(-t^2/K) * cos(2*pi*freq*t)`` over one ``pcycle + ncycle`` segment, with the
    window width set to ``pcycle/4``; ``pcycle`` is the pulse and ``ncycle`` the gap after it.

    :param volume: peak amplitude, 0 to 1
    :param duration: seconds, **approximate** -- see below
    :param freq: carrier frequency, Hz
    :param pcycle: pulse duration, seconds
    :param ncycle: inter-pulse interval, seconds

    Two inherited quirks, preserved so that data recorded before and after the port compares:

    - The duration is quantised to a whole number of segments and then a quarter-segment is trimmed
      off the front, so the realised length is not ``duration``. Ask :meth:`duration_at`.
    - At ``volume=1.0`` the centre sample of every pulse is exactly 1.0, because the segment length
      is usually odd and the time grid is mean-centred onto a point containing zero, where
      ``exp(0)*cos(0) == 1``. That is the sample that used to overflow the int16 cast into a
      full-scale negative spike -- an audible click on every pulse. The waveform here is unchanged;
      :func:`stimpack.audio.util.to_int16` is where it stopped wrapping.
    """

    def __init__(self, volume=1.0, duration=1.0, freq=125.0, pcycle=0.016, ncycle=0.020):
        self.volume = volume
        self.duration = duration
        self.freq = freq
        self.pcycle = pcycle
        self.ncycle = ncycle

    def generate(self, sample_rate):
        period = self.pcycle + self.ncycle
        cycles = round(self.duration / period)
        seg = int(period * sample_rate)
        if cycles < 1 or seg < 1:
            # A duration under half a segment rounds to zero pulses. Silence is the honest answer;
            # the alternative was an empty buffer that the manager would play as a missing trial.
            return np.zeros(0)

        sigm = self.pcycle / 4
        K = 0.5 * sigm ** 2

        t = np.linspace(0, (seg - 1) / sample_rate, seg)
        t = t - np.mean(t)
        pulse = np.exp(-t ** 2 / K) * np.cos(2 * np.pi * self.freq * t)

        samples = np.tile(pulse, cycles)
        # Trim the leading quarter-segment, so the train opens on the rising edge of a pulse rather
        # than on a quarter-segment of near-silence. multistim spelled this np.delete(slice(...)).
        return self.volume * samples[int(seg / 4):]


class WhiteNoise(BaseSound):
    """
    Gaussian white noise, clipped to [-1, 1].

    :param volume: standard deviation of the noise, before clipping
    :param duration: seconds
    :param seed: fixed by default, so a trial is reproducible and a test can pin the waveform. Pass
        None for a fresh draw each time -- and record what you did, because nothing else can
        reconstruct it afterwards.
    """

    def __init__(self, volume=1.0, duration=1.0, seed=0):
        self.volume = volume
        self.duration = duration
        self.seed = seed

    def generate(self, sample_rate):
        rng = np.random.RandomState(self.seed)
        samples = self.volume * rng.standard_normal(round(self.duration * sample_rate))
        return np.clip(samples, -1.0, 1.0)
