"""Unit tests for the HDF5 data model (stimpack.experiment.data) — writes to a tmp file, no rig."""
import pytest

pytest.importorskip("numpy")
pytest.importorskip("h5py")
pytest.importorskip("yaml")
pytest.importorskip("platformdirs")

import h5py
from stimpack.experiment.data import BaseData, hdf5ify_parameter

pytestmark = pytest.mark.unit


def test_hdf5ify_parameter_coercions():
    assert hdf5ify_parameter(None) == "None"
    assert hdf5ify_parameter({"a": 1}) == str({"a": 1})
    # a list of numbers becomes an array; a list with a string stays a list
    import numpy as np
    assert np.array_equal(hdf5ify_parameter([1, 2, 3]), np.array([1, 2, 3]))
    assert hdf5ify_parameter([1, "x"]) == [1, "x"]


class _Protocol:
    """Minimal stand-in with the attributes BaseData reads."""
    def __init__(self, stim_params):
        self.__class__.__name__  # noqa
        self.run_parameters = {"num_trials": 1, "idle_color": 0.0}
        self.protocol_parameters = {"angle": [0, 90]}
        self.trial_stim_parameters = stim_params
        self.trial_protocol_parameters = {"pre_time": 1.0, "stim_time": 2.0, "tail_time": 1.0}
        self.num_trials_completed = 0


def _make_data(tmp_path):
    data = BaseData(cfg={})
    data.data_directory = str(tmp_path)
    data.experiment_file_name = "test_experiment"
    data.initialize_experiment_file()
    data.create_subject({"subject_id": "s1"})
    return data


def test_list_valued_stim_parameters_are_saved(tmp_path):
    # Regression (#17): a list of stims must be serialized (was silently dropped when only
    # tuple/dict were handled).
    data = _make_data(tmp_path)
    proto = _Protocol(stim_params=[{"name": "StimA", "width": 10}, {"name": "StimB", "width": 20}])
    data.create_series(proto)
    data.create_trial(proto)

    fpath = tmp_path / "test_experiment.hdf5"
    with h5py.File(fpath, "r") as f:
        epoch = f[data.trials_path() + "/trial_001"]
        assert epoch.attrs["stim0_name"] == "StimA"
        assert epoch.attrs["stim1_name"] == "StimB"


def test_end_trial_guard_does_not_raise_without_file(tmp_path):
    # Regression (#16): end_trial must degrade gracefully like its siblings, not open 'r+' blindly.
    data = BaseData(cfg={})
    data.data_directory = str(tmp_path)
    data.experiment_file_name = ""  # no file
    data.end_trial(_Protocol(stim_params={}))  # must not raise


def test_end_series_records_status_and_reason(tmp_path):
    data = _make_data(tmp_path)
    proto = _Protocol(stim_params={"name": "StimA"})
    proto.num_trials_completed = 3
    data.create_series(proto)
    data.end_series(proto, status="aborted", reason="server_connection_lost")

    with h5py.File(tmp_path / "test_experiment.hdf5", "r") as f:
        series = f[data.series_path()]
        assert series.attrs["run_status"] == "aborted"
        assert series.attrs["abort_reason"] == "server_connection_lost"
        assert series.attrs["num_trials_completed"] == 3
        assert "run_end_unix_time" in series.attrs


def test_end_series_completed_has_no_reason(tmp_path):
    data = _make_data(tmp_path)
    proto = _Protocol(stim_params={"name": "StimA"})
    data.create_series(proto)
    data.end_series(proto)  # default status='completed'

    with h5py.File(tmp_path / "test_experiment.hdf5", "r") as f:
        series = f[data.series_path()]
        assert series.attrs["run_status"] == "completed"
        assert "abort_reason" not in series.attrs


def test_end_series_missing_series_group_is_safe(tmp_path):
    # If the run never created its series group, annotating the outcome must not raise.
    data = _make_data(tmp_path)
    data.series_count = 999  # a series that was never created
    data.end_series(_Protocol(stim_params={}), status="error", reason="x")  # must not raise


# --- h5io reads should not require write access (#41) --------------------------------------------

def test_attributes_can_be_read_from_a_read_only_file(tmp_path):
    """Opening 'r+' just to read attrs fails on a read-only file and takes an HDF5 write lock,
    which can block reading metadata for the experiment currently being written."""
    import os
    import stat

    import h5py
    from stimpack.experiment.util import h5io

    path = tmp_path / 'ro.hdf5'
    with h5py.File(path, 'w') as f:
        f.create_group('grp').attrs['note'] = 'hello'
    os.chmod(path, stat.S_IRUSR)

    try:
        assert h5io.get_attributes_from_group(str(path), '/grp')['note'] == 'hello'
    finally:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def test_additional_exclusions_accepts_a_list(tmp_path):
    """It was appended rather than extended, so a list went in as a single element and the
    membership test below it raised TypeError -- the documented list form never worked."""
    import h5py
    from stimpack.experiment.util import h5io

    path = tmp_path / 'tree.hdf5'
    with h5py.File(path, 'w') as f:
        for name in ('keep', 'drop_a', 'drop_b'):
            f.create_group(name)

    hierarchy = h5io.get_hierarchy(str(path), additional_exclusions=['drop_a', 'drop_b'])

    assert 'keep' in hierarchy
    assert 'drop_a' not in hierarchy and 'drop_b' not in hierarchy


def test_additional_exclusions_still_accepts_a_bare_string(tmp_path):
    import h5py
    from stimpack.experiment.util import h5io

    path = tmp_path / 'tree.hdf5'
    with h5py.File(path, 'w') as f:
        f.create_group('keep'), f.create_group('drop_a')

    hierarchy = h5io.get_hierarchy(str(path), additional_exclusions='drop_a')
    assert 'keep' in hierarchy and 'drop_a' not in hierarchy
