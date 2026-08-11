"""
Deprecated: ``stimpack.device`` was split into top-level packages at 1.0.

The runtime organizes one module per capability ('visual', 'locomotion', 'voltage_out'), and the
package tree now mirrors that instead of grouping two of the three under a device category:

    stimpack.device.daq                                        -> stimpack.daq
    stimpack.device.locomotion.loco_managers                   -> stimpack.locomotion
    stimpack.device.locomotion.loco_managers.loco_managers     -> stimpack.locomotion.managers
    stimpack.device.locomotion.loco_managers.keytrac_managers  -> stimpack.locomotion.keytrac
    stimpack/device/locomotion/keytrac/keytrac.py              -> stimpack/locomotion/keytrac/keytrac.py

The modules under this package re-export the same objects from the new locations, so existing
imports (and isinstance checks against them) keep working. This shim will be removed in
stimpack 2.0.
"""
import warnings

warnings.warn("stimpack.device is deprecated and will be removed in stimpack 2.0; "
              "import from stimpack.locomotion / stimpack.daq instead "
              "(see stimpack/device/__init__.py for the path mapping).",
              DeprecationWarning, stacklevel=2)
