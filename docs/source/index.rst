====================================================================================================
stimpack: a modular framework for precise multisensory stimulus generation in systems neuroscience
====================================================================================================

`stimpack`_ is a Python framework for presenting precisely parameterized, flexibly defined
sensory stimuli to a subject — across multiple perspective-corrected flat screens, calibrated
curved projection surfaces, and non-visual outputs — and recording what was presented with timing
precise enough to line up with neural data. Stimuli run open loop or in closed loop against the
subject's own movement, fed by whatever tracker a laboratory uses.

Everything specific to your laboratory — rig geometry, hardware drivers, stimulus definitions,
protocols — lives in a ``labpack`` outside the installed package, so one protocol library runs
unchanged across rigs of different geometry and hardware. Start yours from the
`labpack template <https://github.com/ClandininLab/labpack-template>`_. Data are written through pluggable
backends, including HDF5 and `NWB <https://www.nwb.org/>`_.

.. _stimpack: https://github.com/ClandininLab/stimpack

.. toctree::
    :maxdepth: 1
    :caption: Contents

    overview
    quickstart
    API
    under_the_hood


Looking for a specific function? See the :ref:`index of all functions <genindex>`.
