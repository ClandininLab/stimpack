Customizing Labpack
===================

The labpack directory has four important components that give you complete control over the `stimpack` framework. 


- the Python package (``template_labpack/`` in the template; rename it for your lab)
        your protocols, custom stimuli, data class, client class and device drivers. Stimpack loads
        these by file path, as named in ``module_paths``.
- `configs/`
        one YAML file per user or setup, listing rigs and the ``module_paths`` above. These appear
        in the config dropdown of stimpack's startup dialog.
- `server/`
        rig server scripts, for rigs where the stimulus server runs on a separate machine. Named by
        the ``local_server_path`` key in a config.
- `presets/`
        saved protocol parameter sets, per user. The directory is named by ``parameter_presets_dir``.

You can explore how these may be used to customize `stimpack` by reading the following documentation

.. toctree::
    :maxdepth: 1
    
    labpack_self
    labpack_configs
    labpack_server
    labpack_presets 
