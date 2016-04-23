# -*- coding: utf-8 -*-
#
# $Id: setup.py 1254 2009-09-24 08:47:28Z amelung $

import os
from setuptools import setup, find_packages

def read(*rnames):
    return open(os.path.join(os.path.dirname(__file__), *rnames)).read()

version = read('Products', 'ECQuiz', 'version.txt').strip()
readme = read('Products', 'ECQuiz', 'README.txt')
history = read('Products', 'ECQuiz', 'CHANGES.txt')

long_description = readme + '\n\n' + history

setup(name='Products.ECQuiz',
      version=version,
      description = "Create and deliver multiple-choice tests.",
      long_description = long_description,

      # Get more strings from
      # http://www.python.org/pypi?%3Aaction=list_classifiers
      classifiers=[
        "Framework :: Plone",
        "Framework :: Zope2",
        "Programming Language :: Python",
        "Topic :: Software Development :: Libraries :: Python Modules",
        ],
      keywords = '',
      author = 'Wolfram Fenske and Michael Piotrowski and Mario Amelung',
      author_email = 'wfenske@eudemonia-soltions.de and mxp@dynalabs.de and mario.amelung@gmx.de',
      url = 'http://plone.org/products/ecquiz/',
      license='GPL',
      packages=find_packages(exclude=['ez_setup']),
      namespace_packages=['Products'],
      include_package_data=True,
      zip_safe=False,
      install_requires=[
          'setuptools',
          # -*- Extra requirements: -*-
          'Products.DataGridField >= 1.6',
      ],
       extras_require=dict(
            test=[
                'Products.PloneTestCase',
                'zope.testing',
            ]),
      entry_points="""
      # -*- Entry points: -*-
      """,
      )
