"""GUI tests: drive the real ExperimentGUI headlessly — no human, no rig, no display.

These construct the actual window, select protocols, click actual buttons, and assert on the
resulting state, so GUI regressions (broken wiring, a button that no longer starts a run, a server
error that isn't surfaced) are caught automatically.
"""
import pytest
from PyQt6.QtCore import QThread

pytestmark = pytest.mark.gui


def select_protocol(gui, name):
    """Select a protocol in the dropdown the way a user would (index 0 is the placeholder)."""
    names = [c.__name__ for c in gui.available_protocols]
    idx = names.index(name) + 1
    gui.protocol_selection_combo_box.setCurrentIndex(idx)
    gui.on_selected_protocol_ID(idx)          # `activated` only fires on real user interaction
    return gui.protocol_object


# --- construction / discovery -------------------------------------------------------------------

def test_gui_constructs_with_expected_widgets(experiment_gui):
    gui = experiment_gui
    assert gui.cfg_initialized is True
    assert gui.view_button.isEnabled()
    assert not gui.record_button.isEnabled()                # no subject to record onto yet
    assert gui.status_label.text() == 'Select a protocol'   # nothing selected yet


def test_protocols_are_discovered(experiment_gui):
    names = [c.__name__ for c in experiment_gui.available_protocols]
    assert 'DriftingSquareGrating' in names
    assert 'ServerErrorDemo' in names
    assert 'BaseProtocol' not in names        # the base class itself is excluded


# --- selecting a protocol -----------------------------------------------------------------------

def test_selecting_a_protocol_populates_parameters(experiment_gui):
    gui = experiment_gui
    protocol = select_protocol(gui, 'DriftingSquareGrating')

    assert protocol.__class__.__name__ == 'DriftingSquareGrating'
    assert gui.status_label.text() == 'Ready'
    # the parameter grid is populated from the protocol's defaults
    assert 'num_epochs' in gui.run_parameter_input
    assert 'period' in gui.protocol_parameter_input
    assert protocol.run_parameters['num_epochs'] == 40


def test_editing_a_parameter_field_updates_the_protocol(experiment_gui):
    gui = experiment_gui
    protocol = select_protocol(gui, 'DriftingSquareGrating')

    gui.run_parameter_input['num_epochs'].setText('7')       # type into the field
    gui.update_parameters_from_fillable_fields(compute_epoch_parameters=False)

    assert gui.protocol_object.run_parameters['num_epochs'] == 7
    assert protocol is gui.protocol_object


# --- running: View / Record / Stop ---------------------------------------------------------------

def test_view_button_starts_a_run_without_saving(experiment_gui, qapp):
    gui = experiment_gui
    select_protocol(gui, 'DriftingSquareGrating')

    gui.view_button.click()                                   # a real button click
    gui.run_series_thread.wait(5000)                          # the run thread (FakeClient) finishes fast
    qapp.processEvents()

    assert gui.client.runs == [('DriftingSquareGrating', False)]   # started, save_metadata_flag=False


def test_run_without_selecting_a_protocol_is_refused(experiment_gui):
    gui = experiment_gui
    gui.view_button.click()

    assert gui.client.runs == []                              # nothing started
    assert gui.status_label.text() == 'Select a protocol'


def test_record_without_a_data_file_is_refused(experiment_gui, monkeypatch):
    import stimpack.experiment.gui as gui_mod
    gui = experiment_gui
    select_protocol(gui, 'DriftingSquareGrating')
    gui.data.current_subject = 'subj1'          # enough to enable the button, but there is no file
    gui.update_record_button_enabled()

    alerts = []
    monkeypatch.setattr(gui_mod.QMessageBox, 'exec', lambda self: alerts.append(self.text()))

    gui.record_button.click()

    assert gui.client.runs == []          # refuses to record with no experiment file / subject
    assert alerts and 'data file' in alerts[0]


def test_stop_button_asks_the_client_to_stop(experiment_gui):
    gui = experiment_gui
    select_protocol(gui, 'DriftingSquareGrating')

    stop_button = next(b for b in gui.findChildren(type(gui.view_button)) if b.text() == 'Stop')
    stop_button.click()

    assert gui.client.stop is True


def test_pause_button_toggles_pause_and_resume(experiment_gui):
    gui = experiment_gui
    select_protocol(gui, 'DriftingSquareGrating')
    gui.run_started(save_metadata_flag=False)      # Pause is disabled outside a run

    gui.pause_button.click()                       # "Pause" -> pauses
    assert gui.client.pause is True
    assert gui.pause_button.text() == 'Resume'

    gui.pause_button.click()                       # now "Resume" -> resumes
    assert gui.client.pause is False
    assert gui.pause_button.text() == 'Pause'


# --- error surfacing ----------------------------------------------------------------------------

def test_server_error_surfaces_in_the_gui(experiment_gui, monkeypatch, qapp):
    import stimpack.experiment.gui as gui_mod
    gui = experiment_gui

    alerts = []
    monkeypatch.setattr(gui_mod, 'open_message_window',
                        lambda title="", text="": alerts.append((title, text)))

    # the client pushes a server message exactly as BaseClient.report_server_message does
    gui.client.on_server_message('error', '[screen] load_stim blew up')
    qapp.processEvents()                            # deliver the queued cross-thread signal

    assert gui.status_label.text() == '[server error] [screen] load_stim blew up'
    assert alerts == [('Server error', '[screen] load_stim blew up')]


# --- shutdown -----------------------------------------------------------------------------------

def test_closing_the_gui_stops_a_running_series(experiment_gui, qapp):
    """A run thread that outlives the window delivers signals into a destroyed receiver.

    That is a real crash, not a tidiness issue: it is what made the whole suite segfault in one
    process, and it is reachable in production by closing the GUI mid-series.
    """
    gui = experiment_gui
    gui.protocol_object = None

    class _SlowThread(QThread):
        def run(self):
            self.msleep(200)

    gui.run_series_thread = _SlowThread()
    gui.run_series_thread.finished.connect(lambda: gui.run_finished(False))
    gui.run_series_thread.start()

    gui.close()                                   # must not hang, must not crash

    assert gui.run_series_thread is None
    assert gui.client.stop is True                # the run loop was asked to stop


def test_closing_the_gui_is_fine_with_no_run_thread(experiment_gui):
    experiment_gui.close()                        # must not raise


# --- the status window ----------------------------------------------------------------------------

def test_a_long_status_message_does_not_reshape_the_window(experiment_gui, qapp):
    """A QLabel's size hint grows with its text, so a long server warning -- one naming every
    registered function, say -- used to widen its column and reshape the whole window around it."""
    gui = experiment_gui
    qapp.processEvents()
    before = (gui.width(), gui.height())

    gui.status_label.setText(
        "no function 'set_dlpc_current' is registered on this server's root node (registered: "
        "['load_server_side_state_dependent_control', 'print_on_server', 'set_subject_state', "
        "'unload_server_side_state_dependent_control']); request was dropped. " * 3)
    qapp.processEvents()

    assert (gui.width(), gui.height()) == before


def test_the_status_window_scrolls_instead_of_growing(experiment_gui, qapp):
    gui = experiment_gui
    qapp.processEvents()
    height_before = gui.status_scroll_area.height()

    gui.status_label.setText('a very long message. ' * 200)
    qapp.processEvents()

    assert gui.status_scroll_area.height() == height_before
    # one text line, like the fields below it -- fixed, not merely unchanged
    assert gui.status_scroll_area.height() == (gui.status_label.fontMetrics().height()
                                               + 2 * gui.status_scroll_area.frameWidth())
    # the label itself is taller than the viewport, which is what there is to scroll through
    assert gui.status_label.height() >= gui.status_scroll_area.viewport().height()


def test_an_unbreakable_message_still_does_not_widen_the_window(experiment_gui, qapp):
    """Word wrap only helps where there are spaces. A long path, or a list of names run together,
    has nowhere to break -- so the size policy has to stop the content dictating the width too."""
    gui = experiment_gui
    qapp.processEvents()
    before = gui.width()

    gui.status_label.setText('/very/long/path/' + 'x' * 4000)
    qapp.processEvents()

    assert gui.width() == before


def test_the_status_window_sits_at_the_bottom_with_no_caption(experiment_gui):
    """Full width, below both grids, and uncaptioned -- the line only ever holds status, so the
    word 'Status:' restated the content in space the message itself could use."""
    gui = experiment_gui
    layout = gui.protocol_control_layout

    last = layout.itemAt(layout.count() - 1)
    assert last.widget() is gui.status_scroll_area, 'the status window is not the bottom row'

    # nothing shares its row, and no caption was left behind anywhere in the tab
    from PyQt6.QtWidgets import QLabel
    captions = [w.text() for w in gui.protocol_control_box.findChildren(QLabel)]
    assert 'Status:' not in captions


def test_the_status_window_is_one_line_tall(experiment_gui, qapp):
    """The row is for making a message wider, not the window taller. It should match the
    single-line fields below it."""
    gui = experiment_gui
    qapp.processEvents()
    assert gui.status_scroll_area.height() <= gui.elapsed_time_label.sizeHint().height() + 4


def test_the_whole_message_is_in_the_tooltip(experiment_gui):
    """One line means a long message has to be scrolled to read. Hovering shows all of it."""
    message = 'a long server warning. ' * 20
    experiment_gui.status_label.setText(message)
    assert experiment_gui.status_label.toolTip() == message


def test_status_text_is_selectable_so_an_error_can_be_copied(experiment_gui):
    from PyQt6.QtCore import Qt
    flags = experiment_gui.status_label.textInteractionFlags()
    assert flags & Qt.TextInteractionFlag.TextSelectableByMouse


def test_the_status_label_still_reads_back_as_text(experiment_gui):
    """Everything that sets status uses setText/text(); keeping a QLabel means those still work."""
    experiment_gui.status_label.setText('Ready')
    assert experiment_gui.status_label.text() == 'Ready'


# --- pause -----------------------------------------------------------------------------------

def _recording_run(gui, series=12):
    """Put the GUI in the state run_started leaves it in for a recorded series."""
    import time
    from stimpack.experiment.gui import Status

    gui.status = Status.RECORDING
    gui.data.series_count = series
    gui.protocol_object.est_run_time = 300.0       # normally set by prepare_run
    gui.status_label.setText(gui.run_status_text())
    gui.pause_button.setEnabled(True)
    gui._pause_state_shown = 'running'
    gui.run_start_time = time.time()


def test_resume_does_not_claim_a_recording_run_is_only_viewing(experiment_gui):
    """Resume used to hardcode 'Viewing...', so resuming a recorded series announced that it had
    stopped recording -- while self.status, and the recording, carried on unchanged. Believing the
    label means stopping and restarting a series that was fine."""
    gui = experiment_gui
    _recording_run(gui, series=12)
    assert gui.status_label.text() == 'Recording series 12'

    gui.pause_button.click()                       # Pause
    gui.client.paused_since = None                 # the epoch is still running: pause is pending
    gui.update_run_progress()
    assert gui.status_label.text() == 'Pausing after this epoch finishes...'

    gui.pause_button.click()                       # Resume
    assert gui.status_label.text() == 'Recording series 12'
    assert gui.pause_button.text() == 'Pause'


def test_the_status_line_separates_pausing_from_paused(experiment_gui):
    """Between pressing Pause and the epoch ending, the rig is still presenting and recording."""
    import time

    gui = experiment_gui
    _recording_run(gui)

    gui.client.pause_run()
    gui.update_run_progress()
    assert gui.status_label.text() == 'Pausing after this epoch finishes...'

    gui.client.paused_since = time.monotonic()     # the run loop reached the epoch boundary
    gui.update_run_progress()
    assert gui.status_label.text().startswith('Paused')


def test_elapsed_time_reports_paused_time_separately(experiment_gui):
    """est_run_time is a sum of stimulus durations, so folding pause into elapsed would make the
    ratio overstate progress. The pause is shown alongside instead."""
    import time

    gui = experiment_gui
    _recording_run(gui)
    gui.run_start_time = time.time() - 30          # 30 s ago

    gui.update_run_progress()
    assert '(+' not in gui.elapsed_time_label.text(), 'no pause yet, so nothing to report'
    unpaused = gui.elapsed_time_label.text()

    gui.client.paused_duration = 18.0              # 18 of those 30 s were spent paused
    gui.update_run_progress()
    text = gui.elapsed_time_label.text()

    assert '(+18)' in text
    assert text.split()[0] == '12', f'elapsed should exclude the pause, got {text!r}'
    estimate = lambda s: s.split('/')[1].split()[0]     # noqa: E731 - the denominator alone
    assert estimate(unpaused) == estimate(text) == '300s', 'the estimate should not change'


def test_a_server_message_is_not_wiped_out_a_second_later(experiment_gui):
    """update_run_progress runs once a second and shares the status line with server messages, so
    it writes only when the pause state actually changes."""
    gui = experiment_gui
    _recording_run(gui)

    gui.status_label.setText('[server error] the screen fell over')
    gui.update_run_progress()
    gui.update_run_progress()
    assert gui.status_label.text() == '[server error] the screen fell over'


def test_pause_is_disabled_until_a_run_is_in_progress(experiment_gui):
    """Pressing Pause in standby used to set the client's flag and relabel the button 'Resume',
    leaving the GUI claiming to be paused with nothing running."""
    gui = experiment_gui
    select_protocol(gui, 'DriftingSquareGrating')
    assert not gui.pause_button.isEnabled()

    gui.run_started(save_metadata_flag=False)
    assert gui.pause_button.isEnabled()

    gui.run_finished(save_metadata_flag=False)
    assert not gui.pause_button.isEnabled()
    assert gui.pause_button.text() == 'Pause'


def test_an_ensemble_holds_for_a_pause_requested_in_the_final_epoch(experiment_gui, monkeypatch):
    """The run loop's condition fails before the pause branch is reached on the last epoch, and the
    next start_run clears the flag -- so the next protocol used to start regardless."""
    gui = experiment_gui
    started = []
    monkeypatch.setattr(gui, 'run_ensemble_item', lambda save_metadata_flag=False: started.append(save_metadata_flag))

    gui.ensemble_running = True
    gui.client.pause = True                       # asked for during the final epoch
    gui.run_finished(save_metadata_flag=False)

    assert started == [], 'the next ensemble item started despite the pause'
    assert gui.ensemble_paused is True
    assert gui.pause_button.text() == 'Resume' and gui.pause_button.isEnabled()
    assert gui.status_label.text() == 'Paused before the next ensemble item'

    gui.pause_button.click()                      # Resume
    assert started == [False], 'resuming did not start the next ensemble item'
    assert gui.ensemble_paused is False


def test_an_ensemble_without_a_pause_runs_straight_on(experiment_gui, monkeypatch):
    gui = experiment_gui
    started = []
    monkeypatch.setattr(gui, 'run_ensemble_item', lambda save_metadata_flag=False: started.append(save_metadata_flag))

    gui.ensemble_running = True
    gui.client.pause = False
    gui.run_finished(save_metadata_flag=False)

    assert started == [False]
    assert gui.ensemble_paused is False


def test_stopping_a_held_ensemble_returns_to_standby(experiment_gui, monkeypatch):
    """The hold is not a run, so stop_run has no loop to stop and run_finished has already been."""
    gui = experiment_gui
    monkeypatch.setattr(gui, 'run_ensemble_item', lambda save_metadata_flag=False: None)

    gui.ensemble_running = True
    gui.client.pause = True
    gui.run_finished(save_metadata_flag=False)
    assert gui.ensemble_paused is True

    stop_button = next(b for b in gui.findChildren(type(gui.view_button)) if b.text() == 'Stop')
    stop_button.click()

    assert gui.ensemble_paused is False
    assert gui.ensemble_running is False
    assert not gui.pause_button.isEnabled()
    assert gui.status_label.text() == 'Ready'


def test_record_waits_for_a_subject_but_view_does_not(experiment_gui):
    """Recording without a subject is refused anyway -- but by a modal raised after the click,
    which is a worse way to find out than a button that is plainly not available yet."""
    gui = experiment_gui
    select_protocol(gui, 'DriftingSquareGrating')

    assert not gui.record_button.isEnabled()
    assert gui.view_button.isEnabled(), 'viewing needs no subject'

    gui.show_current_subject('subj1')            # every path that sets the subject goes through here
    assert not gui.record_button.isEnabled(), 'the label changed, but no subject was selected'

    gui.data.current_subject = 'subj1'
    gui.show_current_subject('subj1')
    assert gui.record_button.isEnabled()


def test_a_run_in_progress_keeps_record_disabled(experiment_gui):
    """update_record_button_enabled must not undo the lock run_started puts on the run buttons."""
    gui = experiment_gui
    select_protocol(gui, 'DriftingSquareGrating')
    gui.data.current_subject = 'subj1'

    gui.run_started(save_metadata_flag=False)
    assert not gui.record_button.isEnabled()

    gui.show_current_subject('subj1')            # e.g. the subject dropdown refreshing mid-run
    assert not gui.record_button.isEnabled(), 'a run is in progress'

    gui.run_finished(save_metadata_flag=False)
    assert gui.record_button.isEnabled()


def test_the_buttons_do_not_share_column_widths_with_the_readouts(experiment_gui):
    """One grid sized every column to its widest member, so 'Elapsed / Est:' set the width of the
    View button beneath it. Separate grids size independently."""
    gui = experiment_gui
    status_widgets = {gui.series_counter_input, gui.elapsed_time_label, gui.epoch_count_label}
    action_widgets = {gui.view_button, gui.record_button, gui.pause_button, gui.notes_edit}

    def widgets_of(grid):
        found = set()
        for index in range(grid.count()):
            item = grid.itemAt(index)
            if item.widget() is not None:
                found.add(item.widget())
            elif item.layout() is not None:
                for sub in range(item.layout().count()):
                    if item.layout().itemAt(sub).widget() is not None:
                        found.add(item.layout().itemAt(sub).widget())
        return found

    in_status = widgets_of(gui.protocol_status_grid)
    in_action = widgets_of(gui.protocol_action_grid)

    assert status_widgets <= in_status
    assert action_widgets <= in_action
    assert not (in_status & in_action), 'a widget is in both grids'


def test_the_protocol_dropdown_spans_the_preset_column(experiment_gui):
    grid = experiment_gui.protocol_selector_grid
    index = grid.indexOf(experiment_gui.protocol_selection_combo_box)
    _, _, _, column_span = grid.getItemPosition(index)
    assert column_span == 2


def test_creating_a_subject_enables_record(experiment_gui, tmp_path):
    """The end-to-end path a user actually takes, rather than poking current_subject directly."""
    gui = experiment_gui
    select_protocol(gui, 'DriftingSquareGrating')
    assert not gui.record_button.isEnabled()

    gui.data.experiment_file_name = 'record_button_test'
    gui.data.initialize_experiment_file()
    gui.subject_id_input.setText('subj_new')
    gui.on_created_subject()

    assert gui.data.current_subject == 'subj_new'
    assert gui.record_button.isEnabled()


def test_the_selector_dropdowns_get_the_widths_slack(experiment_gui, qapp):
    """Three equal columns gave a third of the row to a caption and a third to a button, leaving
    the dropdowns -- which hold the longest text on the tab -- elliding in the middle third."""
    gui = experiment_gui
    select_protocol(gui, 'DriftingSquareGrating')
    qapp.processEvents()

    grid = gui.protocol_selector_grid
    assert grid.columnStretch(1) > grid.columnStretch(0)
    assert grid.columnStretch(1) > grid.columnStretch(2)

    # and it reaches the rendered geometry, not just the stretch factors: widening the window has
    # to widen the dropdowns rather than the caption and the button beside them. Asserted as a
    # response to resizing, not as a fraction of the width, so it holds at any window size.
    save_button = next(b for b in gui.findChildren(type(gui.view_button)) if b.text() == 'Save preset')
    before = {w: w.width() for w in (gui.parameter_preset_comboBox,
                                     gui.protocol_selection_combo_box, save_button)}

    extra = 300
    gui.resize(gui.width() + extra, gui.height())
    qapp.processEvents()

    grew = {w: w.width() - before[w] for w in before}
    assert grew[gui.parameter_preset_comboBox] > 0.9 * extra, 'the preset dropdown did not take the slack'
    assert grew[gui.protocol_selection_combo_box] > 0.9 * extra
    assert grew[save_button] < 10, 'the button absorbed width the dropdowns should have had'


def test_the_ensemble_selector_dropdowns_get_the_slack_too(experiment_gui, qapp):
    """The Ensemble tab has the same protocol/preset rows and had the same three equal columns."""
    gui = experiment_gui
    gui.tabs.setCurrentWidget(gui.ensemble_tab)
    qapp.processEvents()

    grid = gui.ensemble_protocol_selector_grid
    assert grid.columnStretch(1) > grid.columnStretch(0)
    assert grid.columnStretch(1) > grid.columnStretch(2)

    append_button = next(b for b in gui.findChildren(type(gui.view_button)) if b.text() == 'Append')
    before = {w: w.width() for w in (gui.ensemble_parameter_preset_comboBox,
                                     gui.ensemble_protocol_selection_combo_box, append_button)}

    extra = 300
    gui.resize(gui.width() + extra, gui.height())
    qapp.processEvents()

    grew = {w: w.width() - before[w] for w in before}
    assert grew[gui.ensemble_parameter_preset_comboBox] > 0.9 * extra
    assert grew[gui.ensemble_protocol_selection_combo_box] > 0.9 * extra
    assert grew[append_button] < 10


def test_both_tabs_call_it_param_preset(experiment_gui):
    from PyQt6.QtWidgets import QLabel
    captions = [w.text() for w in experiment_gui.findChildren(QLabel)]
    assert captions.count('Param preset:') == 2      # Main and Ensemble
    assert 'Parameter preset:' not in captions


# --- the Subject tab ------------------------------------------------------------------------------

def test_subject_tab_labels_are_left_aligned(experiment_gui):
    from PyQt6.QtCore import Qt
    alignment = experiment_gui.data_form.labelAlignment()
    assert alignment & Qt.AlignmentFlag.AlignLeft
    assert not (alignment & Qt.AlignmentFlag.AlignHCenter)


def test_the_subject_tab_names_the_current_subject_once(experiment_gui):
    """It used to be three stacked rows -- a dropdown, a read-only label and the ID field -- all
    showing the same string once a subject was loaded."""
    from PyQt6.QtWidgets import QLabel

    gui = experiment_gui
    captions = [w.text() for w in gui.data_tab.findChildren(QLabel)]
    assert captions.count('Current subject:') == 1
    assert 'Load existing subject' not in captions        # the dropdown IS the current subject now
    assert not hasattr(gui, 'current_subject_display')    # the read-only duplicate is gone


def test_the_subject_dropdown_is_blank_when_no_subject_is_selected(experiment_gui):
    """Left on index 0 it would show whichever subject is first as though it were selected -- and
    Record keys off whether there actually is one."""
    gui = experiment_gui
    gui.existing_subject_input.clear()
    gui.existing_subject_input.addItems(['flyA', 'flyB'])
    gui.data.current_subject = None

    gui.show_current_subject('')

    assert gui.existing_subject_input.currentIndex() == -1
    assert gui.existing_subject_input.currentText() == ''
    assert not gui.record_button.isEnabled()
