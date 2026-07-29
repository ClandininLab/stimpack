"""
The pre-0.3 spelling of the two experiment levels, kept working.

stimpack called one stimulus presentation an *epoch* and a run of them an *epoch run*. NWB calls
them a **trial** and stimpack now calls the run a **series**, so an NWB file written by stimpack
and the code that wrote it use the same words. See :doc:`labpack_configs`.

Renaming the API would otherwise break every labpack: one lab's alone has 105 protocols defining
``get_epoch_parameters`` and about 1500 references to the old attribute names. The helpers here let
both spellings work, so a labpack can be ported when its authors choose rather than the day they
upgrade. Each old name warns once per process, naming its replacement.

The aliases are scheduled for removal in 0.4.0. ``stimpack --check-labpack`` reports which ones a
labpack still uses.
"""
import functools
import warnings


def _warn_once(old, new, kind):
    """Warn about a deprecated name, once per name per process.

    Once, because these sit on per-trial code paths: a protocol reading trial_protocol_parameters
    every trial would otherwise emit the same warning hundreds of times in a run and bury anything
    that mattered. Python's default filter would collapse them anyway, but only while the warning
    is raised from one line, and these are raised from wherever the caller is.
    """
    key = (old, new, kind)
    if key in _warn_once.seen:
        return
    _warn_once.seen.add(key)
    warnings.warn(f"{kind} '{old}' is deprecated and will be removed in stimpack 0.4.0; "
                  f"use '{new}'. Run `stimpack --check-labpack` to find these in a labpack.",
                  DeprecationWarning, stacklevel=3)


_warn_once.seen = set()


def deprecated_method(new_name, old_name):
    """A method that forwards to its new name, warning the first time it is used."""
    def alias(self, *args, **kwargs):
        _warn_once(old_name, new_name, 'Method')
        return getattr(self, new_name)(*args, **kwargs)

    alias.__name__ = old_name
    alias.__qualname__ = old_name
    alias.__doc__ = f"Deprecated alias for :meth:`{new_name}`."
    # Marked so calls_legacy_override can tell "the subclass still overrides the old name" from
    # "the base class supplies the old name as an alias". Comparing against the base class itself
    # would need it to exist at decoration time, which it does not -- the decorator runs while the
    # class body is still executing.
    alias.is_deprecated_alias = True
    return alias


def deprecated_attribute(new_name, old_name):
    """An attribute that reads and writes its new name, warning the first time it is used.

    Read *and* write: a labpack protocol assigns self.epoch_protocol_parameters in its own
    get_epoch_parameters, and the value has to land where stimpack now looks for it.
    """
    def getter(self):
        _warn_once(old_name, new_name, 'Attribute')
        return getattr(self, new_name)

    def setter(self, value):
        _warn_once(old_name, new_name, 'Attribute')
        setattr(self, new_name, value)

    return property(getter, setter, doc=f"Deprecated alias for ``{new_name}``.")


def add_deprecated_aliases(cls, methods=(), attributes=()):
    """Attach deprecated aliases to a class. Returns the class, so it can be used as a decorator."""
    for old_name, new_name in methods:
        setattr(cls, old_name, deprecated_method(new_name, old_name))
    for old_name, new_name in attributes:
        setattr(cls, old_name, deprecated_attribute(new_name, old_name))
    return cls


def calls_legacy_override(legacy_name):
    """Decorator: hand over to a subclass that still overrides the old name.

    A labpack protocol defines ``get_epoch_parameters``; stimpack now calls ``get_trial_parameters``.
    Nothing connects the two unless the new method looks for the old override and defers to it.

    The guard flag matters. A legacy override commonly starts with
    ``super().get_epoch_parameters()``, which reaches the base class's deprecated alias, which
    forwards to the new method -- which would find the override again and recurse forever. While
    dispatching, the new method therefore runs its own body instead, which is what that super()
    call is asking for.
    """
    def decorate(new_method):
        flag = f'_dispatching_{legacy_name}'

        @functools.wraps(new_method)
        def wrapper(self, *args, **kwargs):
            override = getattr(type(self), legacy_name, None)
            if (override is not None
                    and not getattr(override, 'is_deprecated_alias', False)
                    and not getattr(self, flag, False)):
                _warn_once(legacy_name, new_method.__name__, 'Method')
                setattr(self, flag, True)
                try:
                    return override(self, *args, **kwargs)
                finally:
                    setattr(self, flag, False)
            return new_method(self, *args, **kwargs)

        return wrapper
    return decorate


# Run parameters are dict keys rather than attributes, so they need renaming too: a protocol
# declaring num_epochs, or a saved preset carrying it, must still say how many trials to run.
RUN_PARAMETER_RENAMES = {'num_epochs': 'num_trials'}


class RunParameters(dict):
    """Run parameters under their current keys, still answering to the pre-0.3 ones.

    Renaming the key on the way in is not enough: a protocol that *reads*
    ``run_parameters['num_epochs']`` then finds nothing, which is how two labpack protocols
    raised KeyError under a compatibility layer meant to keep them running. Storing both spellings
    instead would let them drift the moment anything wrote one of them.
    """

    def _resolve(self, key):
        if key not in RUN_PARAMETER_RENAMES or dict.__contains__(self, key):
            return key
        new_name = RUN_PARAMETER_RENAMES[key]
        if dict.__contains__(self, new_name):
            _warn_once(key, new_name, 'Run parameter')
            return new_name
        return key

    def __getitem__(self, key):
        return dict.__getitem__(self, self._resolve(key))

    def __contains__(self, key):
        return dict.__contains__(self, self._resolve(key))

    def get(self, key, default=None):
        return dict.get(self, self._resolve(key), default)


def normalize_run_parameters(run_parameters):
    """Rename any pre-0.3 run-parameter keys, warning once each.

    Applied to every assignment of BaseProtocol.run_parameters, so everything downstream --
    the required-parameter check, the data file, a protocol reading its own parameters -- sees
    one spelling. A config that somehow carries both keeps the new one.
    """
    if not isinstance(run_parameters, dict):
        return run_parameters
    for old_name, new_name in RUN_PARAMETER_RENAMES.items():
        if old_name in run_parameters:
            _warn_once(old_name, new_name, 'Run parameter')
            value = dict.pop(run_parameters, old_name)
            run_parameters.setdefault(new_name, value)
    return RunParameters(run_parameters)
