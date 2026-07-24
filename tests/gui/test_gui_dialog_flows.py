"""GUI tests for the flows that normally require a human clicking through dialogs.

Qt's dialog statics (QFileDialog / QInputDialog) are patched to return canned answers, so the real
handlers run end to end: creating/loading an experiment file, creating a subject, entering a note,
saving/loading parameter presets and ensembles, and recording once a file + subject exist.
"""
import h5py
import pytest
from PyQt6.QtWidgets import QPushButton

pytestmark = pytest.mark.gui


def button(gui, text):
    """Find a real button by its label (several are local variables in initUI)."""
    for b in gui.findChildren(QPushButton):
        if b.text() == text:
            return b
    raise AssertionError(f'no button labeled {text!r}')


def make_experiment_file(tmp_path, name='dialog_test'):
    """An existing HDF5 experiment file to load, as a previous session would have left."""
    from stimpack.experiment.data import BaseData
    d = BaseData(cfg={})
    d.data_directory = str(tmp_path)
    d.experiment_file_name = name
    d.initialize_experiment_file()
    return f'{tmp_path}/{name}.hdf5'


def select_protocol(gui, name='DriftingSquareGrating'):
    names = [c.__name__ for c in gui.available_protocols]
    idx = names.index(name) + 1
    gui.protocol_selection_combo_box.setCurrentIndex(idx)
    gui.on_selected_protocol_ID(idx)


# --- experiment file --------------------------------------------------------------------------

def test_load_experiment_via_file_dialog(experiment_gui, tmp_path, monkeypatch):
    import stimpack.experiment.gui as gui_mod
    gui = experiment_gui
    path = make_experiment_file(tmp_path)

    monkeypatch.setattr(gui_mod.QFileDialog, 'getOpenFileName',
                        lambda *a, **k: (path, 'All Files (*)'))
    button(gui, 'Load experiment').click()

    assert gui.data.experiment_file_name == 'dialog_test'
    assert gui.data.data_directory == str(tmp_path)
    assert gui.current_experiment_label.text() == 'dialog_test'
    assert gui.data.experiment_file_exists()


def test_cancelled_file_dialog_is_harmless(experiment_gui, monkeypatch):
    import stimpack.experiment.gui as gui_mod
    gui = experiment_gui

    monkeypatch.setattr(gui_mod.QFileDialog, 'getOpenFileName', lambda *a, **k: ('', ''))
    button(gui, 'Load experiment').click()          # user hit Cancel -> must not raise

    assert gui.data.experiment_file_name == ''      # nothing loaded


# --- subject + notes --------------------------------------------------------------------------

def test_create_subject_writes_to_the_file(experiment_gui, tmp_path, monkeypatch):
    import stimpack.experiment.gui as gui_mod
    gui = experiment_gui
    path = make_experiment_file(tmp_path)
    monkeypatch.setattr(gui_mod.QFileDialog, 'getOpenFileName', lambda *a, **k: (path, ''))
    button(gui, 'Load experiment').click()

    gui.subject_id_input.setText('fly_001')
    gui.subject_age_input.setValue(3)
    gui.subject_notes_input.setPlainText('looks healthy')
    gui.subject_metadata_inputs['genotype'].setCurrentText('mutant')
    button(gui, 'Create subject').click()

    assert gui.data.current_subject == 'fly_001'
    with h5py.File(path, 'r') as f:
        subject = f['/Subjects/fly_001']
        assert subject.attrs['age'] == 3
        assert subject.attrs['notes'] == 'looks healthy'
        assert subject.attrs['genotype'] == 'mutant'   # the config-defined metadata field


def test_enter_note_writes_to_the_file(experiment_gui, tmp_path, monkeypatch):
    import stimpack.experiment.gui as gui_mod
    gui = experiment_gui
    path = make_experiment_file(tmp_path)
    monkeypatch.setattr(gui_mod.QFileDialog, 'getOpenFileName', lambda *a, **k: (path, ''))
    button(gui, 'Load experiment').click()

    gui.notes_edit.setPlainText('stimulus looked dim')
    button(gui, 'Enter note').click()

    with h5py.File(path, 'r') as f:
        assert 'stimulus looked dim' in list(f['/Notes'].attrs.values())
    assert gui.notes_edit.toPlainText() == ''         # the box is cleared after saving


# --- parameter presets ------------------------------------------------------------------------

def test_save_preset_via_input_dialog(experiment_gui, tmp_path, monkeypatch):
    import stimpack.experiment.gui as gui_mod
    gui = experiment_gui
    select_protocol(gui)
    gui.protocol_object.parameter_preset_directory = str(tmp_path)   # don't write into the repo

    gui.run_parameter_input['num_epochs'].setText('11')
    monkeypatch.setattr(gui_mod.QInputDialog, 'getText', lambda *a, **k: ('my_preset', True))
    button(gui, 'Save preset').click()

    assert 'my_preset' in gui.protocol_object.parameter_presets
    assert gui.protocol_object.parameter_presets['my_preset']['run_parameters']['num_epochs'] == 11
    assert gui.parameter_preset_comboBox.findText('my_preset') >= 0   # offered in the dropdown
    assert (tmp_path / 'DriftingSquareGrating.yaml').exists()         # persisted to disk


# --- ensembles --------------------------------------------------------------------------------

def test_ensemble_save_and_load_roundtrip(experiment_gui, tmp_path, monkeypatch):
    import stimpack.experiment.gui as gui_mod
    gui = experiment_gui
    select_protocol(gui)

    # queue two items on the Ensemble tab, the way the Append button does
    gui.ensemble_protocol_selection_combo_box.setCurrentIndex(1)
    button(gui, 'Append').click()
    button(gui, 'Append').click()
    assert len(gui.ensemble_list.protocol_preset_list) == 2
    saved = list(gui.ensemble_list.protocol_preset_list)

    spens = str(tmp_path / 'my_ensemble.spens')
    monkeypatch.setattr(gui_mod.QFileDialog, 'getSaveFileName', lambda *a, **k: (spens, ''))
    button(gui, 'Save ensemble').click()
    assert (tmp_path / 'my_ensemble.spens').exists()

    button(gui, 'Clear').click()
    assert gui.ensemble_list.protocol_preset_list == []

    monkeypatch.setattr(gui_mod.QFileDialog, 'getOpenFileName', lambda *a, **k: (spens, ''))
    button(gui, 'Load ensemble').click()
    assert gui.ensemble_list.protocol_preset_list == saved      # round-tripped through the file


# --- recording --------------------------------------------------------------------------------

def test_record_runs_once_file_and_subject_exist(experiment_gui, tmp_path, monkeypatch, qapp):
    import stimpack.experiment.gui as gui_mod
    gui = experiment_gui
    path = make_experiment_file(tmp_path)
    monkeypatch.setattr(gui_mod.QFileDialog, 'getOpenFileName', lambda *a, **k: (path, ''))
    button(gui, 'Load experiment').click()

    gui.subject_id_input.setText('fly_rec')
    button(gui, 'Create subject').click()
    select_protocol(gui)

    gui.record_button.click()                       # now allowed: file + subject exist
    gui.run_series_thread.wait(5000)
    qapp.processEvents()

    assert gui.client.runs == [('DriftingSquareGrating', True)]   # started WITH metadata saving
