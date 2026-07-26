# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

import os
import sys

import sphinx_rtd_theme  # noqa: F401 - registers the theme

# The repository root, so autodoc finds `stimpack` whether or not it is installed. The paths that
# used to be here pointed at directories that never existed in this layout, which is why every
# automodule below silently failed to import and the entire API section came out empty.
sys.path.insert(0, os.path.abspath('../..'))

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.autosummary',
    'sphinx.ext.napoleon',      # :param: blocks, which is how this codebase writes docstrings
    'sphinx.ext.viewcode',
]

# PyQt6, moderngl and the hardware drivers are not installed on the docs builder, and importing them
# is not needed to document the modules that use them.
autodoc_mock_imports = [
    'PyQt6', 'moderngl', 'OpenGL', 'hid', 'nidaqmx', 'labjack', 'h5py', 'skimage', 'platformdirs',
]
autodoc_default_options = {'members': True, 'undoc-members': True, 'show-inheritance': True}


autosummary_generate = True  # Automatically generate summary pages
project = 'stimpack'
copyright = '2023, Clandinin Lab'
author = 'Clandinin Lab'
release = '1.0'

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration


templates_path = ['_templates']
exclude_patterns = []



# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'sphinx_rtd_theme'
html_static_path = ['_static']

# -- Options for HTMLHelp output ---------------------------------------------
