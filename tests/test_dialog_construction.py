"""
Regression test for the startup dialogs' double construction, fixed in 0.2.0.

Both InitializeExperimentGUI and InitializeRigGUI are created by their callers as
Cls(parent=dialog), and setupUI() then called super().__init__(parent) on the same object a
second time. Re-running a live QWidget's C++ constructor is undefined behaviour in PyQt: it
re-parents the widget and detaches it from the Python wrapper, so the widget is destroyed out
from under the object still referencing it.

Needs a QApplication but no display; runs offscreen.
"""
import os

import pytest

pytest.importorskip('PyQt6')


@pytest.fixture(scope='module')
def qapp():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class _StubExperimentGUI:
    """Only what setupUI reads off the parent GUI."""
    cfg = {}
    cfg_initialized = False


@pytest.mark.parametrize('dialog_name', ['InitializeRigGUI', 'InitializeExperimentGUI'])
def test_dialogs_survive_repeated_construction(qapp, dialog_name):
    """Opening a dialog is not once-per-process: a session initializes several experiments, and
    each one builds a fresh dialog. Before the fix this raised once the first was collected."""
    import gc
    from PyQt6.QtWidgets import QDialog
    import stimpack.experiment.gui as gui_mod

    cls = getattr(gui_mod, dialog_name)

    for _ in range(50):
        dialog = QDialog()
        dialog_ui = cls(parent=dialog)
        dialog_ui.setupUI(_StubExperimentGUI(), dialog)

        # The widget must still be usable -- i.e. its C++ object must still be alive and still
        # be the one the wrapper points at.
        assert dialog_ui.parent is dialog
        dialog_ui.isVisible()

        dialog_ui.close()
        dialog.close()
        del dialog_ui, dialog
        gc.collect()
        qapp.processEvents()


def test_setup_ui_does_not_reconstruct_the_widget(qapp):
    """The specific defect, stated directly: setupUI must not re-run QWidget's constructor on a
    widget the caller already constructed."""
    import ast
    import inspect
    import textwrap
    import stimpack.experiment.gui as gui_mod

    for dialog_name in ('InitializeRigGUI', 'InitializeExperimentGUI'):
        # Parsed rather than grepped: a comment explaining why the call is absent would otherwise
        # read as the call being present.
        tree = ast.parse(textwrap.dedent(inspect.getsource(getattr(gui_mod, dialog_name).setupUI)))
        calls_super_init = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute) and node.func.attr == '__init__'
            and isinstance(node.func.value, ast.Call)
            and getattr(node.func.value.func, 'id', None) == 'super'
            for node in ast.walk(tree))
        assert not calls_super_init, (
            f'{dialog_name}.setupUI re-initializes a widget its caller already constructed')
