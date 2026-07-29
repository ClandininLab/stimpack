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
      # data: template_labpack/data.py           # class must be named "Data"
      #   Only once it overrides something: naming it here means data_format is ignored.
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



Choosing where data goes
------------------------

``data_format`` selects one of stimpack's built-in storage backends:

.. code-block:: yaml

    data_format: hdf5      # the default; may be omitted
    # or
    data_format: nwb

This sets the default. The startup dialog offers the same choice, showing whatever the selected
config asks for, so a format can be tried without editing the config; ``stimpack --data-format``
overrides both. The choice is made there rather than in the main window because an experiment
cannot change format part-way through -- its file, subject and series number all belong to one
backend.

``hdf5``
    One ``.hdf5`` file per experiment, with each subject and series a group inside it. This is
    stimpack's original format and what everything else in these docs assumes::

        /Subjects/<id>/series/series_001/trials/trial_001

``legacy_hdf5``
    The same file, with the names stimpack used before 0.3, when a trial was called an epoch and a
    series an epoch run::

        /Subjects/<id>/epoch_runs/series_001/epochs/epoch_001

    Choose it if analysis code reads the old layout. It is the same backend as ``hdf5`` with those
    names overridden -- not a copy frozen at 0.2 -- so it keeps every fix the current one gets. A
    test asserts that a file it writes is indistinguishable from one stimpack wrote before the
    rename.

    Put it in a labpack's ``lab_config.yaml`` to apply it to every rig at once, and set
    ``data_format: hdf5`` in one rig's own config to move that rig over when its analysis is ready.

``nwb``
    A *directory* per experiment, holding one `NWB <https://www.nwb.org/>`_ file per series. NWB
    is a community standard for neurophysiology data, so this is the format to choose if you
    intend to share or archive data in it.

    The File tab browses these too: an ``.nwb`` file is HDF5 underneath, so the same tree reads
    it, with one node per series file since an NWB experiment is a directory rather than one file.
    Attributes are shown read-only -- pynwb validates a schema that a hand-edited attribute can
    break, where an HDF5 experiment is stimpack's own layout and editing one is a supported repair.

    Two extra config keys are written into every NWB file as top-level metadata:

    .. code-block:: yaml

        lab: Clandinin
        institution: Stanford University

The same GUI handles all three; it adapts to whichever backend the config names. The interface
differs only where the formats genuinely do — loading an NWB experiment asks for a directory
rather than a file, and its attributes are shown read-only.

To try a format without editing a config, pass ``stimpack --data-format nwb``.

.. warning::

    A config naming its own data module under ``module_paths.data`` uses that class and
    ``data_format`` is **not consulted at all** — not the config's, not the startup dialog's, not
    ``--data-format``. The dialog disables the choice and names the responsible module when this
    is the case, and startup prints the class actually writing the file.

    So a labpack whose ``data.py`` subclasses ``BaseData`` writes ``hdf5`` however the config or
    dialog is set. If you want the setting to decide, do not name a data module; point
    ``module_paths.data`` at your own class only once it overrides something.

.. note::

    ``stimpack --check-labpack`` reports a ``data_format`` naming a backend that is not available
    on this machine (for example ``nwb`` where ``pynwb`` is not installed). Without that check the
    config looks fine and the GUI fails on launch, at the rig.

Settings shared across a lab
----------------------------

A config file named ``lab_config.yaml`` is treated as defaults underneath every *other* config in
the same ``configs/`` directory. Values that are the same for everyone in the lab live there once,
instead of being copied into each rig's config where they drift apart:

.. code-block:: yaml

    # configs/lab_config.yaml
    lab: Clandinin
    institution: Stanford University
    data_format: nwb
    subject_metadata:
      species: [Drosophila melanogaster]
      sex: [Female, Male]

.. code-block:: yaml

    # configs/ephys_rig.yaml -- inherits all of the above
    experimenter: mht
    subject_metadata:
      prep: [ex vivo, in vivo]     # added to the lab-wide fields, not replacing them

The merge is deep: nested dictionaries merge key by key, lists combine without duplicating, and
anything a rig's own config sets wins over the lab-wide value. ``lab_config.yaml`` is not offered
in the config picker at startup, since it is not a config to run against on its own.
