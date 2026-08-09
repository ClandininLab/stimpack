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


@pytest.fixture(autouse=True)
def no_blocking_dialogs(monkeypatch):
    """No test in this tier may enter a nested event loop waiting for a click that cannot arrive.

    QT_QPA_PLATFORM=offscreen does NOT make dialogs non-blocking. The platform runs a real event
    loop, so exec() waits for input that will never come, and prints nothing at all while it waits.
    One test reaching open_message_window that way hung the CI job for six hours a push, on three
    Python versions, for ten days -- with no output naming it.

    Autouse because the failure mode is *forgetting*: the cost of a test that misses one dialog is
    not a red X, it is a suite that never finishes. A test that cares what a dialog returns still
    patches it itself; this only ensures the ones that do not care cannot hang.

    _build_gui patches QDialog.exec too, which is what the tests using `experiment_gui` have always
    relied on. This covers the tests that build a dialog without that fixture, and QMessageBox
    separately because it declares its own exec() in some PyQt6 versions and inherits QDialog's in
    others -- patching only the base is a guard that silently stops working on an upgrade.
    """
    from PyQt6.QtWidgets import QDialog, QMessageBox

    for cls in (QDialog, QMessageBox):
        monkeypatch.setattr(cls, 'exec', lambda self: 0, raising=False)


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


def _build_gui(monkeypatch, cfg):
    import stimpack.experiment.gui as gui_mod
    from PyQt6.QtWidgets import QDialog

    def fake_setupUI(self, experiment_gui_object, parent=None, window_size=None):
        experiment_gui_object.cfg = cfg
        experiment_gui_object.cfg_initialized = True

    monkeypatch.setattr(gui_mod.InitializeRigGUI, 'setupUI', fake_setupUI)
    monkeypatch.setattr(QDialog, 'exec', lambda self: 0)          # don't block on the modal
    monkeypatch.setattr(gui_mod.client, 'BaseClient', FakeClient)  # don't launch a server
    return gui_mod.ExperimentGUI()


@pytest.fixture
def experiment_gui(qapp, monkeypatch, test_cfg):
    """A fully constructed ExperimentGUI, with the startup modal and the client stubbed out."""
    gui = _build_gui(monkeypatch, test_cfg)
    yield gui
    gui.close()


@pytest.fixture
def nwb_experiment_gui(qapp, monkeypatch, test_cfg):
    """The same GUI, writing NWB instead of HDF5 -- the point being that it IS the same GUI."""
    pytest.importorskip("pynwb")
    cfg = dict(test_cfg, data_format='nwb')
    gui = _build_gui(monkeypatch, cfg)
    yield gui
    gui.close()
