"""Unit tests for the GUI's server-message wiring (no live window).

Importing gui.py needs PyQt6 and the full client/render import chain, so these skip where those are
unavailable and run in CI. The cross-thread signal marshalling itself is Qt's job; here we check the
signal is declared and the slot updates the status label.
"""
import pytest

pytest.importorskip("PyQt6")
pytest.importorskip("numpy")
pytest.importorskip("yaml")
pytest.importorskip("platformdirs")

from stimpack.experiment.gui import ExperimentGUI

pytestmark = pytest.mark.unit


def test_server_message_signal_is_declared():
    # Needed so report_server_message (run thread) can marshal onto the GUI thread.
    assert 'server_message_signal' in ExperimentGUI.__dict__


class _Label:
    text = None
    def setText(self, t):
        self.text = t


class _Fake:
    """Duck-typed self so we don't need a live QWidget / QApplication."""
    def __init__(self):
        self.status_label = _Label()
        self._server_error_dialog_open = False


def _capture_alerts(monkeypatch):
    import stimpack.experiment.gui as gui_mod
    alerts = []
    monkeypatch.setattr(gui_mod, "open_message_window",
                        lambda title="", text="": alerts.append((title, text)))
    return alerts


def test_error_updates_label_and_pops_alert(monkeypatch):
    alerts = _capture_alerts(monkeypatch)   # mock so the modal dialog doesn't block the test
    fake = _Fake()
    ExperimentGUI.on_server_message_received(fake, "error", "boom")
    assert fake.status_label.text == "[server error] boom"
    assert alerts == [("Server error", "boom")]


def test_warning_updates_label_without_alert(monkeypatch):
    alerts = _capture_alerts(monkeypatch)
    fake = _Fake()
    ExperimentGUI.on_server_message_received(fake, "warning", "heads up")
    assert fake.status_label.text == "[server warning] heads up"
    assert alerts == []   # non-error messages don't pop a dialog


def test_error_dialog_does_not_stack(monkeypatch):
    # If an error arrives while a dialog is already open, update the label but don't stack a dialog.
    alerts = _capture_alerts(monkeypatch)
    fake = _Fake()
    fake._server_error_dialog_open = True
    ExperimentGUI.on_server_message_received(fake, "error", "second error")
    assert fake.status_label.text == "[server error] second error"
    assert alerts == []
