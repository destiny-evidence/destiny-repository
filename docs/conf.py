# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information


import os
import sys

# Add the project root to sys.path so Sphinx can find your modules
sys.path.insert(0, os.path.abspath('..'))

project = 'DESTINY Repository'
copyright = '2025, DESTINY Team'
author = 'DESTINY Team'
release = 'v0.1'

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = ['sphinxcontrib.autodoc_pydantic', 'sphinx.ext.autodoc', 'sphinxcontrib.mermaid', 'sphinx.ext.graphviz', 'sphinx.ext.linkcode']

templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']

autodoc_pydantic_model_show_json = True
autodoc_pydantic_settings_show_json = False
autodoc_pydantic_model_erdantic_figure = True

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'pydata_sphinx_theme'
html_static_path = ['_static']
html_show_sourcelink = False
html_theme_options = {
  "show_toc_level": 2 # can increase, e.g., if there are nested classes
}


def linkcode_resolve(domain, info):
    if domain != 'py':
        return None
    if not info['module']:
        return None
    filename = info['module'].replace('.', '/')
    return "https://github.com/destiny-evidence/destiny-repository/blob/main/%s.py" % filename
