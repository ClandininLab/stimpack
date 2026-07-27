#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Widget for browsing an experiment's contents on the GUI's File tab.

A data backend supplies its own browser, or none: BaseData.make_data_browser() returns the widget
and the GUI simply places whatever it gets. That keeps format-specific presentation with the format
rather than growing a branch in gui.py per backend -- which is the shape that produced a forked
gui_nwb.py in the first place.

Only Hdf5DataBrowser exists today. NWB has no browser, because an NWB experiment is a directory of
separate files rather than one walkable tree; NWBData declares supports_data_browser = False and
the File tab simply omits these widgets.
"""
import os

import PyQt6.QtCore as QtCore
from PyQt6.QtCore import Qt
import PyQt6.QtGui as QtGui
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem,
                             QTableWidget, QTableWidgetItem)

from stimpack.experiment.util import h5io


class Hdf5DataBrowser(QWidget):
    """
    Tree of groups plus a table of the selected group's attributes, read with util.h5io.

    Attribute values are editable and written straight back to the file, except under a series,
    where epoch parameters are a record of what was actually presented.
    """

    def __init__(self, data, parent=None):
        """
        :param data: the experiment's data object; read for its directory and file name, so the
                     browser follows the GUI when a different experiment is loaded.
        """
        super().__init__(parent)
        self.data = data

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.group_tree = QTreeWidget(self)
        self.group_tree.setHeaderHidden(True)
        self.group_tree.itemClicked.connect(self.on_tree_item_clicked)
        layout.addWidget(self.group_tree)

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

        layout.addWidget(self.table_attributes)

    @property
    def file_path(self):
        return os.path.join(self.data.data_directory, self.data.experiment_file_name + '.hdf5')

    def refresh(self):
        """Re-read the experiment file. Called by the GUI after anything that changes it."""
        group_dset_dict = h5io.get_hierarchy(self.file_path, additional_exclusions='rois')
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
        group_path = h5io.get_path_from_tree_item(self.group_tree.selectedItems()[0])

        if group_path != '':
            attr_dict = h5io.get_attributes_from_group(self.file_path, group_path)
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
                key_item.setFlags(QtCore.Qt.ItemFlag.ItemIsSelectable | QtCore.Qt.ItemFlag.ItemIsEnabled)
                self.table_attributes.setItem(num, 0, key_item)

                val_item = QTableWidgetItem(str(attr_dict[key]))
                if editable_values:
                    val_item.setFlags(QtCore.Qt.ItemFlag.ItemIsSelectable | QtCore.Qt.ItemFlag.ItemIsEditable | QtCore.Qt.ItemFlag.ItemIsEnabled)
                else:
                    val_item.setFlags(QtCore.Qt.ItemFlag.ItemIsSelectable | QtCore.Qt.ItemFlag.ItemIsEnabled)
                self.table_attributes.setItem(num, 1, val_item)

        self.table_attributes.blockSignals(False)

    def update_attrs_to_file(self, item):
        group_path = h5io.get_path_from_tree_item(self.group_tree.selectedItems()[0])

        attr_key = self.table_attributes.item(item.row(), 0).text()
        attr_val = item.text()

        # update attr in file
        h5io.change_attribute(self.file_path, group_path, attr_key, attr_val)
        print('Changed attr {} to = {}'.format(attr_key, attr_val))
