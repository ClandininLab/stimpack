"""Sample conversion and labpack sound-module loading."""
import os
import sys
import warnings
from importlib.util import spec_from_file_location, module_from_spec

import numpy as np

from stimpack.experiment.util.config_tools import convert_labpack_relative_path_to_full_path

# The submodules an audio module directory is expected to provide. Named here so the labpack checker
# can look for the same files this loader will look for -- the same arrangement as
# visual_stim.util.STIM_SUBMODULES.
SOUND_SUBMODULES = ('sounds',)

#: Full scale for signed 16-bit samples. 32767, not 32768: the positive range is one short of the
#: negative one, and using 2**15 here is what made multistim's pulse song click. See to_int16.
INT16_PEAK = 2 ** 15 - 1


def to_int16(samples, legacy_overflow=False):
    """
    Convert float samples in [-1, 1] to the int16 a sound card wants.

    Clips first. multistim computed ``np.floor(samples * 2**15)`` and cast, which overflows for any
    sample at exactly 1.0: 32768 is one past the int16 maximum and wraps to -32768, a full-scale
    negative spike. That is not hypothetical -- ``PulseSong`` at the default parameters puts exactly
    1.0 at the centre of every pulse, so at ``volume=1.0`` (the value every multistim protocol and
    preset used) the click fired 28 times a second.

    :param legacy_overflow: reproduce that wrap, for regenerating a stimulus bit-exactly as an
        older recording heard it. Off by default: new data should not inherit the bug.
    """
    samples = np.asarray(samples, dtype=np.float64)

    if legacy_overflow:
        # Deliberately unclipped, and scaled by 2**15, so the cast wraps exactly as it used to.
        return np.floor(samples * 2 ** 15).astype(np.int16)

    return np.clip(np.round(samples * INT16_PEAK), -INT16_PEAK - 1, INT16_PEAK).astype(np.int16)


def constant_power_gains(bearing_deg, channels, gain=1.0):
    """
    Per-channel gains placing a mono source at a bearing, by constant-power stereo pan.

    Loudness tracks power, not amplitude, so a linear crossfade audibly dips mid-pan; with
    L = cos(theta), R = sin(theta) the power L^2 + R^2 is 1 everywhere and the phantom source
    sweeps at constant loudness. Bearing is in the rig's convention -- degrees from straight
    ahead, positive to the subject's right -- and is clipped to [-90, +90]: two speakers span
    one axis, so a source behind the subject renders at the nearest side, which is the honest
    front/back collapse of level-only panning rather than a pretend answer.

    One channel gets ``[gain]`` (no axis to pan along); more than two put the pair on the first
    two channels and silence on the rest -- a speaker ring wants its own bearing-to-pair law,
    which is a rig-geometry question, not a formula this helper can guess.

    :param bearing_deg: source bearing relative to the subject's heading, degrees
    :param channels: output channel count of the device
    :param gain: overall level, applied on top of the pan (e.g. a distance rolloff)
    """
    if channels < 2:
        return [float(gain)]
    import math
    theta = (min(max(float(bearing_deg), -90.0), 90.0) + 90.0) / 180.0 * (math.pi / 2)
    gains = [float(gain) * math.cos(theta), float(gain) * math.sin(theta)]
    return gains + [0.0] * (channels - 2)


def probe_default_output():
    """
    ``(rate, channels, None)`` when this machine can play audio; ``(None, None, why_not)`` when
    it cannot.

    ``channels`` is the device's own output count **capped at two**: stereo is what panning
    wants and what headphones and laptop speakers are, while a "7.1" chipset reporting eight
    would cost six interleaved lanes of silence every block. A rig with a real speaker array
    sets its channel count explicitly when constructing the server; this probe serves the
    machine whose audio is whatever the OS calls default.

    This is the "can this machine do audio at all" probe, and every failure returns rather than
    raises: PyAudio missing, PortAudio failing to initialize, or no default output device. A
    headless rig or a CI runner hits the last two with PyAudio installed, and the default local
    server is constructed while the GUI starts up -- so raising here would stop stimpack opening
    at all, on a machine that simply has no speaker.

    The three failures get three different reasons, because they have three different fixes and
    the caller is expected to *print the reason*. Collapsing them into one None is how the first
    symptom becomes a "no audio module on this rig" warning minutes later, at stimulus load,
    pointing at the rig instead of at pip.

    The rate matters because sounds are generated against it: opening at the device's own rate is
    what keeps the ordinary laptop case from being resampled by the OS, and from warning about it
    every run (see :meth:`~stimpack.audio.managers.PyAudioManager._warn_if_resampling`). A rig
    should set its rate explicitly rather than rely on this -- which device is "default" changes
    when somebody plugs in a monitor.
    """
    try:
        import pyaudio
    except ImportError:
        return None, None, ("pyaudio is not installed; pip install stimpack[audio] -- PortAudio "
                            "needed system-side to build it (apt install portaudio19-dev / "
                            "zypper install portaudio-devel / brew install portaudio)")

    try:
        pa = pyaudio.PyAudio()
    except Exception as e:
        # PortAudio present but unable to start: no host API, no sound server.
        return None, None, f'pyaudio is installed but PortAudio could not start ({e})'

    try:
        info = pa.get_default_output_device_info()
        channels = max(1, min(int(info.get('maxOutputChannels', 1)), 2))
        return int(info['defaultSampleRate']), channels, None
    except Exception:
        # No output device at all, or one that will not describe itself.
        return None, None, 'pyaudio is installed but PortAudio found no default output device'
    finally:
        pa.terminate()


def default_output_sample_rate():
    """The default output device's own sample rate, or None if there is nothing to play on.

    The rate half of :func:`probe_default_output`; callers who can print should use the probe
    itself and say *why* when the answer is None."""
    return probe_default_output()[0]


def load_sound_module_from_path(path, module_name='loaded_sound_module', submodules=SOUND_SUBMODULES):
    """
    Load a labpack's sound module from a path. The directory must contain ``sounds.py``.

    Exec'd under a caller-supplied namespace rather than imported by package name, so a labpack need
    not be installed. Its classes subclass the same :class:`~stimpack.audio.sounds.BaseSound` and so
    become resolvable by name through ``get_all_subclasses`` -- no registration step, the same way
    custom stimuli work.
    """
    full_module_path = convert_labpack_relative_path_to_full_path(path)
    for submodule_name in submodules:
        submodule_name_full = module_name + '.' + submodule_name
        submodule_path = os.path.join(full_module_path, submodule_name + '.py')
        if not os.path.exists(submodule_path):
            warnings.warn(f'Could not find {submodule_name} at {submodule_path}')
            continue
        spec = spec_from_file_location(submodule_name_full, submodule_path)
        loaded_mod = module_from_spec(spec)
        sys.modules[submodule_name_full] = loaded_mod
        spec.loader.exec_module(loaded_mod)
    return
