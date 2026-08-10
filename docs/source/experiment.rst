stimpack.experiment
===================

Subpackages
-----------

.. toctree::
   :maxdepth: 4

   experiment.util

Submodules
----------

experiment.client module
------------------------

.. automodule:: stimpack.experiment.client
   :members:
   :show-inheritance:

experiment.data module
----------------------

.. automodule:: stimpack.experiment.data
   :members:
   :show-inheritance:

experiment.data_legacy module
-----------------------------

The HDF5 layout stimpack wrote before 1.0, selected with ``data_format: legacy_hdf5`` in a config,
so analysis code that walks the old group names keeps working. See :doc:`labpack_configs`.

.. automodule:: stimpack.experiment.data_legacy
   :members:
   :show-inheritance:

experiment.data_nwb module
--------------------------

The NWB storage backend, selected with ``data_format: nwb`` in a config. Requires ``pynwb``.
See :doc:`labpack_configs`.

.. automodule:: stimpack.experiment.data_nwb
   :members:
   :show-inheritance:

experiment.deprecated_names module
----------------------------------

The pre-1.0 *epoch* spellings of the trial and series API, kept working with a once-per-process
warning each. See :doc:`overview` for the rename.

.. automodule:: stimpack.experiment.deprecated_names
   :members:
   :show-inheritance:

experiment.gui_data_browser module
----------------------------------

The File tab's data browser. Supplied by the data backend via
:meth:`~stimpack.experiment.data.BaseData.make_data_browser`, so a format that cannot be browsed
as a tree simply provides none.

.. automodule:: stimpack.experiment.gui_data_browser
   :members:
   :show-inheritance:

experiment.gui module
---------------------

.. automodule:: stimpack.experiment.gui
   :members:
   :undoc-members:
   :show-inheritance:

experiment.protocol module
--------------------------

.. automodule:: stimpack.experiment.protocol
   :members:
   :undoc-members:
   :show-inheritance:

experiment.server module
------------------------

.. automodule:: stimpack.experiment.server
   :members:
   :undoc-members:
   :show-inheritance:

Module contents
---------------

.. automodule:: stimpack.experiment
   :members:
   :undoc-members:
   :show-inheritance:
