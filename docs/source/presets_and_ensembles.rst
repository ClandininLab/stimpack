=======================
Presets and ensembles
=======================

Two mechanisms for not retyping an experiment. A **preset** is a named set of parameters for one
protocol. An **ensemble** is an ordered queue of protocols to run back to back.

Parameter presets
=================

Fill in a protocol's parameters, press **Save preset**, give it a name, and it appears in the
*Param preset* dropdown from then on. Selecting it restores those parameters.

Presets are per protocol and live in the ``labpack``, at
``<parameter_presets_dir>/<ProtocolName>.yaml``, where ``parameter_presets_dir`` comes from the
config (see :doc:`labpack_configs`). They are therefore shared with everyone using that ``labpack`` and
versioned with it -- which is the point: "the version of this we ran last month" becomes a
selection rather than a reconstruction.

A preset stores both parameter sets::

    fast_drift:
      run_parameters:
        num_trials: 40
        idle_color: 0.5
      protocol_parameters:
        angle: [0, 45, 90]
        rate: 60.0

**A preset need not be complete.** Parameters absent from it keep the protocol's own defaults, so
adding a parameter to a protocol does not invalidate presets saved before it existed.

``Default``
-----------

Every protocol's dropdown offers ``Default``, which is the protocol's own declared defaults rather
than a saved preset. It cannot be overwritten -- saving under the name ``Default`` (in any spelling
or padding) is refused, because a dropdown entry that sometimes means "the code's defaults" and
sometimes means "whatever I last saved" is worse than no entry.

Names are trimmed of surrounding spaces, and an empty or space-only name is refused; ``' fast '``
and ``'fast'`` would otherwise be two presets indistinguishable in the dropdown. Re-saving an
existing name replaces it and says so, without a confirmation dialog -- revising the preset you are
working on is the common case.

**Delete preset** removes the selected one and rewrites the file. Both saving and deleting re-read
the file first, so two people editing presets for different protocols, or for the same one from
different machines, do not silently discard each other's work.

Ensembles
=========

A session is usually several protocols in a fixed order: a receptive-field map, then two stimulus
sets, then the map again to check nothing drifted. The **Ensemble** tab makes that a saved object
rather than a sequence someone remembers to perform.

Pick a protocol and a preset, press **Append**, repeat. The list can be reordered by dragging, and
**Remove** and **Clear** do what they say. **View** and **Record** run the whole queue, one item
after another, each as its own series with its own parameters and its own row in the data file.

Saving and loading
------------------

**Save ensemble** writes a ``.spens`` file -- YAML, a list of ``(protocol, preset)`` pairs, human
readable and diffable::

    - !!python/tuple [DriftingSquareGrating, fast_drift]
    - !!python/tuple [MovingPatch, Default]
    - !!python/tuple [DriftingSquareGrating, fast_drift]

**Load ensemble** reads one back. A pair naming a protocol this ``labpack`` does not have is reported
and dropped rather than failing the load, so an ensemble written against a ``labpack`` with one extra
protocol still opens.

Running one
-----------

While an ensemble runs, the Main tab's protocol and parameters follow the item in progress, and the
parameter fields stay locked -- editing them mid-ensemble would change what the remaining items do
without changing what the file says they did.

**Pause takes effect at the next trial boundary**, and an ensemble additionally holds *between
items*: a pause requested during the last trial of one protocol stops before the next protocol
starts, rather than after it has begun. **Stop** ends the ensemble, not just the item running, and
returns the GUI to standby.

.. note::

   An ensemble references presets by name. Renaming or deleting a preset an ensemble uses will make
   that item fall back to the protocol's defaults when it next runs -- silently, since a missing
   preset is not an error. If an ensemble matters, treat its presets as part of it.
