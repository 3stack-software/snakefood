#!/usr/bin/env python
"""
Install script for the snakefood dependency graph tool.
"""

__author__ = "Martin Blais <blais@furius.ca>"

import os
import sys
from os.path import join, isfile

from setuptools import setup

# Install all scripts under bin.
scripts = list(filter(isfile, [join('bin', x) for x in os.listdir('bin')]))

def read_version():
    try:
        return open('VERSION', 'r').readline().strip()
    except IOError:
        _, e, _ = sys.exc_info()
        raise SystemExit(
            "Error: you must run setup from the root directory (%s)" % str(e))

setup(name="snakefood",
      version=read_version(),
      description=\
      "Dependency Graphing for Python",
      long_description="""
Generate dependencies from Python code, filter, cluster and generate graphs
from the dependency list.
""",
      license="GPL",
      author="Martin Blais",
      author_email="blais@furius.ca",
      url="http://furius.ca/snakefood",
      download_url="http://bitbucket.org/blais/snakefood",
      package_dir = {'': 'lib/python'},
      packages = ['snakefood', 'snakefood/fallback'],
      install_requires=[ 'six' ],
      setup_requires=['pytest-runner' ],
      tests_require=[ 'pytest' ],
      scripts=scripts
     )
