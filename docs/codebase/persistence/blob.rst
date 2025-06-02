Blob Storage
============

Blob storage is used for storing large and/or ephemeral data that is not suitable for other persistence stores. This includes:
- Large permanent data files such as full texts of documents.
- Temporary files that are generated during processing but not needed long-term.
- Large payloads that are not suitable for REST APIs, such as batch processes.

.. contents:: Table of Contents
    :depth: 2
    :local:

Interface
---------

External actors such as robots interact with blob storage purely through ``GET/PUT`` signed URLs, they are not granted direct access to the storage itself. These have short-lived signatures, typically valid for one hour, but can be refreshed by re-requesting the resource from the Repository API.

The repository codebase interacts with blob storage through the :class:`BlobStorageRepository <app.persistence.blob.repository.BlobStorageRepository>` interface, which provides methods for uploading and downloading files, as well as managing file metadata. This interface is primarily a streaming interface, allowing for efficient handling of large files for upload and download without loading them entirely into memory. When getting, files are streamed line-by-line to the caller, and when putting, files can either be streamed with the :class:`FileStream <app.persistence.blob.stream.FileStream>` class or compiled into an in-memory ``BytesIO`` object for simpler cases.


Representation
^^^^^^^^^^^^^^

Blob files are represented in the repository as a :class:`BlobStorageFile <app.persistence.blob.models.BlobStorageFile>` object.

.. automodule:: app.persistence.blob.models
    :members:
    :undoc-members:
    :inherited-members: BaseModel, str

Client
^^^^^^

Each blob storage client implements the :class:`GenericBlobStorageClient <app.persistence.blob.client.GenericBlobStorageClient>` interface, which defines methods for interacting with blob storage.

.. autoclass:: app.persistence.blob.client.GenericBlobStorageClient
    :members:

Blob Repository
^^^^^^^^^^^^^^^

The codebase interacts with the blob clients through the :class:`BlobStorageRepository <app.persistence.blob.repository.BlobStorageRepository>` interface:

.. autoclass:: app.persistence.blob.repository.BlobRepository
    :members:


File Content
^^^^^^^^^^^^

When getting, the file content is streamed line-by-line to the caller, allowing for efficient handling of large files without loading them entirely into memory.

When putting, files can either be streamed with the :class:`FileStream <app.persistence.blob.stream.FileStream>` class or compiled into an in-memory ``BytesIO`` object for simpler cases.

.. autoclass:: app.domain.base.SDKJsonlMixin
    :members:

.. autoclass:: app.persistence.blob.stream.FileStream
    :members:


Implementations
---------------

Azure
^^^^^

Azure Blob Storage is used for application deployments. At present there is one container, ``destiny-repository-<env>-ops``, which is used only for ephemeral operational data. The file tree is as below:

.. code-block::

    destiny-repository-<env>-ops/
        ├── batch_enhancement_result/
        │   └── <batch_request_id>.jsonl - the enhancement result as published by the robot to the repository
        │   └── <batch_request_id>.txt   - the validation result of importing the above as published by the repository
        ├── batch_enhancement_request_reference_data/
        │   └── <batch_request_id>.jsonl - the reference data provided to the robot for the batch enhancement request


MinIO
^^^^^

MinIO is used for testing and local development. It is S3-compatible, if an AWS implementation is ever desired. However the current implementation is synchronous and so does not utilise the memory efficiency of the FileStream interface.
