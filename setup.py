from setuptools import setup

setup(
    name='stimpack',
    version='0.0.1',
    description='Suite for experiments involving various types of stimuli, such as visual and optogenetic.',
    url='https://github.com/ClandininLab/stimpack',
    author='Max Turner, Minseung Choi',
    author_email='mhturner@stanford.edu, minseung@stanford.edu',
    packages=[
        'stimpack',
        'stimpack.rpc',
        'stimpack.experiment',
        'stimpack.visual_stim',
        'stimpack.device'
    ],
    package_dir = {"": "src"},
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
)
