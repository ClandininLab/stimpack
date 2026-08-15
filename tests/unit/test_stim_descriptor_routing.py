"""Stimulus descriptors routed to the module they name, by BaseProtocol.load_stimuli.

A descriptor may carry a ``target``; without one it goes to the screens, which is what every
descriptor meant before targets existed. That default is the whole backwards-compatibility story
for labpacks, so it is pinned here rather than left to be noticed later.
"""
import pytest

pytest.importorskip("numpy")
pytest.importorskip("yaml")
pytest.importorskip("platformdirs")

from fakes import FakeManager

from stimpack.experiment.protocol import BaseProtocol

pytestmark = pytest.mark.unit


def loaded_calls(trial_stim_parameters):
    """Run load_stimuli against a fake link and return the (target, name, kwargs) it batched.

    Only kwargs: every descriptor is sent as ``load_stim(**descriptor)``, so a descriptor's name
    arrives as a keyword. The one exception is the background, which stimpack passes positionally --
    see loaded_requests for that.
    """
    return [(r.get('target'), r['name'], r['kwargs']) for r in loaded_requests(trial_stim_parameters)]


def loaded_requests(trial_stim_parameters):
    """The raw request dicts load_stimuli batched, args included."""
    protocol = BaseProtocol(cfg={})
    protocol.run_parameters = {'num_trials': 1, 'idle_color': 0.0}
    protocol.trial_stim_parameters = trial_stim_parameters

    manager = FakeManager()
    protocol.load_stimuli(manager)

    # MyMultiCall flushes as one write_request_list(...) call, which FakeManager records untargeted.
    request_lists = [args[0] for target, name, args, kwargs in manager.calls
                     if name == 'write_request_list']
    assert len(request_lists) == 1, 'load_stimuli should send exactly one batch'
    return request_lists[0]


def test_a_descriptor_with_no_target_still_goes_to_the_screens():
    calls = loaded_calls({'name': 'MovingPatch', 'width': 10})
    assert ('visual', 'load_stim', {'name': 'MovingPatch', 'width': 10, 'hold': True}) in calls


def test_a_descriptor_naming_audio_goes_to_audio():
    calls = loaded_calls({'name': 'PulseSong', 'target': 'audio', 'freq': 225.0})
    assert ('audio', 'load_stim', {'name': 'PulseSong', 'freq': 225.0, 'hold': True}) in calls
    assert not any(target == 'visual' and kwargs.get('name') == 'PulseSong'
                   for target, name, kwargs in calls), 'the song was also sent to the screens'


def test_the_target_key_is_consumed_and_not_passed_to_the_module():
    """load_stim would reject it: 'target' is routing, not a stimulus parameter."""
    calls = loaded_calls({'name': 'PulseSong', 'target': 'audio'})
    audio = [kwargs for target, name, kwargs in calls if target == 'audio']
    assert audio and 'target' not in audio[0]


def test_a_mixed_list_reaches_both_modules_in_one_batch():
    """One multicall, so the sound and the picture are loaded together."""
    calls = loaded_calls([
        {'name': 'MovingPatch', 'width': 10},
        {'name': 'PulseSong', 'target': 'audio', 'freq': 225.0},
    ])
    targets = [target for target, name, kwargs in calls if name == 'load_stim']
    assert 'visual' in targets and 'audio' in targets


def test_the_descriptor_the_protocol_holds_is_not_mutated():
    """It is what the data file saves, and it is reused across trials when precomputed. Popping
    'target' out of the caller's dict would strip the routing after the first trial and silently
    send every later trial's sound to the screens."""
    descriptor = {'name': 'PulseSong', 'target': 'audio', 'freq': 225.0}
    loaded_calls(descriptor)
    assert descriptor == {'name': 'PulseSong', 'target': 'audio', 'freq': 225.0}


def test_the_background_is_still_loaded_on_the_visual_target():
    """An audio-only trial still blanks the screens, exactly as it did before targets existed."""
    requests = loaded_requests({'name': 'PulseSong', 'target': 'audio'})
    background = [r for r in requests
                  if r['name'] == 'load_stim' and r['args'] == ('ConstantBackground',)]
    assert len(background) == 1
    assert background[0]['target'] == 'visual'
    assert background[0]['kwargs']['hold'] is True


def test_a_none_entry_in_the_list_is_skipped():
    calls = loaded_calls([None, {'name': 'MovingPatch'}])
    assert sum(1 for target, name, kwargs in calls if name == 'load_stim') == 2   # bg + patch



# # # The built-in audio protocols # # #

def audio_protocol(name):
    """Load a built-in protocol the way the GUI does, by name."""
    import os
    from stimpack.experiment.util import config_tools
    from stimpack.util import ROOT_DIR, get_all_subclasses

    path = os.path.join(ROOT_DIR, 'experiment', 'example_protocol.py')
    config_tools.load_user_module_from_path(path, 'protocol_examples')
    matches = [c for c in get_all_subclasses(BaseProtocol) if c.__name__ == name]
    assert matches, f'no built-in protocol named {name}'
    return matches[-1]


@pytest.mark.parametrize('name', ['SineSong', 'PulseSong', 'AudiovisualPairing'])
def test_the_built_in_audio_protocols_are_discoverable_like_any_other(name):
    """What puts them in the GUI's dropdown: subclasses of BaseProtocol in example_protocol.py."""
    assert issubclass(audio_protocol(name), BaseProtocol)


@pytest.mark.parametrize('name', ['SineSong', 'PulseSong'])
def test_the_audio_only_protocols_send_their_sound_to_the_audio_module(name):
    protocol = audio_protocol(name)(cfg={})
    protocol.trial_protocol_parameters = protocol.get_protocol_parameter_defaults()
    protocol.trial_protocol_parameters['freq'] = 225.0      # collapse the sweep to one value
    protocol.trial_protocol_parameters['ncycle'] = 0.020
    protocol.get_trial_parameters()

    assert protocol.trial_stim_parameters['target'] == 'audio'
    assert protocol.trial_stim_parameters['name'] == name


def test_the_audiovisual_protocol_pairs_one_descriptor_per_module():
    """The mixed list, which is the thing Phase 4 exists for."""
    protocol = audio_protocol('AudiovisualPairing')(cfg={})
    protocol.trial_protocol_parameters = protocol.get_protocol_parameter_defaults()
    protocol.trial_protocol_parameters['freq'] = 225.0
    protocol.get_trial_parameters()

    descriptors = protocol.trial_stim_parameters
    assert len(descriptors) == 2
    assert [d.get('target', 'visual') for d in descriptors] == ['visual', 'audio']

    # And it routes as written, through the real load_stimuli.
    calls = loaded_calls(descriptors)
    load_targets = [target for target, name, kwargs in calls if name == 'load_stim']
    assert 'visual' in load_targets and 'audio' in load_targets
