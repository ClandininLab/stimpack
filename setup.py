import os

from setuptools import setup, find_packages

# The README is the PyPI page; its images use absolute raw.githubusercontent URLs so they render
# there as well as on GitHub.
with open(os.path.join(os.path.dirname(__file__), 'README.md'), encoding='utf-8') as _readme:
    long_description = _readme.read()

setup(
    name='stimpack',
    # Pre-release marker for the branch, not a released version: PEP 440 orders this after 0.2.0
    # (the current release) and before 1.0.0, so an install from dev is never mistaken for either.
    # dev carries breaking changes already named as 1.0.0 in user-facing errors -- see the
    # other_stim_module_paths TypeError in visual_stim/stim_server.py.
    version='1.0.0.dev0',
    description='A modular framework for precise multisensory stimulus generation in systems neuroscience.',
    long_description=long_description,
    long_description_content_type='text/markdown',
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
        # No platform marker: the marker dated from when only the Linux EGL path
        # imported PyOpenGL; the cube-map pass (visual_stim/cubemap.py) now needs raw
        # GL on every platform, and a Mac/Windows install without it loses curved
        # screens to an ImportError. Pure-Python, so unconditional costs nothing.
        'PyOpenGL',
        'scikit-image',
    ],
    extras_require={
        'test': ['pytest', 'pytest-cov', 'pillow', 'ruff'],  # pillow: GL reference images; ruff: lint
        # PyAudio needs PortAudio system-side (brew install portaudio / apt install portaudio19-dev),
        # which is reason enough to keep it optional. Only PyAudioManager imports it, and only when
        # it opens a device -- NullAudioManager, the sounds and the tests all run without it.
        'audio': ['pyaudio'],
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
