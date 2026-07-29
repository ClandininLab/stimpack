#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
The HDF5 layout stimpack wrote before 0.3, so existing analysis keeps working.

stimpack renamed a stimulus presentation from *epoch* to *trial* and a run of them from *epoch
run* to *series*, matching NWB (see :mod:`stimpack.experiment.deprecated_names`). The file layout
follows the code, which would otherwise mean every analysis script that walks
``epoch_runs/series_001/epochs/epoch_001`` breaks the day a lab upgrades.

This backend writes the old layout instead. Choose it with::

    data_format: legacy_hdf5

in a config -- or in a labpack's ``lab_config.yaml``, which applies it to every rig at once.

It is the same class as :class:`~stimpack.experiment.data.BaseData` in every other respect: the
same code writes the file, and only the names it writes differ. That is deliberate. A copy of the
backend frozen at 0.2 would keep the old names and none of the fixes, and would drift further
apart with each release; this cannot, because there is nothing to drift.

Files written by either backend can be read by either -- nothing here changes what a group
contains, only what it is called.
"""
from stimpack.experiment.data import BaseData


class LegacyHdf5Data(BaseData):
    """BaseData writing the pre-0.3 group and attribute names."""

    # /Subjects/<id>/epoch_runs/series_001/epochs/epoch_001
    SERIES_GROUP = 'epoch_runs'
    TRIALS_GROUP = 'epochs'
    TRIAL_PREFIX = 'epoch_'

    ATTRIBUTE_NAMES = {'num_trials_completed': 'num_epochs_completed',
                       'trial_duration': 'epoch_duration',
                       'trial_end_reason': 'epoch_end_reason',
                       'trial_unix_time': 'epoch_unix_time',
                       'trial_end_unix_time': 'epoch_end_unix_time'}

    output_noun = 'data file (legacy layout)'

    # No data_format / stimpack_version attributes: a file this backend writes must stay
    # indistinguishable from one stimpack 0.2 wrote, which a marker would end. Readers tell the
    # layouts apart by the marker's ABSENCE, which means exactly 'legacy, or pre-0.3'.
    DATA_FORMAT = 'legacy_hdf5'
    WRITES_FORMAT_MARKER = False

    # Run parameters reach the file as attributes named after their keys, so the rename shows up
    # in the data as well as in the code: a series group would carry num_trials where analysis
    # looks for num_epochs. Renamed rather than written under both names -- a file this backend
    # writes is meant to be indistinguishable from one stimpack wrote before 0.3, and a test
    # asserts exactly that against the pre-rename code.
    RUN_PARAMETER_NAMES = {'num_trials': 'num_epochs'}

    def create_series(self, protocol_object):
        import h5py
        import os

        super().create_series(protocol_object)

        if not (self.current_subject_exists() and self.experiment_file_exists()):
            return
        path = os.path.join(self.data_directory, self.experiment_file_name + '.hdf5')
        with h5py.File(path, 'r+') as experiment_file:
            series_group = experiment_file.get(self.series_path())
            if series_group is None:
                return
            for new_name, old_name in self.RUN_PARAMETER_NAMES.items():
                if new_name in series_group.attrs:
                    series_group.attrs[old_name] = series_group.attrs[new_name]
                    del series_group.attrs[new_name]
