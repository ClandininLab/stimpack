#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Data file class for the .nwb file format.

Where BaseData writes one HDF5 file per experiment, this writes a DIRECTORY per experiment
holding one .nwb file per series. That difference is the only thing the GUI needs to know, and
it reads it from the output_is_directory trait rather than from this class's name.

Requires pynwb, which stimpack installs as a dependency.
"""
from copy import deepcopy
from csv import writer
import os
import json
import numpy as np
from pathlib import Path
import posixpath
import re
import warnings
from datetime import datetime, timezone

from pynwb.file import Subject
from pynwb import NWBFile, NWBHDF5IO
from pynwb.epoch import TimeIntervals
from hdmf.common import VectorData, VectorIndex
from hdmf.backends.hdf5.h5_utils import H5DataIO
from hdmf.common.table import ElementIdentifiers

from stimpack.experiment.data import BaseData, hdf5ify_parameter
from stimpack.experiment.util import config_tools, provenance


def _row_shape(value):
    """Shape of a single row of a column holding ``value``, for declaring the column's maxshape.

    ``()`` for a scalar, ``(2,)`` for a pair, and ``()`` again for anything numpy cannot measure
    (a ragged nested list, say) -- in which case the write fails on its own terms rather than on a
    shape computed here.
    """
    try:
        return tuple(np.shape(value))
    except ValueError:
        return ()


def _days_from_iso8601_duration(age):
    """
    Invert the day-valued ISO 8601 duration NWB stores an age as: 'P3D' -> 3.

    Anything else -- a duration in other units, or an age that was never a plain number of days --
    is handed back untouched rather than guessed at.
    """
    if isinstance(age, str):
        match = re.fullmatch(r'P(\d+)D', age.strip())
        if match:
            return int(match.group(1))
    return age


class NWBData(BaseData):
    """
    Data class corresponding to a series of .nwb files. One .nwb file per trial run / series.

    Vocabulary note: this backend's own terms map onto BaseData's as::

        nwb_directory      -> experiment_file_name   (the directory's name)
        parent_directory   -> data_directory         (what it sits in)
        current_subject_id -> current_subject

    The NWB spellings are kept as properties, so protocols and labpack code written against
    either name keep working.
    """
    output_is_directory = True

    # An .nwb file identifies its format itself -- its extension, and a schema version pynwb
    # writes -- so it needs no data_format attribute. Which stimpack wrote it goes in the schema's
    # own field for that, source_script; see initialize_session.
    DATA_FORMAT = 'nwb'
    DECLARES_DATA_FORMAT = False
    supports_data_browser = True
    output_noun = 'NWB directory'

    # An .nwb file is HDF5, so the same tree browser reads it; what differs is that an experiment
    # is a directory of them rather than one file, which browsable_files expresses.
    browser_is_editable = False

    def __init__(self, cfg):
        super().__init__(cfg)
        self.subject = None
        # Set here rather than only in create_series / create_trial, so the end_* methods can
        # ask whether there is anything to write without tripping over a missing attribute --
        # they run from the client's finally block, after failures that never got that far.
        # What gets written as this series' row: its identity, every run and protocol parameter,
        # and how the run ended. Not 'parameters' -- run_status and paused_duration are outcomes,
        # and stimpack already uses that word for two specific things (see BaseProtocol).
        self.series_record = {}
        self.trial_parameters = {}

    # # # NWB-flavored aliases for BaseData's storage-neutral attribute names # # #

    @property
    def nwb_directory(self):
        return self.experiment_file_name

    @nwb_directory.setter
    def nwb_directory(self, value):
        self.experiment_file_name = value

    @property
    def parent_directory(self):
        return self.data_directory

    @parent_directory.setter
    def parent_directory(self, value):
        self.data_directory = value

    @property
    def current_subject_id(self):
        return self.current_subject

    @current_subject_id.setter
    def current_subject_id(self, value):
        self.current_subject = value

    @property
    def nwb_directory_path(self):
        """Full path to the experiment directory. Derived, so it cannot fall out of step with
        the parent directory and name the GUI may still be editing."""
        return Path(os.path.join(self.data_directory, self.experiment_file_name))


# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
# # # # # # # # #  Creating experiment file and groups  # # # # # # # # # # # #
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #

    def initialize_experiment_file(self):
        """
        Create a dict of top level metadata that all the nwb files will share
        Also create the directory where the nwb files will be stored
        """
        self.nwb_directory_path.mkdir(parents=True, exist_ok=True)
        self.initialize_session()

    # The name this backend used before it conformed to the BaseData interface.
    initialize_experiment = initialize_experiment_file

    def load_experiment(self, path):
        # os.path.split returns (head, tail); [:-1] took the head as a one-element TUPLE, which
        # then failed every os.path call made on the parent directory afterwards.
        super().load_experiment(path)
        self.initialize_session()

    def initialize_session(self):
        self.timezone = timezone.utc  # This could be changed if desired
        session_start_time = datetime.now(self.timezone)

        # Guarded the way BaseData reads the same thing: a config with no rig_config section, or
        # one whose current_rig_name names no rig, is a config that can still write a file. This
        # raised instead -- AttributeError on the missing section, TypeError iterating the None
        # from an unmatched name -- so an experiment could not be initialized at all.
        rig_config = (self.cfg.get('rig_config') or {}).get(self.cfg.get('current_rig_name')) or {}
        self.rig_config_parameters = dict()
        for key in rig_config:
            self.rig_config_parameters[key] = str(rig_config.get(key, ""))

        experiment_description = str(self.rig_config_parameters)
        
        # Store the metadata that all the files will share
        self.general_nwb_kwargs = dict(
            session_description='Experiment data',
            session_start_time=session_start_time,
            experimenter=self.experimenter,
            lab=config_tools.get_lab(self.cfg),
            institution=config_tools.get_institution(self.cfg),
            experiment_description=experiment_description,
            # The schema's own field for 'what software wrote this'. source_script_file_name is
            # required alongside it -- without it pynwb writes the file but warns
            # MissingRequiredBuildWarning, leaving a technically invalid file.
            # NWB has no free-form file attributes of stimpack's, so the whole provenance line
            # goes in the schema's own field for what software wrote a file.
            source_script=provenance.provenance_summary(self.cfg),
            source_script_file_name='stimpack',
        )


    def define_subject(self, subject_metadata):
        """
        Record which subject is being run, without touching disk.

        Unlike the HDF5 backend there is no file to write a subject into yet: each series gets its
        own .nwb file, written at the start of that series, and the subject is embedded in each.
        """
        self.subject_metadata = subject_metadata
        self.select_subject(subject_metadata['subject_id'])

    def update_subject(self, subject_metadata):
        """
        Revise the current subject's metadata. Takes effect in files written from now on; .nwb
        files already written keep the metadata they were written with.
        """
        if subject_metadata.get('subject_id') != self.current_subject:
            print('No subject with this ID is currently selected!')
            return
        self.subject_metadata = subject_metadata

    def create_subject(self, subject_metadata):
        """
        Create an NWB subject for the data object
        """

        if not self.experiment_file_exists():
            print(f'Initialize a {self.output_noun} before defining a subject')
            return

        self.define_subject(subject_metadata)
        self.build_nwb_subject(subject_metadata)
        print('Created subject {}'.format(subject_metadata.get('subject_id')))

    def build_nwb_subject(self, subject_metadata):
        """
        Translate a subject-metadata dict into the pynwb Subject and per-subject NWBFile kwargs
        used when writing each series file. Pure translation: touches no disk and selects nothing.
        """
        # If those files are passed as metadata, they will be mapped to their canonical place in the nwbfile
        keywords_in_the_nwb_subject_class = ["age", "genotype", "sex", "weight", "age__reference", 
                                                "species", "subject_id", "date_of_birth", "strain", ]
        
        # Here we deep copy the general dictionary and we modify it for the specific subject 
        self.subject_nwbfile_kwargs = deepcopy(self.general_nwb_kwargs)
        self.subject_nwbfile_kwargs["identifier"] = subject_metadata.get('subject_id')

        # Create the subject object
        subject_kwargs = {key: subject_metadata[key] for key in keywords_in_the_nwb_subject_class if key in subject_metadata}
        
        # In NWB the age is a string
        if 'age' in subject_kwargs:
            age_days = subject_kwargs['age']
            subject_kwargs['age'] = f'P{age_days}D' # string format to ISO 8601 duration

        for key in subject_kwargs: # convert empty strings to None
            if subject_kwargs[key] == '':
                subject_kwargs[key] = None

        
        # Save the rest as subject description
        rest_of_the_subject_metadata = {key: subject_metadata[key] for key in subject_metadata if key not in keywords_in_the_nwb_subject_class}
        subject_kwargs['description'] = json.dumps(rest_of_the_subject_metadata)
        
        # Creates a subject object with all the metadata
        self.subject = Subject(**subject_kwargs)

    def prepare_series(self):
        """
        Write the file for this trial run.

        Called by the GUI before each recorded series (BaseData.prepare_series), because this
        backend puts each series in its own file rather than a group in a shared one.
        """
        if (self.current_subject_exists() and self.experiment_file_exists()):
            # Re-build the nwb Subject object from the current metadata
            self.build_nwb_subject(self.subject_metadata)

            nwbfile_kwargs = deepcopy(self.subject_nwbfile_kwargs)

            nwbfile_path = self.get_nwb_file_path()

            # Refuse a series that has already been written, and say so in those terms. 'w-'
            # refuses too, but it does so from inside HDF5, and an HDF5-level failure raised
            # through a Qt slot takes the whole GUI down rather than reporting anything.
            if os.path.isfile(nwbfile_path):
                raise FileExistsError(
                    f'Series {self.series_count} already exists for subject {self.current_subject} '
                    f'({nwbfile_path}). Choose an unused series number.')

            # Create the nwbfile and save it to disk
            nwbfile = NWBFile(**nwbfile_kwargs, subject=self.subject)

            with NWBHDF5IO(nwbfile_path, 'w-') as io:
                io.write(nwbfile)

        else:
            print(f'Create an {self.output_noun} and/or define a subject first')

    # The name this backend used before it conformed to the BaseData interface.
    create_data_file = prepare_series


    def create_series(self, protocol_object):
        """
        Store the protocol parameters and the protocol ID.
        """
        
        self.series_record = {}
                
        if (self.current_subject_exists() and self.experiment_file_exists()):
            
            self.series_record = {}
            self.series_record["series"] = f"series_{str(self.series_count).zfill(3)}"
            self.series_record['protocol_id'] = protocol_object.__class__.__name__
            
            # Add the protocol parameters to the series_record
            for key in protocol_object.run_parameters:  # add run parameter attributes
                self.series_record[key] = hdf5ify_parameter(protocol_object.run_parameters[key])
                
            for key in protocol_object.protocol_parameters:  # add user-entered protocol params
                self.series_record[key] = hdf5ify_parameter(protocol_object.protocol_parameters[key])
                
            # Add the series start time
            self.series_record['series_start_time'] = datetime.now(self.timezone).timestamp()
            
            # NWB's two interval tables map onto stimpack's two levels: a stimpack series is one
            # row of NWB's `epochs` table, and each stimpack trial a row of its `trials` table.
            # I am going to shift the nomencalture to be consistent with nwb
            self.series_record["num_trials"] = self.series_record.get("num_trials", "")
            
        else:
            print('Create an nwb file directory and/or define a subject first')

    def end_series(self, protocol_object, status='completed', reason=None, paused_seconds=0.0):
        """
        NWB requires the stop time to be set when the interval is created, so this runs after the
        series is finished and adds the row of NWB's `epochs` table that covers the whole series.
        (NWB's `epochs` are coarse blocks of time, which is why a stimpack series goes there and
        each of its trials goes in `trials`.)

        :param status: how the run ended -- 'completed', 'stopped', 'aborted' or 'error'
        :param reason: detail for a run that did not complete, e.g. the exception text

        The client calls this from a finally block, so it runs for runs that failed as well as
        runs that finished. Everything below therefore has to cope with a run that never got as
        far as creating its series parameters or its file.
        """
        # create_series bails out (leaving series_record empty) when there is no subject or
        # no directory, and the client still reaches its finally block. Popping a key that was
        # never set would then raise from inside the error handler, replacing whatever actually
        # went wrong with a bare KeyError.
        if not self.series_record or 'series_start_time' not in self.series_record:
            warnings.warn(f'No series to close out (run ended {status}); nothing written to NWB.')
            return

        # Likewise, the per-series file is written by prepare_series; a run that failed before
        # that has nothing to append to.
        nwbfile_path = self.get_nwb_file_path()
        if not os.path.isfile(nwbfile_path):
            warnings.warn(f'No NWB file at {nwbfile_path} (run ended {status}); nothing written.')
            return

        # Record how the run ended alongside its parameters, so a partial run is identifiable in
        # the data rather than looking like a short but successful one.
        self.series_record['run_status'] = str(status)
        self.series_record['run_status_reason'] = str(reason) if reason is not None else ''
        # A pause sits between trials, so it is otherwise an unexplained gap in the timeline --
        # during which the subject was in the rig with nothing being presented.
        self.series_record['paused_duration'] = float(paused_seconds)

        # Open the nwbfile in append mode
        with NWBHDF5IO(nwbfile_path, 'r+') as io:
            subject_nwbfile = io.read()

            # Shift the time to be relative to the session start time
            session_start_time = subject_nwbfile.session_start_time
            start_time = self.series_record.pop('series_start_time')
            start_time = start_time - session_start_time.timestamp()
            stop_time = datetime.now(self.timezone).timestamp() - session_start_time.timestamp()
        
            # Creates the table such that is dynamically grows
            if subject_nwbfile.epochs is None:
                ids = ElementIdentifiers(
                    name='id',
                    data=H5DataIO(data=[0], maxshape=(None,)),
                )
                
                columns_to_add = []
                start_time = VectorData(name='start_time', description="the time the trial started",
                                              data=H5DataIO(data=[start_time], maxshape=(None,)))
                columns_to_add.append(start_time)
                stop_time = VectorData(name='stop_time', description="the time the trial ended",
                                             data=H5DataIO(data=[stop_time], maxshape=(None,)))
                columns_to_add.append(stop_time)

                for column in self.series_record:
                    value = self.series_record[column]
                    value_is_list_tuple_or_array = isinstance(value, (tuple, list, np.ndarray))
                    if not value_is_list_tuple_or_array:
                        vector_column = VectorData(name=column, description=column, data=H5DataIO(data=[value], maxshape=(None,)))
                        columns_to_add.append(vector_column)
                    else:
                        value_has_list_tuple_or_array_as_elements = isinstance(value[0], (tuple, list, np.ndarray))
                        if not value_has_list_tuple_or_array_as_elements:
                            data = list(value)
                            # Recursion to second level for nested lists
                            
                            vector_column = VectorData(name=column, description=column, data=H5DataIO(data=data, maxshape=(None, )))
                            end_index_first_element = len(value)
                            vector_index = VectorIndex(name=column + "_index", target=vector_column, data=H5DataIO(data=[end_index_first_element], maxshape=(None,)))
                            columns_to_add.append(vector_column)
                            columns_to_add.append(vector_index) 
                        else:
                            # Flatten the value
                            data = [item for sublist in value for item in sublist]
                            lengths = [len(x) for x in value]
                            # Flattening one level leaves rows that may themselves be lists -- a
                            # parameter whose per-trial value is a list of pairs is three deep at
                            # run level, since this table holds the whole list of choices. So the
                            # maxshape needs the rank of what is left, exactly as in the trials
                            # table: declaring rank 1 over 2-D data wrote an epochs group with no
                            # neurodata_type at all, and pynwb could then not open the file --
                            # including the trials data underneath it, which was written correctly.
                            vector_column = VectorData(name=column, description=column,
                                                       data=H5DataIO(data=data,
                                                                     maxshape=(None,) + _row_shape(data[0] if data else None)))
                            # Cumulative value of the lengths
                            data_index = np.cumsum(lengths).tolist()
                            vector_index = VectorIndex(name=column + "_index", target=vector_column, data=H5DataIO(data=data_index, maxshape=(None,)))
                            end_index_first_element = len(lengths)
                            vector_index_index = VectorIndex(name=column + "_index_index", target=vector_index, data=H5DataIO(data=[end_index_first_element], maxshape=(None,)))
                            columns_to_add.append(vector_column)
                            columns_to_add.append(vector_index)
                            columns_to_add.append(vector_index_index)
                            
                epochs_table = TimeIntervals(
                    name='epochs',
                    description="experimental epochs",
                    columns=columns_to_add,
                    id=ids,
                )
                
                subject_nwbfile.epochs = epochs_table
            
            else: # If the table exists just add a row
                series_row_kargs = self.series_record
                series_row_kargs["start_time"] = start_time
                series_row_kargs["stop_time"] = stop_time
                subject_nwbfile.add_epoch(**series_row_kargs)
            
            # Write the nwbfile to disk
            io.write(subject_nwbfile)
            
    def create_trial(self, protocol_object):
        """
        This loads the data from the protocol object stim parameters.
        Then, when the trial is concluded, we add the data as a row of the trials table.
        """
                
        self.trial_parameters = {}
        if not (self.current_subject_exists() and self.experiment_file_exists()):
            # Return, rather than warning and carrying on: collecting parameters for a trial
            # that has nowhere to go only defers the failure to end_trial, which then reports a
            # missing file instead of the missing subject that actually caused it.
            warnings.warn(f'Create an {self.output_noun} and/or define a subject first; '
                          f'this trial will not be saved.')
            return

        self.trial_parameters['trial_start_time'] = datetime.now(self.timezone).timestamp()

        if protocol_object.save_stringified_params:
            assert hasattr(protocol_object, 'all_trial_stim_parameter_keys'), 'must specify a list of all_trial_stim_parameter_keys within protocol object to use save_stringified_params flag'
            for key in protocol_object.all_trial_stim_parameter_keys:
                if key in protocol_object.trial_stim_parameters:
                    # Note string-ifying everything so we can build a big trial matrix with potentially different data types across trials within a column
                    self.trial_parameters[key] = str(protocol_object.trial_stim_parameters[key])
                else:  # store a dummy value
                    self.trial_parameters[key] = str(None)

        else:
            # Extract trial stim parameters
            if type(protocol_object.trial_stim_parameters) is tuple:  # stimulus is tuple of multiple stims layered on top of one another
                num_stims = len(protocol_object.trial_stim_parameters)
                for stim_ind in range(num_stims):
                    
                    prefix = f"stim{stim_ind}_"
                    for key in protocol_object.trial_stim_parameters[stim_ind]:
                        value = protocol_object.trial_stim_parameters[stim_ind][key]
                        self.trial_parameters[prefix + key] = hdf5ify_parameter(value)

            elif type(protocol_object.trial_stim_parameters) is dict:  # single stim class
                for key, value in protocol_object.trial_stim_parameters.items():
                    self.trial_parameters[key] = hdf5ify_parameter(value)
            
        # Extract and store protocol parameters
        for key, value in protocol_object.trial_protocol_parameters.items():
            self.trial_parameters[key] = hdf5ify_parameter(value)

        # In NWB the name is reserved so I am adding a prefix
        self.trial_parameters["protocol"] = self.trial_parameters.pop("name", "")

    def end_trial(self, protocol_object, reason=None):
        """
        Finalize the trial information and add the trial to the trials table.

        :param reason: None if the trial ran its full length, otherwise why it was cut short --
            see BaseData.end_trial. Recorded as trial columns, so a behaviour-ended trial can be
            told from one that ran to time. The trials table already carries start and stop times,
            so the duration is there by construction.

        Degrades quietly when there is nothing to write to, the same way create_trial and
        end_series do: this is called once per trial during a run, and a run that is not
        saving metadata should not raise on every trial.
        """
        if not self.trial_parameters or 'trial_start_time' not in self.trial_parameters:
            return

        self.trial_parameters['ended_early'] = reason is not None
        self.trial_parameters['trial_end_reason'] = str(reason) if reason is not None else ''

        nwbfile_path = self.get_nwb_file_path()
        if not os.path.isfile(nwbfile_path):
            warnings.warn(f'No NWB file at {nwbfile_path}; this trial was not saved.')
            return

        with NWBHDF5IO(nwbfile_path, 'r+') as io:
            subject_nwbfile = io.read()

            # Shift the time to be relative to the session start time
            session_start_time = subject_nwbfile.session_start_time
            start_time = self.trial_parameters.pop('trial_start_time')
            start_time = start_time - session_start_time.timestamp()
            stop_time = datetime.now(self.timezone).timestamp() - session_start_time.timestamp()
            
            # Create the table if it doesn't exist.
            #
            # None, not a number: this was 1000, which is a hard ceiling on the number of trials a
            # series can hold -- trial 1001 would have failed to write, and only then. The epochs
            # table alongside it already declares its columns unlimited.
            maxshape = None
            if subject_nwbfile.trials is None:
                ids = ElementIdentifiers(
                    name='id',
                    data=H5DataIO(data=[0], maxshape=(maxshape,)),
                )
                
                columns_to_add = []
                start_time = VectorData(name='start_time', description="the time the trial started",
                                              data=H5DataIO(data=[start_time], maxshape=(maxshape,)))
                columns_to_add.append(start_time)
                stop_time = VectorData(name='stop_time', description="the time the trial ended",
                                             data=H5DataIO(data=[stop_time], maxshape=(maxshape,)))
                columns_to_add.append(stop_time)
                for column in self.trial_parameters:
                    value = self.trial_parameters[column]
                    # maxshape has to have the same rank as the data, and a parameter is not
                    # always a scalar: width_height and center are pairs, and MovingPatch and
                    # MovingEllipse both have them. One row of a pair is shape (1, 2), so a
                    # rank-1 maxshape made h5py refuse the dataset and aborted the run on its
                    # first trial. Growing along rows only -- the width of a row is fixed by the
                    # first trial, which is what a table column means.
                    vector_column = VectorData(name=column, description=column,
                                               data=H5DataIO(data=[value],
                                                             maxshape=(maxshape,) + _row_shape(value)))
                    columns_to_add.append(vector_column)

                trials_table = TimeIntervals(
                    name='trials',
                    description="experimental trials",
                    columns=columns_to_add,
                    id=ids,
                )
                
                subject_nwbfile.trials = trials_table
            
            else:  # Just add a row to the table
                trial_row_kargs = self.trial_parameters
                trial_row_kargs["start_time"] = start_time
                trial_row_kargs["stop_time"] = stop_time
                subject_nwbfile.add_trial(**trial_row_kargs)

            # Write the nwbfile to disk
            io.write(subject_nwbfile)

    
    def create_note(self, note_text):
        """
        Because every trial run has its own file, and it isn't written until 'record'
        just use a big .csv file for experiment notes and timestamps
        """
        if self.experiment_file_exists():            
            timestamp = datetime.now(self.timezone).timestamp()

            notes_path = os.path.join(self.nwb_directory_path, 'notes.csv')

            with open(notes_path, 'a') as f_object:
                new_row = [timestamp, note_text]

                writer(f_object).writerow(new_row)

        else:
            print('Initialize a NWB file directory before writing a note')

# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
# # # # # # # # #  Retrieve / query data file # # # # # # # # # # # # # # # # #
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #

    def experiment_file_exists(self):
        if not self.experiment_file_name:
            return False

        # Directory with the nwb files
        return self.nwb_directory_path.is_dir()

    # The name this backend used before it conformed to the BaseData interface.
    nwb_directory_exists = experiment_file_exists

    def get_nwb_file_path(self):
        date_code = datetime.today().strftime('%Y%m%d')  # YYYYMMDD
        return Path(os.path.join(self.nwb_directory_path, f"{date_code}_{self.current_subject}_{str(self.series_count).zfill(3)}.nwb"))

    # current_subject_exists() is inherited: BaseData already tests current_subject, which is what
    # current_subject_id now aliases.

    def browsable_files(self):
        """One entry per series file, newest last, labelled by file name."""
        return [(os.path.basename(path), str(path)) for path in self.get_series_files()]

    def get_series_files(self):
        """The .nwb files in this experiment's directory, or none if it has not been made yet."""
        if not self.experiment_file_exists():
            return []
        return sorted(path for path in self.nwb_directory_path.iterdir() if path.suffix == '.nwb')

    def delete_series(self, series_number=None):
        """Remove a recorded series so its number can be recorded onto again.

        One file per series here, so this deletes that file rather than a group inside one. Found
        by number across the directory rather than by rebuilding the current subject's file name:
        a series number is global, and the file holding it may be another subject's or another
        day's, neither of which get_nwb_file_path would name.
        """
        series_number = self.series_count if series_number is None else series_number
        suffix = str(series_number).zfill(3)
        for path in self.get_series_files():
            stem = os.path.basename(str(path)).rsplit('.', 1)[0]
            if stem.split('_')[-1] == suffix:
                os.remove(path)
                return True
        return False

    def series_owner(self, series_number=None):
        """Which subject holds this series number, or None. Read from the file names, which carry
        the subject: <date>_<subject>_<NNN>.nwb."""
        series_number = self.series_count if series_number is None else series_number
        suffix = str(series_number).zfill(3)
        for path in self.get_series_files():
            stem = os.path.basename(str(path)).rsplit('.', 1)[0]
            parts = stem.split('_')
            if len(parts) >= 3 and parts[-1] == suffix:
                return '_'.join(parts[1:-1])      # a subject id may itself contain underscores
        return None

    def get_existing_series(self):
        series_numbers = []
        for file_path in self.get_series_files():
            series_no = int(os.path.split(file_path)[-1].split('.')[0][-3:])
            series_numbers.append(series_no)

        return series_numbers

    # get_highest_series_count() is inherited: it is written in terms of get_existing_series().

    def get_existing_subject_data(self):
        subject_data_list = []
        all_files = self.get_series_files()

        # Iterate over all the files open them with nwb and extract the subject metadata
        for file_path in all_files:
            with NWBHDF5IO(file_path, 'r') as io:
                subject_nwbfile = io.read()
                subject_metadata = dict(subject_nwbfile.subject.fields)
                # Unfold description as that was all the rest of the attributes that are non-canonical in nwb
                description_json = subject_metadata.pop('description')
                description = json.loads(description_json)
                subject_metadata.update(**description)

                # Undo the NWB-specific encodings applied on the way in, so what comes back out is
                # what was handed in. Without this the age reads back as 'P3D' and no caller can
                # tell an age in days from an ISO 8601 duration string.
                if 'age' in subject_metadata:
                    subject_metadata['age'] = _days_from_iso8601_duration(subject_metadata['age'])

                subject_data_list.append(subject_metadata)

        return subject_data_list

    # advance_series_count / update_series_count / get_series_count are inherited: the series
    # counter is just an integer, with nothing storage-specific about it.

    def reload_series_count(self):
        series_numbers = self.get_existing_series()

        # Find the max
        self.series_count = np.max(series_numbers) + 1 if series_numbers else 1

    def get_server_subdir(self):
        # One level deeper than the HDF5 backend: the experiment is a directory here, so
        # server-side files are filed under it by subject.
        return posixpath.join(self.experiment_file_name, str(self.current_subject))