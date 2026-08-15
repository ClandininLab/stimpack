"""
The locomotion module: movement trackers feeding subject state to the server.

Base classes live in :mod:`stimpack.locomotion.managers`; :mod:`stimpack.locomotion.keytrac` is
the keyboard stand-in tracker. Real tracker drivers subclass these from a labpack.
"""
from stimpack.locomotion.managers import LocoManager, LocoClosedLoopManager

__all__ = ['LocoManager', 'LocoClosedLoopManager']
