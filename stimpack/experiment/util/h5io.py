"""
Read-only helpers for browsing an HDF5 experiment file's group hierarchy and attributes.

Used by the GUI's data browser (:mod:`stimpack.experiment.gui_data_browser`). Bulk data groups
are excluded from the hierarchy, since this is for inspecting metadata rather than reading data.
"""
import h5py
import numpy as np

# H5io fxns
def get_hierarchy(file_path, additional_exclusions=None, exclusions=None):
    """Group tree of the file, as nested dicts.

    ``exclusions`` replaces the default hidden-group list outright -- what is noise is a fact
    about the file's layout, so the data backend supplies it (BaseData.browser_tree_exclusions):
    stimpack's own HDF5 hides its per-trial group explosion, NWB hides its schema cache but must
    show 'trials'/'epochs', which there are single tables holding the series and trial records.
    ``additional_exclusions`` extends whichever list is in effect.
    """
    with h5py.File(file_path, 'r') as experiment_file:
        hierarchy = recursively_load_dict_contents_from_group(experiment_file, '/',
                                                              additional_exclusions=additional_exclusions,
                                                              exclusions=exclusions)
    return hierarchy


def get_group_contents(file_path, group_path, max_array_elems=8):
    """A group's attributes AND its datasets, each as {name: display value}.

    Returned separately because they are different things to a browser: attributes may be
    editable (stimpack's own HDF5 layout), datasets are a record and never are. Datasets display
    as their value (scalars), their values (arrays up to ``max_array_elems``), or a shape/dtype
    summary. Showing them at all is what makes an NWB file browsable: NWB keeps its payload --
    subject fields, session metadata, the trials/epochs table columns -- in datasets, and its
    group *attributes* are schema bookkeeping.
    """
    def display(value):
        if isinstance(value, bytes):
            return value.decode('utf-8', errors='replace')
        return value

    with h5py.File(file_path, 'r') as experiment_file:
        group = experiment_file[group_path]
        attrs = {key: group.attrs[key] for key in group.attrs}
        datasets = {}
        for name, item in group.items():
            if not isinstance(item, h5py.Dataset):
                continue
            try:
                if item.shape == ():
                    datasets[name] = display(item[()])
                elif item.size <= max_array_elems:
                    datasets[name] = [display(v) for v in item[()].tolist()]
                else:
                    datasets[name] = f'{item.dtype} array, shape {item.shape}'
            except Exception:
                # Object references and exotic dtypes are not worth failing the whole table over.
                datasets[name] = f'{item.dtype} array, shape {item.shape}'
        return attrs, datasets


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


# What the default hidden-group list hides is stimpack's own HDF5 layout: 'trials'/'epochs' hold
# one subgroup per presentation (hundreds per series), and the rest are bulk data. A backend with
# a different layout supplies its own list (BaseData.browser_tree_exclusions).
DEFAULT_TREE_EXCLUSIONS = ['acquisition', 'Client', 'trials', 'epochs', 'stimulus_timing',
                           'roipath', 'subpath']


def recursively_load_dict_contents_from_group(h5file, path, additional_exclusions=None, exclusions=None):
    # https://codereview.stackexchange.com/questions/120802/recursively-save-python-dictionaries-to-hdf5-files-using-h5py
    exclusions = list(DEFAULT_TREE_EXCLUSIONS if exclusions is None else exclusions)
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
                # Recurse with the resolved list: it already folds in additional_exclusions.
                ans[key] = recursively_load_dict_contents_from_group(h5file, path + key + '/', exclusions=exclusions)
    return ans