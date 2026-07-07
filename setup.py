from setuptools import setup, find_packages

setup(
    name='stimpack',
    version='0.1.1',
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
        'PyYAML',

        'moderngl',
        'PyOpenGL; platform_system=="Linux"',
        'scikit-image',
    ],
    extras_require={
        'test': ['pytest', 'pytest-cov', 'pillow', 'ruff'],  # pillow: GL reference images; ruff: lint
    },
    entry_points={
        'console_scripts': [
            'stimpack=stimpack.experiment.gui:main'
        ]
    },
    include_package_data=True,
    zip_safe=False,
    project_urls={
        'Documentation': 'https://stimpack.readthedocs.io/en/latest/index.html',
    }
)
