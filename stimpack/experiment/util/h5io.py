"""
Read-only helpers for browsing an HDF5 experiment file's group hierarchy and attributes.

Used by the GUI's data browser (:mod:`stimpack.experiment.gui_data_browser`). Bulk data groups
are excluded from the hierarchy, since this is for inspecting metadata rather than reading data.
"""
import h5py
import numpy as np

# H5io fxns
def get_hierarchy(file_path, additional_exclusions=None):
    with h5py.File(file_path, 'r') as experiment_file:
        hierarchy = recursively_load_dict_contents_from_group(experiment_file, '/', additional_exclusions=additional_exclusions)
    return hierarchy


def get_path_from_tree_item(tree_item):
    path = tree_item.text(0)
    parent = tree_item.parent()
    while parent is not None:
        path = parent.text(0) + '/' + path
        parent = parent.parent()
    path = '/' + path
    return path

def get_attributes_from_group(file_path, group_path):
    # see https://github.com/CCampJr/LazyHDF5
    # Opened read-only: this only reads. 'r+' takes an HDF5 write lock, which fails outright on a
    # read-only file (archived data, a read-only share) and can fail or block while another process
    # has the file open -- i.e. browsing metadata for the experiment currently being written.
    with h5py.File(file_path, 'r') as experiment_file:
        group = experiment_file[group_path]
        attr_dict = {}
        for at in group.attrs:
            attr_dict[at] = group.attrs[at]
        return attr_dict

def change_attribute(file_path, group_path, attr_key, attr_val):
    # see https://github.com/CCampJr/LazyHDF5
    # TODO: try to keep the type the same?
    with h5py.File(file_path, 'r+') as experiment_file:
        group = experiment_file[group_path]
        group.attrs[attr_key] = attr_val


def recursively_load_dict_contents_from_group(h5file, path, additional_exclusions=None):
    # https://codereview.stackexchange.com/questions/120802/recursively-save-python-dictionaries-to-hdf5-files-using-h5py
    # 'trials' and 'epochs' are the same group under stimpack's new and old names -- one file
    # browser opens files written by either backend, so both are hidden. Per-trial groups are what
    # makes a tree unreadable: one node per presentation, hundreds per series.
    exclusions = ['acquisition', 'Client', 'trials', 'epochs', 'stimulus_timing', 'roipath', 'subpath']
    if additional_exclusions is not None:
        # extend, not append: appending a list put the list itself in as one element, and the
        # membership test below then did `['a', 'b'] in key`, which raises TypeError. So the
        # documented list-valued form never worked -- only a bare string did.
        if isinstance(additional_exclusions, str):
            additional_exclusions = [additional_exclusions]
        exclusions.extend(additional_exclusions)
    ans = {}
    for key, item in h5file[path].items():
        if isinstance(item, h5py._hl.dataset.Dataset):
            pass
        elif isinstance(item, h5py._hl.group.Group):
            if np.any([x in key for x in exclusions]):
                pass
            else:
                ans[key] = recursively_load_dict_contents_from_group(h5file, path + key + '/', additional_exclusions=additional_exclusions)
    return ans