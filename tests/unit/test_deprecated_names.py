"""The pre-0.3 spelling must keep working, or renaming the API breaks every labpack at once.

One lab's labpack alone defines get_epoch_parameters in 105 protocols and refers to the old
attribute names about 1500 times. These tests stand in for that labpack: each drives stimpack
through the OLD names only and asserts the new machinery still sees the right values.
"""
import warnings

import pytest

from stimpack.experiment.protocol import BaseProtocol

pytestmark = pytest.mark.unit


class LegacyProtocol(BaseProtocol):
    """Written the way labpack protocols are written today, and not ported.

    The __init__ matters: 75 protocols in one labpack re-assign run_parameters exactly like this,
    which never passes through stimpack's own code. A legacy protocol without it would test a
    path no real protocol takes -- and did, until the template was run against this and raised
    KeyError: 'num_trials'.
    """
    def __init__(self, cfg):
        super().__init__(cfg)
        self.run_parameters = self.get_run_parameter_defaults()

    def get_run_parameter_defaults(self):
        return {'num_epochs': 3, 'idle_color': 0.5}

    def get_protocol_parameter_defaults(self):
        return {'angle': [0, 45, 90]}

    def get_epoch_parameters(self):
        super().get_epoch_parameters()          # the common shape: super(), then add stim params
        self.epoch_stim_parameters = {'name': 'FakeStim',
                                      'angle': self.epoch_protocol_parameters['angle']}


class ModernProtocol(BaseProtocol):
    def get_run_parameter_defaults(self):
        return {'num_trials': 3, 'idle_color': 0.5}

    def get_protocol_parameter_defaults(self):
        return {'angle': [0, 45, 90]}

    def get_trial_parameters(self):
        super().get_trial_parameters()
        self.trial_stim_parameters = {'name': 'FakeStim',
                                      'angle': self.trial_protocol_parameters['angle']}


@pytest.fixture
def fresh_warnings():
    """Deprecation warnings fire once per process, so a test that asserts on them has to start
    from a clean slate or it depends on which tests ran first."""
    from stimpack.experiment.deprecated_names import _warn_once
    _warn_once.seen.clear()
    yield
    _warn_once.seen.clear()


def deprecation_names(recorded):
    return sorted({str(w.message).split("'")[1] for w in recorded
                   if issubclass(w.category, DeprecationWarning)})


def test_an_unported_protocol_still_runs():
    """stimpack calls get_trial_parameters; the protocol only defines get_epoch_parameters."""
    protocol = LegacyProtocol(cfg={})

    with warnings.catch_warnings(record=True):
        warnings.simplefilter('always')
        protocol.get_trial_parameters()

    # what the old code set through the old names is what the new code reads through the new ones
    assert protocol.trial_stim_parameters['name'] == 'FakeStim'
    assert protocol.trial_stim_parameters['angle'] in (0, 45, 90)
    assert protocol.trial_protocol_parameters['angle'] == protocol.trial_stim_parameters['angle']


def test_a_legacy_run_parameter_still_says_how_many_trials():
    """num_epochs is a dict key, not an attribute, so an alias on the class cannot cover it -- and
    30 saved presets carry it."""
    protocol = LegacyProtocol(cfg={})
    assert protocol.run_parameters['num_trials'] == 3
    # `in` answers True for the old key by design -- it resolves to the new one. What must not
    # happen is the value being *stored* twice, where the two copies could drift.
    assert sorted(protocol.run_parameters) == ['idle_color', 'num_trials']


def test_the_old_names_say_what_to_use_instead(fresh_warnings):
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter('always')
        protocol = LegacyProtocol(cfg={})
        protocol.get_trial_parameters()

    assert deprecation_names(recorded) == ['epoch_protocol_parameters', 'epoch_stim_parameters',
                                           'get_epoch_parameters', 'num_epochs']
    assert all('0.4.0' in str(w.message) for w in recorded
               if issubclass(w.category, DeprecationWarning)), 'no removal version given'


def test_a_ported_protocol_is_not_warned_at(fresh_warnings):
    """The dispatch must tell a subclass that overrides the old name from the base class supplying
    it as an alias -- otherwise every protocol, ported or not, gets a deprecation warning."""
    protocol = ModernProtocol(cfg={})

    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter('always')
        protocol.get_trial_parameters()

    assert deprecation_names(recorded) == []
    assert protocol.trial_stim_parameters['name'] == 'FakeStim'


def test_super_from_a_legacy_override_does_not_recurse():
    """A legacy override calling super().get_epoch_parameters() reaches the alias, which forwards
    to get_trial_parameters, which would find the override again."""
    protocol = LegacyProtocol(cfg={})

    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        protocol.get_trial_parameters()          # must return rather than hit the recursion limit

    assert protocol.trial_protocol_parameters != {}


def test_old_attribute_names_write_through_not_just_read():
    """A labpack protocol assigns self.epoch_stim_parameters; the value has to land where stimpack
    now looks for it."""
    protocol = ModernProtocol(cfg={})

    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        protocol.epoch_stim_parameters = {'name': 'AssignedThroughTheOldName'}

    assert protocol.trial_stim_parameters == {'name': 'AssignedThroughTheOldName'}


def test_the_data_and_client_classes_keep_their_old_method_names():
    from stimpack.experiment.client import BaseClient
    from stimpack.experiment.data import BaseData

    for cls, names in [(BaseData, ['create_epoch', 'end_epoch', 'create_epoch_run', 'end_epoch_run']),
                       (BaseClient, ['start_epoch', 'stop_epoch'])]:
        for name in names:
            assert callable(getattr(cls, name, None)), f'{cls.__name__}.{name} is gone'


def test_a_pre_0_3_server_can_still_end_a_trial_over_the_wire():
    """The server stamps its request with epoch_index; that is a wire signature, not just a method
    name, so a method alias would not cover it."""
    from stimpack.experiment.client import BaseClient

    client = BaseClient.__new__(BaseClient)
    client.current_trial_index = 4
    client.trial_end_reason = None

    class Protocol:
        stopped = False
        def stop_trial(self):
            Protocol.stopped = True

    client.protocol_object = Protocol()

    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        client.stop_trial(epoch_index=4, reason='reached_goal')

    assert Protocol.stopped is True
    assert client.trial_end_reason == 'reached_goal'


def test_a_late_request_under_the_old_wire_name_is_still_ignored():
    """The guard against a request arriving for a trial that already ended must apply to the old
    spelling too, or the compatibility path reintroduces the bug it was written for."""
    from stimpack.experiment.client import BaseClient

    client = BaseClient.__new__(BaseClient)
    client.current_trial_index = 5          # trial 4 has ended
    client.trial_end_reason = None

    class Protocol:
        stopped = False
        def stop_trial(self):
            Protocol.stopped = True

    client.protocol_object = Protocol()

    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        client.stop_trial(epoch_index=4, reason='too late')

    assert Protocol.stopped is False
    assert client.trial_end_reason is None


def test_each_old_name_is_reported_once_not_once_per_trial(fresh_warnings):
    """These sit on per-trial code paths: a protocol reading trial parameters every trial would
    otherwise bury everything else in the same warning."""
    protocol = LegacyProtocol(cfg={})

    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter('always')
        for _ in range(20):
            protocol.get_trial_parameters()

    counts = {}
    for name in [str(w.message).split("'")[1] for w in recorded
                 if issubclass(w.category, DeprecationWarning)]:
        counts[name] = counts.get(name, 0) + 1
    assert counts and set(counts.values()) == {1}, counts


def test_run_parameters_are_renamed_however_they_are_assigned():
    """The usual labpack protocol sets run_parameters itself, after stimpack has already built
    them, so normalising where stimpack assigns them misses every one of those protocols."""
    protocol = LegacyProtocol(cfg={})
    assert protocol.run_parameters['num_trials'] == 3

    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        protocol.run_parameters = {'num_epochs': 11, 'idle_color': 0.5}   # assigned again, later

    assert protocol.run_parameters['num_trials'] == 11
    assert 'num_epochs' not in list(protocol.run_parameters)


def test_reading_a_run_parameter_by_its_old_key_still_works():
    """Renaming the key on the way in is not enough. A protocol that reads
    run_parameters['num_epochs'] then finds nothing -- which is how two labpack protocols raised
    KeyError under a compatibility layer whose whole job was to keep them running."""
    protocol = ModernProtocol(cfg={})

    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        assert protocol.run_parameters['num_epochs'] == 3
        assert protocol.run_parameters.get('num_epochs') == 3
        assert 'num_epochs' in protocol.run_parameters


def test_a_run_parameter_is_stored_once_not_under_both_names():
    """Storing both spellings would let them drift the moment anything wrote one of them."""
    protocol = ModernProtocol(cfg={})
    assert list(protocol.run_parameters).count('num_trials') == 1
    assert 'num_epochs' not in list(protocol.run_parameters), 'stored twice'

    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        protocol.run_parameters['num_trials'] = 9
        assert protocol.run_parameters['num_epochs'] == 9, 'the old key read a stale copy'


def test_run_parameters_serialize_as_a_plain_mapping():
    """PyYAML tagged them by type, so saving a parameter preset wrote

        run_parameters: !!python/object/new:...RunParameters

    which yaml.safe_load refuses to construct -- a file stimpack had just written and could not
    read back. Both dumpers, since either could be reached from a labpack.
    """
    import yaml

    from stimpack.experiment.deprecated_names import RunParameters

    parameters = RunParameters({'num_trials': 5, 'idle_color': 0.5})

    for dump in (yaml.dump, yaml.safe_dump):
        text = dump({'run_parameters': parameters}, default_flow_style=False, sort_keys=False)
        assert 'python/object' not in text
        assert yaml.safe_load(text) == {'run_parameters': {'num_trials': 5, 'idle_color': 0.5}}

    assert parameters['num_epochs'] == 5, 'the old key must still resolve'
