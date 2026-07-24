"""Fixtures for GUI tests: build the real ExperimentGUI headlessly (QT_QPA_PLATFORM=offscreen).

Two things are bypassed so no human or rig is needed:
  - the blocking rig/config modal (InitializeRigGUI + QDialog.exec), replaced by a fixed test cfg
  - BaseClient, replaced by FakeClient so no stimulus server is launched
Everything else — widget construction, protocol discovery, button wiring — is the real thing.
"""
import pytest

pytest.importorskip("numpy")
pytest.importorskip("h5py")
pytest.importorskip("yaml")
pytest.importorskip("platformdirs")
pytest.importorskip("PyQt6")

from fakes import FakeClient  # noqa: E402 - tests/ is on sys.path via pytest's pythonpath setting


@pytest.fixture(scope="session")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def test_cfg(tmp_path):
    return {
        'experimenter': 'tester',
        'subject_metadata': {'genotype': ['wildtype', 'mutant']},
        'current_rig_name': 'test_rig',
        'current_cfg_name': 'test_cfg',
        'rig_config': {'test_rig': {'screen_center': [0, 0],
                                    'loco_available': False,
                                    'data_directory': str(tmp_path)}},
    }


@pytest.fixture
def experiment_gui(qapp, monkeypatch, test_cfg):
    """A fully constructed ExperimentGUI, with the startup modal and the client stubbed out."""
    import stimpack.experiment.gui as gui_mod
    from PyQt6.QtWidgets import QDialog

    def fake_setupUI(self, experiment_gui_object, parent=None, window_size=None):
        experiment_gui_object.cfg = test_cfg
        experiment_gui_object.cfg_initialized = True

    monkeypatch.setattr(gui_mod.InitializeRigGUI, 'setupUI', fake_setupUI)
    monkeypatch.setattr(QDialog, 'exec', lambda self: 0)          # don't block on the modal
    monkeypatch.setattr(gui_mod.client, 'BaseClient', FakeClient)  # don't launch a server

    gui = gui_mod.ExperimentGUI()
    yield gui
    gui.close()
