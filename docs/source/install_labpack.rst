======================
Installation (Labpack)
======================

``stimpack`` allows extensive customization and fine-tuning through a sister package, your *labpack*. A labpack is not published on PyPI: it is a lab-specific local collection of protocols, stimuli, rig configs and device drivers that augment the core ``stimpack`` facilities. You install your own copy from source, in editable mode.

1. Make your own copy of the template
-------------------------------------
Go to `github.com/ClandininLab/labpack-template <https://github.com/ClandininLab/labpack-template>`_ and press **Use this template** to create your lab's repository, then clone it:

.. code-block:: console

    git clone https://github.com/<your-org>/<your-labpack>
    cd <your-labpack>

You can make your repository **private**. Rig configs hold data paths, machine addresses and experimenter names, which most labs would rather not publish. (A *fork* of a public repository cannot be made private; a template copy can.)

2. Rename the package, then install it
--------------------------------------
The template's package is called ``template_labpack`` so it can be installed alongside an existing labpack. Rename it for your lab, which keeps yours from colliding with anyone else's:

.. code-block:: console

    python scripts/rename_package.py smithlab_pack --dry-run   # preview
    python scripts/rename_package.py smithlab_pack
    pip3 install -e ./

The ``-e`` flag installs it in editable mode, so changes you make take effect immediately without reinstalling. Add hardware drivers only if the rig needs them: ``pip3 install -e .[nidaq]`` or ``.[labjack]``.

.. note::

    The template's Python package is named ``template_labpack``, not ``labpack``, so it can be
    installed alongside a lab's existing labpack. **Renaming it for your lab is encouraged.** Pick
    something unique, then rename the package directory and update ``name``/``packages`` in
    ``setup.py``, the ``from template_labpack...`` imports, and the ``module_paths`` entries in your
    configs — those four have to agree.

    Stimpack never imports your labpack by name. It resolves the directory recorded in
    ``path_to_labpack.txt`` and loads modules by file path, so the package name is yours to choose.

