==================
The experiment GUI
==================

``stimpack`` opens the same window on every rig. It is a thin shell over the protocol object and
the data backend, which is why a protocol written this morning is drivable without writing any
interface code for it: selecting a protocol reads its declared parameters and builds the fields.

.. figure:: /images/gui.png
   :align: center
   :alt: The stimpack experiment GUI, the Main tab mid-run and the Subject tab with lab-declared metadata fields

   The experiment GUI, identical on every rig. Left: the Main tab mid-run, its parameter fields
   built from the protocol class's own declarations; the list-valued angle sweeps across trials
   in randomized order, and the bottom panel tracks the run. Right: the Subject tab, whose
   metadata fields beyond the built-ins are declared in the labpack's config.

Starting up
===========

Before the window opens, a dialog asks which **config** and which **rig** within it, and which
**data format** to write. That choice settles where data go, what geometry the screens have and
which hardware the server will claim; it is recorded in the file. If the chosen config names
things stimpack cannot find, the problems are reported here rather than discovered mid-session --
see :doc:`check_labpack`.

The Main tab
============

**Protocol** and **Param preset** choose what to run; the parameters below fill in from the
protocol's own declarations, split into *run parameters* (which stimpack reads: ``num_trials``,
``idle_color``, ``randomize_order``) and *protocol parameters* (which only your protocol reads).
Give a protocol parameter a list of values and it sweeps across trials. See :doc:`overview` for
which is which, and :doc:`presets_and_ensembles` for saving a filled-in set under a name.

Four buttons run it:

**View**
    Present the stimulus, save nothing. No series number is used and no data are written.

**Record**
    The same run, written to the data file as a numbered series. Requires an experiment file and a
    subject; the button stays disabled until both exist, and its tooltip says which is missing.

**Pause**
    Takes effect **at the next trial boundary**, not mid-presentation, so a paused run resumes with
    an intact trial structure. The status line distinguishes *pausing after this trial* from
    *paused*, because the gap between the two is a whole trial long.

**Stop**
    Ends the run without waiting out the trial in progress.

Keeping View and Record separate makes checking a stimulus before committing to it an explicit
choice rather than a file to delete afterwards.

While a run is going, the readouts below the parameters show the series number, elapsed and
estimated time, trials completed, the subject, and **This trial** -- the parameters that differ
between trials, which is the thing you actually want to see and the only part of a large parameter
set worth watching. **Note** writes free text into the data file at the moment you take it.

The other tabs
==============

**Ensemble**
    A queue of (protocol, preset) pairs run back to back, saved and loaded as a file. See
    :doc:`presets_and_ensembles`.

**Subject**
    Create or update the subject being recorded. The fields are whatever the config's
    ``subject_metadata`` declares -- a field given a list of values becomes a dropdown -- plus the
    built-in id, age and notes. What is collected is therefore a property of your laboratory rather
    than of stimpack. See :doc:`labpack_configs`.

**File**
    Create or load an experiment file, and browse what is in the one you have open as it fills.

Neither the Main tab nor the Ensemble tab can start a run while the other is running, and the
buttons say so rather than silently doing nothing.

.. note::

   The GUI is not required. Everything it drives is a plain object, and a protocol can be run from
   a script instead -- see :doc:`first_stimulus`, which presents stimuli with no GUI and no rig.
