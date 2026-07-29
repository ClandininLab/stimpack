"""
Tests for the File tab's HDF5 data browser.

This code reads and *writes* the user's experiment file -- editing an attribute in the table
changes it on disk -- and had no test at all while it lived inside ExperimentGUI. Pulling it out
into its own widget made it reachable.
"""
import h5py
import pytest

pytestmark = pytest.mark.gui


@pytest.fixture
def experiment(tmp_path):
    """A real HDF5 experiment with two subjects, one of which has a series with epochs."""
    from stimpack.experiment.data import BaseData

    class Proto:
        run_parameters = {'num_trials': 2, 'idle_color': 0.0}
        protocol_parameters = {'angle': [0, 90]}
        trial_stim_parameters = {'name': 'DriftingSquareGrating'}
        trial_protocol_parameters = {'pre_time': 1.0, 'stim_time': 2.0, 'tail_time': 1.0}
        num_trials_completed = 0

    data = BaseData(cfg={})
    data.data_directory = str(tmp_path)
    data.experiment_file_name = 'browsable'
    data.initialize_experiment_file()
    data.create_subject({'subject_id': 'fly1', 'age': 3, 'notes': 'healthy'})
    proto = Proto()
    data.create_series(proto)
    data.create_trial(proto)
    data.end_trial(proto)
    data.end_series(proto)
    data.create_subject({'subject_id': 'fly2', 'age': 5, 'notes': ''})
    return data


@pytest.fixture
def browser(qapp, experiment):
    b = experiment.make_data_browser()
    b.refresh()
    yield b
    b.close()


def tree_labels(item):
    """Every label under a tree item, depth first."""
    out = []
    for i in range(item.childCount()):
        child = item.child(i)
        out.append(child.text(0))
        out.extend(tree_labels(child))
    return out


def select(browser, path):
    """Select the tree item at e.g. ['Subjects', 'fly1'] and fire the click handler."""
    item = browser.group_tree.invisibleRootItem()
    for name in path:
        item = next(item.child(i) for i in range(item.childCount())
                    if item.child(i).text(0) == name)
    browser.group_tree.setCurrentItem(item)
    browser.on_tree_item_clicked(item, 0)
    return item


def table_contents(browser):
    return {browser.table_attributes.item(r, 0).text(): browser.table_attributes.item(r, 1).text()
            for r in range(browser.table_attributes.rowCount())}


# --- the tree ------------------------------------------------------------------------------------

def test_refresh_shows_the_experiment_hierarchy(browser):
    labels = tree_labels(browser.group_tree.invisibleRootItem())
    assert 'Subjects' in labels
    assert 'fly1' in labels and 'fly2' in labels
    assert browser.data.SERIES_GROUP in labels and 'series_001' in labels


def test_noisy_groups_are_excluded(browser):
    """h5io hides the bulk data groups; the browser is for metadata."""
    labels = tree_labels(browser.group_tree.invisibleRootItem())
    for hidden in (browser.data.TRIALS_GROUP, 'acquisition', 'stimulus_timing', 'rois'):
        assert hidden not in labels


def test_refresh_rebuilds_rather_than_appending(browser, experiment):
    """refresh() is called after every subject, series and note, so a tree that appended instead
    of rebuilding would show each subject once per refresh."""
    experiment.create_subject({'subject_id': 'fly3', 'age': 1, 'notes': ''})
    assert 'fly3' not in tree_labels(browser.group_tree.invisibleRootItem())

    browser.refresh()
    labels = tree_labels(browser.group_tree.invisibleRootItem())
    assert 'fly3' in labels
    assert labels.count('fly1') == 1 and labels.count('Subjects') == 1

    browser.refresh()                       # and again, for good measure
    labels = tree_labels(browser.group_tree.invisibleRootItem())
    assert labels.count('fly1') == 1 and labels.count('fly3') == 1


def test_file_path_follows_the_data_object(browser, experiment, tmp_path):
    """The browser reads the data object each time rather than caching a path, so loading a
    different experiment re-points it without rebuilding the widget."""
    assert browser.file_path == str(tmp_path / 'browsable.hdf5')
    experiment.experiment_file_name = 'something_else'
    assert browser.file_path == str(tmp_path / 'something_else.hdf5')


# --- the attribute table -------------------------------------------------------------------------

def test_clicking_a_subject_shows_its_metadata(browser):
    select(browser, ['Subjects', 'fly1'])
    attrs = table_contents(browser)
    assert attrs['subject_id'] == 'fly1'
    assert attrs['age'] == '3'
    assert attrs['notes'] == 'healthy'


def test_selecting_another_group_replaces_the_table(browser):
    select(browser, ['Subjects', 'fly1'])
    assert table_contents(browser)['subject_id'] == 'fly1'
    select(browser, ['Subjects', 'fly2'])
    assert table_contents(browser)['subject_id'] == 'fly2'      # not appended to the first


def test_subject_attributes_are_editable(browser):
    from PyQt6.QtCore import Qt
    select(browser, ['Subjects', 'fly1'])
    value_flags = browser.table_attributes.item(0, 1).flags()
    assert value_flags & Qt.ItemFlag.ItemIsEditable


def test_series_attributes_are_read_only(browser):
    """A series records what was actually presented, so its parameters must not be editable."""
    from PyQt6.QtCore import Qt
    select(browser, ['Subjects', 'fly1', browser.data.SERIES_GROUP, 'series_001'])
    attrs = table_contents(browser)
    assert 'protocol_ID' in attrs
    for row in range(browser.table_attributes.rowCount()):
        assert not (browser.table_attributes.item(row, 1).flags() & Qt.ItemFlag.ItemIsEditable)


def test_keys_are_never_editable(browser):
    from PyQt6.QtCore import Qt
    select(browser, ['Subjects', 'fly1'])
    for row in range(browser.table_attributes.rowCount()):
        assert not (browser.table_attributes.item(row, 0).flags() & Qt.ItemFlag.ItemIsEditable)


# --- editing writes to the file ------------------------------------------------------------------

def test_editing_a_value_writes_it_back_to_the_file(browser, experiment):
    select(browser, ['Subjects', 'fly1'])
    row = next(r for r in range(browser.table_attributes.rowCount())
               if browser.table_attributes.item(r, 0).text() == 'notes')

    browser.table_attributes.item(row, 1).setText('edited in the browser')   # fires itemChanged

    with h5py.File(browser.file_path, 'r') as f:
        assert f['/Subjects/fly1'].attrs['notes'] == 'edited in the browser'


def test_populating_the_table_does_not_write_to_the_file(browser):
    """The table is filled in programmatically, which fires itemChanged for every cell. Those
    must be suppressed, or merely clicking a group would rewrite every attribute as a string."""
    with h5py.File(browser.file_path, 'r') as f:
        before = dict(f['/Subjects/fly1'].attrs)

    select(browser, ['Subjects', 'fly1'])

    with h5py.File(browser.file_path, 'r') as f:
        after = dict(f['/Subjects/fly1'].attrs)
    assert after == before
    assert type(after['age']) is type(before['age'])     # and not turned into a string
