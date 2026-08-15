"""The legacy HDF5 backend must write what stimpack wrote before the epoch -> trial rename.

A lab's analysis walks epoch_runs/series_001/epochs/epoch_001. If the legacy backend drifts from
that by even an attribute name, choosing it has not protected anything -- so these assert the
layout literally, not just that a file appears.
"""
import h5py
import pytest

from stimpack.experiment.data import BaseData
from stimpack.experiment.data_legacy import LegacyHdf5Data
from stimpack.experiment.protocol import BaseProtocol

pytestmark = pytest.mark.integration


class TinyProtocol(BaseProtocol):
    def get_run_parameter_defaults(self):
        return {'num_trials': 2, 'idle_color': 0.5, 'do_loco': False}

    def get_protocol_parameter_defaults(self):
        return {'pre_time': 0.0, 'stim_time': 0.0, 'tail_time': 0.0}

    def get_trial_parameters(self):
        super().get_trial_parameters()
        self.trial_stim_parameters = {'name': 'FakeStim'}


def run_into(data_class, tmp_path, client):
    tmp_path.mkdir(parents=True, exist_ok=True)
    data = data_class(cfg={})
    data.data_directory = str(tmp_path)
    data.experiment_file_name = 'layout'
    data.initialize_experiment_file()
    data.create_subject({'subject_id': 's1'})
    client.start_run(TinyProtocol(cfg={}), data, save_metadata_flag=True)
    return data


def groups_in(data):
    with h5py.File(f'{data.data_directory}/{data.experiment_file_name}.hdf5', 'r') as f:
        found = []
        f.visit(found.append)
    return found


def test_the_legacy_backend_writes_the_pre_rename_group_names(tmp_path, client):
    data = run_into(LegacyHdf5Data, tmp_path, client)
    groups = groups_in(data)

    assert 'Subjects/s1/epoch_runs' in groups
    assert 'Subjects/s1/epoch_runs/series_001' in groups
    assert 'Subjects/s1/epoch_runs/series_001/epochs' in groups
    assert 'Subjects/s1/epoch_runs/series_001/epochs/epoch_001' in groups
    assert not any('/trials' in g or '/trial_' in g for g in groups), \
        'the new names leaked into the legacy layout'


def test_the_legacy_backend_writes_the_pre_rename_attribute_names(tmp_path, client):
    data = run_into(LegacyHdf5Data, tmp_path, client)

    with h5py.File(f'{data.data_directory}/layout.hdf5', 'r') as f:
        series = f['Subjects/s1/epoch_runs/series_001']
        trial = series['epochs/epoch_001']

        assert 'num_epochs_completed' in series.attrs
        assert 'num_trials_completed' not in series.attrs
        # a run parameter reaches the file named after its key, so the rename shows in the data too
        assert 'num_epochs' in series.attrs
        assert 'num_trials' not in series.attrs, 'both spellings would drift apart'
        assert 'epoch_duration' in trial.attrs
        assert 'trial_duration' not in trial.attrs


def test_the_modern_backend_writes_the_new_names(tmp_path, client):
    data = run_into(BaseData, tmp_path, client)
    groups = groups_in(data)

    assert 'Subjects/s1/series/series_001/trials/trial_001' in groups
    assert not any('epoch' in g for g in groups)

    with h5py.File(f'{data.data_directory}/layout.hdf5', 'r') as f:
        series = f['Subjects/s1/series/series_001']
        assert 'num_trials_completed' in series.attrs
        assert 'trial_duration' in series['trials/trial_001'].attrs


def test_both_backends_hold_the_same_things_under_different_names(tmp_path, client):
    """Only the names differ. If the legacy backend were a frozen copy it would drift; it is the
    same code with five strings overridden, so it cannot."""
    legacy = run_into(LegacyHdf5Data, tmp_path / 'a', client)
    modern = run_into(BaseData, tmp_path / 'b', client)

    def shape(data, series_group, trials_group, prefix):
        with h5py.File(f'{data.data_directory}/layout.hdf5', 'r') as f:
            series = f[f'Subjects/s1/{series_group}/series_001']
            trials = series[trials_group]
            return (sorted(series.keys()), len(trials), sorted(trials[f'{prefix}001'].attrs))

    legacy_keys, legacy_trials, legacy_attrs = shape(legacy, 'epoch_runs', 'epochs', 'epoch_')
    modern_keys, modern_trials, modern_attrs = shape(modern, 'series', 'trials', 'trial_')

    assert legacy_trials == modern_trials == 2
    assert set(legacy_keys) - {'epochs'} == set(modern_keys) - {'trials'}
    assert sorted(a.replace('epoch_', 'trial_') for a in legacy_attrs) == modern_attrs


def test_the_data_format_key_selects_the_legacy_backend():
    from stimpack.experiment.util import config_tools

    assert config_tools.get_data_format({'data_format': 'legacy_hdf5'}) == 'legacy_hdf5'
    assert config_tools.get_builtin_data_class({'data_format': 'legacy_hdf5'}) is LegacyHdf5Data
