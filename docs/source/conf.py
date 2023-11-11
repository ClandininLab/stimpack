# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

import sys
import os
import sphinx_rtd_theme
import os
import sys
import stimpack

# sys.path.insert(0, os.path.abspath('/dennis/stimpack/src/stimpack/'))
# sys.path.insert(0, os.path.abspath('/home/dennis/stimpack/src/stimpack/visual_stim'))

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.autosummary',
    'sphinx.ext.viewcode'
]


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
