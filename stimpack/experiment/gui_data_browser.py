#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Widget for browsing an experiment's contents on the GUI's File tab.

A data backend supplies its own browser, or none: BaseData.make_data_browser() returns the widget
and the GUI simply places whatever it gets. That keeps format-specific presentation with the format
rather than growing a branch in gui.py per backend -- which is the shape that produced a forked
gui_nwb.py in the first place.

One browser serves all three backends. An .nwb file is HDF5 underneath, so the same tree reads it;
what differs is that an NWB experiment is a directory of files rather than one, and that its
attributes must not be edited (pynwb validates a schema that a hand-edited attribute can break).
Both differences are answered by the backend -- browsable_files() and browser_is_editable -- rather
than by the browser knowing which format it is looking at.
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
    where trial parameters are a record of what was actually presented.
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
        """The single file being browsed, for a backend that has one. None when there are several."""
        files = self.data.browsable_files()
        return files[0][1] if len(files) == 1 else None

    def refresh(self):
        """Re-read the experiment. Called by the GUI after anything that changes it.

        One file is shown as its own contents, with no wrapper node -- the extra level would be
        noise when there is only ever one. Several are shown one node each, labelled by file name,
        which is the only way a directory-per-experiment format can be walked at all.
        """
        self._files = {}
        files = [(label, path) for label, path in self.data.browsable_files() if os.path.exists(path)]

        if len(files) == 1:
            label, path = files[0]
            self._files[None] = path
            hierarchy = h5io.get_hierarchy(path, additional_exclusions='rois')
        else:
            hierarchy = {}
            for label, path in files:
                self._files[label] = path
                hierarchy[label] = h5io.get_hierarchy(path, additional_exclusions='rois')

        self._populateTree(self.group_tree, hierarchy)

    def file_and_path_for(self, group_path):
        """Split a tree path into the file it names and the path within that file.

        With one file the whole tree path is the group path; with several, its first component is
        the file, which is why the file is resolved here rather than assumed by the caller.
        """
        if None in self._files:
            return self._files[None], group_path
        head, _, rest = group_path.lstrip('/').partition('/')
        return self._files.get(head), '/' + rest

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
        tree_path = h5io.get_path_from_tree_item(self.group_tree.selectedItems()[0])
        if tree_path == '':
            return

        file_path, group_path = self.file_and_path_for(tree_path)
        if file_path is None or group_path in ('', '/'):
            self.populate_attrs(attr_dict={}, editable_values=False)   # a file node itself
            return

        attr_dict = h5io.get_attributes_from_group(file_path, group_path)
        # A series' attributes record what was actually presented, so they are read-only whatever
        # the backend allows.
        editable_values = (self.data.browser_is_editable
                           and 'series' not in group_path.split('/')[-1])
        self.populate_attrs(attr_dict=attr_dict, editable_values=editable_values)

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
        # Refuse rather than trust the table's edit flags: this writes to the user's data file, and
        # a backend that declares itself read-only (NWB, whose schema pynwb validates) must not be
        # written to through any path that reaches here.
        if not self.data.browser_is_editable:
            return

        tree_path = h5io.get_path_from_tree_item(self.group_tree.selectedItems()[0])
        file_path, group_path = self.file_and_path_for(tree_path)
        if file_path is None:
            return

        attr_key = self.table_attributes.item(item.row(), 0).text()
        attr_val = item.text()

        h5io.change_attribute(file_path, group_path, attr_key, attr_val)
        print('Changed attr {} to = {}'.format(attr_key, attr_val))
