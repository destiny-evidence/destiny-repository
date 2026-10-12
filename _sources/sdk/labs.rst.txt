SDK Labs
========

The ``labs`` module of the DESTINY Repository SDK provides experimental features and interfaces for interacting with the DESTINY data repository.

Anything in this module should be considered experimental and may change or be deprecated in the future.

There may be additional dependencies required to use some features of this module. These can be installed by specifying the ``labs`` extra when installing the SDK:

.. code-block:: bash

    pip install destiny-sdk[labs]

    uv add destiny-sdk --extra labs


.. contents::
    :depth: 2
    :local:

References
----------
.. autoclass:: libs.sdk.src.destiny_sdk.labs.references.LabsReference
    :members:
    :inherited-members: BaseModel, str, Reference
