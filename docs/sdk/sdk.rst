SDK
===

The DESTINY Repository SDK is a Python package that provides an interface for interacting with the DESTINY data repository.

At present, the SDK primarily provides a set of ``Pydantic`` models that are used to define the API interface. It will be expanded to provide additional functionality in the future.

It is not yet on PyPI, but you can install it from the GitHub repository:

.. code-block:: bash

   poetry add git+ssh://git@github.com:destiny-evidence/destiny-repository.git#subdirectory=libs/sdk


.. toctree::
   :maxdepth: 1
   :caption: Contents:

   models
   auth
