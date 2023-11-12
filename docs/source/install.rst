Installation (Stimpack)
==========


1. Make a new python virtualenvironment
^^^^^^^^^^^^^^^^^^^

In the terminal, type:
    >>> python3 -m venv .stimpack

This will create a new virtual environment in the current directory. You can activate it by typing:
    >>> source .stimpack/bin/activate

2. ``pip`` install stimpack 
^^^^^^^^^^^^^^^^^^^

In your virtualenvironment, install stimpack via ``pip``:
    >>> python3 -m pip install stimpack


3. Confirm installation 
^^^^^^^^^^^^^^^^^^^^^^^

In the ``.stimpack`` virtual environment, type:
    >>> stimpack


This should result in a window opening, that looks like this:

.. image:: /assets/labpack_query.png
    :width: 200px
    :align: center
    :alt: Stimpack window

If you see this window, you have successfully installed stimpack. 
Press `Enter` (red). You should now see a window that looks like this:

.. image:: /assets/stimpack_gui.png
    :width: 500px
    :align: center
    :alt: Stimpack window
