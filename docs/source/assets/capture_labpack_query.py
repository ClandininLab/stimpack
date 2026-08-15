#!/usr/bin/env python
"""Regenerate docs/source/assets/labpack_query.png: the startup config-selection dialog.

Renders offscreen (no window appears). The dialog is pointed at the public labpack-template so
the combo boxes show generic example content, and the directory line is overridden to a neutral
path for the screenshot.

    QT_QPA_PLATFORM=offscreen python capture_labpack_query.py <output.png>
"""
import os
import sys
import types

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_SCALE_FACTOR', '2')

from PyQt6.QtWidgets import QApplication, QDialog, QVBoxLayout

from stimpack.experiment.util import config_tools
from stimpack.experiment import gui as stimpack_gui

TEMPLATE_LABPACK = '/home/minseung/src/labpack-template'
DISPLAY_PATH = '/home/jdoe/my_labpack'

out = sys.argv[1] if len(sys.argv) > 1 else 'labpack_query.png'

# The dialog reads the configured labpack from the pointer file; show the template instead,
# without touching the user's configuration.
config_tools.get_labpack_directory = lambda: TEMPLATE_LABPACK

app = QApplication([])

dialog = QDialog()
dialog.setWindowTitle('Stimpack Config Selection')
dialog_ui = stimpack_gui.InitializeRigGUI(parent=dialog)
dialog_ui.setupUI(types.SimpleNamespace(), dialog, window_size=None)
layout = QVBoxLayout(dialog)
layout.addWidget(dialog_ui)

# Select the template's example config (index 0 is 'default') so the rig and data-format rows
# show the labpack-driven content the surrounding docs describe.
if dialog_ui.config_combobox.count() > 1:
    dialog_ui.config_combobox.setCurrentIndex(1)
    dialog_ui.on_selected_config()

dialog_ui.le_labpack_dir.setText(DISPLAY_PATH)

dialog.setMinimumWidth(430)
dialog.adjustSize()
dialog.show()
app.processEvents()
pixmap = dialog.grab()
pixmap.save(out)
print(f'wrote {out} ({pixmap.width()}x{pixmap.height()})')
