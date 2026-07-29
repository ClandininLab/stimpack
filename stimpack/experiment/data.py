#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
The HDF5 data backend: one file per experiment, named ``<experiment_file_name>.hdf5``.

The file is laid out as::

    /                                    (attrs: date, experimenter, rig_config, ...)
        Subjects
            <subject_id>                 (attrs: subject metadata)
                epoch_runs
                    series_00n           (attrs: protocol + run parameters, run outcome)
                        acquisition
                        trials
                            epoch_001    (attrs: this trial's stimulus parameters)
                            epoch_002
                        stimulus_timing
        Notes                            (attrs: timestamp -> note text)

See :mod:`stimpack.experiment.data_nwb` for the NWB backend, which writes a directory of files
instead. Which one an experiment uses is set by ``data_format`` in the config.
"""
import h5py
import os
from datetime import datetime
import numpy as np

from stimpack.experiment.util import config_tools
from stimpack.experiment.deprecated_names import add_deprecated_aliases


def stimpack_version() -> str:
    """The running stimpack version, or ``'unknown'`` outside an installed distribution."""
    try:
        from importlib.metadata import PackageNotFoundError, version
        return version('stimpack')
    except PackageNotFoundError:
        return 'unknown'


class BaseData():
    # # # Traits the GUI reads to adapt itself to a storage backend # # #
    #
    # There are two built-in backends -- one HDF5 file per experiment (this class) and a directory
    # of NWB files (data_nwb.NWBData) -- and labpacks supply their own. Rather than the GUI asking
    # "is this NWB?", each backend declares what it is, and the GUI branches on these. Adding a
    # third backend then means setting these flags, not editing the GUI.

    # Is the experiment one file, or a directory holding many? Decides whether the GUI offers a
    # file picker or a directory picker when loading, and how it words itself.
    output_is_directory = False

    # Can the GUI's file tab browse this format's contents? Declared separately from
    # make_data_browser() below so that headless callers -- the client, --check-labpack, tests --
    # can ask without importing Qt.
    supports_data_browser = True

    # Word for one experiment's worth of data, used in GUI labels and messages.
    output_noun = 'data file'

    # # # The names this backend writes into the file # # #
    #
    # Held here rather than inline, so LegacyHdf5Data can write the pre-0.3 layout by overriding
    # five strings instead of reimplementing every method that touches the file. stimpack renamed
    # an epoch to a trial and an epoch run to a series; the layout follows the code, and a lab
    # whose analysis reads the old names keeps writing them by choosing the legacy backend.
    SERIES_GROUP = 'series'         # was 'epoch_runs'
    TRIALS_GROUP = 'trials'         # was 'epochs'
    TRIAL_PREFIX = 'trial_'         # was 'epoch_'

    # Written into the file so a reader can tell the layouts apart. Both HDF5 backends produce a
    # .hdf5 whose root attributes were otherwise identical, so analysis had to probe for a group
    # name to know which reader to use -- and nothing recorded which stimpack wrote the file.
    #
    # The legacy backend deliberately writes neither (see WRITES_FORMAT_MARKER): its contract is
    # that its output is indistinguishable from stimpack 0.2's, and a test asserts exactly that.
    # Absence therefore means 'legacy layout, or written before 0.3', which is what a reader needs
    # to know -- any later layout declares itself, so absence stays unambiguous.
    DATA_FORMAT = 'hdf5'
    WRITES_FORMAT_MARKER = True
    # Attributes whose spelling changed with the rename. Anything not named here is written the
    # same by both backends.
    ATTRIBUTE_NAMES = {'num_trials_completed': 'num_trials_completed',
                       'trial_duration': 'trial_duration',
                       'trial_end_reason': 'trial_end_reason',
                       'trial_unix_time': 'trial_unix_time',
                       'trial_end_unix_time': 'trial_end_unix_time'}

    def attribute_name(self, name):
        """The spelling this backend writes for an attribute stimpack knows by ``name``."""
        return self.ATTRIBUTE_NAMES.get(name, name)

    def series_path(self, subject=None, series_number=None):
        """Path of one series' group. The single place the layout is spelled out."""
        subject = self.current_subject if subject is None else subject
        series_number = self.series_count if series_number is None else series_number
        return '/Subjects/{}/{}/series_{}'.format(subject, self.SERIES_GROUP,
                                                  str(series_number).zfill(3))

    def trials_path(self, subject=None, series_number=None):
        """Path of the group holding one series' trials."""
        return '{}/{}'.format(self.series_path(subject, series_number), self.TRIALS_GROUP)

    def subject_series_path(self, subject=None):
        """Path of the group holding all of a subject's series."""
        subject = self.current_subject if subject is None else subject
        return '/Subjects/{}/{}'.format(subject, self.SERIES_GROUP)

    def __init__(self, cfg):
        self.cfg = cfg

        self.experiment_file_name: str = ""
        self.series_count: int = 1
        self.subject_metadata = {}  # populated in GUI or user protocol
        self.current_subject = None

        # default data_directory, experiment_file_name, experimenter from cfg
        # may be overwritten by GUI or other before initialize_experiment_file() is called
        self.data_directory = config_tools.get_data_directory(self.cfg)
        self.experimenter = config_tools.get_experimenter(self.cfg)

# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
# # # # # # # # #  Creating experiment file and groups  # # # # # # # # # # # #
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #

    def initialize_experiment_file(self):
        """
        Create HDF5 data file and initialize top-level hierarchy nodes
        """
        with h5py.File(os.path.join(self.data_directory, self.experiment_file_name + '.hdf5'), 'w-') as experiment_file:
            # Experiment date/time
            init_now = datetime.now()
            date = init_now.isoformat()[:-16]
            init_unix_time = init_now.timestamp()

            # Write experiment metadata as top-level attributes
            experiment_file.attrs['date'] = date
            experiment_file.attrs['init_unix_time'] = init_unix_time
            experiment_file.attrs['data_directory'] = self.data_directory
            experiment_file.attrs['experimenter'] = self.experimenter
            experiment_file.attrs['rig_config'] = self.cfg.get('current_rig_name', '')
            if self.WRITES_FORMAT_MARKER:
                experiment_file.attrs['data_format'] = self.DATA_FORMAT
                experiment_file.attrs['stimpack_version'] = stimpack_version()
            rig_config = (self.cfg.get('rig_config') or {}).get(self.cfg.get('current_rig_name')) or {}
            for key in rig_config:
                experiment_file.attrs[key] = str(rig_config.get(key))

            # Create a top-level group for series and user-entered notes
            experiment_file.create_group('Subjects')
            experiment_file.create_group('Notes')

    def load_experiment(self, path):
        """
        Point this object at an experiment that already exists on disk.

        :param path: what the GUI's picker returned -- a file for file-backed formats, a directory
                     for directory-backed ones (see output_is_directory).

        Split into a parent directory and a name here so the GUI does not have to know how a
        backend lays itself out on disk.
        """
        path = os.path.normpath(str(path))
        self.data_directory, name = os.path.split(path)
        # Strip the extension for a file ('2024-07-05.hdf5' -> '2024-07-05') but not for a
        # directory, whose name is already the name and may legitimately contain a dot.
        self.experiment_file_name = name if self.output_is_directory else os.path.splitext(name)[0]

    def browsable_files(self):
        """The files the File tab's browser should show, as ``[(label, path)]``.

        One entry for a format that keeps an experiment in a single file, one per series for a
        format that writes a directory of them. Asking the backend, rather than having the browser
        work out where the data is, is what lets one browser serve all three backends.
        """
        return [(self.experiment_file_name,
                 os.path.join(self.data_directory, self.experiment_file_name + '.hdf5'))]

    # Whether the browser may write edited attributes back. HDF5 experiments are stimpack's own
    # layout and editing one is a supported repair; an NWB file has a schema that pynwb validates,
    # and a hand-edited attribute can make it unreadable.
    browser_is_editable = True

    def make_data_browser(self, parent=None):
        """
        Widget for browsing this experiment's contents on the GUI's File tab, or None.

        The backend supplies its own browser rather than the GUI keeping one per format: a new
        backend that wants one overrides this, and the GUI places whatever it is handed.

        GUI-only, and the Qt import is deliberately inside the method -- BaseData is used
        headlessly by the client, the labpack checker and the tests, none of which should pull in
        PyQt to write a file.
        """
        if not self.supports_data_browser:
            return None
        from stimpack.experiment.gui_data_browser import Hdf5DataBrowser
        return Hdf5DataBrowser(self, parent=parent)

    def prepare_series(self):
        """
        Hook called by the GUI immediately before each recorded series starts.

        Nothing to do for a single-file format: initialize_experiment_file() already made the file
        and each series is a new group inside it. A backend that writes one file per series
        (data_nwb) creates that file here.
        """
        pass

    def create_subject(self, subject_metadata):
        """
        """
        if subject_metadata.get('subject_id') in [x.get('subject_id') for x in self.get_existing_subject_data()]:
            print('A subject with this ID already exists')
            return

        if self.experiment_file_exists():
            with h5py.File(os.path.join(self.data_directory, self.experiment_file_name + '.hdf5'), 'r+') as experiment_file:
                subject_init_unix_time = datetime.now().timestamp()
                subjects_group = experiment_file['/Subjects']
                new_subject = subjects_group.create_group(subject_metadata.get('subject_id'))
                new_subject.attrs['init_unix_time'] = subject_init_unix_time
                for key in subject_metadata:
                    new_subject.attrs[key] = subject_metadata.get(key)

                new_subject.create_group(self.SERIES_GROUP)

            self.select_subject(subject_metadata.get('subject_id'))
            print('Created subject {}'.format(subject_metadata.get('subject_id')))
        else:
            print('Initialize a data file before defining a subject')

    def update_subject(self, subject_metadata):
        """
        """
        # check if subject already exists
        if subject_metadata.get('subject_id') in [x.get('subject_id') for x in self.get_existing_subject_data()]:
            if self.experiment_file_exists():
                with h5py.File(os.path.join(self.data_directory, self.experiment_file_name + '.hdf5'),'r+') as experiment_file:
                    subjects_group = experiment_file['/Subjects']
                    current_subject = subjects_group[subject_metadata.get('subject_id')]
                    for key in subject_metadata:
                        print(key)
                        # Ignore subject id as it's already defined
                        if key != 'subject_id':
                            current_subject.attrs[key] = subject_metadata.get(key)

        else:
            print('No subject with this ID exists!')
            return



    def create_series(self, protocol_object):
        """"
        """
        # create a new series group in the data file
        if (self.current_subject_exists() and self.experiment_file_exists()):
            with h5py.File(os.path.join(self.data_directory, self.experiment_file_name + '.hdf5'), 'r+') as experiment_file:
                run_start_unix_time = datetime.now().timestamp()
                new_series = experiment_file.create_group(self.series_path())
                new_series.attrs['run_start_unix_time'] = run_start_unix_time
                for key in protocol_object.run_parameters:  # add run parameter attributes
                    new_series.attrs[key] = protocol_object.run_parameters[key]
                new_series.attrs['protocol_ID'] = protocol_object.__class__.__name__

                for key in protocol_object.protocol_parameters:  # add user-entered protocol params
                    new_series.attrs[key] = hdf5ify_parameter(protocol_object.protocol_parameters[key])

                # add subgroups:
                new_series.create_group('acquisition')
                new_series.create_group(self.TRIALS_GROUP)
                new_series.create_group('rois')
                new_series.create_group('stimulus_timing')

        else:
            print('Create a data file and/or define a subject first')

    def create_trial(self, protocol_object):
        """
        """
        if (self.current_subject_exists() and self.experiment_file_exists()):
            with h5py.File(os.path.join(self.data_directory, self.experiment_file_name + '.hdf5'), 'r+') as experiment_file:
                trial_unix_time = datetime.now().timestamp()
                trials_group = experiment_file[self.trials_path()]
                new_trial = trials_group.create_group('{}{}'.format(self.TRIAL_PREFIX, str(protocol_object.num_trials_completed+1).zfill(3)))
                new_trial.attrs[self.attribute_name('trial_unix_time')] = trial_unix_time

                epoch_stim_parameters_group = new_trial
                # Handle both tuple and list of stims (protocol.load_stimuli supports a list too);
                # otherwise a list-valued trial_stim_parameters is silently not saved.
                if type(protocol_object.trial_stim_parameters) in (tuple, list):  # multiple stims layered on top of one another
                    num_stims = len(protocol_object.trial_stim_parameters)
                    for stim_ind in range(num_stims):
                        for key in protocol_object.trial_stim_parameters[stim_ind]:
                            prefix = 'stim{}_'.format(str(stim_ind))
                            epoch_stim_parameters_group.attrs[prefix + key] = hdf5ify_parameter(protocol_object.trial_stim_parameters[stim_ind][key])

                elif type(protocol_object.trial_stim_parameters) is dict:  # single stim class
                    for key in protocol_object.trial_stim_parameters:
                        epoch_stim_parameters_group.attrs[key] = hdf5ify_parameter(protocol_object.trial_stim_parameters[key])

                epoch_protocol_parameters_group = new_trial
                for key in protocol_object.trial_protocol_parameters:  # save out convenience parameters
                    epoch_protocol_parameters_group.attrs[key] = hdf5ify_parameter(protocol_object.trial_protocol_parameters[key])

        else:
            print('Create a data file and/or define a subject first')

    def end_trial(self, protocol_object, reason=None):
        """
        Record when the trial ended, and why.

        :param reason: None if it ran its full length, otherwise why it was cut short -- the
            string a labpack passed to BaseServer.end_trial, for a trial ended by the animal's
            behaviour.

        Also stores the trial's actual duration. With a fixed stim_time that is redundant, but a
        behaviour-ended trial is as long as the animal made it, and the protocol parameters then
        describe the intent rather than what happened.
        """
        # Match the guard used by the sibling create_* methods; without it, opening 'r+' on a missing
        # file raises mid-run.
        if not (self.current_subject_exists() and self.experiment_file_exists()):
            print('Create a data file and/or define a subject first')
            return
        with h5py.File(os.path.join(self.data_directory, self.experiment_file_name + '.hdf5'), 'r+') as experiment_file:
            trial_end_unix_time = datetime.now().timestamp()
            trials_group = experiment_file[self.trials_path()]
            trial_group = trials_group['{}{}'.format(self.TRIAL_PREFIX, str(protocol_object.num_trials_completed+1).zfill(3))]
            trial_group.attrs[self.attribute_name('trial_end_unix_time')] = trial_end_unix_time
            start = trial_group.attrs.get(self.attribute_name('trial_unix_time'))
            if start is not None:
                trial_group.attrs[self.attribute_name('trial_duration')] = trial_end_unix_time - start
            trial_group.attrs['ended_early'] = reason is not None
            if reason is not None:
                trial_group.attrs[self.attribute_name('trial_end_reason')] = str(reason)

    def end_series(self, protocol_object, status='completed', reason=None, paused_seconds=0.0):
        """
        Record the outcome of an series as attributes on its series group.

        There is otherwise no run-completion marker in the file (create_series only writes a start
        time), so this also gives every run an end timestamp and a completion status.

        :param status: 'completed' | 'stopped' | 'aborted' | 'error'
        :param reason: optional short string, saved as 'abort_reason' when the run did not complete normally
        :param paused_seconds: seconds the run spent paused between trials. Written every time,
            including as 0.0: a pause leaves an otherwise unexplained gap between one trial's end
            and the next one's start, and during it the subject sat in the rig with no stimulus.
            Recording zero explicitly says nothing was paused, rather than leaving it ambiguous.
        """
        if not (self.current_subject_exists() and self.experiment_file_exists()):
            print('Create a data file and/or define a subject first')
            return
        with h5py.File(os.path.join(self.data_directory, self.experiment_file_name + '.hdf5'), 'r+') as experiment_file:
            series_path = self.series_path()
            series_group = experiment_file.get(series_path)
            if series_group is None:  # run never created its series group (e.g. nothing recorded)
                return
            series_group.attrs['run_status'] = status
            series_group.attrs['run_end_unix_time'] = datetime.now().timestamp()
            series_group.attrs[self.attribute_name('num_trials_completed')] = int(protocol_object.num_trials_completed)
            series_group.attrs['paused_duration'] = float(paused_seconds)
            if reason is not None:
                series_group.attrs['abort_reason'] = str(reason)

    def create_note(self, note_text):
        """Append a timestamped free-text note to the experiment, from the GUI's Notes box."""
        ""
        ""
        if self.experiment_file_exists():
            with h5py.File(os.path.join(self.data_directory, self.experiment_file_name + '.hdf5'), 'r+') as experiment_file:
                note_unix_time = str(datetime.now().timestamp())
                notes = experiment_file['/Notes']
                notes.attrs[note_unix_time] = note_text
        else:
            print('Initialize a data file before writing a note')

# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
# # # # # # # # #  Retrieve / query data file # # # # # # # # # # # # # # # # #
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #

    def experiment_file_exists(self):
        """Whether this experiment already exists on disk. What that means is the backend's
        business -- a file here, a directory for :class:`~stimpack.experiment.data_nwb.NWBData`."""
        if self.experiment_file_name == "":
            tf = False
        else:
            tf = os.path.isfile(os.path.join(self.data_directory, self.experiment_file_name + '.hdf5'))
        return tf

    def current_subject_exists(self):
        """Whether a subject has been selected. Recording requires both this and an experiment."""
        if self.current_subject is None:
            tf = False
        else:
            tf = True
        return tf

    def get_existing_series(self):
        """Series numbers already recorded in this experiment, so the GUI can refuse to reuse one."""
        all_series = []
        with h5py.File(os.path.join(self.data_directory, self.experiment_file_name + '.hdf5'), 'r') as experiment_file:
            for subject_id in list(experiment_file['/Subjects'].keys()):
                new_series = list(experiment_file[self.subject_series_path(subject_id)].keys())
                all_series.append(new_series)
        all_series = [val for s in all_series for val in s]
        series = [int(x.split('_')[-1]) for x in all_series]
        return series

    def series_owner(self, series_number=None):
        """Which subject holds this series number, or None if nobody does.

        Series numbers are global across an experiment, but each series lives under one subject,
        so "is this number taken" and "is it mine" are different questions. Answering only the
        first let a run be recorded as series 1 while another subject already held series 1 --
        two groups with the same number, in a scheme whose whole point is that the number
        identifies one recording.
        """
        series_number = self.series_count if series_number is None else series_number
        if not self.experiment_file_exists():
            return None
        name = 'series_{}'.format(str(series_number).zfill(3))
        with h5py.File(os.path.join(self.data_directory, self.experiment_file_name + '.hdf5'), 'r') as experiment_file:
            for subject_id in list(experiment_file['/Subjects'].keys()):
                series_group = experiment_file.get(self.subject_series_path(subject_id))
                if series_group is not None and name in series_group:
                    return subject_id
        return None

    def delete_series(self, series_number=None):
        """Remove a recorded series so its number can be recorded onto again.

        Destructive and not undoable: the GUI asks first (a series number that already exists used
        to be refused outright, which meant renumbering around a false start rather than replacing
        it). Returns whether anything was removed.

        Deletes the series wherever it is, not only under the current subject. Series numbers are
        global while each series sits under one subject, so looking only under the current one
        found nothing when the number belonged to another -- and the caller, told nothing had been
        removed, went on to record a second series with the same number.

        :param series_number: which series; the current one if not given.
        """
        series_number = self.series_count if series_number is None else series_number
        owner = self.series_owner(series_number)
        if owner is None:
            return False
        with h5py.File(os.path.join(self.data_directory, self.experiment_file_name + '.hdf5'), 'r+') as experiment_file:
            runs = experiment_file.get(self.subject_series_path(owner))
            name = 'series_{}'.format(str(series_number).zfill(3))
            if runs is None or name not in runs:
                return False
            del runs[name]
        return True

    def get_highest_series_count(self):
        """The largest series number recorded so far, or 0 if none."""
        series = self.get_existing_series()
        if len(series) == 0:
            return 0
        else:
            return np.max(series)

    def get_existing_subject_data(self):
        """Metadata for every subject in this experiment, one dict each."""
        # return list of dicts for subject metadata already present in experiment file
        subject_data_list = []
        if self.experiment_file_exists():
            with h5py.File(os.path.join(self.data_directory, self.experiment_file_name + '.hdf5'), 'r') as experiment_file:
                for subject in experiment_file['/Subjects']:
                    new_subject = experiment_file['/Subjects'][subject]
                    new_dict = {}
                    for at in new_subject.attrs:
                        new_dict[at] = new_subject.attrs[at]

                    subject_data_list.append(new_dict)
        return subject_data_list

    def select_subject(self, subject_id):
        """Make this the subject that subsequent series are recorded against."""
        self.current_subject = subject_id

    def advance_series_count(self):
        """Move to the next series number. Called after a recorded run finishes."""
        self.series_count += 1

    def update_series_count(self, val):
        """Set the series number the next run will use."""
        self.series_count = val

    def get_series_count(self):
        """The series number the next run will use."""
        return self.series_count

    def reload_series_count(self):
        """Re-read the series number from disk, after loading an experiment recorded earlier."""
        all_series = []
        with h5py.File(os.path.join(self.data_directory, self.experiment_file_name + '.hdf5'), 'r') as experiment_file:
            for subject_id in list(experiment_file['/Subjects'].keys()):
                new_series = list(experiment_file[self.subject_series_path(subject_id)].keys())
                all_series.append(new_series)
        all_series = [val for s in all_series for val in s]
        series = [int(x.split('_')[-1]) for x in all_series]

        if len(series) == 0:
            self.series_count = 0 + 1
        else:
            self.series_count = np.max(series) + 1

    def get_server_subdir(self):
        """
        Sub-directory the server files this experiment's own output under -- locomotion position
        histories, for instance. Relative to the server's ``data_directory``.
        """
        return self.experiment_file_name


# The pre-0.3 spelling. A labpack's own data class subclasses BaseData and calls these.
add_deprecated_aliases(
    BaseData,
    methods=[
        ('create_epoch', 'create_trial'),
        ('end_epoch', 'end_trial'),
        ('create_epoch_run', 'create_series'),
        ('end_epoch_run', 'end_series'),
    ],
)


def hdf5ify_parameter(value):
    """
    Coerce a parameter into something HDF5 can store as an attribute.

    Dictionaries and tuples become their string representation, ragged lists become strings, and
    numeric lists become arrays. Lossy by design: this is metadata for later reference, not data
    to be read back programmatically.
    """
    if value is None:
        value = 'None'
    if type(value) is dict:  # TODO: Find a way to split this into subgroups. Hacky work around.
        value = str(value)
    if type(value) is np.str_:
        value = str(value)
    if type(value) is np.ndarray:
        if value.dtype == 'object':
            value = value.astype('float')
    if type(value) is list:
        new_value = [hdf5ify_parameter(x) for x in value]
        if any([type(x) is str for x in new_value]):
            value = new_value
        else:
            try:
                value = np.array(new_value)
            except ValueError:
                value = str(value)
    # if tuple, every element must be the same length. If not, convert to string
    if type(value) is tuple:
        element_lengths = [len(x) if type(x) in [list, tuple, np.ndarray] else 1 for x in value]
        if not all([x == element_lengths[0] for x in element_lengths]):
            value = str(value) 

    return value
