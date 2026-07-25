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

.. code-block:: yaml

    experimenter: jbm
    subject_metadata:
      sex: [Male, Female]
      species: Mouse
      area_1: left V1
      genotype: isoD1
      state: starved

    rig_config:
      ephys_rig:
        data_directory: ~/Desktop
        screen_center: [0, 0]

    # Paths below are relative to the labpack directory recorded in path_to_labpack.txt.
    parameter_presets_dir: presets/jbm

    module_paths:
      protocol:                                  # may be a list of modules
        - template_labpack/protocol/JBM_protocol.py
      data: template_labpack/data.py             # class must be named "Data"
      client: template_labpack/client.py         # class must be named "Client"
      daq: template_labpack/device/daq.py
      visual_stim:                               # may be a list of directories
        - template_labpack/visual_stim/example

.. note::

    ``template_labpack`` is the package name in the template repository. If you renamed the package
    for your lab (recommended), use your own name here — these are file paths relative to your
    labpack directory, so they must match the directory on disk.

.. warning::

    Custom stimuli belong under ``module_paths.visual_stim``. An older layout put them in
    ``server_options.visual_stim_module_paths``; current stimpack does **not** read that key, so
    stimuli listed there are silently never loaded, and referencing one fails at run time with
    "0 stimulus candidates".


