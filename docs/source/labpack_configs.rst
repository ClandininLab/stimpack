Stimpack Configs
================

The configs in this directory are used to define user-specific information.
The following fields must be defined:

- experimenter
- subject_metadata
- rig config
- parameter_presets_dir
- module_paths

An example may look like:

- experimenter:
- subject_metadata:
    - sex: Male
    - species: Mouse
    - area_1: left V1
    - genotype: isoD1
    - state: starved
- rig_config:
    - ephys_rig:
    - data_directory: ~/Desktop
    - screen_center: [0, 0]
- parameter_presets_dir: presets/jbm
- module_paths:
    - protocol: labpack/protocol/JBM_protocol.py
    - data: labpack/data.py
    - client: labpack/client.py
    - daq: labpack/device/daq.py


