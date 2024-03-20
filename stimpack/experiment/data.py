#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Data file class

Data File structure is:
yyyy-mm-dd
    Subjects
        subject_id
            epoch_runs
                series_00n (attrs = protocol_parameters)
                    acquisition
                    epochs
                        epoch_001
                        epoch_002
                    stimulus_timing
    Notes

"""
import h5py
import os
import json
from datetime import datetime
import numpy as np
from pathlib import Path

from stimpack.experiment.util import config_tools


class BaseData():
    def __init__(self, cfg):
        self.cfg = cfg

        self.experiment_file_name = None
        self.series_count = 1
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
            rig_config = self.cfg.get('rig_config').get(self.cfg.get('current_rig_name'))
            for key in rig_config:
                experiment_file.attrs[key] = str(rig_config.get(key))

            # Create a top-level group for epoch runs and user-entered notes
            experiment_file.create_group('Subjects')
            experiment_file.create_group('Notes')

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

                new_subject.create_group('epoch_runs')

            self.select_subject(subject_metadata.get('subject_id'))
            print('Created subject {}'.format(subject_metadata.get('subject_id')))
        else:
            print('Initialize a data file before defining a subject')

    def create_epoch_run(self, protocol_object):
        """"
        """
        # create a new epoch run group in the data file
        if (self.current_subject_exists() and self.experiment_file_exists()):
            with h5py.File(os.path.join(self.data_directory, self.experiment_file_name + '.hdf5'), 'r+') as experiment_file:
                run_start_unix_time = datetime.now().timestamp()
                subject_group = experiment_file['/Subjects/{}/epoch_runs'.format(self.current_subject)]
                new_epoch_run = subject_group.create_group('series_{}'.format(str(self.series_count).zfill(3)))
                new_epoch_run.attrs['run_start_unix_time'] = run_start_unix_time
                for key in protocol_object.run_parameters:  # add run parameter attributes
                    new_epoch_run.attrs[key] = protocol_object.run_parameters[key]
                new_epoch_run.attrs['protocol_ID'] = protocol_object.__class__.__name__

                for key in protocol_object.protocol_parameters:  # add user-entered protocol params
                    new_epoch_run.attrs[key] = hdf5ify_parameter(protocol_object.protocol_parameters[key])

                # add subgroups:
                new_epoch_run.create_group('acquisition')
                new_epoch_run.create_group('epochs')
                new_epoch_run.create_group('rois')
                new_epoch_run.create_group('stimulus_timing')

        else:
            print('Create a data file and/or define a subject first')

    def create_epoch(self, protocol_object):
        """
        """
        if (self.current_subject_exists() and self.experiment_file_exists()):
            with h5py.File(os.path.join(self.data_directory, self.experiment_file_name + '.hdf5'), 'r+') as experiment_file:
                epoch_unix_time = datetime.now().timestamp()
                epoch_run_group = experiment_file['/Subjects/{}/epoch_runs/series_{}/epochs'.format(self.current_subject, str(self.series_count).zfill(3))]
                new_epoch = epoch_run_group.create_group('epoch_{}'.format(str(protocol_object.num_epochs_completed+1).zfill(3)))
                new_epoch.attrs['epoch_unix_time'] = epoch_unix_time

                epoch_stim_parameters_group = new_epoch
                if type(protocol_object.epoch_stim_parameters) is tuple:  # stimulus is tuple of multiple stims layered on top of one another
                    num_stims = len(protocol_object.epoch_stim_parameters)
                    for stim_ind in range(num_stims):
                        for key in protocol_object.epoch_stim_parameters[stim_ind]:
                            prefix = 'stim{}_'.format(str(stim_ind))
                            epoch_stim_parameters_group.attrs[prefix + key] = hdf5ify_parameter(protocol_object.epoch_stim_parameters[stim_ind][key])

                elif type(protocol_object.epoch_stim_parameters) is dict:  # single stim class
                    for key in protocol_object.epoch_stim_parameters:
                        epoch_stim_parameters_group.attrs[key] = hdf5ify_parameter(protocol_object.epoch_stim_parameters[key])

                epoch_protocol_parameters_group = new_epoch
                for key in protocol_object.epoch_protocol_parameters:  # save out convenience parameters
                    epoch_protocol_parameters_group.attrs[key] = hdf5ify_parameter(protocol_object.epoch_protocol_parameters[key])

        else:
            print('Create a data file and/or define a subject first')

    def end_epoch(self, protocol_object):
        """
        Save the timestamp when the epoch ends
        """
        with h5py.File(os.path.join(self.data_directory, self.experiment_file_name + '.hdf5'), 'r+') as experiment_file:
            epoch_end_unix_time = datetime.now().timestamp()
            epoch_run_group = experiment_file['/Subjects/{}/epoch_runs/series_{}/epochs'.format(self.current_subject, str(self.series_count).zfill(3))]
            epoch_group = epoch_run_group['epoch_{}'.format(str(protocol_object.num_epochs_completed+1).zfill(3))]
            epoch_group.attrs['epoch_end_unix_time'] = epoch_end_unix_time

    
    def end_epoch_run(protocol_object):
        """
        Empty for the hdf5 data file
        """
        pass

    def create_note(self, note_text):
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
        if self.experiment_file_name is None:
            tf = False
        else:
            tf = os.path.isfile(os.path.join(self.data_directory, self.experiment_file_name + '.hdf5'))
        return tf

    def current_subject_exists(self):
        if self.current_subject is None:
            tf = False
        else:
            tf = True
        return tf

    def get_existing_series(self):
        all_series = []
        with h5py.File(os.path.join(self.data_directory, self.experiment_file_name + '.hdf5'), 'r') as experiment_file:
            for subject_id in list(experiment_file['/Subjects'].keys()):
                new_series = list(experiment_file['/Subjects/{}/epoch_runs'.format(subject_id)].keys())
                all_series.append(new_series)
        all_series = [val for s in all_series for val in s]
        series = [int(x.split('_')[-1]) for x in all_series]
        return series

    def get_highest_series_count(self):
        series = self.get_existing_series()
        if len(series) == 0:
            return 0
        else:
            return np.max(series)

    def get_existing_subject_data(self):
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
        self.current_subject = subject_id

    def advance_series_count(self):
        self.series_count += 1

    def update_series_count(self, val):
        self.series_count = val

    def get_series_count(self):
        return self.series_count

    def reload_series_count(self):
        all_series = []
        with h5py.File(os.path.join(self.data_directory, self.experiment_file_name + '.hdf5'), 'r') as experiment_file:
            for subject_id in list(experiment_file['/Subjects'].keys()):
                new_series = list(experiment_file['/Subjects/{}/epoch_runs'.format(subject_id)].keys())
                all_series.append(new_series)
        all_series = [val for s in all_series for val in s]
        series = [int(x.split('_')[-1]) for x in all_series]

        if len(series) == 0:
            self.series_count = 0 + 1
        else:
            self.series_count = np.max(series) + 1


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


class NWBData():
    def __init__(self, cfg):
        self.cfg = cfg


        # In the case of nwb this should be a directory, where the subjects are store as nwbfile is one-file-per-subject
        # I am keeping the semantics to make the gui compatible
        self.experiment_file_name = None
        self.series_count = 1
        self.subject_metadata = {}  # populated in GUI or user protocol
        self.current_subject = None

        # default data_directory, experiment_file_name, experimenter from cfg
        # may be overwritten by GUI or other before initialize_experiment_file() is called
        self.data_directory = Path(config_tools.get_data_directory(self.cfg))
        self.experimenter = config_tools.get_experimenter(self.cfg)
        
        self.nwb_file_directory = None  # Should be data_directory / experiment_file_name when that is created
        # This is where all the subjects will be preserved
    
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
# # # # # # # # #  Creating experiment file and groups  # # # # # # # # # # # #
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #

    def initialize_experiment_file(self):     
        """
        Save top level metadata that all the nwb files will share
        Also create the directory where the nwb files will be stored
        """
        
        self.nwb_file_directory = self.data_directory / Path(self.experiment_file_name)
        self.nwb_file_directory.mkdir(parents=True, exist_ok=True)

        from datetime import datetime, timezone
        self.timezone = timezone.utc  # This could be changed if desired
        session_start_time = datetime.now(self.timezone)


        rig_config = self.cfg.get('rig_config').get(self.cfg.get('current_rig_name'))        
        self.rig_config_parameters = dict()
        for key in rig_config:
            self.rig_config_parameters[key] = str(rig_config.get(key, ""))

        experiment_description = str(self.rig_config_parameters)
        
        # The nwbfile is per-subject so we only store the metadata that all the files will share
        self.general_nwb_kwargs = dict(
            session_description='Experiment data', # what should this be? 
            session_start_time=session_start_time,
            experimenter=self.experimenter,
            lab='Clandinin',  #TODO could be added to the config.yaml for more flexibility
            institution='Stanford University',  # TODO could be added to the config.yaml for more flexibility
            experiment_description=experiment_description, 
        )
        

    def create_subject(self, subject_metadata):
        """
        Create a NWB file for the subject
        """
        # Inline imports unless you decide to add pynwb as a dependency
        from pynwb.file import Subject
        from pynwb import NWBFile, NWBHDF5IO
        from copy import deepcopy

        subject_id = subject_metadata.get('subject_id')
        self.current_subject = subject_id
        nwbfile_path = self.nwb_file_directory / f"{subject_id}.nwb"
        if nwbfile_path.is_file():
            print('A subject with this ID already exists')
            return

        if not self.experiment_file_exists():
            print('Initialize a data file before defining a subject')
            return 
        
        nwbfile_path = self.nwb_file_directory / f"{subject_id}.nwb"
        
        # If those files are passed as metadata, they will be mapped to their canonical place in the nwbfile
        keywords_in_the_nwb_subject_class = ["age", "genotype", "sex", "genotype", "weight", "age__reference", 
                                                "species", "subject_id", "date_of_birth", "strain", ]
        
        # Here we deep copy the general dictionary and we modify it for the specific subject 
        nwbfile_kwargs = deepcopy(self.general_nwb_kwargs)
        nwbfile_kwargs["identifier"] = subject_id

        # Create the subject object
        subject_kwargs = {key: subject_metadata[key] for key in keywords_in_the_nwb_subject_class if key in subject_metadata}
        
        # In NWB the age is a string
        if 'age' in subject_kwargs:
            subject_kwargs['age'] = str(subject_kwargs['age'])
        
        # Save the rest as subject description
        rest_of_the_subject_metadata = {key: subject_metadata[key] for key in subject_metadata if key not in keywords_in_the_nwb_subject_class}
        subject_kwargs['description'] = json.dumps(rest_of_the_subject_metadata)
        
        # Creates  a subject object with allthe metadata
        subject = Subject(**subject_kwargs)
        
        # Create the nwbfile and save it to disk
        nwbfile = NWBFile(**nwbfile_kwargs, subject=subject)
        with NWBHDF5IO(nwbfile_path, 'w-') as io:
            io.write(nwbfile)

    def create_epoch_run(self, protocol_object):
        """
        This will only store the protocol parameters and the protocol ID.
        The epoch 
        """
        
        
        self.epoch_parameters = {}
        
        # TODO: Get an example of protocol_object from Minseung and Max
        
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
            print('Create a data file and/or define a subject first')

    def end_epoch_run(self, protocol_object):
        """
        NWB requires the stop time to be set when the epoch is created
        So this function is called after an epoch run is concluded and this adds an entry
        to the epochs table that corresponds to the whole epoch run
        """
        # Have the imports here until you decide to add pynwb as a dependency
        from pynwb import NWBHDF5IO
        from pynwb.epoch import TimeIntervals
        from hdmf.common import VectorData,VectorIndex
        from hdmf.backends.hdf5.h5_utils import H5DataIO
        from hdmf.common.table import ElementIdentifiers        
        
        # Open the nwbfile in append mode (do we need to close this? maybe we can keep an open reference)
        nwbfile_path = self.nwb_file_directory / f"{self.current_subject}.nwb"
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
                        # columns_to_add.append(vector_column)
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
                
        if not (self.current_subject_exists() and self.experiment_file_exists()):
            print('Create a data file and/or define a subject first')

            
        self.trial_parameters = {}
        self.trial_parameters['trial_start_time'] = datetime.now(self.timezone).timestamp()
        
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
        # Have the imports here until you decide to add pynwb as a dependency
        from pynwb import NWBHDF5IO
        from pynwb.epoch import TimeIntervals
        from hdmf.common import VectorData,VectorIndex
        from hdmf.backends.hdf5.h5_utils import H5DataIO
        from hdmf.common.table import ElementIdentifiers        

        nwbfile_path = self.nwb_file_directory / f"{self.current_subject}.nwb"
        with NWBHDF5IO(nwbfile_path, 'r+') as io:
            subject_nwbfile = io.read()

            # Shift the time to be relative to the session start time
            session_start_time = subject_nwbfile.session_start_time
            start_time = self.trial_parameters.pop('trial_start_time')
            start_time = start_time - session_start_time.timestamp()
            stop_time = datetime.now(self.timezone).timestamp() - session_start_time.timestamp()
            
            # Create the table if it doesn't exist
            if subject_nwbfile.trials is None:
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
                for column in self.trial_parameters:
                    value = self.trial_parameters[column]
                    value_is_list_tuple_or_array = isinstance(value, (tuple, list, np.ndarray))
                    if not value_is_list_tuple_or_array:
                        vector_column = VectorData(name=column, description=column, data=H5DataIO(data=[value], maxshape=(None,)))
                        columns_to_add.append(vector_column)
                    else:
                        data = list(value)
                        vector_column = VectorData(name=column, description=column, data=H5DataIO(data=data, maxshape=(None, )))
                        end_index_first_element = len(value)
                        vector_index = VectorIndex(name=column + "_index", target=vector_column, data=H5DataIO(data=[end_index_first_element], maxshape=(None,)))
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
        
        # Have the imports here until you decide to add pynwb as a dependency
        from pynwb import NWBHDF5IO, ProcessingModule
        from pynwb.core import DynamicTable
        from hdmf.common import VectorData
        from hdmf.backends.hdf5.h5_utils import H5DataIO
        from hdmf.common.table import ElementIdentifiers

        
        if self.experiment_file_exists():
            nwbfile_path = Path(self.nwb_file_directory) / f"{self.current_subject}.nwb"

            with NWBHDF5IO(str(nwbfile_path), 'r+') as io:
                nwbfile = io.read()

                # Check if a processing module for notes exists, if not, create it
                module_name = 'NotesModule'
                table_name = "Notes"
                if module_name not in nwbfile.processing:
                    notes_module = ProcessingModule(name=module_name,
                                                    description='Module to store experiment notes')
                    nwbfile.add_processing_module(notes_module)

                
                    timestamp = datetime.now().timestamp() - nwbfile.session_start_time.timestamp()    

                    timestamp_column = VectorData(name='timestamp', description="the time the note was taken",
                                                  data=H5DataIO(data=[timestamp], maxshape=(None,)))
                    text_column = VectorData(name='note', description="a note",
                                             data=H5DataIO(data=[note_text], maxshape=(None,)))

                    ids = ElementIdentifiers(
                        name='id',
                        data=H5DataIO(data=[0], maxshape=(None,)),
                    )
                    notes_table = DynamicTable(
                        name=table_name,
                        description="Experiment notes",
                        columns=[timestamp_column, text_column],
                        id=ids,
                    )                    
                    notes_module.add(notes_table)
                else:
                    notes_module = nwbfile.processing[module_name]
                    notes_table = notes_module.get_data_interface(table_name)

                    # Add the new note
                    timestamp = datetime.now().timestamp() - nwbfile.session_start_time.timestamp()    
                    notes_table.add_row(timestamp=timestamp, note=note_text)
                
                # Write changes to file
                io.write(nwbfile)
        else:
            print('Initialize a NWB file before writing a note')
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
# # # # # # # # #  Retrieve / query data file # # # # # # # # # # # # # # # # #
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #

    def experiment_file_exists(self):
        if self.experiment_file_name is None:
            return False 
        
        # Directory with the nwb files, one per subject
        return Path(self.data_directory / self.experiment_file_name).is_dir()

        
    def current_subject_exists(self):
        if self.current_subject is None:
            tf = False
        else:
            tf = True
        return tf

    def get_existing_series(self):
        from pynwb import NWBHDF5IO

        all_series = []
        # Gets all the paths for the NWB files 
        all_files = [path for path in self.nwb_file_directory.iterdir()]
        
        # Iterate over all the files open them with nwb and extract the subject metadata
        for file_path in all_files:

            with NWBHDF5IO(file_path, 'r') as io:
                subject_nwbfile = io.read()
                subject_series = subject_nwbfile.epochs["series"].data
                all_series.extend(subject_series)
        
        series = [int(x.split('_')[-1]) for x in all_series]
        return series  
        

    def get_highest_series_count(self):
        series = self.get_existing_series()
        if len(series) == 0:
            return 0
        else:
            return np.max(series)

    def get_existing_subject_data(self):
        
        from pynwb import NWBHDF5IO

        subject_data_list = []
        
        # Gets all the paths for the NWB files 
        all_files = [path for path in self.nwb_file_directory.iterdir()]
        
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
        from pynwb import NWBHDF5IO
        import numpy as np

        all_series = []
        # Iterate over all NWB files in the directory
        all_files = [path for path in self.nwb_file_directory.iterdir() if path.is_file()]

        for file_path in all_files:
            with NWBHDF5IO(file_path, 'r') as io:
                subject_nwbfile = io.read()
                # Extract 'series' data from the 'epochs' table
                if 'epochs' in subject_nwbfile and 'series' in subject_nwbfile.epochs.colnames:
                    subject_series = subject_nwbfile.epochs['series'].data[:]
                    all_series.extend(subject_series)

        # Convert series identifiers to integers and find the max
        series_numbers = [int(x.split('_')[-1]) for x in all_series if isinstance(x, str) and x.startswith('series_')]
        self.series_count = np.max(series_numbers) + 1 if series_numbers else 1