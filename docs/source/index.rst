======================================================================
stimpack: precise and flexible generation of stimuli for neuroscience
======================================================================

`stimpack`_ is a Python framework for presenting precisely parameterized, flexibly defined
sensory stimuli to an animal — across multiple perspective-corrected flat screens, calibrated
curved projection surfaces, and non-visual outputs — and recording what happened with timing
precise enough to line up with neural data. Stimuli run open loop or in closed loop against the
animal's own movement, fed by whatever tracker a laboratory uses.

Everything specific to your laboratory — rig geometry, hardware drivers, stimulus definitions,
protocols — lives in a *labpack* outside the installed package, so one protocol library runs
unchanged across rigs of different geometry and hardware. Data are written through pluggable
backends, including HDF5 and `NWB <https://www.nwb.org/>`_.

.. _stimpack: https://github.com/ClandininLab/stimpack

.. toctree::
    :maxdepth: 1
    :caption: Contents

    overview
    quickstart
    API
    under_the_hood


:ref:`genindex` of all functions.
