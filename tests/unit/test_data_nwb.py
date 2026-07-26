"""
Unit tests for the NWB data backend (stimpack.experiment.data_nwb).

Writes real .nwb files under tmp_path -- no rig, no GUI. Skipped entirely when pynwb is not
installed, since it is an optional dependency (pip install stimpack[nwb]).
"""
import os
import warnings

import pytest

pytest.importorskip("pynwb")

from pynwb import NWBHDF5IO

from stimpack.experiment.data import BaseData
from stimpack.experiment.data_nwb import NWBData

pytestmark = pytest.mark.unit


CFG = {
    'experimenter': 'TestPerson',
    'lab': 'TestLab',
    'institution': 'TestUniversity',
    'current_rig_name': 'rig1',
    'rig_config': {'rig1': {'screen_center': [0, 0], 'server_options': {'host': 'localhost'}}},
}


class _Protocol:
    """Minimal stand-in with the attributes the data object reads."""
    def __init__(self, stim_params=None):
        self.run_parameters = {"num_epochs": 2, "idle_color": 0.0}
        self.protocol_parameters = {"angle": [0, 90]}
        self.epoch_stim_parameters = stim_params if stim_params is not None else {"name": "StimA"}
        self.epoch_protocol_parameters = {"pre_time": 1.0, "stim_time": 2.0, "tail_time": 1.0}
        self.num_epochs_completed = 0
        self.save_stringified_params = False


def _make_data(tmp_path, subject='s1'):
    data = NWBData(cfg=CFG)
    data.data_directory = str(tmp_path)
    data.experiment_file_name = 'expt_2026-07-26'
    data.initialize_experiment_file()
    if subject is not None:
        data.create_subject({'subject_id': subject, 'age': 5, 'notes': ''})
    return data


# --- conforms to the interface the GUI and client use -------------------------------------------

def test_is_a_basedata():
    """The GUI holds one data object and does not branch on its class, so the NWB backend has to
    be substitutable for the HDF5 one."""
    assert issubclass(NWBData, BaseData)

    gui_and_client_interface = [
        'initialize_experiment_file', 'load_experiment', 'prepare_series',
        'experiment_file_exists', 'current_subject_exists',
        'create_subject', 'update_subject', 'select_subject', 'get_existing_subject_data',
        'create_epoch_run', 'end_epoch_run', 'create_epoch', 'end_epoch', 'create_note',
        'get_existing_series', 'get_highest_series_count', 'get_series_count',
        'update_series_count', 'advance_series_count', 'reload_series_count',
        'get_server_subdir',
    ]
    missing = [name for name in gui_and_client_interface if not hasattr(NWBData, name)]
    assert missing == []


def test_declares_itself_as_directory_backed():
    assert NWBData.output_is_directory is True
    assert NWBData.supports_data_browser is False
    assert BaseData.output_is_directory is False
    assert BaseData.supports_data_browser is True


def test_nwb_names_alias_the_generic_ones(tmp_path):
    """Max's protocols and labpack code are written against the nwb_* spellings; those have to
    keep working now that the generic names are canonical."""
    data = NWBData(cfg=CFG)
    data.nwb_directory = 'expt'
    data.parent_directory = str(tmp_path)
    data.current_subject_id = 's1'

    assert data.experiment_file_name == 'expt'
    assert data.data_directory == str(tmp_path)
    assert data.current_subject == 's1'

    # and the other direction
    data.experiment_file_name = 'other'
    assert data.nwb_directory == 'other'
    assert data.nwb_directory_exists() == data.experiment_file_exists()


# --- experiment lifecycle -----------------------------------------------------------------------

def test_initialize_creates_the_directory(tmp_path):
    data = _make_data(tmp_path, subject=None)
    assert (tmp_path / 'expt_2026-07-26').is_dir()
    assert data.experiment_file_exists()


def test_experiment_file_exists_is_false_before_initialization(tmp_path):
    data = NWBData(cfg=CFG)
    data.data_directory = str(tmp_path)
    assert data.experiment_file_exists() is False       # name still ''
    data.experiment_file_name = 'not_created_yet'
    assert data.experiment_file_exists() is False       # named, but no directory


def test_load_experiment_splits_the_path(tmp_path):
    """Regression: os.path.split(path)[:-1] made parent_directory a one-element TUPLE, so every
    os.path call on it afterwards raised -- including the GUI's own isdir() check."""
    data = _make_data(tmp_path)
    loaded = NWBData(cfg=CFG)
    loaded.load_experiment(str(tmp_path / 'expt_2026-07-26'))

    assert loaded.data_directory == str(tmp_path)
    assert isinstance(loaded.parent_directory, str)
    assert os.path.isdir(loaded.parent_directory)
    assert loaded.experiment_file_name == 'expt_2026-07-26'
    assert loaded.experiment_file_exists()


def test_load_experiment_keeps_dots_in_a_directory_name(tmp_path):
    (tmp_path / '2026.07.26').mkdir()
    data = NWBData(cfg=CFG)
    data.load_experiment(str(tmp_path / '2026.07.26'))
    assert data.experiment_file_name == '2026.07.26'    # not truncated to '2026.07'


def test_hdf5_load_experiment_strips_the_extension(tmp_path):
    data = BaseData(cfg={})
    data.load_experiment(str(tmp_path / 'my_expt.hdf5'))
    assert data.experiment_file_name == 'my_expt'
    assert data.data_directory == str(tmp_path)


# --- subjects -----------------------------------------------------------------------------------

def test_select_subject_is_visible_to_everything_that_reads_it(tmp_path):
    """Regression: select_subject wrote current_subject while the file path, the existence check
    and get_server_subdir all read current_subject_id, so picking an existing subject from the
    GUI dropdown changed nothing."""
    data = _make_data(tmp_path, subject=None)
    assert data.current_subject_exists() is False

    data.select_subject('s2')
    assert data.current_subject_exists() is True
    assert data.current_subject_id == 's2'
    assert 's2' in str(data.get_nwb_file_path())
    assert data.get_server_subdir().endswith('s2')


def test_update_subject_revises_metadata(tmp_path):
    data = _make_data(tmp_path)
    data.update_subject({'subject_id': 's1', 'age': 9, 'notes': 'revised'})
    assert data.subject_metadata['age'] == 9

    data.update_subject({'subject_id': 'someone_else', 'age': 1})
    assert data.subject_metadata['age'] == 9        # unchanged: not the current subject


def test_get_existing_subject_data_on_a_fresh_directory(tmp_path):
    # Must not raise just because no series have been written yet.
    assert _make_data(tmp_path).get_existing_subject_data() == []


def test_get_existing_subject_data_round_trips(tmp_path):
    data = _make_data(tmp_path)
    data.prepare_series()

    subjects = data.get_existing_subject_data()
    assert [s['subject_id'] for s in subjects] == ['s1']
    assert subjects[0]['notes'] == ''            # non-canonical fields survive via description


# --- series -------------------------------------------------------------------------------------

def test_prepare_series_writes_one_file_per_series(tmp_path):
    data = _make_data(tmp_path)
    data.prepare_series()
    data.advance_series_count()
    data.prepare_series()

    assert len(data.get_series_files()) == 2
    assert sorted(data.get_existing_series()) == [1, 2]
    assert data.get_highest_series_count() == 2


@pytest.mark.parametrize('name', ['', 'named_but_never_created'])
def test_series_queries_are_safe_before_initialization(tmp_path, name):
    """The GUI queries these while the user is still filling in the experiment dialog, so they
    have to answer for a directory that does not exist yet rather than raising FileNotFoundError."""
    data = NWBData(cfg=CFG)
    data.data_directory = str(tmp_path)
    data.experiment_file_name = name
    assert not data.nwb_directory_path.is_dir() or name == ''

    assert data.get_series_files() == []
    assert data.get_existing_series() == []
    assert data.get_highest_series_count() == 0
    assert data.get_existing_subject_data() == []
    assert data.get_series_count() == 1


def test_reload_series_count_from_disk(tmp_path):
    data = _make_data(tmp_path)
    data.prepare_series()
    data.advance_series_count()
    data.prepare_series()

    fresh = NWBData(cfg=CFG)
    fresh.load_experiment(str(tmp_path / 'expt_2026-07-26'))
    fresh.reload_series_count()
    assert fresh.get_series_count() == 3


def test_get_server_subdir_is_experiment_then_subject(tmp_path):
    data = _make_data(tmp_path)
    assert data.get_server_subdir() == 'expt_2026-07-26/s1'


# --- run outcome --------------------------------------------------------------------------------

def _epochs_table(data):
    with NWBHDF5IO(data.get_nwb_file_path(), 'r') as io:
        return io.read().epochs.to_dataframe()


def test_end_epoch_run_records_status_and_reason(tmp_path):
    data = _make_data(tmp_path)
    data.prepare_series()
    proto = _Protocol()
    data.create_epoch_run(proto)
    data.end_epoch_run(proto, status='aborted', reason='server_connection_lost')

    row = _epochs_table(data).iloc[0]
    assert row['run_status'] == 'aborted'
    assert row['run_status_reason'] == 'server_connection_lost'
    assert row['stop_time'] >= row['start_time']


def test_end_epoch_run_defaults_to_completed(tmp_path):
    data = _make_data(tmp_path)
    data.prepare_series()
    proto = _Protocol()
    data.create_epoch_run(proto)
    data.end_epoch_run(proto)

    row = _epochs_table(data).iloc[0]
    assert row['run_status'] == 'completed'
    assert row['run_status_reason'] == ''


def test_end_epoch_run_without_an_epoch_run_does_not_raise(tmp_path):
    """The client calls this from a finally block, so it runs even when the run failed before
    create_epoch_run stored anything. Popping epoch_start_time then raised KeyError from inside
    the error handler, hiding whatever actually went wrong."""
    data = _make_data(tmp_path, subject=None)      # no subject -> create_epoch_run bails out
    proto = _Protocol()
    data.create_epoch_run(proto)
    with pytest.warns(UserWarning, match='No epoch run to close out'):
        data.end_epoch_run(proto, status='error', reason='boom')


def test_end_epoch_run_without_a_series_file_does_not_raise(tmp_path):
    """A run that failed before prepare_series has no file to append to."""
    data = _make_data(tmp_path)
    proto = _Protocol()
    data.create_epoch_run(proto)                   # parameters exist...
    assert not os.path.isfile(data.get_nwb_file_path())   # ...but the file does not
    with pytest.warns(UserWarning, match='No NWB file at'):
        data.end_epoch_run(proto, status='error', reason='boom')


def test_a_full_series_round_trips(tmp_path):
    data = _make_data(tmp_path)
    data.prepare_series()
    proto = _Protocol()
    data.create_epoch_run(proto)
    for _ in range(2):
        data.create_epoch(proto)
        data.end_epoch(proto)
        proto.num_epochs_completed += 1
    data.end_epoch_run(proto)

    with NWBHDF5IO(data.get_nwb_file_path(), 'r') as io:
        nwbfile = io.read()
        assert len(nwbfile.trials) == 2
        assert len(nwbfile.epochs) == 1
        assert nwbfile.subject.subject_id == 's1'
        assert nwbfile.lab == 'TestLab'
        assert nwbfile.institution == 'TestUniversity'
        trials = nwbfile.trials.to_dataframe()
        assert trials['protocol'].iloc[0] == 'StimA'
        assert trials['pre_time'].iloc[0] == 1.0


def test_notes_go_to_a_csv_beside_the_series_files(tmp_path):
    data = _make_data(tmp_path)
    data.create_note('a note')
    notes = tmp_path / 'expt_2026-07-26' / 'notes.csv'
    assert notes.is_file()
    assert 'a note' in notes.read_text()


def test_create_epoch_without_a_subject_does_not_collect_parameters(tmp_path):
    """Warning and carrying on only defers the failure to end_epoch, which then reports a missing
    file instead of the missing subject that caused it."""
    data = _make_data(tmp_path, subject=None)
    with pytest.warns(UserWarning, match='define a subject first'):
        data.create_epoch(_Protocol())
    assert data.trial_parameters == {}


def test_end_epoch_without_a_series_file_does_not_raise(tmp_path):
    """Called once per epoch during a run; a run not saving metadata must not raise every epoch."""
    data = _make_data(tmp_path)
    data.create_epoch(_Protocol())                        # parameters collected...
    assert not os.path.isfile(data.get_nwb_file_path())   # ...but no file was ever written
    with pytest.warns(UserWarning, match='No NWB file at'):
        data.end_epoch(_Protocol())


def test_end_epoch_with_nothing_collected_is_silent(tmp_path):
    """Not merely non-raising: with no epoch collected there is nothing wrong, so it must not
    complain about a missing file either. During a View run this is called every epoch."""
    data = _make_data(tmp_path, subject=None)
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        data.end_epoch(_Protocol())
