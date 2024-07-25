#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Data file class for .nwb file format

"""
from copy import deepcopy
from csv import writer
import os
import json
import numpy as np
from pathlib import Path
import posixpath
from datetime import datetime, timezone

from pynwb.file import Subject
from pynwb import NWBFile, NWBHDF5IO
from pynwb.epoch import TimeIntervals
from hdmf.common import VectorData,VectorIndex
from hdmf.backends.hdf5.h5_utils import H5DataIO
from hdmf.common.table import ElementIdentifiers

from stimpack.experiment.util import config_tools

class NWBData():
    """

    Data class corresponding to a series of .nwb files. One .nwb file per trial run / series
    
    """
    def __init__(self, cfg):
        self.cfg = cfg
        self.subject_metadata = {}  # populated in GUI or user protocol

        self.subject = None
        self.nwb_directory = None

        self.series_count = 1
        self.current_subject_id = None

        # default parent_directory, experimenter from cfg
        # may be overwritten by GUI or other before initialize_experiment() is called
        self.parent_directory = config_tools.get_data_directory(self.cfg)
        self.experimenter = config_tools.get_experimenter(self.cfg)
        
    
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
# # # # # # # # #  Creating experiment file and groups  # # # # # # # # # # # #
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #

    def initialize_experiment(self):     
        """
        Create a dict of top level metadata that all the nwb files will share
        Also create the directory where the nwb files will be stored
        """
        
        # Create experiment file directory:
        self.nwb_directory_path = Path(os.path.join(self.parent_directory, self.nwb_directory))
        self.nwb_directory_path.mkdir(parents=True, exist_ok=True)

        self.initialize_session()

    def load_experiment(self, nwb_directory_path):
        self.nwb_directory_path = Path(nwb_directory_path)
        self.parent_directory = os.path.split(nwb_directory_path)[:-1]
        self.nwb_directory = os.path.split(nwb_directory_path)[-1]
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
        self.subject_metadata = subject_metadata
        self.current_subject_id = subject_metadata['subject_id']

    def create_subject(self, subject_metadata):
        """
        Create an NWB subject for the data object
        """

        if not self.nwb_directory_exists():
            print('Initialize a nwb directory before defining a subject')
            return 
                
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
            subject_kwargs['age'] = str(subject_kwargs['age'])
        
        # Save the rest as subject description
        rest_of_the_subject_metadata = {key: subject_metadata[key] for key in subject_metadata if key not in keywords_in_the_nwb_subject_class}
        subject_kwargs['description'] = json.dumps(rest_of_the_subject_metadata)
        
        # Creates a subject object with all the metadata
        self.subject = Subject(**subject_kwargs)

    def create_data_file(self):
        """
        Write the file for this trial run

        """
        if (self.current_subject_exists() and self.nwb_directory_exists()):
            # Re-create the nwb subject object
            self.create_subject(self.subject_metadata)

            nwbfile_kwargs = self.subject_nwbfile_kwargs
            nwbfile_kwargs = deepcopy(self.subject_nwbfile_kwargs)

            nwbfile_path = self.get_nwb_file_path()

            # Create the nwbfile and save it to disk
            nwbfile = NWBFile(**nwbfile_kwargs, subject=self.subject)

            with NWBHDF5IO(nwbfile_path, 'w-') as io:
                io.write(nwbfile)

        else:
            print('Create an nwb file directory and/or define a subject first')

        

    def create_epoch_run(self, protocol_object):
        """
        Store the protocol parameters and the protocol ID.
        """
        
        self.epoch_parameters = {}
                
        if (self.current_subject_exists() and self.nwb_directory_exists()):
            
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

    def end_epoch_run(self, protocol_object):
        """
        NWB requires the stop time to be set when the epoch is created
        So this function is called after an epoch run is concluded and this adds an entry
        to the epochs table that corresponds to the whole epoch run
        """   
        
        # Open the nwbfile in append mode
        nwbfile_path = self.get_nwb_file_path()
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
                
        if not (self.current_subject_exists() and self.nwb_directory_exists()):
            print('Create a data file and/or define a subject first')

            
        self.trial_parameters = {}
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
        """

        nwbfile_path = self.get_nwb_file_path()
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
                    value_is_list_tuple_or_array = isinstance(value, (tuple, list, np.ndarray))
                    if not value_is_list_tuple_or_array:
                        vector_column = VectorData(name=column, description=column, data=H5DataIO(data=[value], maxshape=(maxshape,)))
                        columns_to_add.append(vector_column)
                    else:
                        data = list(value)
                        vector_column = VectorData(name=column, description=column, data=H5DataIO(data=data, maxshape=(maxshape, )))
                        end_index_first_element = len(value)
                        vector_index = VectorIndex(name=column + "_index", target=vector_column, data=H5DataIO(data=[end_index_first_element], maxshape=(maxshape,)))
                        columns_to_add.append(vector_column)
                        columns_to_add.append(vector_index)
                          
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
        if self.nwb_directory_exists():            
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

    def nwb_directory_exists(self):
        if self.nwb_directory is None:
            return False
        
        # Directory with the nwb files
        return self.nwb_directory_path.is_dir()

    def get_nwb_file_path(self):
        return Path(os.path.join(self.nwb_directory_path, f"{self.current_subject_id}_{str(self.series_count).zfill(3)}.nwb"))
            
    def current_subject_exists(self):
        if self.current_subject_id is None:
            tf = False
        else:
            tf = True
        return tf

    def get_existing_series(self):
        series_numbers = []
        # Iterate over all NWB files in the directory
        all_files = [path for path in self.nwb_directory_path.iterdir() if str(path).split('.')[-1] == 'nwb']

        for file_path in all_files:
            series_no = int(os.path.split(file_path)[-1].split('.')[0][-3:])
            series_numbers.append(series_no)

        return series_numbers
        
    def get_highest_series_count(self):
        series = self.get_existing_series()
        if len(series) == 0:
            return 0
        else:
            return np.max(series)

    def get_existing_subject_data(self):
        subject_data_list = []
        
        # Gets all the paths for the NWB files
        if self.nwb_directory is not None:
            all_files = [path for path in self.nwb_directory_path.iterdir() if '.nwb' in str(path)]
        else:
            all_files = []
        
        # Iterate over all the files open them with nwb and extract the subject metadata
        for file_path in all_files:
            with NWBHDF5IO(file_path, 'r') as io:
                subject_nwbfile = io.read()
                subject_metadata = subject_nwbfile.subject.fields
                # Unfold description as that was all the rest of the attributes that are non-canonical in nwb
                description_json = subject_metadata.pop('description')
                description = json.loads(description_json)
                subject_metadata.update(**description)
                
                subject_data_list.append(subject_metadata)

        return subject_data_list
        

    def select_subject(self, subject_id):
        self.current_subject = subject_id

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
        return posixpath.join(self.nwb_directory, self.current_subject_id)

def hdf5ify_parameter(value):
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