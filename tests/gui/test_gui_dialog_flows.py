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


# --- labpack preflight at startup ----------------------------------------------------------------

def test_startup_alerts_on_a_labpack_error(qapp, monkeypatch, tmp_path):
    """An error found in the chosen config must reach the person at the rig, not just the log."""
    import stimpack.experiment.gui as gui_mod
    from stimpack.experiment.util.check_labpack import Finding

    alerts = []
    monkeypatch.setattr(gui_mod, 'open_message_window',
                        lambda title="", text="": alerts.append((title, text)))
    monkeypatch.setattr(gui_mod.check_labpack, 'check_config',
                        lambda cfg, name, d: [Finding('error', 'missing-module-path', name,
                                                      'module_paths.protocol -> gone.py')])

    dialog = gui_mod.InitializeRigGUI.__new__(gui_mod.InitializeRigGUI)
    dialog.cfg, dialog.cfg_name, dialog.labpack_dir = {}, 'x_config.yaml', str(tmp_path)
    dialog.warn_about_labpack_problems()

    assert alerts, "an error finding produced no dialog"
    assert 'gone.py' in alerts[0][1]
    assert 'check-labpack' in alerts[0][1]          # points at the full report


def test_startup_does_not_alert_on_warnings_alone(qapp, monkeypatch, tmp_path):
    """Warnings are common and often deliberate; a modal for each would train people to dismiss."""
    import stimpack.experiment.gui as gui_mod
    from stimpack.experiment.util.check_labpack import Finding

    alerts = []
    monkeypatch.setattr(gui_mod, 'open_message_window',
                        lambda title="", text="": alerts.append((title, text)))
    monkeypatch.setattr(gui_mod.check_labpack, 'check_config',
                        lambda cfg, name, d: [Finding('warning', 'missing-presets-dir', name, 'no presets')])

    dialog = gui_mod.InitializeRigGUI.__new__(gui_mod.InitializeRigGUI)
    dialog.cfg, dialog.cfg_name, dialog.labpack_dir = {}, 'x_config.yaml', str(tmp_path)
    dialog.warn_about_labpack_problems()

    assert alerts == []


def test_a_failing_check_never_blocks_startup(qapp, monkeypatch, tmp_path):
    import stimpack.experiment.gui as gui_mod

    def boom(cfg, name, d):
        raise RuntimeError('checker is broken')

    monkeypatch.setattr(gui_mod.check_labpack, 'check_config', boom)

    dialog = gui_mod.InitializeRigGUI.__new__(gui_mod.InitializeRigGUI)
    dialog.cfg, dialog.cfg_name, dialog.labpack_dir = {}, 'x_config.yaml', str(tmp_path)
    with pytest.warns(UserWarning):
        dialog.warn_about_labpack_problems()        # must not raise


# --- dialog construction ------------------------------------------------------------------------

def test_repeatedly_opening_the_experiment_dialog_is_safe(experiment_gui, tmp_path):
    """Regression: setupUI ran QWidget.__init__ a second time on a widget the caller had already
    constructed with its parent. Re-running a live QWidget's constructor corrupts the C++ object,
    which does not fail where it happens -- it segfaults later, in unrelated code. Opening the
    dialog repeatedly in one process is what makes it show up."""
    from PyQt6.QtWidgets import QDialog
    import stimpack.experiment.gui as gui_mod

    for i in range(25):
        dialog = QDialog()
        dialog_ui = gui_mod.InitializeExperimentGUI(parent=dialog)
        dialog_ui.setupUI(experiment_gui, dialog)
        dialog_ui.le_filename.setText(f'expt_{i}')
        dialog_ui.le_data_directory.setText(str(tmp_path))
        dialog_ui.on_pressed_enter_button()
        assert dialog_ui.label_status.text() == 'Data entered'

    assert experiment_gui.data.experiment_file_name == 'expt_24'


# --- choosing the data format at startup ----------------------------------------------------------

def make_startup_dialog(qapp, tmp_path, cfg, data_format_override=None):
    """An InitializeRigGUI with its UI built, standing in for the startup modal.

    Constructed against a stub 'experiment GUI' rather than a real one: the dialog runs before the
    real GUI exists, and what it produces (a cfg) is the whole of its contract.
    """
    import stimpack.experiment.gui as gui_mod

    class StubGUI:
        pass

    stub = StubGUI()
    stub.data_format_override = data_format_override
    stub.cfg, stub.cfg_initialized = {}, False

    dialog = gui_mod.InitializeRigGUI()
    dialog.setupUI(stub, parent=None)
    dialog.cfg = dict(cfg)
    dialog.cfg_name = 'test_config.yaml'
    dialog.update_data_format_selection()
    return dialog, stub


def test_the_startup_dialog_defaults_to_the_config_data_format(qapp, tmp_path):
    dialog, _ = make_startup_dialog(qapp, tmp_path, {'data_format': 'nwb'})
    assert dialog.data_format_combobox.currentText() == 'nwb'

    dialog, _ = make_startup_dialog(qapp, tmp_path, {'data_format': 'hdf5'})
    assert dialog.data_format_combobox.currentText() == 'hdf5'

    dialog, _ = make_startup_dialog(qapp, tmp_path, {})      # unset: the documented default
    assert dialog.data_format_combobox.currentText() == 'hdf5'


def test_the_startup_dialog_offers_every_built_in_format(qapp, tmp_path):
    from stimpack.experiment.util import config_tools

    dialog, _ = make_startup_dialog(qapp, tmp_path, {})
    offered = [dialog.data_format_combobox.itemText(i)
               for i in range(dialog.data_format_combobox.count())]
    assert sorted(offered) == sorted(config_tools.BUILTIN_DATA_FORMATS)


def test_the_chosen_format_reaches_the_config(qapp, tmp_path):
    """What the dialog produces is a cfg; the GUI reads data_format out of it to pick a backend."""
    dialog, stub = make_startup_dialog(qapp, tmp_path, {'data_format': 'hdf5'})
    dialog.rig_combobox.addItem('rig_a')
    dialog.rig_combobox.setCurrentIndex(0)

    index = dialog.data_format_combobox.findText('nwb')
    dialog.data_format_combobox.setCurrentIndex(index)
    dialog.on_pressed_enter_button()

    assert stub.cfg['data_format'] == 'nwb'
    assert stub.cfg_initialized is True


def test_a_command_line_override_is_shown_and_locked(qapp, tmp_path):
    """--data-format is applied after this dialog either way, so a dialog showing something else
    would be worse than no dialog."""
    dialog, _ = make_startup_dialog(qapp, tmp_path, {'data_format': 'hdf5'},
                                    data_format_override='nwb')

    assert dialog.data_format_combobox.currentText() == 'nwb'
    assert not dialog.data_format_combobox.isEnabled()


def test_the_format_follows_the_selected_config(qapp, tmp_path):
    """Picking a different config re-reads its data_format rather than leaving the last answer."""
    dialog, _ = make_startup_dialog(qapp, tmp_path, {'data_format': 'nwb'})
    assert dialog.data_format_combobox.currentText() == 'nwb'

    dialog.cfg = {'data_format': 'hdf5'}
    dialog.update_data_format_selection()
    assert dialog.data_format_combobox.currentText() == 'hdf5'
