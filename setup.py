from setuptools import setup, find_packages

setup(
    name='stimpack',
    # Pre-release marker for the branch, not a released version: PEP 440 orders this after 0.2.0
    # (the current release) and before 0.3.0, so an install from dev is never mistaken for either.
    # dev carries breaking changes already named as 0.3.0 in user-facing errors -- see the
    # other_stim_module_paths TypeError in visual_stim/stim_server.py.
    version='0.3.0.dev0',
    description='Precise and flexible generation of stimuli for neuroscience experiments.',
    url='https://github.com/ClandininLab/stimpack',
    author='Minseung Choi',
    author_email='minseung@stanford.edu',
    packages=find_packages(),
    python_requires='>=3.10',  # code uses PEP 604 (X | Y) unions evaluated at import time
    install_requires=[
        'numpy',
        'scipy',
        'pandas',
        'matplotlib',

        'platformdirs',
        'PyQt6',
        'h5py',
        'pynwb',          # the NWB data backend; required, so the GUI can offer either format
        'PyYAML',
        'deepmerge',      # merging a lab-wide config with a user's own

        'moderngl',
        'PyOpenGL; platform_system=="Linux"',
        'scikit-image',
    ],
    extras_require={
        'test': ['pytest', 'pytest-cov', 'pillow', 'ruff'],  # pillow: GL reference images; ruff: lint
    },
    entry_points={
        'console_scripts': [
            'stimpack=stimpack.experiment.gui:main',
            # Retained so an existing NWB setup keeps working; it warns and defers to
            # `stimpack --data-format nwb`. Prefer setting data_format in the config file.
            'stimpack_nwb=stimpack.experiment.gui:main_nwb',
        ]
    },
    include_package_data=True,
    zip_safe=False,
    project_urls={
        'Documentation': 'https://stimpack.readthedocs.io/en/latest/index.html',
    }
)
