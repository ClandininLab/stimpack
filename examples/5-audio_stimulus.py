#!/usr/bin/env python3
"""
Play the two Drosophila courtship songs, standalone -- no server, no screens, no labpack.

What 1-hello_world.py is for vision. The trial structure below (load, wait, start, wait, stop) is
the same one BaseProtocol.start_stimuli runs, so what you hear here is what a trial sounds like.

Real playback needs PyAudio:

    brew install portaudio        # macOS; apt install portaudio19-dev on Debian/Ubuntu
    pip install stimpack[audio]

Without it this still runs, on the software stand-in that renders and times everything and plays
nothing -- which is the point of the stand-in, and is how audio protocols get written away from a
rig. To actually hear the sounds with no PortAudio on the machine, pass --wav: it writes them to
files you can open in anything (`afplay sounds/SineSong.wav` on macOS).
"""
import argparse
import os
import wave
from importlib.util import find_spec
from time import sleep

from stimpack.audio import NullAudioManager, PyAudioManager
from stimpack.audio.sounds import make_as_sound
from stimpack.audio.util import to_int16

SAMPLE_RATE = 44100

# One descriptor per trial, in the shape a protocol would put in trial_stim_parameters.
TRIALS = [
    {'name': 'SineSong',  'duration': 1.5, 'freq': 225.0, 'volume': 0.6},
    {'name': 'PulseSong', 'duration': 1.5, 'freq': 225.0, 'volume': 0.6, 'pcycle': 0.016, 'ncycle': 0.020},
    {'name': 'PulseSong', 'duration': 1.5, 'freq': 125.0, 'volume': 0.6, 'pcycle': 0.030, 'ncycle': 0.040},
    {'name': 'WhiteNoise', 'duration': 1.0, 'volume': 0.2},
]


def build_manager():
    """A real sound card if PyAudio is importable, otherwise the stand-in."""
    if find_spec('pyaudio') is None:
        print('PyAudio not installed -- running on NullAudioManager, which plays nothing.\n'
              'Install it with: brew install portaudio && pip install stimpack[audio]\n'
              'Or re-run with --wav to write the sounds to files instead.\n')
        return NullAudioManager(sample_rate=SAMPLE_RATE)
    return PyAudioManager(sample_rate=SAMPLE_RATE)


def play(manager):
    manager.start()
    try:
        for trial in TRIALS:
            descriptor = dict(trial)
            name = descriptor.pop('name')
            print(f"{name}: {descriptor}")

            manager.load_stim(name, **descriptor)

            sleep(0.5)                          # pre time
            manager.start_stim()
            # Sleep past the sound rather than exactly its length: the trial is timed by this
            # clock, and playback starts an output buffer after the call. Stopping at exactly
            # `duration` would clip the tail on every trial. Same reasoning as a protocol's
            # stim_time being set a little longer than the stimulus it contains.
            sleep(trial['duration'] + 0.2)
            manager.stop_stim()
            sleep(0.5)                          # tail time
    finally:
        manager.close()


def write_wavs(directory):
    """Render each trial to a .wav, for listening with no PortAudio on the machine."""
    os.makedirs(directory, exist_ok=True)
    for index, trial in enumerate(TRIALS):
        sound = make_as_sound(dict(trial))
        samples = to_int16(sound.generate(SAMPLE_RATE))

        path = os.path.join(directory, f"{index}-{trial['name']}.wav")
        with wave.open(path, 'wb') as f:
            f.setnchannels(1)
            f.setsampwidth(2)                   # int16
            f.setframerate(SAMPLE_RATE)
            f.writeframes(samples.tobytes())
        print(f'{path}  ({len(samples) / SAMPLE_RATE:.3f} s)')


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--wav', nargs='?', const='sounds', default=None, metavar='DIR',
                        help='write the sounds to DIR (default: ./sounds) instead of playing them')
    args = parser.parse_args()

    if args.wav is not None:
        write_wavs(args.wav)
    else:
        play(build_manager())


if __name__ == '__main__':
    main()
