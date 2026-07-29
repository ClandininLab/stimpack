"""
GUI tests for the two built-in storage backends.

There used to be two GUIs -- gui.py for HDF5 and gui_nwb.py for NWB, forked in July 2024 and
drifting apart ever since. These drive the ONE GUI against both backends, so the consolidation
stays consolidated: anything that works for only one format fails here.

HDF5-only flows (loading, subjects, notes) are covered in test_gui_dialog_flows.py; this file is
about the parts that had to become backend-aware.
"""
import os

import pytest
from PyQt6.QtWidgets import QPushButton

pytestmark = pytest.mark.gui


def button(gui, text):
    for b in gui.findChildren(QPushButton):
        if b.text() == text:
            return b
    raise AssertionError(f'no button labeled {text!r}')


def make_dialog(gui):
    """The 'Initialize experiment' dialog, built exactly as on_pressed_button builds it."""
    import stimpack.experiment.gui as gui_mod
    from PyQt6.QtWidgets import QDialog
    dialog = QDialog()
    dialog_ui = gui_mod.InitializeExperimentGUI(parent=dialog)
    dialog_ui.setupUI(gui, dialog)
    # Keep the parent alive for as long as the caller holds the child. Qt deletes children with
    # their parent, and the real handler keeps its dialog on the stack across a blocking exec();
    # letting it be collected here leaves the child's Python wrapper pointing at freed memory,
    # which segfaults an unrelated test later on.
    dialog_ui._parent_dialog = dialog
    return dialog_ui


def initialize(gui, name='expt'):
    """Fill in and accept that dialog, as a user would."""
    dialog_ui = make_dialog(gui)
    dialog_ui.le_filename.setText(name)
    dialog_ui.le_data_directory.setText(gui.data.data_directory)
    dialog_ui.le_experimenter.setText('tester')
    dialog_ui.on_pressed_enter_button()
    return dialog_ui


def add_subject(gui, subject_id='fly1', age=3):
    gui.subject_id_input.setText(subject_id)
    gui.subject_age_input.setValue(age)
    button(gui, 'Create subject').click()


# --- the config picks the backend ---------------------------------------------------------------

def test_default_config_gets_the_hdf5_backend(experiment_gui):
    from stimpack.experiment.data import BaseData
    assert type(experiment_gui.data) is BaseData
    assert experiment_gui.data.output_is_directory is False


def test_data_format_nwb_gets_the_nwb_backend(nwb_experiment_gui):
    from stimpack.experiment.data_nwb import NWBData
    assert type(nwb_experiment_gui.data) is NWBData
    assert nwb_experiment_gui.data.output_is_directory is True


def test_unknown_data_format_warns_and_falls_back(test_cfg):
    from stimpack.experiment.util import config_tools
    with pytest.warns(UserWarning, match='Unknown data_format'):
        assert config_tools.get_data_format(dict(test_cfg, data_format='parquet')) == 'hdf5'


def _write_data_module(tmp_path, name, base_import, base):
    """A labpack data module on disk, since these are loaded by file path rather than imported."""
    path = tmp_path / name
    path.write_text(f'from {base_import} import {base}\n\n'
                    f'class Data({base}):\n'
                    f'    lab_marker = {name!r}\n')
    return str(path)


def test_one_labpack_data_module_still_wins_over_data_format(tmp_path, test_cfg):
    """A config naming a single data class has its format decided by that class's base, so
    data_format cannot be honoured and is not consulted. Overriding it the other way -- building
    the built-in for the requested format -- would drop the lab's overrides instead, which is the
    same silent discard and much harder to notice."""
    from stimpack.experiment.util import config_tools

    path = _write_data_module(tmp_path, 'data.py', 'stimpack.experiment.data', 'BaseData')
    cfg = dict(test_cfg, data_format='nwb', module_paths={'data': path})

    assert config_tools.load_user_data_class(cfg).lab_marker == 'data.py'


@pytest.mark.parametrize('data_format, expected', [('hdf5', 'data.py'), ('nwb', 'data_nwb.py')])
def test_a_module_per_format_lets_data_format_choose_among_them(tmp_path, test_cfg,
                                                                data_format, expected):
    """The point of the mapping: a labpack keeping a class per format gets to keep its overrides
    AND have the choice honoured, which naming one module cannot do."""
    from stimpack.experiment.util import config_tools

    cfg = dict(test_cfg, data_format=data_format, module_paths={'data': {
        'hdf5': _write_data_module(tmp_path, 'data.py', 'stimpack.experiment.data', 'BaseData'),
        'nwb': _write_data_module(tmp_path, 'data_nwb.py', 'stimpack.experiment.data_nwb', 'NWBData'),
    }})

    assert config_tools.load_user_data_class(cfg).lab_marker == expected


def test_a_mapping_does_not_narrow_what_can_be_written(tmp_path, test_cfg):
    """Which formats stimpack can write and which ones the labpack has customized are different
    questions. Filtering the first by the second left a lab that customized HDF5 unable to reach
    NWB from the dialog, though --data-format could still do it."""
    from stimpack.experiment.util import config_tools

    cfg = dict(test_cfg, module_paths={'data': {
        'hdf5': _write_data_module(tmp_path, 'data.py', 'stimpack.experiment.data', 'BaseData'),
    }})

    assert config_tools.get_available_data_formats(cfg) == sorted(config_tools.BUILTIN_DATA_FORMATS)


def test_a_mapping_can_add_a_format_stimpack_does_not_have(tmp_path, test_cfg):
    """The class is loaded by path and only ever duck-typed, so a labpack can supply a backend of
    its own. Validating data_format against the built-ins alone made that unreachable."""
    from stimpack.experiment.util import config_tools

    path = _write_data_module(tmp_path, 'data.py', 'stimpack.experiment.data', 'BaseData')
    cfg = dict(test_cfg, data_format='parquet', module_paths={'data': {'parquet': path}})

    assert 'parquet' in config_tools.get_available_data_formats(cfg)
    assert config_tools.get_data_format(cfg) == 'parquet'
    assert config_tools.load_user_data_class(cfg).lab_marker == 'data.py'


def test_one_module_can_hold_a_class_per_format(tmp_path, test_cfg):
    """The two HDF5 layouts differ by five strings, so a labpack supporting both would otherwise
    put its overrides in a mixin and write two three-line modules importing it."""
    from stimpack.experiment.util import config_tools

    path = tmp_path / 'data.py'
    path.write_text('from stimpack.experiment.data import BaseData\n'
                    'from stimpack.experiment.data_legacy import LegacyHdf5Data\n\n'
                    'class _Lab:\n    lab_marker = "shared"\n\n'
                    'class Data(_Lab, BaseData): pass\n'
                    'class DataLegacy(_Lab, LegacyHdf5Data): pass\n')
    cfg = dict(test_cfg, module_paths={'data': {
        'hdf5': str(path), 'legacy_hdf5': f'{path}:DataLegacy'}})

    for data_format, expected_group in [('hdf5', 'series'), ('legacy_hdf5', 'epoch_runs')]:
        data_class = config_tools.load_user_data_class(dict(cfg, data_format=data_format))
        assert data_class.lab_marker == 'shared'
        assert data_class.SERIES_GROUP == expected_group


def test_a_mapping_without_the_requested_format_falls_back_to_the_builtin(tmp_path, test_cfg):
    """A labpack that customizes HDF5 and not NWB should still be able to write NWB with
    stimpack's own class, rather than being refused or handed the HDF5 one."""
    from stimpack.experiment.util import config_tools

    cfg = dict(test_cfg, data_format='nwb', module_paths={'data': {
        'hdf5': _write_data_module(tmp_path, 'data.py', 'stimpack.experiment.data', 'BaseData'),
    }})

    with pytest.warns(UserWarning, match='has none for'):
        assert config_tools.load_user_data_class(cfg) is None


# --- the GUI adapts to the backend rather than being forked per backend --------------------------

def test_the_backend_supplies_the_browser(experiment_gui, nwb_experiment_gui):
    """Both formats get one. An .nwb file is HDF5 underneath, so the same tree reads it; what
    differs is that an NWB experiment is a directory of files, which the backend expresses through
    browsable_files() rather than the browser knowing the format."""
    from stimpack.experiment.gui_data_browser import Hdf5DataBrowser

    assert isinstance(experiment_gui.data_browser, Hdf5DataBrowser)
    assert isinstance(nwb_experiment_gui.data_browser, Hdf5DataBrowser)

    # and it is actually on the File tab, not merely constructed
    assert experiment_gui.data_browser.parent() is not None
    assert experiment_gui.data_browser in experiment_gui.findChildren(Hdf5DataBrowser)


def test_a_backend_can_decline_a_browser_without_the_gui_knowing_why(experiment_gui, monkeypatch):
    """make_data_browser is the only thing the GUI asks. A backend returning None gets a File tab
    without those widgets -- no branch on the format anywhere in gui.py."""
    assert experiment_gui.data.make_data_browser(parent=None) is not None
    monkeypatch.setattr(type(experiment_gui.data), 'supports_data_browser', False)
    assert experiment_gui.data.make_data_browser(parent=None) is None


def test_populate_groups_is_a_noop_without_a_browser(nwb_experiment_gui):
    # Called after anything that changes the data; must not reach h5io for a directory backend.
    nwb_experiment_gui.populate_groups()


def test_window_title_names_a_non_default_backend(experiment_gui, nwb_experiment_gui):
    assert 'NWBData' not in experiment_gui.windowTitle()
    assert 'NWBData' in nwb_experiment_gui.windowTitle()


def test_labels_use_the_backend_s_own_noun(experiment_gui, nwb_experiment_gui):
    assert experiment_gui.data.output_noun == 'data file'
    assert nwb_experiment_gui.data.output_noun == 'NWB directory'
    # the initialize dialog labels itself with the backend's noun
    dialog_ui = make_dialog(nwb_experiment_gui)
    assert 'NWB directory' in dialog_ui.layout().itemAt(0).widget().text()


# --- initializing an experiment -----------------------------------------------------------------

def test_initialize_creates_a_file_for_hdf5(experiment_gui, tmp_path):
    initialize(experiment_gui, 'expt_h5')
    assert (tmp_path / 'expt_h5.hdf5').is_file()
    assert experiment_gui.current_experiment_label.text() == 'expt_h5'
    assert experiment_gui.data.experiment_file_exists()


def test_initialize_creates_a_directory_for_nwb(nwb_experiment_gui, tmp_path):
    initialize(nwb_experiment_gui, 'expt_nwb')
    assert (tmp_path / 'expt_nwb').is_dir()
    assert nwb_experiment_gui.current_experiment_label.text() == 'expt_nwb'
    assert nwb_experiment_gui.data.experiment_file_exists()


@pytest.mark.parametrize('fixture', ['experiment_gui', 'nwb_experiment_gui'])
def test_initialize_refuses_to_overwrite(fixture, request):
    """The existence check has to follow the backend: for NWB the experiment is a directory, and
    testing for an .hdf5 file -- as the shared dialog used to -- would never fire."""
    gui = request.getfixturevalue(fixture)
    initialize(gui, 'twice')
    dialog_ui = initialize(gui, 'twice')
    assert 'already exists' in dialog_ui.label_status.text()


@pytest.mark.parametrize('fixture', ['experiment_gui', 'nwb_experiment_gui'])
def test_initialize_reports_a_missing_data_directory(fixture, request, tmp_path):
    gui = request.getfixturevalue(fixture)
    dialog_ui = make_dialog(gui)
    dialog_ui.le_filename.setText('x')
    dialog_ui.le_data_directory.setText(str(tmp_path / 'nope'))
    dialog_ui.on_pressed_enter_button()
    assert 'does not exist' in dialog_ui.label_status.text()


# --- loading an existing experiment ---------------------------------------------------------------

def test_load_experiment_uses_a_directory_picker_for_nwb(nwb_experiment_gui, tmp_path, monkeypatch):
    import stimpack.experiment.gui as gui_mod
    gui = nwb_experiment_gui
    initialize(gui, 'to_reload')
    gui.data.select_subject('fly1')
    path = str(tmp_path / 'to_reload')

    # A directory backend must not be offered a file picker.
    used = []
    monkeypatch.setattr(gui_mod.QFileDialog, 'getOpenFileName',
                        lambda *a, **k: (used.append('file'), ('', ''))[1])
    monkeypatch.setattr(gui_mod.QFileDialog, 'getExistingDirectory',
                        lambda *a, **k: (used.append('directory'), path)[1])

    gui.data.experiment_file_name = ''       # forget it, then load it back
    button(gui, 'Load experiment').click()

    assert used == ['directory']             # not the file picker
    assert gui.data.experiment_file_name == 'to_reload'
    assert gui.data.data_directory == str(tmp_path)
    assert isinstance(gui.data.parent_directory, str)
    assert gui.data.experiment_file_exists()
    assert gui.current_experiment_label.text() == 'to_reload'


def test_cancelling_the_nwb_load_dialog_keeps_the_current_experiment(nwb_experiment_gui, monkeypatch):
    """Cancelling returns an empty path, which used to be written straight into the data object,
    silently detaching the GUI from the experiment being recorded."""
    import stimpack.experiment.gui as gui_mod
    gui = nwb_experiment_gui
    initialize(gui, 'keep_me')

    # Patch both pickers: whichever one the GUI reaches for, it must not open a real dialog and
    # block the suite forever.
    monkeypatch.setattr(gui_mod.QFileDialog, 'getExistingDirectory', lambda *a, **k: '')
    monkeypatch.setattr(gui_mod.QFileDialog, 'getOpenFileName', lambda *a, **k: ('', ''))
    button(gui, 'Load experiment').click()

    assert gui.data.experiment_file_name == 'keep_me'
    assert gui.data.experiment_file_exists()


# --- subjects -------------------------------------------------------------------------------------

@pytest.mark.parametrize('fixture', ['experiment_gui', 'nwb_experiment_gui'])
def test_creating_a_subject_selects_and_displays_it(fixture, request):
    gui = request.getfixturevalue(fixture)
    initialize(gui, 'subjects')
    add_subject(gui, 'fly1')

    assert gui.data.current_subject == 'fly1'
    assert gui.data.current_subject_exists()
    assert gui.existing_subject_input.currentText() == 'fly1'


def test_subject_dropdown_lists_each_subject_once(nwb_experiment_gui):
    """NWB keeps subject metadata in every series file, so a subject run three times was reported
    three times and appeared three times in the dropdown. The backend keys by subject id now, so
    the answer is right before the GUI ever sees it -- the dropdown's own deduplication stays as
    the second line of defence."""
    gui = nwb_experiment_gui
    initialize(gui, 'dupes')
    add_subject(gui, 'fly1')

    for _ in range(3):                       # three series for the same subject
        gui.data.prepare_series()
        gui.data.advance_series_count()

    assert [s['subject_id'] for s in gui.data.get_existing_subject_data()] == ['fly1']
    gui.update_existing_subject_input()
    assert gui.existing_subject_input.count() == 1


def test_selecting_from_the_dropdown_selects_that_subject(nwb_experiment_gui):
    """Regression: the handler indexed get_existing_subject_data() by dropdown position, which
    stops matching as soon as the dropdown is deduplicated."""
    gui = nwb_experiment_gui
    initialize(gui, 'pick')
    for subject_id in ('flyA', 'flyB'):
        add_subject(gui, subject_id)
        gui.data.prepare_series()
        gui.data.advance_series_count()

    gui.update_existing_subject_input()
    labels = [gui.existing_subject_input.itemText(i) for i in range(gui.existing_subject_input.count())]
    gui.on_selected_existing_subject(labels.index('flyA'))

    assert gui.data.current_subject == 'flyA'
    assert gui.subject_id_input.text() == 'flyA'
    assert 'flyA' in str(gui.data.get_nwb_file_path())


def test_note_before_initialization_is_refused(nwb_experiment_gui, monkeypatch):
    """Refused before the dialog opens -- there is nowhere to leave typed text now."""
    import stimpack.experiment.gui as gui_mod

    gui = nwb_experiment_gui
    monkeypatch.setattr(gui_mod, 'open_message_window', lambda title="", text="": None)

    button(gui, 'Note').click()

    assert gui.note_dialog is None, 'asked for a note with no NWB directory to save it in'


def test_note_is_written_beside_the_nwb_files(nwb_experiment_gui, tmp_path):
    gui = nwb_experiment_gui
    initialize(gui, 'noted')

    button(gui, 'Note').click()
    gui.note_dialog.setTextValue('stimulus looked dim')
    gui.note_dialog.accept()

    notes = tmp_path / 'noted' / 'notes.csv'
    assert notes.is_file() and 'stimulus looked dim' in notes.read_text()


# --- recording ------------------------------------------------------------------------------------

def select_protocol(gui, name='DriftingSquareGrating'):
    names = [c.__name__ for c in gui.available_protocols]
    idx = names.index(name) + 1
    gui.protocol_selection_combo_box.setCurrentIndex(idx)
    gui.on_selected_protocol_ID(idx)


def test_recording_creates_the_series_file_for_nwb(nwb_experiment_gui, qapp):
    """The NWB backend needs its per-series file created before the run thread starts; HDF5 needs
    nothing, which is why the GUI calls a hook rather than branching on the format. Driven through
    the Record button so the wiring is covered and not just the backend method."""
    gui = nwb_experiment_gui
    initialize(gui, 'recording')
    add_subject(gui, 'fly1')
    select_protocol(gui)

    assert gui.data.get_series_files() == []
    # Capture the path before the run: run_finished advances the series counter afterwards,
    # so get_nwb_file_path() then names the NEXT series, not the one just recorded.
    expected = gui.data.get_nwb_file_path()
    gui.record_button.click()
    gui.run_series_thread.wait(5000)
    qapp.processEvents()

    assert gui.client.runs == [('DriftingSquareGrating', True)]
    assert gui.data.get_series_files() == [expected]


def test_viewing_does_not_create_a_series_file(nwb_experiment_gui, qapp):
    """View means "no metadata saved", so it must not write a file either."""
    gui = nwb_experiment_gui
    initialize(gui, 'viewing')
    add_subject(gui, 'fly1')
    select_protocol(gui)

    gui.view_button.click()
    gui.run_series_thread.wait(5000)
    qapp.processEvents()

    assert gui.client.runs == [('DriftingSquareGrating', False)]   # ran, without saving
    assert gui.data.get_series_files() == []


def test_hdf5_prepare_series_changes_nothing(experiment_gui, tmp_path):
    initialize(experiment_gui, 'noop')
    before = sorted(os.listdir(tmp_path))
    experiment_gui.data.prepare_series()
    assert sorted(os.listdir(tmp_path)) == before


# --- choosing the backend from the command line ---------------------------------------------------

def test_data_format_flag_overrides_the_config(qapp, monkeypatch, test_cfg):
    """For trying a format without editing a config. The config still decides by default."""
    pytest.importorskip('pynwb')
    from stimpack.experiment.data_nwb import NWBData
    import stimpack.experiment.gui as gui_mod
    from PyQt6.QtWidgets import QDialog
    from fakes import FakeClient

    def fake_setupUI(self, experiment_gui_object, parent=None, window_size=None):
        experiment_gui_object.cfg = dict(test_cfg)     # no data_format -> hdf5
        experiment_gui_object.cfg_initialized = True

    monkeypatch.setattr(gui_mod.InitializeRigGUI, 'setupUI', fake_setupUI)
    monkeypatch.setattr(QDialog, 'exec', lambda self: 0)
    monkeypatch.setattr(gui_mod.client, 'BaseClient', FakeClient)

    gui = gui_mod.ExperimentGUI(data_format='nwb')
    try:
        assert type(gui.data) is NWBData
    finally:
        gui.close()


def test_stimpack_nwb_command_still_works_and_says_what_to_use(monkeypatch):
    """Max's existing command. It now defers to the one GUI rather than a forked one."""
    import stimpack.experiment.gui as gui_mod

    seen = {}
    monkeypatch.setattr(gui_mod, 'main', lambda argv=None: seen.setdefault('argv', argv))
    monkeypatch.setattr(gui_mod.sys, 'argv', ['stimpack_nwb'])

    with pytest.warns(UserWarning, match="data_format: nwb"):
        gui_mod.main_nwb()

    assert seen['argv'] == ['--data-format', 'nwb']


def test_recording_over_an_existing_series_is_refused(nwb_experiment_gui, qapp):
    """NWB writes each series with 'w-', which refuses to clobber. The GUI has to catch a reused
    series number BEFORE that, or the run aborts mid-flight on an hdmf error instead of the user
    simply being told to pick another number."""
    gui = nwb_experiment_gui
    initialize(gui, 'reuse')
    add_subject(gui, 'fly1')
    select_protocol(gui)

    gui.record_button.click()                    # series 1
    gui.run_series_thread.wait(5000)
    qapp.processEvents()
    assert len(gui.data.get_series_files()) == 1

    gui.series_counter_input.setValue(1)         # back to a series that already exists
    gui.record_button.click()

    assert gui.status_label.text() == 'Select an unused series number'
    assert len(gui.data.get_series_files()) == 1    # nothing written, nothing clobbered
    assert len(gui.client.runs) == 1                # and no second run started


def test_a_backend_that_cannot_prepare_a_series_refuses_the_run_instead_of_dying(nwb_experiment_gui):
    """prepare_series runs inside a Qt slot, where an unhandled Python exception is fatal -- the
    GUI would disappear mid-experiment. Any failure there has to be reported and the run refused."""
    gui = nwb_experiment_gui
    initialize(gui, 'boom')
    add_subject(gui, 'fly1')
    select_protocol(gui)

    def explode():
        raise RuntimeError('disk is full')

    gui.data.prepare_series = explode
    with pytest.warns(UserWarning, match='Could not prepare storage'):
        gui.record_button.click()

    assert 'disk is full' in gui.status_label.text()
    assert gui.client.runs == []              # the run did not start


def test_writing_over_an_existing_series_says_so_in_stimpack_s_terms(nwb_experiment_gui, qapp):
    """Bypassing the GUI's series-number check (a labpack calling create_data_file itself, say)
    must still give a readable error rather than an HDF5-level one."""
    gui = nwb_experiment_gui
    initialize(gui, 'clash')
    add_subject(gui, 'fly1')
    gui.data.prepare_series()

    with pytest.raises(FileExistsError, match='already exists for subject fly1'):
        gui.data.prepare_series()


def test_the_current_subject_shows_on_the_main_tab_too(experiment_gui):
    """The Subject tab is not where you look while starting a run, and recording onto the wrong
    subject is a mistake worth making hard to miss."""
    initialize(experiment_gui, 'subject_on_main')
    add_subject(experiment_gui, 'fly_42')

    assert experiment_gui.current_subject_main_label.text() == 'fly_42'
    assert experiment_gui.existing_subject_input.currentText() == 'fly_42'


def test_selecting_an_existing_subject_updates_both_displays(nwb_experiment_gui):
    gui = nwb_experiment_gui
    initialize(gui, 'both_displays')
    for subject_id in ('flyA', 'flyB'):
        add_subject(gui, subject_id)
        gui.data.prepare_series()
        gui.data.advance_series_count()

    gui.update_existing_subject_input()
    labels = [gui.existing_subject_input.itemText(i) for i in range(gui.existing_subject_input.count())]
    gui.on_selected_existing_subject(labels.index('flyA'))

    assert gui.current_subject_main_label.text() == 'flyA'
    assert gui.existing_subject_input.currentText() == 'flyA'


def test_naming_no_data_module_is_not_worth_a_warning(test_cfg):
    """Using a built-in is the normal configuration. load_user_module warns for any unspecified
    module, so routing through it made every correct config print 'No user module specified for
    data' at launch -- a warning that suggests a mistake where there is none."""
    import warnings

    from stimpack.experiment.util import config_tools

    cfg = dict(test_cfg, module_paths={'protocol': []})
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        assert config_tools.load_user_data_class(cfg) is None
    assert [str(w.message) for w in caught] == []


def test_a_created_subject_is_acknowledged_on_both_backends(experiment_gui, nwb_experiment_gui):
    """The button and the field's styling both ask the backend whether this experiment has the
    typed subject. NWB read that from written series files only, so a subject created but not yet
    run did not exist as far as the GUI could tell: the button went on saying 'Create subject'
    for a subject that had just been created, and the field never showed it had become a
    selection."""
    for gui, name in [(experiment_gui, 'hdf5'), (nwb_experiment_gui, 'nwb')]:
        initialize(gui, f'subjects_{name}')
        gui.subject_id_input.setText('fly1')
        gui.refresh_subject_button()
        assert gui.subject_button.text() == 'Create subject', name

        add_subject(gui, 'fly1')

        assert gui.typed_subject_is_new() is False, name
        assert gui.subject_button.text() == 'Update subject', name
        assert 'fly1' in [gui.existing_subject_input.itemText(i)
                          for i in range(gui.existing_subject_input.count())], name


def test_switching_experiments_forgets_subjects_of_the_previous_one(nwb_experiment_gui, tmp_path):
    """Remembered subjects belong to the experiment they were created in, and must not follow the
    user into another."""
    gui = nwb_experiment_gui
    initialize(gui, 'first')
    add_subject(gui, 'fly1')
    assert gui.data.get_existing_subject_data()

    initialize(gui, 'second')

    assert gui.data.get_existing_subject_data() == []
