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
      #   Only once it overrides something -- see "Using your own data class" below.
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

    The file's root attributes record ``data_format``, so a reader can tell which layout it is
    holding without probing for group names, along with the provenance below.

``legacy_hdf5``
    The same file, with the names stimpack used before 0.3, when a trial was called an epoch and a
    series an epoch run::

        /Subjects/<id>/epoch_runs/series_001/epochs/epoch_001

    Choose it if analysis code reads the old layout. It is the same backend as ``hdf5`` with those
    names overridden — not a copy frozen at 0.2 — so it keeps every fix the current one gets.
    Tests assert that the group and attribute names it writes are the pre-rename ones, and that
    the two backends hold the same things under their two sets of names.

    Put it in a labpack's ``lab_config.yaml`` to apply it to every rig at once, and set
    ``data_format: hdf5`` in one rig's own config to move that rig over when its analysis is ready.

    It writes no ``data_format`` root attribute, deliberately: *absence* is how a reader
    recognises this layout, and means exactly "legacy, or written before 0.3". It does record
    provenance, since what this backend guarantees is the names analysis reads, and added root
    attributes cost none of that.

``nwb``
    A *directory* per experiment, holding one `NWB <https://www.nwb.org/>`_ file per series. NWB
    is a community standard for neurophysiology data, so this is the format to choose if you
    intend to share or archive data in it.

    The File tab browses these too: an ``.nwb`` file is HDF5 underneath, so the same tree reads
    it, with one node per series file since an NWB experiment is a directory rather than one file.
    Attributes are shown read-only -- pynwb validates a schema that a hand-edited attribute can
    break, where an HDF5 experiment is stimpack's own layout and editing one is a supported repair.

    Every NWB file records its provenance in ``source_script``, the schema's own field for what
    software wrote a file, as one line: ``stimpack 0.3.0.dev0 (28a303e); labpack clandinin_labpack
    (18b2dfe); config mc_config.yaml``. Two extra config keys are written in as top-level
    metadata:

    .. code-block:: yaml

        lab: Clandinin
        institution: Stanford University

The same GUI handles all three; it adapts to whichever backend the config names. The interface
differs only where the formats genuinely do — loading an NWB experiment asks for a directory
rather than a file, and its attributes are shown read-only.

To try a format without editing a config, pass ``stimpack --data-format nwb``.

What produced a file
~~~~~~~~~~~~~~~~~~~~

Every experiment records the code that made it — in root attributes for the HDF5 backends, in
``source_script`` for NWB:

=======================  ========================================================================
``stimpack_version``     the installed distribution's version
``stimpack_revision``    stimpack's git commit, ``.dirty`` if its tree had uncommitted changes
``labpack_directory``    where the labpack was read from
``labpack_name``         that directory's name
``labpack_revision``     the labpack's git commit, with the same ``.dirty`` marker
``config_name``          which config file was used
=======================  ========================================================================

Both halves are recorded because a stimulus is defined by both: the protocol that ran, the
parameters it exposed and the stimuli it drew all live in the labpack, so a stimpack version alone
cannot say what an experiment did.

``stimpack_revision`` is there because ``stimpack_version`` can lie. It comes from installed
distribution metadata, which for an editable install is whatever ``setup.py`` said at install
time — a rig running from a git checkout can report 0.1.1 while running 0.3.0 code. Prefer the
revision wherever it is present.

Anything that cannot be determined is left out rather than written empty, so a file never claims
to know something it does not. A labpack that is not a git checkout simply has no
``labpack_revision``.

Using your own data class
~~~~~~~~~~~~~~~~~~~~~~~~~

``module_paths.data`` names a class of your own. Its format is decided by the class it subclasses
— ``BaseData`` is HDF5, ``NWBData`` is NWB — so naming **one** class settles the format, and
``data_format`` is then **not consulted at all**: not the config's, not the startup dialog's, not
``--data-format``.

.. code-block:: yaml

    module_paths:
      data: labpack/data.py     # one class; its base fixes the format

That is a real constraint rather than a missing feature. Honouring a request for ``nwb`` against a
``class Data(BaseData)`` would mean constructing stimpack's ``NWBData`` instead of your class, so
the format would be right and every override you wrote would be silently gone — a worse failure
than the wrong format, because a wrong extension is obvious immediately and a missing frame
counter is not.

To keep both, give the key **one module per format**:

.. code-block:: yaml

    module_paths:
      data:
        hdf5: labpack/data.py
        nwb:  labpack/data_nwb.py

Now ``data_format``, the startup dialog and ``--data-format`` select among *your* classes exactly
as they select among the built-ins.

The dialog states which class will write the file whatever you choose — ``Written by
labpack/data_nwb.py.`` or ``Written by stimpack's built-in NWBData.`` — so the question is
answered even for a config with no data module of its own.

It also offers **every** format, not only the ones you supplied a class for: what stimpack can
write and what your labpack has customized are different questions. Each entry says which class
will write it, and choosing one you have no class for adds what that costs:

.. code-block:: text

    Data format:  hdf5 — labpack/data.py            ▾
                  legacy_hdf5 — stimpack built-in
                  nwb — labpack/data_nwb.py

Two classes in one module are named with a ``:ClassName`` suffix, which is worth knowing for the
two HDF5 layouts — they differ by five strings, so a labpack supporting both would otherwise put
its overrides in a mixin and write two three-line modules importing it:

.. code-block:: yaml

    module_paths:
      data:
        hdf5:        labpack/data.py:Data
        legacy_hdf5: labpack/data.py:DataLegacy
        nwb:         labpack/data_nwb.py

A mapping may also name a format stimpack has never heard of (``parquet: labpack/data_parquet.py``).
The class is loaded by path and only ever duck-typed, so that works.

With a single module the dialog disables the choice and shows the module's name rather than a
format: the path does not say which format the class writes, and finding out means importing it.
A one-entry mapping is the same class with the format stated. Either way, startup prints the class
actually writing the file.

``--check-labpack`` reports a config that maps data modules but sets no ``data_format`` (which one
runs is then decided by a default rather than by you), and one whose ``data_format`` is outside its
own mapping (legitimate — custom HDF5 and stock NWB is reasonable — but it means every launch
bypasses your classes).

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
