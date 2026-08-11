"""The stimpack.device shim: old import paths still work, warn, and yield the same objects.

The package split (device -> locomotion + daq) landed just before 1.0, but labpacks in the wild
import the old paths, and their server scripts build the KeyTrac app's path from stimpack's
install directory. The shim holds until 2.0. These tests pin that it forwards identity, not
copies -- an isinstance across old and new imports must agree, or the client's DAQonServer
detection silently stops matching -- and that the old app path still launches.
"""
import importlib
import os
import sys

import pytest

pytestmark = pytest.mark.unit


def test_the_old_paths_yield_the_very_same_classes():
    from stimpack.daq import DAQ, DAQonServer
    from stimpack.locomotion import LocoManager, LocoClosedLoopManager
    from stimpack.locomotion.keytrac import KeytracClosedLoopManager

    from stimpack.device.daq import DAQ as old_DAQ, DAQonServer as old_DAQonServer
    from stimpack.device.locomotion.loco_managers import (
        LocoManager as old_LocoManager, LocoClosedLoopManager as old_LocoClosedLoopManager)
    from stimpack.device.locomotion.loco_managers.loco_managers import (
        LocoClosedLoopManager as oldest_LocoClosedLoopManager)
    from stimpack.device.locomotion.loco_managers.keytrac_managers import (
        KeytracClosedLoopManager as old_KeytracClosedLoopManager)

    assert old_DAQ is DAQ
    assert old_DAQonServer is DAQonServer
    assert old_LocoManager is LocoManager
    assert old_LocoClosedLoopManager is LocoClosedLoopManager
    assert oldest_LocoClosedLoopManager is LocoClosedLoopManager
    assert old_KeytracClosedLoopManager is KeytracClosedLoopManager


def test_importing_the_old_package_warns_of_the_move():
    # The warning fires on first import; drop any cached copy so this test sees it regardless
    # of what ran before it.
    for name in [m for m in sys.modules if m.startswith('stimpack.device')]:
        del sys.modules[name]
    with pytest.warns(DeprecationWarning, match='stimpack.device is deprecated'):
        importlib.import_module('stimpack.device')


def test_the_keytrac_app_exists_at_both_paths():
    # Labpack server scripts construct the OLD path from ROOT_DIR and Popen it; the forwarder
    # at that path re-runs the moved app. Both files must exist for both generations to launch.
    from stimpack.util import ROOT_DIR
    assert os.path.isfile(os.path.join(ROOT_DIR, 'locomotion/keytrac/keytrac.py'))
    assert os.path.isfile(os.path.join(ROOT_DIR, 'device/locomotion/keytrac/keytrac.py'))
