#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Data file class for the .nwb file format.

Where BaseData writes one HDF5 file per experiment, this writes a DIRECTORY per experiment
holding one .nwb file per series. That difference is the only thing the GUI needs to know, and
it reads it from the output_is_directory trait rather than from this class's name.

Requires pynwb, which is an optional dependency:  pip install stimpack[nwb]
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

try:
    from pynwb.file import Subject
    from pynwb import NWBFile, NWBHDF5IO
    from pynwb.epoch import TimeIntervals
    from hdmf.common import VectorData, VectorIndex
    from hdmf.backends.hdf5.h5_utils import H5DataIO
    from hdmf.common.table import ElementIdentifiers
except ImportError as e:  # pragma: no cover - depends on how stimpack was installed
    # Raised on use rather than on import, so that merely importing stimpack.experiment.data_nwb
    # (which gui.py does when listing the available backends) does not break an HDF5-only install.
    raise ImportError(
        "The NWB data backend requires pynwb. Install it with:  pip install stimpack[nwb]"
    ) from e

from stimpack.experiment.data import BaseData, hdf5ify_parameter
from stimpack.experiment.util import config_tools


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

    Vocabulary note: this backend's own terms map onto BaseData's as
        nwb_directory      -> experiment_file_name   (the directory's name)
        parent_directory   -> data_directory         (what it sits in)
        current_subject_id -> current_subject
    The NWB spellings are kept as properties, so protocols and labpack code written against
    either name keep working.
    """
    output_is_directory = True
    supports_data_browser = False   # h5io's tree browser cannot read a directory of nwb files
    output_noun = 'NWB directory'

    def __init__(self, cfg):
        super().__init__(cfg)
        self.subject = None
        # Set here rather than only in create_epoch_run / create_epoch, so the end_* methods can
        # ask whether there is anything to write without tripping over a missing attribute --
        # they run from the client's finally block, after failures that never got that far.
        self.epoch_parameters = {}
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

        rig_config = self.cfg.get('rig_config').get(self.cfg.get('current_rig_name'))        
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

            # Create the nwbfile and save it to disk
            nwbfile = NWBFile(**nwbfile_kwargs, subject=self.subject)

            with NWBHDF5IO(nwbfile_path, 'w-') as io:
                io.write(nwbfile)

        else:
            print(f'Create an {self.output_noun} and/or define a subject first')

    # The name this backend used before it conformed to the BaseData interface.
    create_data_file = prepare_series


    def create_epoch_run(self, protocol_object):
        """
        Store the protocol parameters and the protocol ID.
        """
        
        self.epoch_parameters = {}
                
        if (self.current_subject_exists() and self.experiment_file_exists()):
            
            self.epoch_parameters = {}
            self.epoch_parameters["series"] = f"series_{str(self.series_count).zfill(3)}"
            self.epoch_parameters['protocol_id'] = protocol_object.__class__.__name__
            
            # Add the protocol parameters to the epoch_parameters
            for key in protocol_object.run_parameters:  # add run parameter attributes
                self.epoch_parameters[key] = hdf5ify_parameter(protocol_object.run_parameters[key])
                
            for key in protocol_object.protocol_parameters:  # add user-entered protocol params
                self.epoch_parameters[key] = hdf5ify_parameter(protocol_object.protocol_parameters[key])
                
            # Add the epoch start time
            self.epoch_parameters['epoch_start_time'] = datetime.now(self.timezone).timestamp()
            
            # Given that we are using epochs, epochs in nwb for your "epochs runs" and "trials " for your "epochs" 
            # I am going to shift the nomencalture to be consistent with nwb
            self.epoch_parameters["num_trials"] = self.epoch_parameters.get("num_epochs", "")
            
        else:
            print('Create an nwb file directory and/or define a subject first')

    def end_epoch_run(self, protocol_object, status='completed', reason=None):
        """
        NWB requires the stop time to be set when the epoch is created
        So this function is called after an epoch run is concluded and this adds an entry
        to the epochs table that corresponds to the whole epoch run

        :param status: how the run ended -- 'completed', 'stopped', 'aborted' or 'error'
        :param reason: detail for a run that did not complete, e.g. the exception text

        The client calls this from a finally block, so it runs for runs that failed as well as
        runs that finished. Everything below therefore has to cope with a run that never got as
        far as creating its epoch parameters or its file.
        """
        # create_epoch_run bails out (leaving epoch_parameters empty) when there is no subject or
        # no directory, and the client still reaches its finally block. Popping a key that was
        # never set would then raise from inside the error handler, replacing whatever actually
        # went wrong with a bare KeyError.
        if not self.epoch_parameters or 'epoch_start_time' not in self.epoch_parameters:
            warnings.warn(f'No epoch run to close out (run ended {status}); nothing written to NWB.')
            return

        # Likewise, the per-series file is written by prepare_series; a run that failed before
        # that has nothing to append to.
        nwbfile_path = self.get_nwb_file_path()
        if not os.path.isfile(nwbfile_path):
            warnings.warn(f'No NWB file at {nwbfile_path} (run ended {status}); nothing written.')
            return

        # Record how the run ended alongside its parameters, so a partial run is identifiable in
        # the data rather than looking like a short but successful one.
        self.epoch_parameters['run_status'] = str(status)
        self.epoch_parameters['run_status_reason'] = str(reason) if reason is not None else ''

        # Open the nwbfile in append mode
        with NWBHDF5IO(nwbfile_path, 'r+') as io:
            subject_nwbfile = io.read()

            # Shift the time to be relative to the session start time
            session_start_time = subject_nwbfile.session_start_time
            start_time = self.epoch_parameters.pop('epoch_start_time')
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

                for column in self.epoch_parameters:
                    value = self.epoch_parameters[column]
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
                            vector_column = VectorData(name=column, description=column, data=H5DataIO(data=data, maxshape=(None, )))
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
                epoch_row_kargs = self.epoch_parameters
                epoch_row_kargs["start_time"] = start_time
                epoch_row_kargs["stop_time"] = stop_time
                subject_nwbfile.add_epoch(**epoch_row_kargs)
            
            # Write the nwbfile to disk
            io.write(subject_nwbfile)
            
    def create_epoch(self, protocol_object):
        """
        This loads the data from the protocol object stim parameters.
        Then, when the epoch is concluded, we add the data as a row of the trials table.
        """
                
        self.trial_parameters = {}
        if not (self.current_subject_exists() and self.experiment_file_exists()):
            # Return, rather than warning and carrying on: collecting parameters for an epoch
            # that has nowhere to go only defers the failure to end_epoch, which then reports a
            # missing file instead of the missing subject that actually caused it.
            warnings.warn(f'Create an {self.output_noun} and/or define a subject first; '
                          f'this epoch will not be saved.')
            return

        self.trial_parameters['trial_start_time'] = datetime.now(self.timezone).timestamp()

        if protocol_object.save_stringified_params:
            assert hasattr(protocol_object, 'all_epoch_stim_parameter_keys'), 'must specify a list of all_epoch_stim_parameter_keys within protocol object to use save_stringified_params flag'
            for key in protocol_object.all_epoch_stim_parameter_keys:
                if key in protocol_object.epoch_stim_parameters:
                    # Note string-ifying everything so we can build a big trial matrix with potentially different data types across trials within a column
                    self.trial_parameters[key] = str(protocol_object.epoch_stim_parameters[key])
                else:  # store a dummy value
                    self.trial_parameters[key] = str(None)

        else:
            # Extract epoch stim parameters
            if type(protocol_object.epoch_stim_parameters) is tuple:  # stimulus is tuple of multiple stims layered on top of one another
                num_stims = len(protocol_object.epoch_stim_parameters)
                for stim_ind in range(num_stims):
                    
                    prefix = f"stim{stim_ind}_"
                    for key in protocol_object.epoch_stim_parameters[stim_ind]:
                        value = protocol_object.epoch_stim_parameters[stim_ind][key]
                        self.trial_parameters[prefix + key] = hdf5ify_parameter(value)

            elif type(protocol_object.epoch_stim_parameters) is dict:  # single stim class
                for key, value in protocol_object.epoch_stim_parameters.items():
                    self.trial_parameters[key] = hdf5ify_parameter(value)
            
        # Extract and store protocol parameters
        for key, value in protocol_object.epoch_protocol_parameters.items():
            self.trial_parameters[key] = hdf5ify_parameter(value)

        # In NWB the name is reserved so I am adding a prefix
        self.trial_parameters["protocol"] = self.trial_parameters.pop("name", "")

    def end_epoch(self, protocol_object):
        """
        Finalize the trial information and add the trial to the trials table.

        Degrades quietly when there is nothing to write to, the same way create_epoch and
        end_epoch_run do: this is called once per epoch during a run, and a run that is not
        saving metadata should not raise on every epoch.
        """
        if not self.trial_parameters or 'trial_start_time' not in self.trial_parameters:
            return

        nwbfile_path = self.get_nwb_file_path()
        if not os.path.isfile(nwbfile_path):
            warnings.warn(f'No NWB file at {nwbfile_path}; this epoch was not saved.')
            return

        with NWBHDF5IO(nwbfile_path, 'r+') as io:
            subject_nwbfile = io.read()

            # Shift the time to be relative to the session start time
            session_start_time = subject_nwbfile.session_start_time
            start_time = self.trial_parameters.pop('trial_start_time')
            start_time = start_time - session_start_time.timestamp()
            stop_time = datetime.now(self.timezone).timestamp() - session_start_time.timestamp()
            
            # Create the table if it doesn't exist
            maxshape = 1000
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
                    vector_column = VectorData(name=column, description=column, data=H5DataIO(data=[value], maxshape=(maxshape,)))
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

    def get_series_files(self):
        """The .nwb files in this experiment's directory, or none if it has not been made yet."""
        if not self.experiment_file_exists():
            return []
        return sorted(path for path in self.nwb_directory_path.iterdir() if path.suffix == '.nwb')

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

    def advance_series_count(self):
        self.series_count += 1

    def update_series_count(self, val):
        self.series_count = val

    def get_series_count(self):
        return self.series_count

    def reload_series_count(self):
        series_numbers = self.get_existing_series()

        # Find the max
        self.series_count = np.max(series_numbers) + 1 if series_numbers else 1

    def get_server_subdir(self):
        # One level deeper than the HDF5 backend: the experiment is a directory here, so
        # server-side files are filed under it by subject.
        return posixpath.join(self.experiment_file_name, str(self.current_subject))