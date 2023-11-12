============
Installation (Labpack)
============

``stimpack`` allows extensive customization and fine-tuning through the sister package ``labpack``. ``labpack`` is not pip installable, and is meant to be a user-specific local collection of modifications and customizations that replace and augment the core ``stimpack`` facilities.

1. Download the ``labpack`` template
-----
In a terminal, run the following command to download the ``labpack`` template:
    >>> git clone https://github.com/clandininlab/labpack

2. Install your ``labpack``
-----
In a terminal, run the following command to install your ``labpack``:
    >>> cd labpack
    >>> pip3 install -e ./

The ``-e`` command installs the ``labpack`` in editable mode, so that you can make changes to the ``labpack`` and have them take effect immediately.

