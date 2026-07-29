#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Jun 21 10:51:42 2018

@author: mhturner
"""
import argparse
from datetime import datetime
import os
import sys
import time
import traceback
from enum import Enum
import warnings
from typing import Any
import yaml

from PyQt6.QtWidgets import (QPushButton, QWidget, QLabel, QTextEdit, QGridLayout, QApplication,
                             QComboBox, QLineEdit, QFormLayout, QDialog, QFileDialog, QInputDialog,
                             QMessageBox, QCheckBox, QSpinBox, QTabWidget, QVBoxLayout, QHBoxLayout, QFrame,
                             QScrollArea, QListWidget, QSizePolicy, QAbstractItemView)
import PyQt6.QtCore as QtCore
from PyQt6.QtCore import QThread, QTimer, Qt, pyqtSignal, QUrl
import PyQt6.QtGui as QtGui

from stimpack.experiment.util import config_tools, check_labpack
from stimpack.experiment import protocol, data, client

from stimpack.util import get_all_subclasses, ICON_PATH, ROOT_DIR
from stimpack.util import open_message_window

Status = Enum('Status', ['STANDBY', 'RECORDING', 'VIEWING'])

class ParseError(Exception):
    def __init__(self, message):
        super().__init__()
        self.message = message

class _StatusLabel(QLabel):
    """
    The status line, which mirrors whatever it is showing into its tooltip.

    The window is one text line tall, so a long message -- a server warning listing every
    registered function -- has to be scrolled to be read. Hovering shows all of it at once,
    which is usually what someone wants when a warning goes by.

    A QLabel rather than a read-only text box so that setText/text() keep working at the several
    dozen call sites that set status.
    """
    def setText(self, text):
        super().setText(text)
        self.setToolTip(text)


# How many characters a protocol/preset dropdown asks to fit. Qt6 sizes a combo to its longest
# entry the first time it is shown, so one long protocol name -- a labpack with several protocol
# modules appends the module to each -- set the width of the box, the width of the tab, and with it
# the whole window. Measured: one 70-character entry took a combo from 102 px to 484. Capping what
# it asks for lets the name elide instead; the box still fills its column, which has the stretch.
DROPDOWN_CHARACTERS = 24


def cap_dropdown_width(combo_box, characters=DROPDOWN_CHARACTERS):
    """Stop a long entry in `combo_box` dictating the width of everything around it."""
    combo_box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo_box.setMinimumContentsLength(characters)
    return combo_box


class ExperimentGUI(QWidget):

    # Emitted when the server pushes a message. report_server_message runs on the run thread, so this
    # signal (a queued cross-thread connection) marshals the update onto the GUI thread.
    server_message_signal = pyqtSignal(str, str)
    # A failure to write the data file, raised on the run thread and surfaced on the GUI thread.
    data_error_signal = pyqtSignal(str)

    def __init__(self, data_format=None):
        """
        :param data_format: overrides the config's data_format for this session ('hdf5' or 'nwb').
                            None means use whatever the chosen config says.
        """
        super().__init__()
        # set GUI icon
        self.setWindowIcon(QtGui.QIcon(ICON_PATH))

        self.data_format_override = data_format

        self.note_text = ''
        self.run_parameter_input = {}
        self.protocol_parameter_input = {}
        self.mid_parameter_edit = False
        self.status = Status.STANDBY
        # Last pause state written to the status line, so update_run_progress can write only on a
        # change and leave server messages alone the rest of the time.
        self._pause_state_shown = 'running'

        # user input to select configuration file and rig name
        # sets self.cfg
        self.cfg_initialized = False
        self.cfg: dict[str, Any] = {}
        init_gui_size = None
        dialog = QDialog()
        dialog.setWindowIcon(QtGui.QIcon(ICON_PATH))
        dialog.setWindowTitle('Stimpack Config Selection')
        dialog_ui = InitializeRigGUI(parent=dialog)
        dialog_ui.setupUI(self, dialog, window_size=init_gui_size)
        dialog.exec()

        # No config file selected, exit
        if not self.cfg_initialized:
            print('!!! No configuration selected. Exiting !!!')
            sys.exit()

        print('# # # Loading protocol, data and client modules # # #')

        # Load protocol module(s). Multiple user-specific protocol modules can be loaded.
        self.protocol_modules = config_tools.load_user_module(self.cfg, 
                                                              module_name='protocol', 
                                                              allow_multiple=True, 
                                                              distinct_module_names=True)
        if len(self.protocol_modules) == 0:  # use the built-in
            print('!!! Using builtin protocol module. To use user defined module, you must point to that module in your config file !!!')
            example_protocol_path = os.path.join(ROOT_DIR, 'experiment', 'example_protocol.py')
            self.protocol_modules = [config_tools.load_user_module_from_path(example_protocol_path, 'protocol_examples')]

        # Get parameter presets directory
        self.parameter_preset_directory = config_tools.get_parameter_preset_directory(self.cfg)

        # start a protocol object
        self.protocol_object =  protocol.BaseProtocol(self.cfg)
        self.available_protocols =  [x for x in get_all_subclasses(protocol.BaseProtocol) if x.__name__ not in ['BaseProtocol', 'SharedPixMapProtocol']]

        # start a data object
        user_data_module_list = config_tools.load_user_module(self.cfg, 'data')
        if user_data_module_list:
            self.data = user_data_module_list[0].Data(self.cfg)
        else:  # use a built-in, chosen by the config's data_format (default hdf5, or nwb)
            if self.data_format_override is not None:
                self.cfg['data_format'] = self.data_format_override
            data_class = config_tools.get_builtin_data_class(self.cfg)
            print('!!! Using builtin {} module ({}). To use user defined module, you must point to that module in your config file !!!'.format('data', data_class.__name__))
            self.data = data_class(self.cfg)

         # start a client
        user_client_module_list = config_tools.load_user_module(self.cfg, 'client')
        if user_client_module_list:
            self.client = user_client_module_list[0].Client(self.cfg)
        else:  # use the built-in
            print('!!! Using builtin {} module. To use user defined module, you must point to that module in your config file !!!'.format('client'))
            self.client = client.BaseClient(self.cfg)

        # Route server-pushed messages to the GUI thread (see server_message_signal above).
        self.server_message_signal.connect(self.on_server_message_received)
        self.client.on_server_message = self.server_message_signal.emit
        self.data_error_signal.connect(self.on_data_error_received)
        self.client.on_data_error = self.data_error_signal.emit
        self._server_error_dialog_open = False  # guards against stacking error dialogs

        self.current_ensemble_idx = 0

        self.ensemble_running = False
        # An ensemble held between items because Pause was pressed during the final trial of one of
        # them, and the flag needed to resume it. See run_finished.
        self.ensemble_paused = False
        self.ensemble_save_metadata_flag = False
        # Whether the protocol/preset selectors and parameter fields accept edits. Off mid-ensemble.
        self.parameter_editing_enabled = True
        # When the ensemble began, for the Ensemble tab's elapsed readout. None when none is running.
        self.ensemble_start_time = None

        print('# # # # # # # # # # # # # # # #')
        
        self.initUI()

    def initUI(self):
        # Name the storage backend in the title when it is not the default, so it is obvious at a
        # glance which format a running experiment is being written in. Taken from the object in
        # use rather than from the config's data_format, which a labpack's own data module ignores.
        format_note = '' if type(self.data) is data.BaseData else f'{type(self.data).__name__}, '
        self.setWindowTitle(f"Stimpack Experiment ({format_note}{self.cfg['current_cfg_name'].split('.')[0]}: {self.cfg['current_rig_name']})")

        # # # TAB 1: MAIN controls, for selecting / playing stimuli

        # Protocol tab layout
        self.protocol_selector_box = QWidget()
        self.protocol_selector_box.setSizePolicy(QSizePolicy(QSizePolicy.Policy.MinimumExpanding,
                                                             QSizePolicy.Policy.Fixed))
        self.protocol_selector_grid = QGridLayout()
        self.protocol_selector_box.setLayout(self.protocol_selector_grid)
        # Give the whole row's slack to the dropdowns. Left at stretch 0 the grid divides itself
        # into three equal columns, so a third of the width went to the caption and another third
        # to a button, leaving the dropdowns -- which hold the longest text on the tab, a protocol
        # name plus its module -- elliding in the middle third.
        self.protocol_selector_grid.setColumnStretch(0, 0)   # captions: as wide as their text
        self.protocol_selector_grid.setColumnStretch(1, 1)   # dropdowns: everything left over
        self.protocol_selector_grid.setColumnStretch(2, 0)   # Save preset: as wide as the button

        self.parameters_box = QWidget()
        self.parameters_box.setSizePolicy(QSizePolicy(QSizePolicy.Policy.MinimumExpanding,
                                                    QSizePolicy.Policy.MinimumExpanding))
        self.parameters_grid = QGridLayout()
        self.parameters_grid.setSpacing(10)
        self.parameters_box.setLayout(self.parameters_grid)
        self.parameters_scroll_area = QScrollArea()
        self.parameters_scroll_area.setWidget(self.parameters_box)
        self.parameters_scroll_area.setWidgetResizable(True)

        self.protocol_control_box = QWidget()
        self.protocol_control_box.setSizePolicy(QSizePolicy(QSizePolicy.Policy.MinimumExpanding,
                                                            QSizePolicy.Policy.Fixed))
        # Two grids, stacked, rather than one. A QGridLayout sizes each column to its widest
        # member, so while the readouts and the buttons shared a grid, the width of 'Elapsed /
        # Est:' set the width of the View button under it and every column was a compromise
        # between a label and a button. Separate layouts size independently.
        self.protocol_control_layout = QVBoxLayout()
        self.protocol_control_box.setLayout(self.protocol_control_layout)
        self.protocol_status_grid = QGridLayout()      # status line and run readouts
        self.protocol_action_grid = QGridLayout()      # View / Record / Pause / Stop, and notes
        self.protocol_control_layout.addLayout(self.protocol_status_grid)
        self.protocol_control_layout.addLayout(self.protocol_action_grid)

        # Splitting the grids is not enough on its own: with every column at stretch 0 a grid
        # shares its slack out equally, so both ended up with four equal columns and the buttons
        # still lined up under the readouts. Give the slack to the value columns only, so the
        # captions take the width of their text and the buttons divide the row on their own terms.
        for caption_column in (0, 2):
            self.protocol_status_grid.setColumnStretch(caption_column, 0)
        for value_column in (1, 3):
            self.protocol_status_grid.setColumnStretch(value_column, 1)
        for button_column in range(4):
            self.protocol_action_grid.setColumnStretch(button_column, 1)

        # Captions sized to their text sit right against the field they name. Widen the gap
        # between columns, and widen it again before the second caption ('Subject:', 'Trials run:')
        # so the two pairs on a row read as two pairs rather than as four things in a line.
        self.protocol_status_grid.setHorizontalSpacing(10)
        self.protocol_status_grid.setColumnMinimumWidth(2, 24)

        self.protocol_tab = QWidget()
        self.protocol_tab_layout = QVBoxLayout()
        self.protocol_tab_layout.addWidget(self.protocol_selector_box)
        self.protocol_tab_layout.addWidget(self.parameters_scroll_area)
        self.protocol_tab_layout.addWidget(self.protocol_control_box)
        self.protocol_tab.setLayout(self.protocol_tab_layout)

        # Protocol ID drop-down:
        self.protocol_selection_combo_box = QComboBox(self)
        cap_dropdown_width(self.protocol_selection_combo_box)
        self.protocol_selection_combo_box.addItem("(select a protocol to run)")
        for sub_class in self.available_protocols:
            if len(self.protocol_modules) > 1:
                protocol_module_label = os.path.basename(sys.modules[sub_class.__module__].__file__)[:-3]
                self.protocol_selection_combo_box.addItem(sub_class.__name__ + ' (' + protocol_module_label + ')' )
            else:
                self.protocol_selection_combo_box.addItem(sub_class.__name__)
        protocol_label = QLabel('Protocol:')
        self.protocol_selection_combo_box.activated.connect(self.on_selected_protocol_ID)
        self.protocol_selector_grid.addWidget(protocol_label, 1, 0)
        # Spans the preset column too: protocol names are the longest text in this box (a labpack
        # with several protocol modules appends the module name to each), and the dropdown was
        # elliding them into one column while the column beside it held a button.
        self.protocol_selector_grid.addWidget(self.protocol_selection_combo_box, 1, 1, 1, 2)

        # Parameter preset drop-down:
        parameter_preset_label = QLabel('Param preset:')
        self.protocol_selector_grid.addWidget(parameter_preset_label, 2, 0)
        self.parameter_preset_comboBox = None
        self.update_parameter_preset_selector()

        # Save parameter preset button:
        save_preset_button = QPushButton("Save preset", self)
        save_preset_button.clicked.connect(self.on_pressed_button)
        self.protocol_selector_grid.addWidget(save_preset_button, 2, 2)

        # Status window: its own row at the bottom of the tab, below the buttons.
        #
        # No caption. 'Status:' was one, but the line only ever holds status -- 'Ready', 'Recording
        # series 12', a server error -- so the word was restating what the content already said,
        # in space the message itself could use.
        #
        # Inside a scroll area rather than bare, because a QLabel's size hint grows with its text:
        # a long message -- a server warning naming every registered function, say -- used to widen
        # its column and reshape the whole window. The label wraps to the viewport instead, and the
        # area scrolls, so the message can be as long as it likes without moving anything.
        self.status_label = _StatusLabel('Select a protocol')
        self.status_label.setWordWrap(True)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        # Selectable so an error can be copied out of the GUI rather than retyped from a screenshot.
        self.status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.status_scroll_area = QScrollArea()
        self.status_scroll_area.setWidget(self.status_label)
        self.status_scroll_area.setWidgetResizable(True)      # wrap to the viewport, not the text
        self.status_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.status_scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        # One text line tall, like the fields below it -- the row is for making the message wider,
        # not the window taller. Anything longer scrolls, and the whole text is in the tooltip.
        # Derived from the font rather than a pixel count, so it still fits at another font size.
        self.status_scroll_area.setFixedHeight(self.status_label.fontMetrics().height()
                                               + 2 * self.status_scroll_area.frameWidth())
        # No size policy needed: a scroll area's size hint comes from its own frame, not from the
        # widget inside it, so the message length cannot reach the window width from here. Measured
        # -- a 5000-character label gives the same hint as an empty one.
        #
        # Added to the window's layout, below the tab widget, rather than to a tab: a server error
        # can arrive while you are on the Subject or File tab, and the run aborts whichever tab you
        # happen to be looking at. Inside a tab, the only notice of it would be on one you are not
        # looking at. See the end of initUI, where the window layout is assembled.

        # Current series counter
        new_label = QLabel('Series #')
        self.protocol_status_grid.addWidget(new_label, 0, 0)
        self.series_counter_input = QSpinBox()
        self.series_counter_input.setMinimum(1)
        self.series_counter_input.setMaximum(1000)
        self.series_counter_input.setValue(1)
        self.series_counter_input.valueChanged.connect(self.on_entered_series_count)
        self.protocol_status_grid.addWidget(self.series_counter_input, 0, 1)

        # Current subject, next to the series counter: together they say what the next run will
        # be recorded as. Otherwise the only place to see the subject is the Subject tab, and
        # recording onto the wrong one is a mistake worth making hard.
        new_label = QLabel('Subject:')
        self.protocol_status_grid.addWidget(new_label, 0, 2)
        self.current_subject_main_label = QLabel()
        self.current_subject_main_label.setFrameShadow(QFrame.Shadow(1))
        self.protocol_status_grid.addWidget(self.current_subject_main_label, 0, 3)

        # Elapsed time and trial count share a row: both say how far through the run we are, and
        # neither needs a third of the window to show "0 / 240".
        new_label = QLabel('Elapsed / Est:')
        self.protocol_status_grid.addWidget(new_label, 1, 0)
        self.elapsed_time_label = QLabel()
        self.elapsed_time_label.setFrameShadow(QFrame.Shadow(1))
        self.protocol_status_grid.addWidget(self.elapsed_time_label, 1, 1)
        self.elapsed_time_label.setText('')

        new_label = QLabel('Trials run:')
        self.protocol_status_grid.addWidget(new_label, 1, 2)
        self.trial_count_label = QLabel()
        self.trial_count_label.setFrameShadow(QFrame.Shadow(1))
        self.protocol_status_grid.addWidget(self.trial_count_label, 1, 3)
        self.trial_count_label.setText('')

        # What this trial drew: the parameters that vary from trial to trial, at their values for
        # the trial running now. Those values are chosen on the client and sent to the server,
        # which prints them; until now the GUI never showed them, so the only way to see what was
        # on screen was the server's terminal.
        #
        # Same treatment as the status line, and for the same reason: a protocol varying several
        # parameters produces a long line, and a bare QLabel's size hint grows with its text until
        # it reshapes the window. One line tall, scrolls if longer, whole text in the tooltip.
        self.epoch_parameters_label = _StatusLabel('')
        self.epoch_parameters_label.setWordWrap(True)
        self.epoch_parameters_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.epoch_parameters_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.epoch_parameters_scroll_area = QScrollArea()
        self.epoch_parameters_scroll_area.setWidget(self.epoch_parameters_label)
        self.epoch_parameters_scroll_area.setWidgetResizable(True)
        self.epoch_parameters_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.epoch_parameters_scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.epoch_parameters_scroll_area.setFixedHeight(
            self.epoch_parameters_label.fontMetrics().height()
            + 2 * self.epoch_parameters_scroll_area.frameWidth())

        self.protocol_status_grid.addWidget(QLabel('This trial:'), 2, 0)
        self.protocol_status_grid.addWidget(self.epoch_parameters_scroll_area, 2, 1, 1, 3)

        # Elapsed timer for protocol
        self.progress_timer = QTimer()
        self.progress_timer.setSingleShot(False)
        self.progress_timer.setInterval(1000)
        self.progress_timer.timeout.connect(self.update_run_progress)

        # View button:
        self.view_button = QPushButton("View", self)
        self.view_button.clicked.connect(self.on_pressed_button)
        self.protocol_action_grid.addWidget(self.view_button, 0, 0)

        # Record button. Disabled until a subject is selected: recording without one is refused
        # anyway, but by a modal raised after the click, which is a worse way to learn it.
        self.record_button = QPushButton("Record", self)
        self.record_button.setEnabled(False)
        self.record_button.clicked.connect(self.on_pressed_button)
        self.protocol_action_grid.addWidget(self.record_button, 0, 1)

        # Pause/resume button. Disabled until a run is in progress: pressing it in standby used to
        # set the client's pause flag and relabel itself 'Resume' with nothing running, so the GUI
        # sat there claiming to be paused.
        self.pause_button = QPushButton("Pause", self)
        self.pause_button.setEnabled(False)
        self.pause_button.clicked.connect(self.on_pressed_button)
        self.protocol_action_grid.addWidget(self.pause_button, 0, 2)

        # Stop button:
        self.stop_button = QPushButton("Stop", self)
        self.stop_button.clicked.connect(self.on_pressed_button)
        self.protocol_action_grid.addWidget(self.stop_button, 0, 3)

        # Enter note button. The box to type in appears when it is pressed, rather than sitting
        # in the window: a note is written a few times a session, and an always-present field was
        # spending a permanent row on something almost always empty.
        self.note_button = QPushButton("Note", self)
        self.note_button.clicked.connect(self.on_pressed_button)


        # # # TAB 2: ENSEMBLE tab # # #

        # Ensemble tab layout

        self.ensemble_selector_box = QWidget()
        self.ensemble_selector_box.setSizePolicy(QSizePolicy(QSizePolicy.Policy.MinimumExpanding,
                                                             QSizePolicy.Policy.Fixed))
        self.ensemble_protocol_selector_grid = QGridLayout()
        self.ensemble_selector_box.setLayout(self.ensemble_protocol_selector_grid)
        # Same as the Main tab's selector: the slack goes to the dropdowns, not to the caption
        # beside them or the button next to the preset.
        self.ensemble_protocol_selector_grid.setColumnStretch(0, 0)   # captions
        self.ensemble_protocol_selector_grid.setColumnStretch(1, 1)   # dropdowns
        self.ensemble_protocol_selector_grid.setColumnStretch(2, 0)   # Append button

        self.ensemble_list_box = QWidget()
        self.ensemble_list_box.setSizePolicy(QSizePolicy(QSizePolicy.Policy.MinimumExpanding,
                                                         QSizePolicy.Policy.MinimumExpanding))
        self.ensemble_list_grid = QGridLayout()
        self.ensemble_list_box.setLayout(self.ensemble_list_grid)

        # The Ensemble tab's own readouts and run buttons. Its own, rather than the Main tab's
        # section moved across: the two tabs run different things, and the numbers that describe
        # them are different numbers. One shared section meant buttons that changed meaning with
        # the tab, and readouts ('Elapsed / Est', 'Trials run') that only ever described a series.
        self.ensemble_control_box = QWidget()
        self.ensemble_control_box.setSizePolicy(QSizePolicy(QSizePolicy.Policy.MinimumExpanding,
                                                            QSizePolicy.Policy.Fixed))
        self.ensemble_control_layout = QVBoxLayout()
        self.ensemble_control_box.setLayout(self.ensemble_control_layout)
        self.ensemble_status_grid = QGridLayout()      # what the ensemble is doing
        self.ensemble_action_grid = QGridLayout()      # the buttons that act on it
        self.ensemble_control_layout.addLayout(self.ensemble_status_grid)
        self.ensemble_control_layout.addLayout(self.ensemble_action_grid)
        for caption_column in (0, 2):
            self.ensemble_status_grid.setColumnStretch(caption_column, 0)
        for value_column in (1, 3):
            self.ensemble_status_grid.setColumnStretch(value_column, 1)
        for button_column in range(4):
            self.ensemble_action_grid.setColumnStretch(button_column, 1)
        self.ensemble_status_grid.setHorizontalSpacing(10)
        self.ensemble_status_grid.setColumnMinimumWidth(2, 24)

        self.ensemble_tab = QWidget()
        self.ensemble_tab_layout = QVBoxLayout()
        self.ensemble_tab_layout.addWidget(self.ensemble_selector_box)
        self.ensemble_tab_layout.addWidget(self.ensemble_list_box)
        self.ensemble_tab_layout.addWidget(self.ensemble_control_box)
        self.ensemble_tab.setLayout(self.ensemble_tab_layout)

        # Protocol ID drop-down:
        self.ensemble_protocol_selection_combo_box = QComboBox(self)
        cap_dropdown_width(self.ensemble_protocol_selection_combo_box)
        self.ensemble_protocol_selection_combo_box.addItem("(select a protocol to add to ensemble)")
        for sub_class in self.available_protocols:
            self.ensemble_protocol_selection_combo_box.addItem(sub_class.__name__)
        protocol_label = QLabel('Protocol:')
        self.ensemble_protocol_selection_combo_box.textActivated.connect(self.on_selected_ensemble_protocol_ID)
        self.ensemble_protocol_selector_grid.addWidget(protocol_label, 0, 0)
        self.ensemble_protocol_selector_grid.addWidget(self.ensemble_protocol_selection_combo_box, 0, 1, 1, 2)

        # Parameter preset drop-down:
        parameter_preset_label = QLabel('Param preset:')
        self.ensemble_parameter_preset_comboBox = QComboBox(self)
        cap_dropdown_width(self.ensemble_parameter_preset_comboBox)
        self.ensemble_parameter_preset_comboBox.addItem("Default")
        self.ensemble_protocol_selector_grid.addWidget(parameter_preset_label, 1, 0)
        self.ensemble_protocol_selector_grid.addWidget(self.ensemble_parameter_preset_comboBox, 1, 1)

        # Ensemble append button:
        self.ensemble_append_button = QPushButton("Append", self)
        self.ensemble_append_button.clicked.connect(self.on_pressed_button_ensemble)
        self.ensemble_protocol_selector_grid.addWidget(self.ensemble_append_button, 1, 2)

        # Ensemble preset file label
        self.ensemble_file_label = QLabel('No ensemble file loaded')
        self.ensemble_file_label.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Fixed,
                                                           QSizePolicy.Policy.Fixed))
        self.ensemble_list_grid.addWidget(self.ensemble_file_label, 0, 0)

        # Ensemble list
        self.ensemble_list = EnsembleList()
        self.ensemble_list.row_moved_signal.connect(self.on_reordered_ensemble_list)
        self.ensemble_list_scroll_area = QScrollArea()
        self.ensemble_list_scroll_area.setWidget(self.ensemble_list)
        self.ensemble_list_scroll_area.setWidgetResizable(True)
        self.ensemble_list_grid.addWidget(self.ensemble_list_scroll_area, 1, 0, 5, 1)
        
        # Load ensemble preset file button
        self.ensemble_load_preset_button = QPushButton('Load ensemble')
        self.ensemble_load_preset_button.clicked.connect(self.on_pressed_button_ensemble)
        self.ensemble_list_grid.addWidget(self.ensemble_load_preset_button, 1, 1)

        # Save ensemble preset file button
        self.ensemble_save_preset_button = QPushButton('Save ensemble')
        self.ensemble_save_preset_button.clicked.connect(self.on_pressed_button_ensemble)
        self.ensemble_list_grid.addWidget(self.ensemble_save_preset_button, 2, 1)

        # Remove ensemble item button
        self.ensemble_remove_item_button = QPushButton('Remove item')
        self.ensemble_remove_item_button.clicked.connect(self.on_pressed_button_ensemble)
        self.ensemble_list_grid.addWidget(self.ensemble_remove_item_button, 3, 1)

        # Clear ensemble button
        self.ensemble_clear_button = QPushButton('Clear')
        self.ensemble_clear_button.clicked.connect(self.on_pressed_button_ensemble)
        self.ensemble_list_grid.addWidget(self.ensemble_clear_button, 4, 1)

        # Ensemble readouts. 'Protocols run' is the ensemble's equivalent of the Main tab's
        # 'Trials run'; elapsed is measured from the start of the ensemble rather than of the item
        # in progress. No estimate to measure it against: that would mean precomputing every
        # item's trial parameters up front, which is what makes est_run_time available for a
        # single protocol.
        # Same order as the Main tab's readout row -- elapsed on the left, the count on the right.
        # Switching tabs mid-run should not move the numbers around under the eye.
        self.ensemble_status_grid.addWidget(QLabel('Elapsed:'), 0, 0)
        self.ensemble_elapsed_label = QLabel()
        self.ensemble_elapsed_label.setFrameShadow(QFrame.Shadow(1))
        self.ensemble_status_grid.addWidget(self.ensemble_elapsed_label, 0, 1)

        self.ensemble_status_grid.addWidget(QLabel('Protocols run:'), 0, 2)
        self.ensemble_progress_label = QLabel()
        self.ensemble_progress_label.setFrameShadow(QFrame.Shadow(1))
        self.ensemble_status_grid.addWidget(self.ensemble_progress_label, 0, 3)

        # Ensemble run buttons. Separate widgets from the Main tab's, so each tab's buttons act on
        # that tab's subject and nothing has to be relabelled or routed by label.
        self.ensemble_view_button = QPushButton("View ensemble", self)
        self.ensemble_view_button.clicked.connect(self.on_pressed_button_ensemble)
        self.ensemble_action_grid.addWidget(self.ensemble_view_button, 0, 0)

        self.ensemble_record_button = QPushButton("Record ensemble", self)
        self.ensemble_record_button.setEnabled(False)
        self.ensemble_record_button.clicked.connect(self.on_pressed_button_ensemble)
        self.ensemble_action_grid.addWidget(self.ensemble_record_button, 0, 1)

        # Pause is the exception to "each tab's buttons act on that tab's subject": there is one
        # run loop, and pausing it is the same act either way. Two buttons onto one piece of
        # client state, so both are relabelled together -- see set_pause_button_label.
        self.ensemble_pause_button = QPushButton("Pause", self)
        self.ensemble_pause_button.setEnabled(False)
        self.ensemble_pause_button.clicked.connect(self.on_pressed_button)
        self.ensemble_action_grid.addWidget(self.ensemble_pause_button, 0, 2)

        self.ensemble_stop_button = QPushButton("Stop ensemble", self)
        self.ensemble_stop_button.setEnabled(False)
        self.ensemble_stop_button.clicked.connect(self.on_pressed_button_ensemble)
        self.ensemble_action_grid.addWidget(self.ensemble_stop_button, 0, 3)

        # # # TAB 3: Current subject metadata information # # #

        # Data tab layout
        self.data_tab = QWidget()
        self.data_form = QFormLayout()
        self.data_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        # Left, not centred: centring ragged-length captions puts every one of them at a different
        # x, so the eye has no edge to run down.
        self.data_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.data_tab.setLayout(self.data_form)

        # # subject info:
        #
        # One row, not three. This was 'Load existing subject' (a dropdown), 'Current subject:' (a
        # read-only label) and 'subject ID:' (a line edit) stacked together, all showing the same
        # string once a subject was loaded. The dropdown is the one that both shows the current
        # subject and changes it, so it is the one that stays; the read-only label said nothing it
        # did not, and the Main tab now carries the at-a-glance readout anyway.
        new_label = QLabel('Current subject:')
        self.existing_subject_input = QComboBox()
        self.existing_subject_input.activated.connect(self.on_selected_existing_subject)
        self.data_form.addRow(new_label, self.existing_subject_input)

        self.update_existing_subject_input()

        # Only built-ins are "subject_id," "age" and "notes"
        # The editable identity, which the dropdown is not: what Create subject names a new subject,
        # and what Update subject looks up. Distinct from the row above, so it keeps its own field.
        new_label = QLabel('Subject ID:')
        self.subject_id_input = QLineEdit()
        self.data_form.addRow(new_label, self.subject_id_input)

        # Age: 
        new_label = QLabel('Age:')
        self.subject_age_input = QSpinBox()
        self.subject_age_input.setMinimum(0)
        self.subject_age_input.setValue(1)
        self.data_form.addRow(new_label, self.subject_age_input)

        # Notes: 
        new_label = QLabel('Notes:')
        self.subject_notes_input = QTextEdit()
        self.data_form.addRow(new_label, self.subject_notes_input)

        # Use user cfg to populate other metadata options
        self.subject_metadata_inputs = {}
        ct = 0
        for key in self.cfg['subject_metadata']:
            ct += 1
            new_label = QLabel(key)
            new_input = QComboBox()
            for choiceID in self.cfg['subject_metadata'][key]:
                new_input.addItem(choiceID)
            self.data_form.addRow(new_label, new_input)

            self.subject_metadata_inputs[key] = new_input

        # One button, saying which of the two things it will do. Two always-enabled buttons meant
        # Update subject on an unknown ID printed "No subject with this ID is currently selected!"
        # to the terminal and did nothing the GUI showed -- so the only feedback for pressing the
        # wrong one was its absence.
        self.subject_button = QPushButton("Create subject", self)
        self.subject_button.clicked.connect(self.on_pressed_subject_button)
        self.data_form.addRow(self.subject_button)
        self.subject_id_input.textChanged.connect(self.refresh_subject_button)
        self.refresh_subject_button()

        # # # TAB 4: FILE tab - init, load, close etc. h5 file # # #

        # File tab layout
        self.file_tab = QWidget()
        self.file_form = QFormLayout()
        self.file_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.file_form.setLabelAlignment(Qt.AlignmentFlag.AlignCenter)
        self.file_tab.setLayout(self.file_form)

        # Data file info
        # Initialize new experiment button
        initialize_button = QPushButton("Initialize experiment", self)
        initialize_button.clicked.connect(self.on_pressed_button)
        new_label = QLabel(f'Current {self.data.output_noun}:')
        self.file_form.addRow(initialize_button, new_label)
        # Load existing experiment button
        load_button = QPushButton("Load experiment", self)
        load_button.clicked.connect(self.on_pressed_button)
        # Label with current expt file
        self.current_experiment_label = QLabel('')
        self.file_form.addRow(load_button, self.current_experiment_label)

        # # # # Data browser: # # # # # # # #
        # Supplied by the data backend, or not at all -- see BaseData.make_data_browser. A backend
        # without one gets the rest of the tab without these widgets, rather than a second copy of
        # the GUI without them.
        self.data_browser = self.data.make_data_browser(parent=self)
        if self.data_browser is not None:
            self.file_form.addRow(self.data_browser)

        # # # Add each tab to the main layout # # #
        self.tabs = QTabWidget()
        self.tabs.resize(450, 500)
        self.tabs.addTab(self.protocol_tab, "Main")
        self.tabs.addTab(self.ensemble_tab, "Ensemble")
        self.tabs.addTab(self.data_tab, "Subject")
        self.tabs.addTab(self.file_tab, "File")

        # Below the tabs, so both are there whichever tab is showing: a note is about the
        # experiment rather than about one tab, and a server error aborts the run wherever you
        # happen to be looking when it arrives.
        bottom_row = QHBoxLayout()
        bottom_row.addWidget(self.status_scroll_area)
        bottom_row.addWidget(self.note_button)

        self.layout = QVBoxLayout(self)
        self.layout.addWidget(self.tabs)
        self.layout.addLayout(bottom_row)

        self.update_run_button_states()

        # Resize window based on protocol tab
        self.update_window_width()

        self.show()

    def closeEvent(self, event):
        print("Closing Experiment GUI")
        self.stop_run_thread()
        self.client.close()
        super().closeEvent(event)

    def stop_run_thread(self, timeout_ms=5000):
        '''
        End the run thread before this window is torn down.

        Its started/finished signals are connected to lambdas that call back into this window. A
        thread that outlives the window delivers those into a destroyed receiver, which segfaults --
        so disconnect first, then ask the run loop to stop and wait for it.
        '''
        thread = self.__dict__.get('run_series_thread')
        if thread is None:
            return

        for signal in (thread.started, thread.finished):
            try:
                signal.disconnect()
            except TypeError:
                pass                              # that one had no connections; keep going

        if thread.isRunning():
            self.client.stop_run()                # BaseClient.start_run checks this between trials
            if not thread.wait(timeout_ms):
                warnings.warn("The run thread did not finish; closing anyway.")

        self.run_series_thread = None

    def on_reordered_ensemble_list(self):
        if not self.ensemble_file_label.text().endswith('(changes unsaved)'):
            self.ensemble_file_label.setText(f'{self.ensemble_file_label.text()} (changes unsaved)')

    def on_selected_protocol_ID(self, protocol_dropdown_idx, preset_name='Default'):
        if protocol_dropdown_idx == 0:
            return
        # Clear old params list from grid
        self.reset_layout()

        # initialize the selected protocol object
        self.protocol_object = self.available_protocols[protocol_dropdown_idx-1](self.cfg)

        # update display lists of run & protocol parameters
        self.protocol_object.load_parameter_presets()
        self.protocol_object.select_protocol_preset(name=preset_name)
        self.protocol_object.prepare_run(manager=self.client.manager)
        self.update_parameter_preset_selector()
        self.parameter_preset_comboBox.setCurrentIndex(self.parameter_preset_comboBox.findText(preset_name))
        self.update_parameters_input()
        self.update_window_width()
        self.show()

        self.update_parameters_from_fillable_fields(compute_epoch_parameters=True)

        # No need to re-apply the parameter lock after rebuilding the inputs: Qt disables a widget
        # added to a disabled parent, and these all go into parameters_box / protocol_selector_box.
        # Verified by removing the call and watching the test below still pass -- which is why the
        # test asserts the behaviour rather than the mechanism.

        # Only announce readiness if that is true. This is also how an ensemble loads its next
        # item, and declaring STANDBY there both said 'Ready' in the middle of an ensemble and
        # re-enabled View and Record, which update_run_button_states reads status to decide.
        if self.status == Status.STANDBY:
            self.status_label.setText('Ready')

    def on_server_message_received(self, level, text):
        '''Runs on the GUI thread (via server_message_signal): surface a message the server pushed back.

        For an 'error' the client also aborts the run (see BaseClient.report_server_message), so pop a
        modal alert -- the status label alone is immediately overwritten by run_finished ('Ready'). The
        guard avoids stacking dialogs if several errors arrive (e.g. one per screen) before teardown.
        '''
        self.status_label.setText(f'[server {level}] {text}')
        if level == 'error' and not self._server_error_dialog_open:
            self._server_error_dialog_open = True
            try:
                open_message_window(title='Server error', text=text)
            finally:
                self._server_error_dialog_open = False

    def on_data_error_received(self, text):
        """Surface a failed data write. Named for what it is, not as a server error.

        Modal rather than the status line alone, for the same reason a server error is: this
        arrives as the run ends, and run_finished overwrites the status line with 'Ready' straight
        afterwards. Shares the dialog guard so a data error and a server error cannot stack.
        """
        self.status_label.setText(f'[data error] {text.splitlines()[0]}')
        if not self._server_error_dialog_open:
            self._server_error_dialog_open = True
            try:
                open_message_window(title='Data file error', text=text)
            finally:
                self._server_error_dialog_open = False

    def on_selected_ensemble_protocol_ID(self, text):
        protocol_dropdown_idx = self.ensemble_protocol_selection_combo_box.currentIndex() # - 1 # first item is "select a protocol"
        if protocol_dropdown_idx == 0:
            return

        # Clear old presets list and add new presets to list
        if self.ensemble_parameter_preset_comboBox is not None:
            self.ensemble_parameter_preset_comboBox.deleteLater()
        self.ensemble_parameter_preset_comboBox = QComboBox(self)
        cap_dropdown_width(self.ensemble_parameter_preset_comboBox)
        self.ensemble_parameter_preset_comboBox.addItem("Default")

        temp_protocol_object = self.available_protocols[protocol_dropdown_idx - 1](self.cfg)
        temp_protocol_object.load_parameter_presets()

        for name in temp_protocol_object.parameter_presets.keys():
            self.ensemble_parameter_preset_comboBox.addItem(name)
        self.ensemble_protocol_selector_grid.addWidget(self.ensemble_parameter_preset_comboBox, 1, 1, 1, 1)
        self.show()

    def on_pressed_button(self):
        sender = self.sender()

        if sender.text() == 'Record':
            if (self.data.experiment_file_exists() and self.data.current_subject_exists()):
                self.send_run(save_metadata_flag=True)
            else:
                msg = QMessageBox()
                msg.setIcon(QMessageBox.Icon.Warning)
                msg.setText(f"You have not initialized a {self.data.output_noun} and/or subject yet")
                msg.setInformativeText("You can show stimuli by clicking the View button, but no metadata will be saved")
                msg.setWindowTitle(f"No {self.data.output_noun} and/or subject")
                msg.setDetailedText(f"Initialize or load both a {self.data.output_noun} and a subject if you'd like to save your metadata")
                msg.setStandardButtons(QMessageBox.StandardButton.Ok)
                msg.exec()

        elif sender.text() == 'View':
            self.send_run(save_metadata_flag=False)
            self.set_pause_button_label('Pause')

        elif sender.text() == 'Pause':
            self.client.pause_run()
            self.set_pause_button_label('Resume')
            # Don't announce "Paused" here: the run is still presenting and recording the trial it
            # was in. update_run_progress reports 'Pausing after this trial finishes...' now, and
            # switches to 'Paused' when the run loop has actually gone idle. Called directly rather
            # than waiting up to a second for the timer, so the button press feels immediate.
            self.update_run_progress()
            self.show()

        elif sender.text() == 'Resume':
            self.client.resume_run()
            self.set_pause_button_label('Pause')
            if self.ensemble_paused:
                # Held between ensemble items rather than inside a run; releasing it starts the
                # next protocol, which is what the pause deferred.
                self.ensemble_paused = False
                self.run_ensemble_item(save_metadata_flag=self.ensemble_save_metadata_flag)
            else:
                self.update_run_progress()
            self.show()

        elif sender.text() == 'Stop':
            self.client.stop_run()
            self.set_pause_button_label('Pause')
            if self.ensemble_paused:
                # Stopping out of a held ensemble: no run is in progress for stop_run to end, so
                # release the hold here or the ensemble would sit there forever.
                self.release_paused_ensemble()

        elif sender.text() == 'Note':
            self.prompt_for_note()

        elif sender.text() == 'Save preset':
            self.update_parameters_from_fillable_fields(compute_epoch_parameters=False)  # get the state of the param input from GUI
            start_name = self.parameter_preset_comboBox.currentText()
            if start_name == 'Default':
                start_name = ''

            text, _ = QInputDialog.getText(self, "Save preset", "Preset Name:",  text=start_name)

            self.protocol_object.update_parameter_presets(text) # TODO update GUI
            self.update_parameter_preset_selector()
            self.parameter_preset_comboBox.setCurrentIndex(self.parameter_preset_comboBox.findText(text))

        elif sender.text() == 'Initialize experiment':
            dialog = QDialog()

            dialog_ui = InitializeExperimentGUI(parent=dialog)
            dialog_ui.setupUI(self, dialog)
            dialog.setFixedSize(300, 200)
            dialog.exec()

            self.data.experiment_file_name = dialog_ui.le_filename.text()
            self.data.data_directory = dialog_ui.le_data_directory.text()
            self.data.experimenter = dialog_ui.le_experimenter.text()

            self.update_existing_subject_input()
            self.populate_groups()

        elif sender.text() == 'Load experiment':
            # An experiment is one file for some backends and a directory for others, so ask for
            # whichever this one is (BaseData.output_is_directory).
            start_dir = self.data.data_directory if os.path.isdir(self.data.data_directory) else ''
            if self.data.output_is_directory:
                path = QFileDialog.getExistingDirectory(self, f"Open {self.data.output_noun}", start_dir)
            else:
                path, _ = QFileDialog.getOpenFileName(self, f"Open {self.data.output_noun}", start_dir)

            if path:  # empty when the dialog was cancelled
                self.data.load_experiment(path)
                self.current_experiment_label.setText(self.data.experiment_file_name)
                # update series count to reflect already-collected series
                self.data.reload_series_count()
                self.series_counter_input.setValue(self.data.get_highest_series_count() + 1)
                self.update_existing_subject_input()
                self.populate_groups()

        # # # Buttons for ensemble tab # # #

    def on_pressed_button_ensemble(self):
        """Slot for the Ensemble tab's own buttons. Takes no arguments -- clicked() passes its
        `checked` flag to any slot that will accept one, which is not what a label lookup wants."""
        self.handle_ensemble_action(self.sender().text())

    def handle_ensemble_action(self, label):
        """The ensemble actions, keyed by label rather than by widget, so the shared run buttons
        can forward to them (see on_pressed_button) without pretending to be the sender."""
        if label == 'Append':
            if self.ensemble_protocol_selection_combo_box.currentIndex() == 0:
                return

            protocol_name = self.ensemble_protocol_selection_combo_box.currentText()
            preset_name = self.ensemble_parameter_preset_comboBox.currentText()
            self.ensemble_list.append_item(protocol_name, preset_name)

            if not self.ensemble_file_label.text().endswith('(changes unsaved)'):
                self.ensemble_file_label.setText(f'{self.ensemble_file_label.text()} (changes unsaved)')

        elif label == 'View ensemble':
            self.run_ensemble(save_metadata_flag=False)

        elif label == 'Record ensemble':
            self.run_ensemble(save_metadata_flag=True)

        elif label == 'Stop ensemble':
            self.client.stop_run()
            self.set_pause_button_label('Pause')
            if self.ensemble_paused:
                self.release_paused_ensemble()
            self.set_ensemble_running(False)

        elif label == 'Save ensemble':
            self.save_ensemble_preset()
        
        elif label == 'Load ensemble':
            self.load_ensemble_preset()
            
        elif label == 'Remove item':
            # Reversing order of selected rows so that removing each doesn't mess up the indices
            selected_row_idxes = sorted([x.row() for x in self.ensemble_list.selectionModel().selectedRows()])[::-1]
            for row_idx in selected_row_idxes:
                self.ensemble_list.remove_item(row_idx)

            if not self.ensemble_file_label.text().endswith('(changes unsaved)'):
                self.ensemble_file_label.setText(f'{self.ensemble_file_label.text()} (changes unsaved)')

        elif label == 'Clear':
            self.ensemble_list.clear()

            # Set label with filename
            self.ensemble_file_label.setText('No ensemble file loaded')

    def save_ensemble_preset(self):
        # Popup to get file path
        # save ensemble to file
        file_path, _= QFileDialog.getSaveFileName(self, "Save ensemble preset", self.parameter_preset_directory, "Stimpack ensemble files (*.spens)")
        if not file_path.endswith('.spens'):
            file_path += '.spens'

        with open(file_path, 'w') as ymlfile:
            yaml.dump(self.ensemble_list.protocol_preset_list, ymlfile, default_flow_style=False, sort_keys=False)

        print('Saved ensemble preset to {}'.format(file_path))
        self.ensemble_file_label.setText(file_path)

    def load_ensemble_preset(self):
        # Popup to get file path
        # load ensemble from file 
        fname, _ = QFileDialog.getOpenFileName(self, "Open ensemble preset", self.parameter_preset_directory, "Stimpack ensemble files (*.spens)")
        
        if os.path.isfile(fname):
            with open(fname, 'r') as ymlfile:
                # Refuse arbitrary-code YAML while still reconstructing the !!python/tuple values .spens files use.
                protocol_name_preset_pairs = config_tools.safe_load_yaml_with_tuples(ymlfile)
        else:
            return

        # Set label with filename
        self.ensemble_file_label.setText(fname)

        # Sanitize file
        for protocol_name, preset_name in protocol_name_preset_pairs:
            if protocol_name not in [x.__name__ for x in self.available_protocols]:
                error_text = f'Protocol {protocol_name} not found in available protocols. Removing from the loaded ensemble.'
                open_message_window(title='Ensemble preset load error', text=error_text)
                protocol_name_preset_pairs.remove((protocol_name, preset_name))

                # Set label with filename
                self.ensemble_file_label.setText(f'{fname} (changes unsaved)')
            
            temp_protocol_object = self.available_protocols[[x.__name__ for x in self.available_protocols].index(protocol_name)](self.cfg)
            temp_protocol_object.load_parameter_presets()
            if preset_name not in temp_protocol_object.parameter_presets.keys() and preset_name != 'Default':
                error_text = f'Preset {preset_name} not found in protocol {protocol_name}. Removing from the loaded ensemble.'
                open_message_window(title='Ensemble preset load error', text=error_text)
                protocol_name_preset_pairs.remove((protocol_name, preset_name))

                # Set label with filename
                self.ensemble_file_label.setText(f'{fname} (changes unsaved)')

        # Clear ensemble list
        self.ensemble_list.clear()
        
        # Load ensemble items and add to dropdown list
        for protocol_name, preset_name in protocol_name_preset_pairs:
            self.ensemble_list.append_item(protocol_name, preset_name)

        # Set label with filename
        self.ensemble_file_label.setText(fname)

    def set_ensemble_running(self, running):
        """Flip the ensemble flag and bring everything that depends on it into step.

        The list widget locks while an ensemble runs, and the run buttons' availability depends on
        whether there is an ensemble to stop. Keeping the three together here is what stops them
        disagreeing -- 'Stop ensemble' stayed enabled through a single-series run because the flag
        moved without the buttons being asked again.
        """
        self.ensemble_running = running
        # Timed from here rather than from the first item's run_started, so the readout covers the
        # whole ensemble including the gaps between its protocols.
        self.ensemble_start_time = time.time() if running else None
        self.ensemble_list.update_UI(self.ensemble_running)
        self.update_run_button_states()
        self.update_ensemble_progress()

    def run_ensemble(self, save_metadata_flag=False):
        self.set_ensemble_running(True)
        self.ensemble_list.reset_current_ensemble_idx()

        self.run_ensemble_item(save_metadata_flag=save_metadata_flag)
    
    def run_ensemble_item(self, save_metadata_flag=False):
        self.ensemble_list.increment_current_ensemble_idx()

        if self.ensemble_list.get_current_ensemble_idx() >= len(self.ensemble_list):
            self.ensemble_list.reset_current_ensemble_idx()
            self.set_ensemble_running(False)
            return

        print(f'Running ensemble item {self.ensemble_list.get_current_ensemble_idx()+1} / {len(self.ensemble_list)}')

        current_protocol_name, current_preset = self.ensemble_list.get_current_protocol_preset()

        matching_protocols = [x for x in self.available_protocols if current_protocol_name == x.__name__]
        if len(matching_protocols) == 0:
            warnings.warn(f'Ensemble: Protocol {current_protocol_name} not found in available protocols.')
            return
        elif len(matching_protocols) > 1:
            warnings.warn(f'Ensemble: Multiple protocols with name {current_protocol_name} found in available protocols. Ensemble does not support this.')
            return
        protocol_idx = self.protocol_selection_combo_box.findText(current_protocol_name, Qt.MatchFlag.MatchStartsWith)
        self.protocol_selection_combo_box.setCurrentIndex(protocol_idx)
        self.parameter_preset_comboBox.setCurrentIndex(self.parameter_preset_comboBox.findText(current_preset))
        self.on_selected_protocol_ID(protocol_idx, preset_name=current_preset)
        self.ensemble_list.update_UI(self.ensemble_running)

        self.send_run(save_metadata_flag=save_metadata_flag)

    def typed_subject_is_new(self):
        """Whether the ID in the field names a subject this experiment does not have yet.

        None when the question cannot be answered -- no experiment file, or nothing typed -- which
        is what disables the button rather than letting it claim to do either thing.
        """
        typed = self.subject_id_input.text().strip() if hasattr(self, 'subject_id_input') else ''
        if not typed or not self.data.experiment_file_exists():
            return None
        existing = {s.get('subject_id') for s in self.data.get_existing_subject_data()}
        return typed not in existing

    def refresh_subject_button(self):
        """Label the button with what pressing it will do, and disable it when that is nothing.

        Also called from update_existing_subject_input, which runs during initUI before the field
        and the button exist -- the subject dropdown is built first.
        """
        if not hasattr(self, 'subject_button'):
            return
        is_new = self.typed_subject_is_new()
        self.subject_button.setEnabled(is_new is not None)
        self.subject_button.setText('Create subject' if is_new is not False else 'Update subject')
        if is_new is None:
            self.subject_button.setToolTip(
                f'Type a subject ID, and create or load a {self.data.output_noun} first.')
        else:
            self.subject_button.setToolTip('')

    def on_pressed_subject_button(self):
        """Create or update, decided by the same question the label was written from.

        Not by reading the label back: the two would then have to agree, and a label is a thing
        somebody renames.
        """
        is_new = self.typed_subject_is_new()
        if is_new is None:
            return
        if is_new:
            self.on_created_subject()
        else:
            self.on_update_subject()
        self.refresh_subject_button()

    def on_created_subject(self):
        # Populate subject metadata from subject data fields
        subject_metadata = {}
        # Built-ins
        subject_metadata['subject_id'] = self.subject_id_input.text()
        subject_metadata['age'] = self.subject_age_input.value()
        subject_metadata['notes'] = self.subject_notes_input.toPlainText()

        # user-defined:
        for key in self.subject_metadata_inputs:
            subject_metadata[key] = self.subject_metadata_inputs[key].currentText()

        self.data.create_subject(subject_metadata)  # creates new subject and selects it as the current subject
        self.update_existing_subject_input()

    def on_update_subject(self):
        # Populate subject metadata from subject data fields
        subject_metadata = {}
        # Built-ins
        # This takes the value entered in the 'SubjectID' text field
        subject_metadata['subject_id'] = self.subject_id_input.text()
        subject_metadata['age'] = self.subject_age_input.value()
        subject_metadata['notes'] = self.subject_notes_input.toPlainText()

        # user-defined:
        for key in self.subject_metadata_inputs:
            subject_metadata[key] = self.subject_metadata_inputs[key].currentText()

        self.data.update_subject(subject_metadata)
        self.update_existing_subject_input()


    def reset_layout(self):
        for ii in range(self.parameters_grid.rowCount()):
            item = self.parameters_grid.itemAtPosition(ii, 0)
            if item is not None:
                item.widget().deleteLater()
            item = self.parameters_grid.itemAtPosition(ii, 1)
            if item is not None:
                item.widget().deleteLater()
        self.show()

    def make_parameter_input_text(self, value):
        if isinstance(value, str):
            return '"'+value+'"'
        else:
            return str(value)

    def update_parameters_input(self):
        def make_parameter_input_field(key, value, input_field_row):
            if isinstance(value, bool):
                input_field = QCheckBox()
                input_field.setChecked(value)
                input_field.stateChanged.connect(self.on_parameter_finished_edit)
            else:
                input_field = QLineEdit()
                input_field.setText(self.make_parameter_input_text(value))
                input_field.editingFinished.connect(self.on_parameter_finished_edit)
                input_field.textEdited.connect(self.on_parameter_mid_edit)

            self.parameters_grid.addWidget(QLabel(key + ':'), input_field_row, 0)
            self.parameters_grid.addWidget(input_field, input_field_row, 1, 1, 2)
            
            return input_field

        def set_validator(input_field, type):
            if type == int:
                validator = QtGui.QIntValidator()
                validator.setBottom(0)
                input_field.setValidator(validator)
            elif type == float:
                validator = QtGui.QDoubleValidator()
                validator.setBottom(0)
                input_field.setValidator(validator)

        def update_run_parameters_input():
            new_label = QLabel('Run parameters:')
            new_label.setStyleSheet('font-weight: bold; text-decoration: underline')
            self.parameters_grid.addWidget(new_label, self.parameters_grid_row_ct, 0) # add label after run_params
            self.parameters_grid_row_ct = +1 # +1 for label 'Run parameters:'

            self.run_parameter_input = {}  # clear old input params dict        
            for key, value in self.protocol_object.run_parameters.items():
                self.run_parameter_input[key] = make_parameter_input_field(key, value, self.parameters_grid_row_ct)
                self.parameters_grid_row_ct += 1
                # set_validator(self.run_parameter_input[key], type(value))

        def update_protocol_parameters_input():
            # update display window to show parameters for this protocol
            new_label = QLabel('Protocol parameters:')
            new_label.setStyleSheet('font-weight: bold; text-decoration: underline; margin-top: 10px;')
            self.parameters_grid.addWidget(new_label, self.parameters_grid_row_ct, 0) # add label after run_params
            self.parameters_grid_row_ct += 1 # +1 for label 'Protocol parameters:'
            
            self.protocol_parameter_input = {}  # clear old input params dict
            for key, value in self.protocol_object.protocol_parameters.items():
                self.protocol_parameter_input[key] = make_parameter_input_field(key, value, self.parameters_grid_row_ct)
                self.parameters_grid_row_ct += 1

        self.parameters_grid_row_ct = 0
        update_run_parameters_input()
        update_protocol_parameters_input()

    def on_parameter_mid_edit(self):
        self.mid_parameter_edit = True

    def on_parameter_finished_edit(self):
        if self.status == Status.STANDBY:
            self.update_parameters_from_fillable_fields(compute_epoch_parameters=True)

    def update_parameter_preset_selector(self):
        if self.parameter_preset_comboBox is not None:
            self.parameter_preset_comboBox.deleteLater()
        self.parameter_preset_comboBox = QComboBox(self)
        cap_dropdown_width(self.parameter_preset_comboBox)
        self.parameter_preset_comboBox.addItem("Default")
        for name in self.protocol_object.parameter_presets.keys():
            self.parameter_preset_comboBox.addItem(name)
        self.parameter_preset_comboBox.textActivated.connect(self.on_selected_parameter_preset)
        self.protocol_selector_grid.addWidget(self.parameter_preset_comboBox, 2, 1, 1, 1)

    def on_selected_parameter_preset(self, text):
        self.protocol_object.select_protocol_preset(text)
        self.reset_layout()
        self.update_parameters_input()
        self.update_parameters_from_fillable_fields()
        self.show()

    def on_selected_existing_subject(self, index):
        # Look the subject up by id rather than by dropdown position: the dropdown lists each
        # subject once, while get_existing_subject_data() may report one record per series
        # (data_nwb), so the two are not the same sequence.
        subject_id = self.existing_subject_input.itemText(index)
        matching = [s for s in self.data.get_existing_subject_data() if s.get('subject_id') == subject_id]
        if not matching:
            return
        self.populate_subject_metadata_fields(matching[-1])   # most recently recorded metadata
        self.data.select_subject(subject_id)
        self.show_current_subject(subject_id)

    def update_existing_subject_input(self):
        self.existing_subject_input.clear()
        # dict.fromkeys, not set(): one entry per subject, in the order they were recorded. A
        # backend that keeps subject metadata in each series file (data_nwb) reports the same
        # subject once per series, which otherwise fills the dropdown with duplicates.
        seen = dict.fromkeys(s['subject_id'] for s in self.data.get_existing_subject_data())
        # The current subject belongs in the list whether or not the backend reports it yet. NWB
        # keeps subject metadata inside each series file, so a subject that has been created but
        # not yet recorded is not in get_existing_subject_data() -- it would be missing from its
        # own dropdown, and now that the dropdown is the only thing naming the current subject on
        # this tab, it would be named nowhere.
        if self.data.current_subject and self.data.current_subject not in seen:
            seen[self.data.current_subject] = None
        for subject_id in seen:
            self.existing_subject_input.addItem(subject_id)

        self.show_current_subject(self.data.current_subject or '')
        self.refresh_subject_button()

    def show_current_subject(self, subject_id):
        """Reflect the current subject in both places it appears -- the Subject tab's dropdown and
        the Main tab's readout.

        The dropdown's index is cleared when there is no current subject. Left alone it would sit
        on whichever subject happens to be first in the list, showing one as selected when none is
        -- which matters more now that the dropdown is the only thing on that tab naming the
        current subject, and that Record keys off whether there is one.
        """
        index = self.existing_subject_input.findText(subject_id) if subject_id else -1
        self.existing_subject_input.setCurrentIndex(index)
        self.current_subject_main_label.setText(subject_id)
        self.update_run_button_states()

    def set_parameter_editing_enabled(self, enabled):
        """Lock or unlock the protocol/preset selectors and the parameter fields.

        Locked mid-ensemble: the values on show belong to the item the ensemble is running, and
        editing them would say something the run will not do. Only the inputs are locked -- the
        scroll area around them is not -- so the parameters stay readable and scrollable, which
        disabling the whole tab prevented.
        """
        self.parameter_editing_enabled = enabled
        self.protocol_selector_box.setEnabled(enabled)
        self.parameters_box.setEnabled(enabled)

    def update_run_button_states(self):
        """Enable each run button only when its action is available right now.

        Each tab owns its buttons and each set acts on that tab's subject -- a series on Main, the
        ensemble on Ensemble -- so nothing here depends on which tab is showing. Starting needs
        nothing running at all (an ensemble runs series of its own, so neither set may start while
        one is going); Record additionally needs a subject to record onto, which View does not.

        Stopping needs the thing named on the button to be going: a series for 'Stop', the
        ensemble for 'Stop ensemble'. They are genuinely different acts -- 'Stop' ends the item in
        progress and the ensemble moves on to the next one, 'Stop ensemble' ends the lot. An
        ensemble held between items for a pause has nothing running, so only 'Stop ensemble' is
        offered there, which is also the way out of the hold.
        """
        running = self.status != Status.STANDBY
        busy = running or self.ensemble_running
        can_record = bool(self.data.current_subject)

        self.view_button.setEnabled(not busy)
        self.record_button.setEnabled(not busy and can_record)
        self.stop_button.setEnabled(running)

        self.ensemble_view_button.setEnabled(not busy)
        self.ensemble_record_button.setEnabled(not busy and can_record)
        self.ensemble_stop_button.setEnabled(self.ensemble_running)

        # One run loop, so both Pause buttons reflect the one piece of client state.
        for button in (self.pause_button, self.ensemble_pause_button):
            button.setEnabled(busy)

    def set_pause_button_label(self, text):
        """Both Pause buttons drive the same run loop, so they say the same thing."""
        self.pause_button.setText(text)
        self.ensemble_pause_button.setText(text)

    def populate_subject_metadata_fields(self, subject_data_dict):
        self.subject_id_input.setText(subject_data_dict['subject_id'])
        # A backend round-trips metadata through its own encoding, so age may come back as a
        # string. Fall back to 0 rather than letting one odd value break the whole dialog.
        try:
            age = int(subject_data_dict.get('age', 0))
        except (TypeError, ValueError):
            warnings.warn(f"Could not read subject age {subject_data_dict.get('age')!r} as a number.")
            age = 0
        self.subject_age_input.setValue(age)
        self.subject_notes_input.setText(subject_data_dict['notes'])
        for key in self.subject_metadata_inputs:
            self.subject_metadata_inputs[key].setCurrentText(subject_data_dict[key])

    def flag_series_number(self, already_used):
        """Mark the series counter when its number has already been recorded, or clear the mark.

        Cleared by removing the override rather than by painting the field white. Forcing white
        left the text colour to the palette, so under a dark theme the field was white text on a
        white background -- unreadable in exactly the state that means "this is fine".

        The warning names both colours for the same reason: a background set without a foreground
        inherits whatever the theme supplies, which is only legible by luck.
        """
        self.series_counter_input.setStyleSheet(
            'background-color: rgb(220, 76, 76); color: black;' if already_used else '')

    def on_entered_series_count(self):
        self.data.update_series_count(self.series_counter_input.value())
        if self.data.experiment_file_exists() is True:
            self.flag_series_number(self.data.get_series_count() <= self.data.get_highest_series_count())

    def confirm_series_overwrite(self, series_number):
        """Ask before recording onto a series number that already holds data. True to go ahead.

        Says only that the number is taken. Which subject recorded it is not the question being
        asked -- a series is not tied to a subject, and naming one implied a rule that does not
        exist. What matters is that recording destroys what is there.

        Its own method so a test can answer it without a human, and so the wording lives in one
        place, with No as the default button.
        """
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle('Overwrite series?')
        msg.setText(f'Series {series_number} already exists.')
        msg.setInformativeText('Recording will delete the existing series and everything in it. '
                               'This cannot be undone.')
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        return msg.exec() == QMessageBox.StandardButton.Yes

    def send_run(self, save_metadata_flag=True):
        # check to make sure a protocol has been selected
        if self.protocol_object.__class__.__name__ == 'BaseProtocol':
            self.status_label.setText('Select a protocol')
            return  # no protocol exists, don't send anything

        # check to make sure the series count does not already exist
        if save_metadata_flag:
            self.data.update_series_count(self.series_counter_input.value())
            series_number = self.data.get_series_count()
            if series_number in self.data.get_existing_series():
                # Usually a false start somebody wants to redo under the same number, and refusing
                # outright left renumbering around it as the only option -- so the file grew a gap
                # and the numbering stopped matching the notebook. Destructive, so it is opt-in and
                # defaults to No. delete_series finds the series wherever it is, which is what
                # stops a second one being recorded under the same number.
                if not self.confirm_series_overwrite(series_number):
                    self.flag_series_number(True)
                    self.status_label.setText('Select an unused series number')
                    return
                self.data.delete_series()
            self.flag_series_number(False)

        # Populate parameters from filled fields
        if self.mid_parameter_edit:
            self.update_parameters_from_fillable_fields(compute_epoch_parameters=True)

        # Let the backend set up storage for this series. No-op for a single-file format; a
        # backend that writes one file per series (data_nwb) creates that file here.
        #
        # Caught rather than allowed to propagate: this runs in a Qt slot, where an unhandled
        # Python exception is fatal -- the GUI would vanish mid-experiment instead of saying what
        # was wrong. Refuse the run and report it, the same as any other reason not to start.
        if save_metadata_flag:
            try:
                self.data.prepare_series()
            except Exception as e:
                warnings.warn(f'Could not prepare storage for this series:\n{traceback.format_exc()}')
                self.status_label.setText(f'Cannot record: {e}')
                return

        # start the series thread:
        self.run_series_thread = runSeriesThread(self.protocol_object,
                                                 self.data,
                                                 self.client,
                                                 save_metadata_flag)

        self.run_series_thread.finished.connect(lambda: self.run_finished(save_metadata_flag))
        self.run_series_thread.started.connect(lambda: self.run_started(save_metadata_flag))

        self.run_series_thread.start()

    def run_started(self, save_metadata_flag):
        if save_metadata_flag:
            self.status = Status.RECORDING
        else:
            self.status = Status.VIEWING
        self.status_label.setText(self.run_status_text())

        # Status first: it is what update_run_button_states reads to lock View and Record, which
        # is what stops a second run thread being spun up on top of this one, and to offer Pause.
        self.update_run_button_states()

        self._pause_state_shown = 'running'   # so the first pause registers as a change
        self.run_start_time = time.time()
        self.progress_timer.start()

        # Enable/disable buttons on ensemble tab
        self.ensemble_append_button.setEnabled(False)

        self.ensemble_load_preset_button.setEnabled(False)
        self.ensemble_save_preset_button.setEnabled(False)
        self.ensemble_remove_item_button.setEnabled(False)
        self.ensemble_clear_button.setEnabled(False)

        if self.ensemble_running:
            self.set_parameter_editing_enabled(False)

    def run_finished(self, save_metadata_flag):
        self.status_label.setText('Ready')
        self.status = Status.STANDBY
        self.set_pause_button_label('Pause')
        self._pause_state_shown = 'running'
        # After self.status is back to STANDBY, so this is allowed to touch the button again.
        self.update_run_button_states()

        self.progress_timer.stop()

        if save_metadata_flag:
            self.update_existing_subject_input()
            # Advance the series_count:
            self.data.advance_series_count()
            self.series_counter_input.setValue(self.data.get_series_count())
            self.populate_groups()

        if self.ensemble_running:
            # A pause asked for during the final trial never took effect: the run loop's condition
            # fails before the pause branch is reached, and the next start_run clears the flag. In
            # an ensemble that meant pressing Pause, watching the button say 'Resume', and having
            # the next protocol start anyway. Hold here instead, and let Resume release it.
            if self.client.pause:
                self.ensemble_paused = True
                self.ensemble_save_metadata_flag = save_metadata_flag
                self.set_pause_button_label('Resume')
                self.status_label.setText('Paused before the next ensemble item')
            else:
                self.run_ensemble_item(save_metadata_flag=save_metadata_flag)

        if not self.ensemble_running: # if ensemble still running, no need to edit buttons or update parameters from fillable fields
            # Enable/disable buttons on ensemble tab
            self.ensemble_append_button.setEnabled(True)

            self.ensemble_load_preset_button.setEnabled(True)
            self.ensemble_save_preset_button.setEnabled(True)
            self.ensemble_remove_item_button.setEnabled(True)
            self.ensemble_clear_button.setEnabled(True)

            self.set_parameter_editing_enabled(True)

            # Prepare for next run
            self.update_parameters_from_fillable_fields(compute_epoch_parameters=True)

    def update_parameters_from_fillable_fields(self, compute_epoch_parameters=True):
        def is_number(s):
            try:
                float(s)
                return True
            except ValueError:
                return False

        def parse_param_str(s, param_type=float): 
            # Remove all whitespace
            s = ''.join(s.split())

            # Base case 1: Empty string
            if len(s) == 0:
                return ParseError('Empty parameter token')

            # Base case 2: number. Parse as int, then fall back to float (which handles inf/nan
            # consistently with is_number). Do NOT eval() GUI text: eval('inf'/'nan') raises NameError,
            # and an unhandled exception in a Qt slot aborts the whole application.
            elif is_number(s):
                try:
                    return int(s)
                except ValueError:
                    return float(s)

            # Base case 3: None
            elif s == 'None':
                return None
            
            # Base case 4: String literal (remove quotes)
            elif (s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'"):
                return s[1:-1]
            
           # List or tuple
            elif (s[0] == '[' and s[-1] == ']') or (s[0] == '(' and s[-1] == ')'):                
                l = []
                sq_bracket_level = 0
                parantheses_level = 0
                token = ''
                # Process each character. If comma is found outside of brackets, end of token.
                for c in s[1:-1]+',':
                    if c == '[':
                        sq_bracket_level += 1
                    if c == ']':
                        sq_bracket_level -= 1
                    if c == '(':
                        parantheses_level += 1
                    if c == ')':
                        parantheses_level -= 1

                    if sq_bracket_level == 0 and parantheses_level == 0 and c == ',': # End of token
                        parsed_token = parse_param_str(token)
                        if isinstance(parsed_token, ParseError):
                            return parsed_token
                        l.append(parsed_token)
                        token = ''
                    else:
                        token += c

                if sq_bracket_level != 0 or parantheses_level != 0:
                    return ParseError('Mismatched () or []: ' + s)

                # If input was a tuple, convert l to a tuple
                if s[0] == '(':
                    l = tuple(l)
                    
                return l

            else:
                return ParseError('Unrecognized token: ' + s)

        # Empty the parameters before filling them from the GUI
        self.protocol_object.run_parameters = {}
        self.protocol_object.protocol_parameters = {}

        for key, value in self.run_parameter_input.items():
            if isinstance(self.run_parameter_input[key], QCheckBox): #QCheckBox
                self.protocol_object.run_parameters[key] = self.run_parameter_input[key].isChecked()
            else: # QLineEdit
                # run_parameter_input_text = self.run_parameter_input[key].text()
                # self.protocol_object.run_parameters[key] = float(run_parameter_input_text) if len(run_parameter_input_text)>0 else 0
                raw_input = self.run_parameter_input[key].text()
                parsed_input = parse_param_str(raw_input)

                if isinstance(parsed_input, ParseError): # Parse error
                    default_value = self.protocol_object.get_run_parameter_defaults()[key]
                    default_value_input_text = self.make_parameter_input_text(default_value)
                    error_text = parsed_input.message + '\n' + \
                                    'Raw input: ' + raw_input + '\n' + \
                                    'Using default value: ' + default_value_input_text
                    open_message_window(title='Parameter parse error', text=error_text)
                    self.protocol_object.run_parameters[key] = default_value
                    self.run_parameter_input[key].setText(default_value_input_text)
                else: # Successful parse
                    self.protocol_object.run_parameters[key] = parsed_input

        for key, value in self.protocol_parameter_input.items():
            if isinstance(self.protocol_parameter_input[key], QCheckBox): #QCheckBox
                self.protocol_object.protocol_parameters[key] = self.protocol_parameter_input[key].isChecked()
            else:  # QLineEdit
                raw_input = self.protocol_parameter_input[key].text()
                parsed_input = parse_param_str(raw_input)

                if isinstance(parsed_input, ParseError): # Parse error
                    default_value = self.protocol_object.get_protocol_parameter_defaults()[key]
                    default_value_input_text = self.make_parameter_input_text(default_value)
                    error_text = parsed_input.message + '\n' + \
                                    'Raw input: ' + raw_input + '\n' + \
                                    'Using default value: ' + default_value_input_text
                    open_message_window(title='Parameter parse error', text=error_text)
                    self.protocol_object.protocol_parameters[key] = default_value
                    self.protocol_parameter_input[key].setText(default_value_input_text)
                else: # Successful parse
                    self.protocol_object.protocol_parameters[key] = parsed_input

        self.protocol_object.prepare_run(manager=self.client.manager, recompute_epoch_parameters=compute_epoch_parameters)
        self.update_run_progress()

        self.mid_parameter_edit = False

    def prompt_for_note(self):
        """Ask for a note and write it to the experiment.

        Checked before asking rather than after: with the field gone there is nowhere to leave
        rejected text, so somebody who types a paragraph into a dialog and then learns there is no
        experiment to put it in has lost it. Refusing up front costs one modal instead.
        """
        if not self.data.experiment_file_exists():
            open_message_window(title=f'No {self.data.output_noun}',
                                text=f'Create or load a {self.data.output_noun} before writing a note.')
            return

        text, accepted = QInputDialog.getMultiLineText(self, 'Enter note', 'Note:')
        if not accepted or not text.strip():
            return

        self.note_text = text
        self.data.create_note(text)
        self.status_label.setText('Note saved: ' + text.strip().replace('\n', ' ')[:60])

    def release_paused_ensemble(self):
        """Abandon an ensemble that was holding between items, and return the GUI to standby.

        The hold is not a run, so nothing else brings the GUI back out of it: run_finished has
        already been and gone, and stop_run has no run loop left to stop.
        """
        self.ensemble_paused = False
        self.client.pause = False
        self.status_label.setText('Ready')
        self.set_ensemble_running(False)

    def run_status_text(self):
        """What the status line should say about a run that is neither pausing nor paused.

        Derived from self.status rather than remembered, because Resume has to restore it: it used
        to hardcode 'Viewing...', so resuming a recording run announced that it was only viewing --
        while it went on recording. Losing the series number is bad enough; claiming a recording
        run is not recording invites somebody to stop and restart a series that was fine.
        """
        if self.status == Status.RECORDING:
            text = 'Recording series ' + str(self.data.get_series_count())
        elif self.status == Status.VIEWING:
            text = 'Viewing...'
        else:
            return 'Ready'

        # Say when this series is one item of an ensemble. Otherwise a recorded series looks
        # exactly like a single run, and the difference matters: an ensemble carries on to the
        # next protocol by itself, so 'this will end shortly' is the wrong thing to assume.
        if self.ensemble_running:
            item = self.ensemble_list.get_current_ensemble_idx() + 1
            text += f'   [ensemble: protocol {item} of {len(self.ensemble_list)}]'
        return text

    def varying_epoch_parameter_names(self):
        """Protocol parameters that take a different value from trial to trial.

        process_input_parameters records these in persistent_parameters, but a protocol is free to
        override that method, and a labpack one that does not call super() leaves the list unset.
        Recomputed from the parameters themselves in that case, using the same rule: a parameter
        given as a list of more than one value is one that varies.
        """
        protocol = self.protocol_object
        names = (protocol.persistent_parameters or {}).get('variable_protocol_parameter_names')
        if names is None:
            names = [key for key, value in protocol.protocol_parameters.items()
                     if isinstance(value, list) and len(value) > 1]
        return names

    def epoch_parameters_text(self):
        """This trial's values for the parameters that vary, as one line.

        Only the varying ones: the rest are on show in the parameter fields above, unchanged for
        the whole run, and repeating them here would bury the two or three that actually differ.
        """
        if self.status == Status.STANDBY:
            return ''

        values = self.protocol_object.trial_protocol_parameters or {}
        names = [name for name in self.varying_epoch_parameter_names() if name in values]
        if not names:
            return '(no parameters vary across trials)'
        return ',   '.join(f'{name}: {values[name]}' for name in names)

    def update_ensemble_progress(self):
        """The Ensemble tab's readouts: how many of its protocols have run, and for how long.

        Measured from the start of the ensemble, not of the item in progress, and it keeps
        counting between items -- the gap between one protocol finishing and the next starting is
        time the ensemble is taking. There is no estimate to show it against: est_run_time comes
        from precomputing a protocol's trial parameters, and doing that for every item up front is
        the expensive part.
        """
        total = len(self.ensemble_list)
        if not self.ensemble_running:
            self.ensemble_progress_label.setText(f'0 / {total}' if total else '')
            self.ensemble_elapsed_label.setText('')
            return

        # The index is of the item running now, so the count completed is that index.
        self.ensemble_progress_label.setText(f'{self.ensemble_list.get_current_ensemble_idx()} / {total}')
        if self.ensemble_start_time is not None:
            self.ensemble_elapsed_label.setText(f'{int(time.time() - self.ensemble_start_time)}s')

    def update_run_progress(self):
        if self.status == Status.STANDBY:
            elapsed_time = 0
            epoch_count = 0
            paused_seconds = 0
        else:
            # Elapsed excludes time spent paused, so it stays comparable to est_run_time, which is
            # a sum of stimulus durations and knows nothing about pauses. The pause total is shown
            # alongside instead of being folded in and silently inflating progress.
            paused_seconds = int(self.client.paused_seconds)
            elapsed_time = int(time.time() - self.run_start_time) - paused_seconds
            epoch_count = self.protocol_object.num_trials_completed

        # est_run_time is only set once prepare_run has precomputed the trials, and this method is
        # now reached from the Pause/Resume slots as well as the timer. An exception raised in a Qt
        # slot takes the whole application down, which is far too high a price for a label.
        est_run_time = getattr(self.protocol_object, 'est_run_time', None)
        est_text = f'{est_run_time:.0f}s' if est_run_time is not None else '?'
        elapsed_text = f'{elapsed_time} / {est_text}'
        if paused_seconds > 0:
            elapsed_text += f'  (+{paused_seconds})'
        self.elapsed_time_label.setText(elapsed_text)
        self.trial_count_label.setText(f'{epoch_count} / {self.protocol_object.run_parameters.get("num_trials", "?")}')
        # Read straight off the protocol object, like the trial count above it. The run loop owns
        # that object on another thread, but these are plain attribute reads of values it replaces
        # wholesale at the start of each trial, so the worst case is showing the previous trial's
        # values for one tick of the timer.
        self.epoch_parameters_label.setText(self.epoch_parameters_text())
        self.update_ensemble_progress()

        # Announce pause transitions only, rather than rewriting the status every tick: the same
        # label carries server messages (see report_server_message), and a once-a-second overwrite
        # would wipe out an error report a second after it arrived.
        pause_state = self.client.pause_state if self.status != Status.STANDBY else 'running'
        if pause_state != self._pause_state_shown:
            self._pause_state_shown = pause_state
            if pause_state == 'pending':
                self.status_label.setText('Pausing after this trial finishes...')
            elif pause_state == 'paused':
                self.status_label.setText(f'Paused after {epoch_count} trials')
            else:
                self.status_label.setText(self.run_status_text())

    def populate_groups(self):
        # Called after anything that changes the experiment's contents. Delegates to whatever
        # browser the backend supplied, and does nothing when it supplied none.
        if self.data_browser is not None:
            self.data_browser.refresh()

    def update_window_width(self):
        self.resize(100, self.height())
        window_width = self.parameters_box.sizeHint().width() + self.parameters_scroll_area.verticalScrollBar().sizeHint().width() + 40
        self.resize(window_width, self.height())

# # # Other accessory classes. For data file initialization and threading # # # #
class InitializeExperimentGUI(QWidget):
    """
    GUI to initialize experiment file to store data
    """
    def setupUI(self, experiment_gui_object, parent=None):
        # NOT super().__init__(parent) again: both callers already construct this widget
        # as InitializeExperimentGUI(parent=dialog), and re-running QWidget's constructor on a live widget
        # is undefined behaviour in PyQt -- it corrupts the C++ side and segfaults later,
        # somewhere unrelated.
        self.parent = parent
        self.experiment_gui_object = experiment_gui_object
        layout = QFormLayout()

        noun = self.experiment_gui_object.data.output_noun
        label_filename = QLabel(f'{noun[0].upper() + noun[1:]} name:')
        init_now = datetime.now()
        defaultName = init_now.isoformat()[:-16]
        self.le_filename = QLineEdit(defaultName)
        layout.addRow(label_filename, self.le_filename)

        select_directory_button = QPushButton("Select Directory...", self)
        select_directory_button.clicked.connect(self.on_pressed_directory_button)
        self.le_data_directory = QLineEdit(config_tools.get_data_directory(self.experiment_gui_object.cfg))
        layout.addRow(select_directory_button, self.le_data_directory)

        label_experimenter = QLabel('Experimenter:')
        self.le_experimenter = QLineEdit(config_tools.get_experimenter(self.experiment_gui_object.cfg))
        layout.addRow(label_experimenter, self.le_experimenter)

        self.label_status = QLabel('Enter experiment info')
        layout.addRow(self.label_status)

        enter_button = QPushButton("Enter", self)
        enter_button.clicked.connect(self.on_pressed_enter_button)
        layout.addRow(enter_button)

        self.setLayout(layout)

    def on_pressed_enter_button(self):
        data = self.experiment_gui_object.data
        data.experiment_file_name = self.le_filename.text()
        data.data_directory = self.le_data_directory.text()
        data.experimenter = self.le_experimenter.text()

        # Ask the backend whether this experiment already exists, rather than testing for an
        # .hdf5 file here: what "already exists" means is the backend's business (a file for
        # HDF5, a directory for NWB), and it already answers exactly this question.
        if data.experiment_file_exists():
            self.label_status.setText(f'{data.output_noun[0].upper() + data.output_noun[1:]} already exists!')
        elif not os.path.isdir(data.data_directory):
            self.label_status.setText('Data directory does not exist!')
        else:
            self.label_status.setText('Data entered')
            self.experiment_gui_object.current_experiment_label.setText(self.experiment_gui_object.data.experiment_file_name)
            self.experiment_gui_object.data.initialize_experiment_file()
            self.experiment_gui_object.series_counter_input.setValue(1)
            self.close()
            self.parent.close()

    def on_pressed_directory_button(self):
        if os.path.isdir(self.experiment_gui_object.data.data_directory):
            filepath = str(QFileDialog.getExistingDirectory(self, "Select Directory", self.experiment_gui_object.data.data_directory))
        else:
            filepath = str(QFileDialog.getExistingDirectory(self, "Select Directory"))
        
        self.le_data_directory.setText(filepath)

class InitializeRigGUI(QWidget):
    def setupUI(self, experiment_gui_object, parent=None, window_size=None):
        # NOT super().__init__(parent) again: both callers already construct this widget
        # as InitializeRigGUI(parent=dialog), and re-running QWidget's constructor on a live widget
        # is undefined behaviour in PyQt -- it corrupts the C++ side and segfaults later,
        # somewhere unrelated.
        self.parent = parent
        self.experiment_gui_object = experiment_gui_object

        self.cfg_name = None
        self.cfg : dict[str, Any] = {}
        self.available_rig_configs = []
    
        # self.layout = QFormLayout()
        if window_size is not None and len(window_size) == 2:
            self.resize(*window_size)

        self.labpack_dir = config_tools.get_labpack_directory()
        
        self.init_grid = QGridLayout()

        self.pb_labpack_dir = QPushButton('Labpack Dir')
        self.pb_labpack_dir.clicked.connect(self.on_pressed_labpack_dir_button)
        self.pb_labpack_dir.setToolTip("You can customize your Stimpack by importing your own Labpack. Click the \"?\" button for a template Labpack repository.")
        self.init_grid.addWidget(self.pb_labpack_dir, 0, 0)
        
        self.le_labpack_dir = QLineEdit(self.labpack_dir)
        self.le_labpack_dir.setReadOnly(True)
        self.init_grid.addWidget(self.le_labpack_dir, 0, 1)
        
        self.pb_labpack_repo = QPushButton('?')
        self.pb_labpack_repo.clicked.connect(lambda: QtGui.QDesktopServices.openUrl(QUrl("https://www.github.com/ClandininLab/labpack-template")))
        self.pb_labpack_repo.setToolTip("You can customize your Stimpack by importing your own Labpack. Click here for a template Labpack repository.")
        self.init_grid.addWidget(self.pb_labpack_repo, 0, 2)

        label_config = QLabel('Config')
        label_config.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        self.init_grid.addWidget(label_config, 1, 0)
        
        self.config_combobox = QComboBox()
        self.config_combobox.activated.connect(self.on_selected_config)
        self.init_grid.addWidget(self.config_combobox, 1, 1, 1, 2)
        
        label_rigname = QLabel('Rig Config')
        label_rigname.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        self.init_grid.addWidget(label_rigname, 2, 0)
        
        self.rig_combobox = QComboBox()
        self.init_grid.addWidget(self.rig_combobox, 2, 1, 1, 2)

        # Which storage backend to write. Chosen here rather than in the main window because this
        # dialog runs to completion before the data object -- or the File tab's browser, or the
        # labels naming it -- is built, so there is nothing yet to swap out and no open experiment
        # to invalidate. An experiment cannot change format part-way through in any case.
        label_data_format = QLabel('Data format')
        label_data_format.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        self.init_grid.addWidget(label_data_format, 3, 0)

        self.data_format_combobox = QComboBox()
        for format_name in sorted(config_tools.BUILTIN_DATA_FORMATS):
            self.data_format_combobox.addItem(format_name)
        self.data_format_combobox.setToolTip(
            "Which format to write. Defaults to the selected config's data_format.\n"
            "Ignored if the labpack supplies its own data module, which takes precedence.")
        self.init_grid.addWidget(self.data_format_combobox, 3, 1, 1, 2)

        self.update_available_rigs()

        self.pb_enter = QPushButton('Enter')
        self.pb_enter.clicked.connect(self.on_pressed_enter_button)
        self.init_grid.addWidget(self.pb_enter, 4, 0, 1, 3)

        self.setLayout(self.init_grid)

        # Load the first config
        self.load_labpack()
        self.on_selected_config()

        self.show()

    def on_pressed_labpack_dir_button(self):
        filepath = QFileDialog.getExistingDirectory(self, "Select Labpack directory")
        if filepath!='' and len(config_tools.get_available_config_files(filepath)) == 0:
            open_message_window(text='No config files found in ' + filepath)
            return
        else:
            self.labpack_dir = filepath
            config_tools.set_labpack_directory(filepath)
            self.load_labpack()
    
    def load_labpack(self):
        self.le_labpack_dir.setText(self.labpack_dir)

        self.config_combobox.clear()
        self.config_combobox.addItem('default')
        if len(config_tools.get_available_config_files(self.labpack_dir)) > 0:
            for choiceID in config_tools.get_available_config_files(self.labpack_dir):
                self.config_combobox.addItem(choiceID)
        self.on_selected_config()

    def update_available_rigs(self):
        self.rig_combobox.clear()
        if len(self.available_rig_configs) > 0:
            for choiceID in self.available_rig_configs:
                self.rig_combobox.addItem(choiceID)

    def on_selected_config(self):
        self.cfg_name = self.config_combobox.currentText()
        self.cfg = config_tools.get_configuration_file(self.cfg_name, self.labpack_dir)
        self.available_rig_configs = config_tools.get_available_rig_configs(self.cfg)
        self.update_available_rigs()
        self.update_data_format_selection()
        self.show()

    def update_data_format_selection(self):
        """Show the format this config would use, so the default is the config's own answer.

        Follows the config selection above it: picking a different config re-reads its
        data_format rather than leaving the previous config's answer showing. A --data-format on
        the command line wins over both, so it is shown here too -- the flag is applied after this
        dialog either way, and a dialog displaying something other than what will be used is worse
        than no dialog.
        """
        override = getattr(self.experiment_gui_object, 'data_format_override', None)
        data_format = override if override is not None else config_tools.get_data_format(self.cfg)
        index = self.data_format_combobox.findText(data_format)
        if index >= 0:
            self.data_format_combobox.setCurrentIndex(index)
        self.data_format_combobox.setEnabled(override is None)

    def on_pressed_enter_button(self):
        # Store the rig and cfg names in the cfg dict
        self.cfg['current_rig_name'] = self.rig_combobox.currentText()
        self.cfg['current_cfg_name'] = self.cfg_name
        self.cfg['data_format'] = self.data_format_combobox.currentText()

        self.warn_about_labpack_problems()

        # Pass cfg up to experiment GUI object
        self.experiment_gui_object.cfg = self.cfg
        self.experiment_gui_object.cfg_initialized = True

        self.close()
        if self.parent is not None:
            self.parent.close()

    def warn_about_labpack_problems(self):
        '''
        Check the chosen config before the session starts, and show anything that would otherwise
        fail silently -- a path that no longer resolves, a key stimpack stopped reading.

        Deliberately does not block: the person at the rig decides whether a finding matters, and a
        modal that refuses to open the GUI would be worse than the silent failure it replaces. Only
        errors get a dialog; warnings go to the terminal. Run `stimpack --check-labpack` for the
        full report across every config.
        '''
        try:
            findings = check_labpack.check_config(self.cfg, self.cfg_name, self.labpack_dir)
        except Exception as e:
            # A broken check must never stop someone from starting an experiment.
            warnings.warn(f'Could not check the labpack: {type(e).__name__}: {e}')
            return

        for finding in findings:
            print(f'[labpack check] {finding}')

        errors = [f for f in findings if f.level == 'error']
        if errors:
            open_message_window(
                title='Labpack problems',
                text=f'{self.cfg_name} names things stimpack cannot find. The GUI will still open, '
                     f'but a run using it may silently do the wrong thing.\n\n'
                     + '\n\n'.join(f'• {f.message}' for f in errors)
                     + '\n\nRun `stimpack --check-labpack` for the full report.')


class runSeriesThread(QThread):
    # https://nikolak.com/pyqt-threading-tutorial/
    # https://stackoverflow.com/questions/41848769/pyqt5-object-has-no-attribute-connect
    def __init__(self, protocol_object, data, client, save_metadata_flag):
        QThread.__init__(self)
        self.protocol_object = protocol_object
        self.data = data
        self.client = client
        self.save_metadata_flag = save_metadata_flag

    # NOTE: deliberately no __del__ that calls self.wait().
    #
    # __del__ runs at whatever moment the garbage collector happens to fire, which for a QThread
    # means calling into a C++ object that Qt may already have destroyed -- a segfault with a
    # traceback pointing at whatever innocent line was executing when GC ran. ExperimentGUI.closeEvent
    # waits for this thread explicitly instead, which is deterministic.

    def _send_run(self):
        self.client.start_run(self.protocol_object, self.data, save_metadata_flag=self.save_metadata_flag)

    def run(self):
        self._send_run()


class EnsembleList(QListWidget):
    row_moved_signal = pyqtSignal()

    def __init__(self):
        super().__init__()

        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.model().rowsMoved.connect(self.on_order_changed)

        self.protocol_preset_list = []
        self.current_ensemble_idx = -1

    def __len__(self):
        assert len(self.protocol_preset_list) == self.count()
        return self.count()

    def append_item(self, protocol_name, preset_name):
        super().addItem(protocol_name + ' (' + preset_name + ')')
        self.protocol_preset_list.append((protocol_name, preset_name))
    
    def clear(self):
        super().clear()
        self.protocol_preset_list = []
        self.current_ensemble_idx = -1

    def remove_item(self, row):
        super().takeItem(row)
        self.protocol_preset_list.pop(row)

    def increment_current_ensemble_idx(self):
        self.current_ensemble_idx += 1
    
    def reset_current_ensemble_idx(self):
        self.current_ensemble_idx = -1
    
    def get_current_ensemble_idx(self):
        return self.current_ensemble_idx
    
    def get_current_protocol_preset(self):
        return self.protocol_preset_list[self.current_ensemble_idx]

    def on_order_changed(self, sourceParent=None, sourceStart=None, sourceEnd=None, destinationParent=None, destinationRow=None):
        destination_idx = destinationRow if destinationRow < sourceStart else destinationRow - 1
        print(f"Row moved from {sourceStart} to {destination_idx}")

        # Update the ensemble
        item = self.protocol_preset_list.pop(sourceStart)
        self.protocol_preset_list.insert(destination_idx, item)

        self.row_moved_signal.emit()
    
    def update_UI(self, ensemble_running):
        if ensemble_running:
            self.setEnabled(False)
            self.clearSelection()
            self.setCurrentRow(self.current_ensemble_idx)
        else:
            self.setEnabled(True)
            self.clearSelection()


def main(argv=None):
    parser = argparse.ArgumentParser(prog='stimpack', description='Stimpack experiment GUI.')
    parser.add_argument('--check-labpack', action='store_true',
                        help="check the configured labpack for problems and exit. Returns nonzero "
                             "if any error was found, so it can be used in a script or CI.")
    parser.add_argument('--labpack-dir', default=None,
                        help="labpack to check (default: the one recorded in path_to_labpack.txt)")
    parser.add_argument('--deep', action='store_true',
                        help="with --check-labpack, also import each protocol and check where its "
                             "calls would be routed. Runs lab code, so it is not done at startup.")
    parser.add_argument('--data-format', default=None,
                        choices=sorted(config_tools.BUILTIN_DATA_FORMATS),
                        help="storage backend for this session, overriding the config's "
                             "data_format. For trying a format without editing a config; set "
                             "data_format in the config file to make it the default.")
    args = parser.parse_args(argv)

    if args.check_labpack:
        from stimpack.experiment.util import check_labpack
        findings, configs = check_labpack.check_labpack(args.labpack_dir, deep=args.deep)
        print(check_labpack.format_report(findings, configs, args.labpack_dir))
        sys.exit(1 if any(f.level == 'error' for f in findings) else 0)

    app = QApplication(sys.argv)
    app.setApplicationName('Stimpack Experiment')
    app.setWindowIcon(QtGui.QIcon(ICON_PATH))
    ex = ExperimentGUI(data_format=args.data_format)  # noqa: F841 - keep a reference so the top-level window isn't garbage-collected
    sys.exit(app.exec())


def main_nwb():
    """
    The `stimpack_nwb` command, from when NWB needed a GUI of its own.

    One GUI now serves both formats, so this is `stimpack --data-format nwb`. Kept so existing
    setups keep working, and it says what to do instead.
    """
    warnings.warn("'stimpack_nwb' is deprecated: one GUI now handles both formats. Put "
                  "'data_format: nwb' in your config file and run 'stimpack', or pass "
                  "'stimpack --data-format nwb'.")
    main(sys.argv[1:] + ['--data-format', 'nwb'])


if __name__ == '__main__':
    main()
