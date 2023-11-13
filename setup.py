from setuptools import setup, find_packages

setup(
    name='stimpack',
    version='0.0.12',
    description='Precise and flexible generation of stimuli for neuroscience experiments.',
    url='https://github.com/ClandininLab/stimpack',
    author='Minseung Choi',
    author_email='minseung@stanford.edu',
    packages=find_packages(),
    install_requires=[
        'numpy',
        'scipy',
        'pandas',
        'matplotlib',
        
        'platformdirs',
        'PyQT6',
        'h5py',
        'pyYaml',
        
        'moderngl',
        'scikit-image',
    ],
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
