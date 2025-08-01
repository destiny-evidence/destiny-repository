SDK
===

The DESTINY Repository SDK is a Python package that provides an interface for interacting with the DESTINY data repository.

At present, the SDK primarily provides a set of ``Pydantic`` schemas that are used to define the API interface. It also provides classes to support authentication to and from destiny repository, which are intended to be used with Robots.

The SDK is published via PyPI at https://pypi.org/project/destiny_sdk/ and can be installed with the following

.. code-block:: bash

   poetry add destiny-sdk

Or whichever python package installation method you prefer.

.. toctree::
   :maxdepth: 1
   :caption: Contents:

   schemas
   auth
