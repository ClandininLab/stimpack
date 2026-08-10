Labpack
=================

The ``labpack``'s Python package (``template_labpack/`` in the template; renamed for your lab)
holds the code side of the ``labpack``: protocols, custom stimuli, a data class, a client class,
and device drivers. Stimpack loads these **by file path at runtime**, from the paths a config
names in ``module_paths`` -- nothing is imported by package name, so the package may be called
whatever your lab likes. Anything it defines is used in place of, or alongside, stimpack's
built-ins: a custom stimulus is addressed exactly as a built-in one, and a data or client class
replaces the default when a config names it.

See :doc:`labpack_configs` for the ``module_paths`` keys, and :doc:`check_labpack` for verifying
that everything a config names still resolves.

