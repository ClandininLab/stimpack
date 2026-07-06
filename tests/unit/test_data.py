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
        self.run_parameters = {"num_epochs": 1, "idle_color": 0.0}
        self.protocol_parameters = {"angle": [0, 90]}
        self.epoch_stim_parameters = stim_params
        self.epoch_protocol_parameters = {"pre_time": 1.0, "stim_time": 2.0, "tail_time": 1.0}
        self.num_epochs_completed = 0


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
    data.create_epoch_run(proto)
    data.create_epoch(proto)

    fpath = tmp_path / "test_experiment.hdf5"
    with h5py.File(fpath, "r") as f:
        epoch = f["/Subjects/s1/epoch_runs/series_001/epochs/epoch_001"]
        assert epoch.attrs["stim0_name"] == "StimA"
        assert epoch.attrs["stim1_name"] == "StimB"


def test_end_epoch_guard_does_not_raise_without_file(tmp_path):
    # Regression (#16): end_epoch must degrade gracefully like its siblings, not open 'r+' blindly.
    data = BaseData(cfg={})
    data.data_directory = str(tmp_path)
    data.experiment_file_name = ""  # no file
    data.end_epoch(_Protocol(stim_params={}))  # must not raise
