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
    assert gui.record_button.isEnabled()
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


def test_the_status_window_has_its_own_row_spanning_the_grid(experiment_gui):
    """Including column 0: the 'Status:' caption is in the row, so the message gets the width the
    caption column would otherwise reserve."""
    grid = experiment_gui.protocol_control_grid

    position = None
    for index in range(grid.count()):
        item = grid.itemAt(index)
        if item.layout() is not None and item.layout().indexOf(experiment_gui.status_scroll_area) >= 0:
            position = grid.getItemPosition(index)
    assert position is not None, 'the status window is not in the control grid'

    row, column, row_span, column_span = position
    assert (row, column) == (0, 0)
    assert column_span == 4          # every column, so nothing shares its row


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

    assert '(+18 paused)' in text
    assert text.split()[0] == '12', f'elapsed should exclude the pause, got {text!r}'
    estimate = lambda s: s.split('/')[1].split()[0]     # noqa: E731 - the denominator alone
    assert estimate(unpaused) == estimate(text) == '300', 'the estimate should not change'


def test_a_server_message_is_not_wiped_out_a_second_later(experiment_gui):
    """update_run_progress runs once a second and shares the status line with server messages, so
    it writes only when the pause state actually changes."""
    gui = experiment_gui
    _recording_run(gui)

    gui.status_label.setText('[server error] the screen fell over')
    gui.update_run_progress()
    gui.update_run_progress()
    assert gui.status_label.text() == '[server error] the screen fell over'
