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

    from stimpack.experiment.gui import STATUS_WINDOW_HEIGHT
    assert gui.status_scroll_area.height() == height_before
    assert gui.status_scroll_area.height() == STATUS_WINDOW_HEIGHT    # fixed, not merely unchanged
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
    grid = experiment_gui.protocol_control_grid
    index = grid.indexOf(experiment_gui.status_scroll_area)
    row, column, row_span, column_span = grid.getItemPosition(index)

    assert (row, column) == (0, 1)
    assert column_span == 3          # the whole width, so nothing shares its row


def test_status_text_is_selectable_so_an_error_can_be_copied(experiment_gui):
    from PyQt6.QtCore import Qt
    flags = experiment_gui.status_label.textInteractionFlags()
    assert flags & Qt.TextInteractionFlag.TextSelectableByMouse


def test_the_status_label_still_reads_back_as_text(experiment_gui):
    """Everything that sets status uses setText/text(); keeping a QLabel means those still work."""
    experiment_gui.status_label.setText('Ready')
    assert experiment_gui.status_label.text() == 'Ready'
