"""The client ships labpack sound modules to the audio module -- the wiring audio.rst promises.

``module_paths.audio_stim`` existed in the docs before it existed in the client (ledger #49):
``AudioManager.import_sound_module`` was reachable by hand but nothing read the config key, so a
labpack following the docs defined sounds that never loaded. These tests pin the wiring, and the
skip rule that keeps one config usable on audio and silent rigs alike.

Unit-tier on purpose: ``BaseClient._import_user_stim_modules`` reads only ``self.cfg`` and
``self.manager``, so a duck-typed stand-in exercises it without a GUI, a server, or a socket.
"""
import warnings

import pytest

pytest.importorskip("numpy")
pytest.importorskip("platformdirs")

from stimpack.experiment.client import BaseClient  # noqa: E402

pytestmark = pytest.mark.unit


class _RecordingProxy:
    def __init__(self, log, target_name):
        self._log, self._target_name = log, target_name

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self._log.append((self._target_name, name, args, kwargs))
        return call


class _FakeManager:
    def __init__(self, available_modules):
        self.available_modules = available_modules
        self.calls = []

    def target(self, name):
        return _RecordingProxy(self.calls, name)


class _Shim:
    """Just the two attributes _import_user_stim_modules reads."""
    def __init__(self, cfg, manager):
        self.cfg, self.manager = cfg, manager


def _sound_dir(tmp_path):
    d = tmp_path / 'lab_audio'
    d.mkdir()
    (d / 'sounds.py').write_text('')
    return str(d)                     # absolute: resolves without labpack machinery


def test_audio_stim_paths_reach_the_audio_module(tmp_path):
    manager = _FakeManager(available_modules=['visual', 'audio'])
    path = _sound_dir(tmp_path)
    BaseClient._import_user_stim_modules(_Shim({'module_paths': {'audio_stim': path}}, manager))
    assert ('audio', 'import_sound_module', (path,), {}) in manager.calls


def test_a_missing_audio_stim_path_warns_and_sends_nothing(tmp_path):
    manager = _FakeManager(available_modules=['visual', 'audio'])
    cfg = {'module_paths': {'audio_stim': str(tmp_path / 'nowhere')}}
    with pytest.warns(UserWarning, match='does not exist'):
        BaseClient._import_user_stim_modules(_Shim(cfg, manager))
    assert manager.calls == []


def test_a_rig_without_audio_skips_sounds_without_warning(tmp_path):
    """One labpack config serves audio and silent rigs; declaring sounds is not a promise."""
    manager = _FakeManager(available_modules=['visual'])
    cfg = {'module_paths': {'audio_stim': _sound_dir(tmp_path)}}
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        BaseClient._import_user_stim_modules(_Shim(cfg, manager))
    assert manager.calls == []


def test_an_older_server_that_never_advertises_still_gets_the_sounds(tmp_path):
    manager = _FakeManager(available_modules=None)
    path = _sound_dir(tmp_path)
    BaseClient._import_user_stim_modules(_Shim({'module_paths': {'audio_stim': path}}, manager))
    assert ('audio', 'import_sound_module', (path,), {}) in manager.calls


def test_visual_stim_wiring_survived_the_refactor(tmp_path):
    stim = tmp_path / 'lab_stim'
    stim.mkdir()
    (stim / 'stimuli.py').write_text('')
    manager = _FakeManager(available_modules=['visual'])
    BaseClient._import_user_stim_modules(_Shim({'module_paths': {'visual_stim': [str(stim)]}}, manager))
    assert ('visual', 'import_stim_module', (str(stim),), {}) in manager.calls
