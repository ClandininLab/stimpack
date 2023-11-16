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
        print(f"{all_series=}")
        print(f"{series=}")
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
            
            
        else:
            print('Create a data file and/or define a subject first')

    def end_epoch_run(self, protocol_object):
        """
        
        """
        
        # Have the imports here until you decide to add pynwb as a dependency
        from pynwb import NWBHDF5IO

        
        # Open the nwbfile in append mode (do we need to close this? maybe we can keep an open reference)
        nwbfile_path = self.nwb_file_directory / f"{self.current_subject}.nwb"
        with NWBHDF5IO(nwbfile_path, 'r+') as io:
            subject_nwbfile = io.read()
            session_start_time = subject_nwbfile.session_start_time
            
            start_time = self.epoch_parameters.pop('epoch_start_time')
            start_time = start_time - session_start_time.timestamp()
            stop_time = datetime.now(self.timezone).timestamp() - session_start_time.timestamp()
            
            for key in self.epoch_parameters:
                subject_nwbfile.add_epoch_column(name=key, description=key)
            
            epoch_row_kargs = self.epoch_parameters
            epoch_row_kargs["start_time"] = start_time
            epoch_row_kargs["stop_time"] = stop_time
            subject_nwbfile.add_epoch(**epoch_row_kargs)
            
            io.write(subject_nwbfile)
            
    def create_epoch(self, protocol_object):
        """
        This will create a row on either the epochs table or the TimeIntervals table
        """
                
        if (self.current_subject_exists() and self.experiment_file_exists()):
            
            # Have the imports here until you decide to add pynwb as a dependency
            from pynwb import Subject, NWBFile, NWBHDF5IO
            
            nwbfile_path = self.nwb_file_directory / f"{self.current_subject}.nwb"
            with NWBHDF5IO(nwbfile_path, 'a') as io:
                subject_nwbfile = io.read()
                
                session_start_time = subject_nwbfile.sesstion_start_time
                start_time =  datetime.now().timestamp() - session_start_time.timestamp()
                
                
            # If we go for one table per series we will need: str(self.series_count) in the table name
            
            # Extract protocol parameters
            if type(protocol_object.epoch_stim_parameters) is tuple:  # stimulus is tuple of multiple stims layered on top of one another
                # In this case add one row per stimuli with an extra attribute to identify the stimuli
                num_stims = len(protocol_object.epoch_stim_parameters)
                for stim_ind in range(num_stims):
                    stimuli_index = stim_ind 
                    row_name = f"stimulus_{stimuli_index}"
                    row_parameters = dict()
                    row_parameters["row_name"] = row_name
                    # TODO Add check that column exists on the table
                        
                
                    for key in protocol_object.epoch_stim_parameters[stim_ind]:
                        row_parameters[key] = hdf5ify_parameter(protocol_object.epoch_stim_parameters[stim_ind][key])

                    # Here add row to the table
                    # DO
                    
            elif type(protocol_object.epoch_stim_parameters) is dict:  # single stim class
                row_parameters = dict()
                for key in protocol_object.epoch_stim_parameters:
                    row_parameters[key] = hdf5ify_parameter(protocol_object.epoch_stim_parameters[key])
            
                # Here add row to the table
                # TODO
        else:
            print('Create a data file and/or define a subject first')

    def end_epoch(self, protocol_object):
        """
        This adds the the trials table
        """
        
    

    
    def create_note(self, note_text):
        
        pass 
        # TODO: Discuss with catalystneuro what is the best representation for notes
        # I am thinking on an AnnotationSeries object
        
        # ""
        # if self.experiment_file_exists():
        #     with h5py.File(os.path.join(self.data_directory, self.experiment_file_name + '.hdf5'), 'r+') as experiment_file:
        #         note_unix_time = str(datetime.now().timestamp())
        #         notes = experiment_file['/Notes']
        #         notes.attrs[note_unix_time] = note_text
        # else:
        #     print('Initialize a data file before writing a note')

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
        #TODO
        # Same comments as in the `get_existing_series` method
        pass
        # all_series = []
        # with h5py.File(os.path.join(self.data_directory, self.experiment_file_name + '.hdf5'), 'r') as experiment_file:
        #     for subject_id in list(experiment_file['/Subjects'].keys()):
        #         new_series = list(experiment_file['/Subjects/{}/epoch_runs'.format(subject_id)].keys())
        #         all_series.append(new_series)
        # all_series = [val for s in all_series for val in s]
        # series = [int(x.split('_')[-1]) for x in all_series]

        # if len(series) == 0:
        #     self.series_count = 0 + 1
        # else:
        #     self.series_count = np.max(series) + 1

