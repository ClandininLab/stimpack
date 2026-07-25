======================
Installation (Labpack)
======================

``stimpack`` allows extensive customization and fine-tuning through a sister package, your *labpack*. A labpack is not published on PyPI: it is a lab-specific local collection of protocols, stimuli, rig configs and device drivers that augment the core ``stimpack`` facilities. You install your own copy from source, in editable mode.

1. Download the labpack template
--------------------------------
In a terminal, run the following command to download the template:
    >>> git clone https://github.com/clandininlab/labpack

2. Install your labpack
-----------------------
In a terminal, run the following commands to install it:
    >>> cd labpack
    >>> pip3 install -e ./

The ``-e`` flag installs it in editable mode, so changes you make take effect immediately without reinstalling.

.. note::

    The template's Python package is named ``template_labpack``, not ``labpack``, so it can be
    installed alongside a lab's existing labpack. **Renaming it for your lab is encouraged.** Pick
    something unique, then rename the package directory and update ``name``/``packages`` in
    ``setup.py``, the ``from template_labpack...`` imports, and the ``module_paths`` entries in your
    configs — those four have to agree.

    Stimpack never imports your labpack by name. It resolves the directory recorded in
    ``path_to_labpack.txt`` and loads modules by file path, so the package name is yours to choose.

