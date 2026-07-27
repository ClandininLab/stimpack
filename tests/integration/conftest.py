"""Fixtures for integration tests: drive real stimpack objects with a fake RPC link.

These exercise the actual BaseClient run loop, BaseProtocol parameter machinery, and BaseData HDF5
writing — no server, screens, GL, GUI, or hardware. The only thing faked is the socket link.
"""
import pytest

pytest.importorskip("numpy")
pytest.importorskip("h5py")
pytest.importorskip("yaml")
pytest.importorskip("platformdirs")
pytest.importorskip("PyQt6")

from fakes import FakeManager  # noqa: E402 - tests/ is on sys.path via pytest's pythonpath setting


@pytest.fixture(scope="session")
def qapp():
    """A QApplication — BaseClient.start_run pumps QApplication.processEvents() in its loop."""
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def fake_manager():
    return FakeManager()


@pytest.fixture
def client(fake_manager, qapp):
    """A BaseClient wired to the fake manager, bypassing __init__ (which would connect to a server)."""
    from stimpack.experiment.client import BaseClient

    c = BaseClient.__new__(BaseClient)
    c.stop = False
    c.pause = False
    c.cfg = {}
    c.server_messages = []
    c.server_error = None
    c.on_server_message = None
    c._message_counts = {}
    c.manager = fake_manager
    c.trigger_device = None
    c.server_options = {}
    return c


@pytest.fixture
def data(tmp_path):
    """A real BaseData writing to a temporary HDF5 file, with a subject selected."""
    from stimpack.experiment.data import BaseData

    d = BaseData(cfg={})
    d.data_directory = str(tmp_path)
    d.experiment_file_name = "integration_test"
    d.initialize_experiment_file()
    d.create_subject({"subject_id": "subj1"})
    return d


@pytest.fixture
def nwb_data(tmp_path):
    """The same, writing NWB: a directory of one .nwb file per series, with a subject selected."""
    pytest.importorskip("pynwb")
    from stimpack.experiment.data_nwb import NWBData

    d = NWBData(cfg={'experimenter': 'tester', 'lab': 'TestLab', 'institution': 'TestU',
                     'current_rig_name': 'rig1', 'rig_config': {'rig1': {'screen_center': [0, 0]}}})
    d.data_directory = str(tmp_path)
    d.experiment_file_name = "integration_test"
    d.initialize_experiment_file()
    d.create_subject({"subject_id": "subj1", "age": 3, "notes": ""})
    d.prepare_series()          # the GUI does this before each recorded series
    return d
