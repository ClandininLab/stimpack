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
from datetime import datetime
import numpy as np

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
        
        # Create one nwbfile per subject
        
        from pynwb import NWBFile, NWBHDF5IO
        
        # Experiment date/time
        
        """
        Create NWB data file and initialize top-level hierarchy nodes
        """
        session_start_time = datetime.now()
        
        # The nwbfile is per-subject so we only store the metadata at this level to create a 
        self.nwbfile_metadata = dict(
            session_description='Experiment data', #TODO what should this be? 
            identifier="identifier", #TODO  What should this be? Most likely subject id
            session_start_time=session_start_time,
            experimenter=self.experimenter,
            lab='Clandinin',  #TODO could be added to the config.yaml for more flexibility
            institution='Stanford University',  # TODO could be added to the config.yaml for more flexibility
            experiment_description='Description of the experiment', 
            session_id='Session ID'
        )
        
        
        # TODO: Discuss this attribute, looks like a stimuli
        # One option is experiment_description but I need to think where it should go
        # rig_config:
        # Bruker_LeftScreen:
        #     data_directory: /home/johndoe/Desktop
        #     screen_center: [0,-30]
        #     rig: Bruker
        #     server_options: {'host': '171.65.17.246',
        #                     'port': 60629,
        #                     'use_server': True,
        #                     'visual_stim_module_paths': ['/home/johndoe/src/labpack/labpack/stimulus/example']} # Where your custom visual stimulus modules reside
        #     trigger: NIUSB6001(dev='Dev5', trigger_channel='ctr0')  # This trigger class should be defined in your daq module


        # Meanwhile make it available as a top level attribute
        self.rig_config_name = self.cfg.get('rig_config').get(self.cfg.get('current_rig_name'))
        rig_config = self.cfg.get('rig_config').get(self.rig_config_name)
        self.rig_config_parameters = dict()
        
        for key in rig_config:
                self.rig_config_parameters[key] = str(rig_config.get(key))


       
    def create_subject(self, subject_metadata):
        """
        """
        
        # Subject metadata looks like this:
        # subject_metadata = {}
        # # Built-ins
        # subject_metadata['subject_id'] = self.subject_id_input.text()
        # subject_metadata['age'] = self.subject_age_input.value()
        # subject_metadata['notes'] = self.subject_notes_input.toPlainText()

        # # user-defined:
        # for key in self.subject_metadata_inputs:
        #     subject_metadata[key] = self.subject_metadata_inputs[key].currentText()
        # From
        #https://github.com/h-mayorquin/stimpack/blob/89a326fcfc218b17bfaae3420ac9f9bf711b58d9/src/stimpack/experiment/gui.py#L733-L740
        
        # Here is were we create the nwbfile for the subject
        # First we check if the file already does not exists
        if subject_metadata.get('subject_id') in [x.get('subject_id') for x in self.get_existing_subject_data()]:
            print('A subject with this ID already exists')
            return


        if self.experiment_file_exists():
            self.nwb_file_directory = self.data_directory / Path(self.experiment_file_name)
            subject_id = subject_metadata.get('subject_id')
            nwbfile_path = self.nwb_file_directory / f"{subject_id}.nwb"
            
            
            keywords_in_the_nwb_subject_class = ["age", "genotype", "sex", "genotype", "weight", "age__reference", 
                                                 "species", "suject_id", "date_of_birth", "strain", ]
            
            # Have the imports here until you decide to add pynwb as a dependency
            from pynwb import Subject, NWBFile, NWBHDF5IO
            
            # Create the subject object
            subject_kwargs = {key: subject_metadata[key] for key in keywords_in_the_nwb_subject_class if key in subject_metadata}
            rest_of_the_subject_metadata = {key: subject_metadata[key] for key in subject_metadata if key not in keywords_in_the_nwb_subject_class}
            # Save the rest as subject description
            subject_kwargs['description'] = str(rest_of_the_subject_metadata)
            
            subject = Subject(**subject_kwargs)
            
            # Create the nwbfile
            self.nwbfile = NWBFile(**self.nwbfile_metadata, subject=subject)

            # Save it to disk
            with NWBHDF5IO(nwbfile_path, 'w') as io:
                io.write(self.nwbfile)

    def create_epoch_run(self, protocol_object):
        """"
        """
        
        # TODO: Get an example of protocol_object from Minseung and Max
        
        if (self.current_subject_exists() and self.experiment_file_exists()):
  
            # Have the imports here until you decide to add pynwb as a dependency
            from pynwb import Subject, NWBFile, NWBHDF5IO

        
            # Open the nwbfile in append mode (do we need to close this? maybe we can keep an open reference)
            nwbfile_path = self.nwb_file_directory / f"{self.current_subject}.nwb"
            with NWBHDF5IO(nwbfile_path, 'a') as io:
                subject_nwbfile = io.read()
                
            # We will create the columns of the nwbfile here
            run_start_unix_time = datetime.now().timestamp()
            protocol_parameters = dict()
            for key in protocol_object.run_parameters:  # add run parameter attributes
                protocol_parameters[key] = hdf5ify_parameter(protocol_object.run_parameters[key])
                
            protocol_id = protocol_object.__class__.__name__
            
            
            # Most likely I will add a TimeIntervals table to the nwbfile
            # But if all the experiments are successive or parts of the same 'session` then maybe all the epochs
            # Across all of the series should be added to an epochs table, not clear yet
            # TODO: Discuss with Max and Minseung
            
        else:
            print('Create a data file and/or define a subject first')

    def create_epoch(self, protocol_object):
        """
        This will create a row on either the epochs table or the TimeIntervals table
        """
        
        # TODO: Discuss with Max and Minseung how does the protcol_object looks like
        

        
        if (self.current_subject_exists() and self.experiment_file_exists()):
            
            # Have the imports here until you decide to add pynwb as a dependency
            from pynwb import Subject, NWBFile, NWBHDF5IO
            
            nwbfile_path = self.nwb_file_directory / f"{self.current_subject}.nwb"
            with NWBHDF5IO(nwbfile_path, 'a') as io:
                subject_nwbfile = io.read()
            
            epoch_unix_time = datetime.now().timestamp()

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
        Save the timestamp when the epoch ends
        """
        # Probably not nececesary for nwb but I can store this somewhere else

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
        #TODO:
        # Might be complicated and require to keep a memory structure / state.
        # They rely on the position of the series to identify structure but in nwb each file has defined place already
        # So better keep a record of which objects were already added. 
        pass
    
        # all_series = []
        # with h5py.File(os.path.join(self.data_directory, self.experiment_file_name + '.hdf5'), 'r') as experiment_file:
        #     for subject_id in list(experiment_file['/Subjects'].keys()):
        #         new_series = list(experiment_file['/Subjects/{}/epoch_runs'.format(subject_id)].keys())
        #         all_series.append(new_series)
        # all_series = [val for s in all_series for val in s]
        # series = [int(x.split('_')[-1]) for x in all_series]
        # return series

    def get_highest_series_count(self):
        series = self.get_existing_series()
        if len(series) == 0:
            return 0
        else:
            return np.max(series)

    def get_existing_subject_data(self):
        #TODO:
        # this should be asier
        pass 
        # # return list of dicts for subject metadata already present in experiment file
        # subject_data_list = []
        # if self.experiment_file_exists():
        #     with h5py.File(os.path.join(self.data_directory, self.experiment_file_name + '.hdf5'), 'r') as experiment_file:
        #         for subject in experiment_file['/Subjects']:
        #             new_subject = experiment_file['/Subjects'][subject]
        #             new_dict = {}
        #             for at in new_subject.attrs:
        #                 new_dict[at] = new_subject.attrs[at]

        #             subject_data_list.append(new_dict)
        # return subject_data_list

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

