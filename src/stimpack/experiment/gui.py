#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Jun 21 10:51:42 2018

@author: mhturner
"""
from datetime import datetime
import os
import sys
import time
from enum import Enum
from PyQt6.QtWidgets import (QPushButton, QWidget, QLabel, QTextEdit, QGridLayout, QApplication,
                             QComboBox, QLineEdit, QFormLayout, QDialog, QFileDialog, QInputDialog,
                             QMessageBox, QCheckBox, QSpinBox, QTabWidget, QVBoxLayout, QFrame,
                             QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem,
                             QScrollArea, QSizePolicy)
import PyQt6.QtCore as QtCore
from PyQt6.QtCore import QThread, QTimer, Qt
import PyQt6.QtGui as QtGui

from stimpack.experiment.util import config_tools, h5io
from stimpack.experiment import protocol, data, client

from stimpack.util import get_all_subclasses, ICON_PATH
from stimpack.util import open_message_window

Status = Enum('Status', ['STANDBY', 'RECORDING', 'VIEWING'])

class ParseError(Exception):
    def __init__(self, message):
        super().__init__()
        self.message = message

class ExperimentGUI(QWidget):

    def __init__(self):
        super().__init__()
        # set GUI icon
        self.setWindowIcon(QtGui.QIcon(ICON_PATH))

        self.note_text = ''
        self.run_parameter_input = {}
        self.protocol_parameter_input = {}
        self.mid_parameter_edit = False
        self.status = Status.STANDBY

        # user input to select configuration file and rig name
        # sets self.cfg
        self.cfg = None
        init_gui_size = None
        dialog = QDialog()
        dialog.setWindowIcon(QtGui.QIcon(ICON_PATH))
        dialog.setWindowTitle('Stimpack Config Selection')
        dialog.ui = InitializeRigGUI(parent=dialog)
        dialog.ui.setupUI(self, dialog, window_size=init_gui_size)
        if init_gui_size is not None:
            dialog.setFixedSize(*init_gui_size)
        dialog.exec()

        # No config file selected, exit
        if self.cfg is None:
            print('!!! No configuration file selected. Exiting !!!')
            sys.exit()

        print('# # # Loading protocol, data and client modules # # #')
        if config_tools.user_module_exists(self.cfg, 'protocol'):
            user_protocol_module = config_tools.load_user_module(self.cfg, 'protocol')
            self.protocol_object = user_protocol_module.BaseProtocol(self.cfg)
            self.available_protocols =  get_all_subclasses(user_protocol_module.BaseProtocol)
        else:   # use the built-in
            print('!!! Using builtin {} module. To use user defined module, you must point to that module in your config file !!!'.format('protocol'))
            self.protocol_object =  protocol.BaseProtocol(self.cfg)
            self.available_protocols =  [x for x in get_all_subclasses(protocol.BaseProtocol) if x.__name__ not in ['BaseProtocol', 'SharedPixMapProtocol']]

        # start a data object
        if config_tools.user_module_exists(self.cfg, 'data'):
            user_data_module = config_tools.load_user_module(self.cfg, 'data')
            self.data = user_data_module.Data(self.cfg)
        else:  # use the built-in
            print('!!! Using builtin {} module. To use user defined module, you must point to that module in your config file !!!'.format('data'))
            self.data = data.BaseData(self.cfg)

         # start a client
        if config_tools.user_module_exists(self.cfg, 'client'):
            user_client_module = config_tools.load_user_module(self.cfg, 'client')
            self.client = user_client_module.Client(self.cfg)
        else:  # use the built-in
            print('!!! Using builtin {} module. To use user defined module, you must point to that module in your config file !!!'.format('client'))
            self.client = client.BaseClient(self.cfg)

        print('# # # # # # # # # # # # # # # #')
        
        self.initUI()

    def initUI(self):
        self.layout = QVBoxLayout(self)
        self.tabs = QTabWidget()

        self.protocol_box = QWidget()
        self.parameter_grid = QGridLayout()
        self.parameter_grid.setSpacing(10)
        self.protocol_box.setSizePolicy(QSizePolicy(QSizePolicy.Policy.MinimumExpanding,
                                            QSizePolicy.Policy.MinimumExpanding))
        
        self.protocol_selector_box = QWidget()
        self.protocol_selector_box.setSizePolicy(QSizePolicy(QSizePolicy.Policy.MinimumExpanding,
                                                            QSizePolicy.Policy.Fixed))
        self.protocol_selector_grid = QGridLayout()

        self.protocol_params_scroll_box = QScrollArea()
        self.protocol_params_scroll_box.setWidget(self.protocol_box)
        self.protocol_params_scroll_box.setWidgetResizable(True)

        self.protocol_control_box = QWidget()
        self.protocol_control_box.setSizePolicy(QSizePolicy(QSizePolicy.Policy.MinimumExpanding,
                                                            QSizePolicy.Policy.Fixed))
        self.protocol_control_grid = QGridLayout()

        self.protocol_tab = QWidget()
        self.protocol_tab_layout = QVBoxLayout()
        self.protocol_tab_layout.addWidget(self.protocol_selector_box)
        self.protocol_tab_layout.addWidget(self.protocol_params_scroll_box)
        self.protocol_tab_layout.addWidget(self.protocol_control_box)

        self.data_tab = QWidget()
        self.data_form = QFormLayout()
        self.data_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.data_form.setLabelAlignment(Qt.AlignmentFlag.AlignCenter)

        self.file_tab = QWidget()
        self.file_form = QFormLayout()
        self.file_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.file_form.setLabelAlignment(Qt.AlignmentFlag.AlignCenter)

        self.tabs.addTab(self.protocol_tab, "Main")
        self.tabs.addTab(self.data_tab, "Subject")
        self.tabs.addTab(self.file_tab, "File")

        self.tabs.resize(450, 500)

        # # # TAB 1: MAIN controls, for selecting / playing stimuli
        # Protocol ID drop-down:
        protocol_selection_combo_box = QComboBox(self)
        protocol_selection_combo_box.addItem("(select a protocol to run)")
        for sub_class in self.available_protocols:
            protocol_selection_combo_box.addItem(sub_class.__name__)
        protocol_label = QLabel('Protocol:')
        protocol_selection_combo_box.textActivated.connect(self.on_selected_protocol_ID)
        self.protocol_selector_grid.addWidget(protocol_label, 1, 0)
        self.protocol_selector_grid.addWidget(protocol_selection_combo_box, 1, 1, 1, 1)

        # Parameter preset drop-down:
        parameter_preset_label = QLabel('Parameter_preset:')
        self.protocol_selector_grid.addWidget(parameter_preset_label, 2, 0)
        self.parameter_preset_comboBox = None
        self.update_parameter_preset_selector()

        # Save parameter preset button:
        save_preset_button = QPushButton("Save preset", self)
        save_preset_button.clicked.connect(self.on_pressed_button)
        self.protocol_selector_grid.addWidget(save_preset_button, 2, 2)

        # Status window:
        new_label = QLabel('Status:')
        self.protocol_control_grid.addWidget(new_label, 0, 0)
        self.status_label = QLabel()
        self.status_label.setFrameShadow(QFrame.Shadow(1))
        self.protocol_control_grid.addWidget(self.status_label, 0, 1)
        self.status_label.setText('Select a protocol')

        # Current series counter
        new_label = QLabel('Series counter:')
        self.protocol_control_grid.addWidget(new_label, 0, 2)
        self.series_counter_input = QSpinBox()
        self.series_counter_input.setMinimum(1)
        self.series_counter_input.setMaximum(1000)
        self.series_counter_input.setValue(1)
        self.series_counter_input.valueChanged.connect(self.on_entered_series_count)
        self.protocol_control_grid.addWidget(self.series_counter_input, 0, 3)

        # Elapsed time window:
        new_label = QLabel('Elapsed time [s]:')
        self.protocol_control_grid.addWidget(new_label, 1, 0)
        self.elapsed_time_label = QLabel()
        self.elapsed_time_label.setFrameShadow(QFrame.Shadow(1))
        self.protocol_control_grid.addWidget(self.elapsed_time_label, 1, 1)
        self.elapsed_time_label.setText('')

        # Elapsed timer for protocol
        self.progress_timer = QTimer()
        self.progress_timer.setSingleShot(False)
        self.progress_timer.setInterval(1000)
        self.progress_timer.timeout.connect(self.update_run_progress)

        # Epoch count refresh button:
        new_label = QLabel('Epoch count:')
        self.protocol_control_grid.addWidget(new_label, 1, 2)
        # Epoch count window:
        self.epoch_count_label = QLabel()
        self.epoch_count_label.setFrameShadow(QFrame.Shadow(1))
        self.protocol_control_grid.addWidget(self.epoch_count_label, 1, 3)
        self.epoch_count_label.setText('')

        # View button:
        self.view_button = QPushButton("View", self)
        self.view_button.clicked.connect(self.on_pressed_button)
        self.protocol_control_grid.addWidget(self.view_button, 2, 0)

        # Record button:
        self.record_button = QPushButton("Record", self)
        self.record_button.clicked.connect(self.on_pressed_button)
        self.protocol_control_grid.addWidget(self.record_button, 2, 1)

        # Pause/resume button:
        self.pause_button = QPushButton("Pause", self)
        self.pause_button.clicked.connect(self.on_pressed_button)
        self.protocol_control_grid.addWidget(self.pause_button, 2, 2)

        # Stop button:
        stop_button = QPushButton("Stop", self)
        stop_button.clicked.connect(self.on_pressed_button)
        self.protocol_control_grid.addWidget(stop_button, 2, 3)

        # Enter note button:
        note_button = QPushButton("Enter note", self)
        note_button.clicked.connect(self.on_pressed_button)
        self.protocol_control_grid.addWidget(note_button, 3, 0)

        # Notes field:
        self.notes_edit = QTextEdit()
        self.notes_edit.setFixedHeight(30)
        self.protocol_control_grid.addWidget(self.notes_edit, 3, 1, 1, 3)

        # # # TAB 2: Current subject metadata information
        # # subject info:
        new_label = QLabel('Load existing subject')
        self.existing_subject_input = QComboBox()
        self.existing_subject_input.activated.connect(self.on_selected_existing_subject)
        self.data_form.addRow(new_label, self.existing_subject_input)
        self.update_existing_subject_input()

        new_label = QLabel('Current Subject info:')
        new_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.data_form.addRow(new_label)

        # Only built-ins are "subject_id," "age" and "notes"
        # subject ID:
        new_label = QLabel('subject ID:')
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

        # Create subject button
        create_subject_button = QPushButton("Create subject", self)
        create_subject_button.clicked.connect(self.on_created_subject)
        self.data_form.addRow(create_subject_button)

        # # # TAB 3: FILE tab - init, load, close etc. h5 file
        # Data file info
        # Initialize new experiment button
        initialize_button = QPushButton("Initialize experiment", self)
        initialize_button.clicked.connect(self.on_pressed_button)
        new_label = QLabel('Current data file:')
        self.file_form.addRow(initialize_button, new_label)
        # Load existing experiment button
        load_button = QPushButton("Load experiment", self)
        load_button.clicked.connect(self.on_pressed_button)
        # Label with current expt file
        self.current_experiment_label = QLabel('')
        self.file_form.addRow(load_button, self.current_experiment_label)

        # # # # Data browser: # # # # # # # #
        self.group_tree = QTreeWidget(self)
        self.group_tree.setHeaderHidden(True)
        self.group_tree.itemClicked.connect(self.on_tree_item_clicked)
        self.file_form.addRow(self.group_tree)

        # Attribute table
        self.table_attributes = QTableWidget()
        self.table_attributes.setStyleSheet("")
        self.table_attributes.setColumnCount(2)
        self.table_attributes.setObjectName("table_attributes")
        self.table_attributes.setRowCount(0)
        item = QTableWidgetItem()
        font = QtGui.QFont()
        font.setPointSize(10)
        item.setFont(font)
        item.setBackground(QtGui.QColor(121, 121, 121))
        brush = QtGui.QBrush(QtGui.QColor(91, 91, 91))
        brush.setStyle(Qt.BrushStyle.SolidPattern)
        item.setForeground(brush)
        self.table_attributes.setHorizontalHeaderItem(0, item)
        item = QTableWidgetItem()
        item.setBackground(QtGui.QColor(123, 123, 123))
        brush = QtGui.QBrush(QtGui.QColor(91, 91, 91))
        brush.setStyle(Qt.BrushStyle.SolidPattern)
        item.setForeground(brush)
        self.table_attributes.setHorizontalHeaderItem(1, item)
        self.table_attributes.horizontalHeader().setCascadingSectionResizes(True)
        self.table_attributes.horizontalHeader().setDefaultSectionSize(200)
        self.table_attributes.horizontalHeader().setHighlightSections(False)
        self.table_attributes.horizontalHeader().setSortIndicatorShown(True)
        self.table_attributes.horizontalHeader().setStretchLastSection(True)
        self.table_attributes.verticalHeader().setVisible(False)
        self.table_attributes.verticalHeader().setHighlightSections(False)
        self.table_attributes.setMinimumSize(QtCore.QSize(200, 400))
        item = self.table_attributes.horizontalHeaderItem(0)
        item.setText("Attribute")
        item = self.table_attributes.horizontalHeaderItem(1)
        item.setText("Value")

        self.table_attributes.itemChanged.connect(self.update_attrs_to_file)

        self.file_form.addRow(self.table_attributes)

        # Add all layouts to window
        self.layout.addWidget(self.tabs)
        self.protocol_tab.setLayout(self.protocol_tab_layout)
        self.protocol_selector_box.setLayout(self.protocol_selector_grid)
        self.protocol_control_box.setLayout(self.protocol_control_grid)
        self.protocol_box.setLayout(self.parameter_grid)
        self.data_tab.setLayout(self.data_form)
        self.file_tab.setLayout(self.file_form)
        self.setWindowTitle(f"Stimpack Experiment ({self.cfg['current_cfg_name'].split('.')[0]}: {self.cfg['current_rig_name']})")

        # Resize window based on protocol tab
        self.update_window_width()

        self.show()

    def on_selected_protocol_ID(self, text):
        if text == "(select a protocol to run)":
            return
        # Clear old params list from grid
        self.reset_layout()

        # initialize the selected protocol object
        prot_names = [x.__name__ for x in self.available_protocols]
        self.protocol_object = self.available_protocols[prot_names.index(text)](self.cfg)

        # update display lists of run & protocol parameters
        self.protocol_object.load_parameter_presets()
        self.protocol_object.select_protocol_preset(name='Default')
        self.protocol_object.prepare_run()
        self.update_parameter_preset_selector()
        self.update_parameters_input()
        self.update_window_width()
        self.show()

        self.update_parameters_from_fillable_fields(compute_epoch_parameters=True)
        self.status = Status.STANDBY
        self.status_label.setText('Ready')

    def on_pressed_button(self):
        sender = self.sender()
        if sender.text() == 'Record':
            if (self.data.experiment_file_exists() and self.data.current_subject_exists()):
                self.send_run(save_metadata_flag=True)
            else:
                msg = QMessageBox()
                msg.setIcon(QMessageBox.Warning)
                msg.setText("You have not initialized a data file and/or subject yet")
                msg.setInformativeText("You can show stimuli by clicking the View button, but no metadata will be saved")
                msg.setWindowTitle("No experiment file and/or subject")
                msg.setDetailedText("Initialize or load both an experiment file and a subject if you'd like to save your metadata")
                msg.setStandardButtons(QMessageBox.Ok)
                msg.exec_()

        elif sender.text() == 'View':
            self.send_run(save_metadata_flag=False)
            self.pause_button.setText('Pause')

        elif sender.text() == 'Pause':
            self.client.pause_run()
            self.pause_button.setText('Resume')
            self.status_label.setText('Paused...')
            self.show()

        elif sender.text() == 'Resume':
            self.client.resume_run()
            self.pause_button.setText('Pause')
            self.status_label.setText('Viewing...')
            self.show()

        elif sender.text() == 'Stop':
            self.client.stop_run()
            self.pause_button.setText('Pause')

        elif sender.text() == 'Enter note':
            self.note_text = self.notes_edit.toPlainText()
            if self.data.experiment_file_exists() is True:
                self.data.create_note(self.note_text)  # save note to expt file
                self.notes_edit.clear()  # clear notes box
            else:
                self.notes_edit.setTextColor(QtGui.QColor("Red"))

        elif sender.text() == 'Save preset':
            self.update_parameters_from_fillable_fields(compute_epoch_parameters=False)  # get the state of the param input from GUI
            start_name = self.parameter_preset_comboBox.currentText()
            if start_name == 'Default':
                start_name = ''

            text, _ = QInputDialog.getText(self, "Save preset", "Preset Name:", QLineEdit.Normal, start_name)

            self.protocol_object.update_parameter_presets(text) # TODO update GUI
            self.update_parameter_preset_selector()
            self.parameter_preset_comboBox.setCurrentIndex(self.parameter_preset_comboBox.findText(text))

        elif sender.text() == 'Initialize experiment':
            dialog = QDialog()

            dialog.ui = InitializeExperimentGUI(parent=dialog)
            dialog.ui.setupUI(self, dialog)
            dialog.setFixedSize(300, 200)
            dialog.exec_()

            self.data.experiment_file_name = dialog.ui.le_filename.text()
            self.data.data_directory = dialog.ui.le_data_directory.text()
            self.data.experimenter = dialog.ui.le_experimenter.text()

            self.update_existing_subject_input()
            self.populate_groups()

        elif sender.text() == 'Load experiment':
            if os.path.isdir(self.data.data_directory):
                filePath, _ = QFileDialog.getOpenFileName(self, "Open file", self.data.data_directory)
            else:
                filePath, _ = QFileDialog.getOpenFileName(self, "Open file")
            self.data.experiment_file_name = os.path.split(filePath)[1].split('.')[0]
            self.data.data_directory = os.path.split(filePath)[0]

            if self.data.experiment_file_name != '':
                self.current_experiment_label.setText(self.data.experiment_file_name)
                # update series count to reflect already-collected series
                self.data.reload_series_count()
                self.series_counter_input.setValue(self.data.get_highest_series_count() + 1)
                self.update_existing_subject_input()
                self.populate_groups()

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

    def reset_layout(self):
        for ii in range(self.parameter_grid.rowCount()):
            item = self.parameter_grid.itemAtPosition(ii, 0)
            if item is not None:
                item.widget().deleteLater()
            item = self.parameter_grid.itemAtPosition(ii, 1)
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

            self.parameter_grid.addWidget(QLabel(key + ':'), input_field_row, 0)
            self.parameter_grid.addWidget(input_field, input_field_row, 1, 1, 2)
            
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
            self.parameter_grid.addWidget(new_label, self.parameter_grid_row_ct, 0) # add label after run_params
            self.parameter_grid_row_ct = +1 # +1 for label 'Run parameters:'

            self.run_parameter_input = {}  # clear old input params dict        
            for key, value in self.protocol_object.run_parameters.items():
                self.run_parameter_input[key] = make_parameter_input_field(key, value, self.parameter_grid_row_ct)
                self.parameter_grid_row_ct += 1
                set_validator(self.run_parameter_input[key], type(value))

        def update_protocol_parameters_input():
            # update display window to show parameters for this protocol
            new_label = QLabel('Protocol parameters:')
            new_label.setStyleSheet('font-weight: bold; text-decoration: underline; margin-top: 10px;')
            self.parameter_grid.addWidget(new_label, self.parameter_grid_row_ct, 0) # add label after run_params
            self.parameter_grid_row_ct += 1 # +1 for label 'Protocol parameters:'
            
            self.protocol_parameter_input = {}  # clear old input params dict
            for key, value in self.protocol_object.protocol_parameters.items():
                self.protocol_parameter_input[key] = make_parameter_input_field(key, value, self.parameter_grid_row_ct)
                self.parameter_grid_row_ct += 1

        self.parameter_grid_row_ct = 0
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
        subject_data = self.data.get_existing_subject_data()
        self.populate_subject_metadata_fields(subject_data[index])
        self.data.current_subject = subject_data[index].get('subject_id')

    def update_existing_subject_input(self):
        self.existing_subject_input.clear()
        for subject_data in self.data.get_existing_subject_data():
            self.existing_subject_input.addItem(subject_data['subject_id'])
        index = self.existing_subject_input.findText(self.data.current_subject)
        if index >= 0:
            self.existing_subject_input.setCurrentIndex(index)

    def populate_subject_metadata_fields(self, subject_data_dict):
        self.subject_id_input.setText(subject_data_dict['subject_id'])
        self.subject_age_input.setValue(subject_data_dict['age'])
        self.subject_notes_input.setText(subject_data_dict['notes'])
        for key in self.subject_metadata_inputs:
            self.subject_metadata_inputs[key].setCurrentText(subject_data_dict[key])

    def on_entered_series_count(self):
        self.data.update_series_count(self.series_counter_input.value())
        if self.data.experiment_file_exists() is True:
            if self.data.get_series_count() <= self.data.get_highest_series_count():
                self.series_counter_input.setStyleSheet("background-color: rgb(255, 0, 0);")
            else:
                self.series_counter_input.setStyleSheet("background-color: rgb(255, 255, 255);")

    def send_run(self, save_metadata_flag=True):
        # check to make sure a protocol has been selected
        if self.protocol_object.__class__.__name__ == 'BaseProtocol':
            self.status_label.setText('Select a protocol')
            return  # no protocol exists, don't send anything

        # check to make sure the series count does not already exist
        if save_metadata_flag:
            self.data.update_series_count(self.series_counter_input.value())
            if (self.data.get_series_count() in self.data.get_existing_series()):
                self.series_counter_input.setStyleSheet("background-color: rgb(255, 0, 0);")
                self.status_label.setText('Select an unused series number')
                return  # group already exists, don't send anything
            else:
                self.series_counter_input.setStyleSheet("background-color: rgb(255, 255, 255);")

        # Populate parameters from filled fields
        if self.mid_parameter_edit:
            self.update_parameters_from_fillable_fields(compute_epoch_parameters=True)

        # start the epoch run thread:
        self.run_series_thread = runSeriesThread(self.protocol_object,
                                                 self.data,
                                                 self.client,
                                                 save_metadata_flag)

        self.run_series_thread.finished.connect(lambda: self.run_finished(save_metadata_flag))
        self.run_series_thread.started.connect(lambda: self.run_started(save_metadata_flag))

        self.run_series_thread.start()

    def run_started(self, save_metadata_flag):
        # Lock the view and run buttons to prevent spinning up multiple threads
        self.view_button.setEnabled(False)
        self.record_button.setEnabled(False)
        if save_metadata_flag:
            self.status_label.setText('Recording series ' + str(self.data.get_series_count()))
            self.status = Status.RECORDING
        else:
            self.status_label.setText('Viewing...')
            self.status = Status.VIEWING
        
        self.run_start_time = time.time()
        self.progress_timer.start()

    def run_finished(self, save_metadata_flag):
        # re-enable view/record buttons
        self.view_button.setEnabled(True)
        self.record_button.setEnabled(True)

        self.status_label.setText('Ready')
        self.status = Status.STANDBY
        self.pause_button.setText('Pause')

        self.progress_timer.stop()

        if save_metadata_flag:
            self.update_existing_subject_input()
            # Advance the series_count:
            self.data.advance_series_count()
            self.series_counter_input.setValue(self.data.get_series_count())
            self.populate_groups()
            
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

            # Base case 2: number
            elif is_number(s):
                return eval(s)

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
                run_parameter_input_text = self.run_parameter_input[key].text()
                self.protocol_object.run_parameters[key] = float(run_parameter_input_text) if len(run_parameter_input_text)>0 else 0

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

        self.protocol_object.prepare_run(recompute_epoch_parameters=compute_epoch_parameters)
        self.update_run_progress()

        self.mid_parameter_edit = False

    def update_run_progress(self):
        if self.status == Status.STANDBY:
            elapsed_time = 0
            epoch_count = 0
        else:
            elapsed_time = int(time.time() - self.run_start_time)
            epoch_count = self.protocol_object.num_epochs_completed

        self.elapsed_time_label.setText(f'{elapsed_time} / {self.protocol_object.est_run_time:.0f}')
        self.epoch_count_label.setText(f'{epoch_count} / {self.protocol_object.run_parameters.get("num_epochs", "?")}')

    def populate_groups(self):
        file_path = os.path.join(self.data.data_directory, self.data.experiment_file_name + '.hdf5')
        group_dset_dict = h5io.get_hierarchy(file_path, additional_exclusions='rois')
        self._populateTree(self.group_tree, group_dset_dict)

    def _populateTree(self, widget, dict):
        widget.clear()
        self.fill_item(widget.invisibleRootItem(), dict)

    def fill_item(self, item, value):
        item.setExpanded(True)
        if type(value) is dict:
            for key, val in sorted(value.items()):
                child = QTreeWidgetItem()
                child.setText(0, key)
                item.addChild(child)
                self.fill_item(child, val)
        elif type(value) is list:
            for val in value:
                child = QTreeWidgetItem()
                item.addChild(child)
                if type(val) is dict:
                    child.setText(0, '[dict]')
                    self.fill_item(child, val)
                elif type(val) is list:
                    child.setText(0, '[list]')
                    self.fill_item(child, val)
                else:
                    child.setText(0, val)
                child.setExpanded(True)
        else:
            child = QTreeWidgetItem()
            child.setText(0, value)
            item.addChild(child)

    def on_tree_item_clicked(self, item, column):
        file_path = os.path.join(self.data.data_directory, self.data.experiment_file_name + '.hdf5')
        group_path = h5io.get_path_from_tree_item(self.group_tree.selectedItems()[0])

        if group_path != '':
            attr_dict = h5io.get_attributes_from_group(file_path, group_path)
            if 'series' in group_path.split('/')[-1]:
                editable_values = False  # don't let user edit epoch parameters
            else:
                editable_values = True
            self.populate_attrs(attr_dict = attr_dict, editable_values = editable_values)

    def populate_attrs(self, attr_dict=None, editable_values=False):
        """ Populate attribute for currently selected group """
        self.table_attributes.blockSignals(True)  # block udpate signals for auto-filled forms
        self.table_attributes.setRowCount(0)
        self.table_attributes.setColumnCount(2)
        self.table_attributes.setSortingEnabled(False)

        if attr_dict:
            for num, key in enumerate(attr_dict):
                self.table_attributes.insertRow(self.table_attributes.rowCount())
                key_item = QTableWidgetItem(key)
                key_item.setFlags(QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled)
                self.table_attributes.setItem(num, 0, key_item)

                val_item = QTableWidgetItem(str(attr_dict[key]))
                if editable_values:
                    val_item.setFlags(QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEditable | QtCore.Qt.ItemIsEnabled)
                else:
                    val_item.setFlags(QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled)
                self.table_attributes.setItem(num, 1, val_item)

        self.table_attributes.blockSignals(False)

    def update_attrs_to_file(self, item):
        file_path = os.path.join(self.data.data_directory, self.data.experiment_file_name + '.hdf5')
        group_path = h5io.get_path_from_tree_item(self.group_tree.selectedItems()[0])

        attr_key = self.table_attributes.item(item.row(), 0).text()
        attr_val = item.text()

        # update attr in file
        h5io.change_attribute(file_path, group_path, attr_key, attr_val)
        print('Changed attr {} to = {}'.format(attr_key, attr_val))

    def update_window_width(self):
        self.resize(100, self.height())
        window_width = self.protocol_box.sizeHint().width() + self.protocol_params_scroll_box.verticalScrollBar().sizeHint().width() + 40
        self.resize(window_width, self.height())

# # # Other accessory classes. For data file initialization and threading # # # #
class InitializeExperimentGUI(QWidget):
    def setupUI(self, experiment_gui_object, parent=None):
        super(InitializeExperimentGUI, self).__init__(parent)
        self.parent = parent
        self.experiment_gui_object = experiment_gui_object
        layout = QFormLayout()

        label_filename = QLabel('File Name:')
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
        self.experiment_gui_object.data.experiment_file_name = self.le_filename.text()
        self.experiment_gui_object.data.data_directory = self.le_data_directory.text()
        self.experiment_gui_object.data.experimenter = self.le_experimenter.text()

        if os.path.isfile(os.path.join(self.experiment_gui_object.data.data_directory, self.experiment_gui_object.data.experiment_file_name) + '.hdf5'):
           self.label_status.setText('Experiment file already exists!')
        elif not os.path.isdir(self.experiment_gui_object.data.data_directory):
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
        super(InitializeRigGUI, self).__init__(parent)
        self.parent = parent
        self.experiment_gui_object = experiment_gui_object

        self.cfg_name = None
        self.cfg = None
        self.available_rig_configs = []
    
        self.layout = QFormLayout()
        if window_size is not None and len(window_size) == 2:
            self.resize(*window_size)

        self.labpack_dir = config_tools.get_labpack_directory()

        self.pb_labpack_dir = QPushButton('Labpack Dir')
        self.pb_labpack_dir.clicked.connect(self.on_pressed_labpack_dir_button)
        self.le_labpack_dir = QLineEdit(self.labpack_dir)
        self.le_labpack_dir.setReadOnly(True)
        self.layout.addRow(self.pb_labpack_dir, self.le_labpack_dir)

        label_config = QLabel('Config')
        self.config_combobox = QComboBox()
        self.config_combobox.activated.connect(self.on_selected_config)
        self.layout.addRow(label_config, self.config_combobox)

        label_rigname = QLabel('Rig Config')
        self.rig_combobox = QComboBox()
        self.layout.addRow(label_rigname, self.rig_combobox)
        self.update_available_rigs()

        self.pb_enter = QPushButton('Enter')
        self.pb_enter.clicked.connect(self.on_pressed_enter_button)
        self.layout.addRow(QLabel(''))
        self.layout.addRow(self.pb_enter)

        self.setLayout(self.layout)

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
        if len(config_tools.get_available_config_files(self.labpack_dir)) > 0:
            for choiceID in config_tools.get_available_config_files(self.labpack_dir):
                self.config_combobox.addItem(choiceID)
        else:
            self.config_combobox.addItem('default')
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
        self.show()

    def on_pressed_enter_button(self):
        # Store the rig and cfg names in the cfg dict
        self.cfg['current_rig_name'] = self.rig_combobox.currentText()
        self.cfg['current_cfg_name'] = self.cfg_name

        # Pass cfg up to experiment GUI object
        self.experiment_gui_object.cfg = self.cfg

        self.close()
        self.parent.close()


class runSeriesThread(QThread):
    # https://nikolak.com/pyqt-threading-tutorial/
    # https://stackoverflow.com/questions/41848769/pyqt5-object-has-no-attribute-connect
    def __init__(self, protocol_object, data, client, save_metadata_flag):
        QThread.__init__(self)
        self.protocol_object = protocol_object
        self.data = data
        self.client = client
        self.save_metadata_flag = save_metadata_flag

    def __del__(self):
        self.wait()

    def _send_run(self):
        self.client.start_run(self.protocol_object, self.data, save_metadata_flag=self.save_metadata_flag)

    def run(self):
        self._send_run()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName('Stimpack Experiment')
    app.setWindowIcon(QtGui.QIcon(ICON_PATH))
    ex = ExperimentGUI()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
