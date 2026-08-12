"""
The audio module: a sound card driven from a protocol, as ``target('audio')``.

Managers live in :mod:`stimpack.audio.managers` -- :class:`~stimpack.audio.managers.PyAudioManager`
for a real card, :class:`~stimpack.audio.managers.NullAudioManager` for the software stand-in.
Sounds live in :mod:`stimpack.audio.sounds`; a labpack adds its own by subclassing
:class:`~stimpack.audio.sounds.BaseSound`.

Importing this package pulls in no audio library: PyAudio is imported when a manager actually opens
a device, so ``pip install stimpack`` without the ``[audio]`` extra still imports cleanly.
"""
from stimpack.audio.managers import AudioManager, NullAudioManager, PyAudioManager
from stimpack.audio.sounds import BaseSound, PulseSong, SineSong, Silence, WhiteNoise, make_as_sound

__all__ = ['AudioManager', 'PyAudioManager', 'NullAudioManager',
           'BaseSound', 'SineSong', 'PulseSong', 'WhiteNoise', 'Silence', 'make_as_sound']
