Labpack
=================

.. image:: /_static/labpack_icon.svg
   :width: 80px
   :align: right
   :alt: The labpack mark: the stimpack screens-and-subject motif, in labpack yellow

The ``labpack``'s Python package (``template_labpack/`` in the template; renamed for your lab)
holds the code side of the ``labpack``: protocols, custom stimuli, a data class, a client class,
and device drivers. Stimpack loads these **by file path at runtime**, from the paths a config
names in ``module_paths`` -- nothing is imported by package name, so the package may be called
whatever your lab likes. Anything it defines is used in place of, or alongside, stimpack's
built-ins: a custom stimulus is addressed exactly as a built-in one, and a data or client class
replaces the default when a config names it.

See :doc:`labpack_configs` for the ``module_paths`` keys, and :doc:`check_labpack` for verifying
that everything a config names still resolves.

How the package is organized
----------------------------

Everything at the package's top level is named after the stimpack namespace it extends, so one
mental model serves both codebases and "where does my tracker subclass go?" answers itself --
the folder named after the stimpack package your class subclasses:

.. list-table::
   :header-rows: 1

   * - Extension point
     - stimpack namespace
     - In the template
     - Wired by
   * - protocols
     - ``stimpack.experiment.protocol``
     - ``protocol/``
     - ``module_paths.protocol``
   * - client
     - ``stimpack.experiment.client``
     - ``client.py``
     - ``module_paths.client``
   * - data
     - ``stimpack.experiment.data``
     - ``data.py``
     - ``module_paths.data``
   * - stimuli
     - ``stimpack.visual_stim``
     - ``visual_stim/``
     - ``module_paths.visual_stim``
   * - tracker
     - ``stimpack.locomotion``
     - ``locomotion/``
     - ``loco_class`` in the rig server
   * - DAQ
     - ``stimpack.daq``
     - ``daq/``
     - ``module_paths.daq`` (client trigger) and ``daq_class`` (rig server)

Two conventions fill in the rest:

**Names are mirrored; depth is not.** A name gets a directory when its content demands one, not
for symmetry with stimpack. ``protocol/`` is a directory because labs accumulate protocol modules
per user; ``daq/`` because each vendor gets a file (``ni.py``, ``labjack.py``, with the
``DAQonServer`` proxy in ``on_server.py``); ``client.py`` and ``data.py`` stay single files.
There is deliberately no ``experiment/`` grouping here even though stimpack has one -- it groups
a large subsystem there, and would group three unrelated files here.

**Hardware with no stimpack counterpart lives in** ``device/``. Not everything a rig needs
extends a stimpack class: the template's ``device/dlpc350.py`` drives a projector's pattern mode
and is called by server scripts at startup, backed by no server module and named by no config
key. Such drivers get a plain home rather than a forced parallel.

None of this is enforced. Stimpack reads the file paths a config names and expects the class
contracts (a protocol subclasses ``BaseProtocol``, a tracker ``LocoClosedLoopManager``, ...);
the layout is a convention for the humans maintaining the labpack, and a lab that outgrows it
can deviate freely.

