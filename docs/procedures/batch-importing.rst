Importing References with Batches
==================================

.. contents:: Table of Contents
    :depth: 2
    :local:

The Import Process
------------------

References are bulk imported using batches per the following process:

.. mermaid::

    sequenceDiagram
        actor M as Import Manager
        participant I as Importer
        participant S as Source
        participant SP as Storage Provider
        participant R as Data Repo
        M ->> I: Start Import (processor id, query)
        I ->> S: Search Query
        S -->> I: Search Results
        I ->>+ R: POST /imports/record/ : Register Import (query, importer metadata, result count)
        R -->> I: ImportRecord (record id)
        loop Each batch
            I ->> SP: Upload Enriched References File
            SP -->> I: Upload Success (file url)
            I ->>+ R: POST /imports/<record id>/batch/ : Register Batch (file url, callback url, import id)
            R -->> I: Batch Enqueued(batch id)
            R ->> SP: Download References File (file url)
            SP -->> R: Enriched References
            R ->> R: Persist Enriched References
            R ->>- I: POST <callback url> : ImportBatchSummary
            I ->> S: Delete Enhancement Batch (file url)
        end
        I ->> R: POST /imports/<record_id>/finalise/ Finalise Import

In words, the interaction with the repository is as follows:

- The importer registers the import with the repository, providing metadata about the import.
- The importer uploads the enriched references file to a storage provider (e.g. Azure blob storage).
- The importer registers a batch with the repository, providing the URL of the enriched references file.
- In the background, the repository downloads the file from the storage provider and processes it.
- Once the processing is done, the repository notifies the importer via a callback URL, providing a summary of the batch processing.
- The importer repeats this for each file that needs processing.
- Once all batches are processed, the importer finalises the import with the repository.

Participants
------------

.. list-table:: Participants
   :header-rows: 1

   * - **Participant**
     - **Description**
   * - Importer
     - Process responsible for preparing the enhanced documents for import
   * - Source
     - Where the importer is getting its data from (e.g. PIK Solr OpenAlex copy, incremental updater)
   * - Storage Provider
     - HTTPS compatible endpoint where the data to import is stored
   * - Data Repo
     - The DESTINY data repository application

Entities
--------

.. mermaid::

    erDiagram

    ImportRecord ||--o{ ImportBatch : "is composed of"

    ImportBatch ||--o{ ImportResult : "produces"

    ImportResult ||--o| Reference : "creates or updates"

    Reference ||--|{ ExternalIdentifier : "has"

    Reference ||--o{ Enhancement : "has"

File Format
-----------

The references file provided to each batch must be in the `jsonl`_ format. Each line is a JSON object in the :class:`ReferenceFileInput <libs.sdk.src.destiny_sdk.references.ReferenceFileInput>` format.

Sample files can be found in the ``.minio/data`` directory.

Callbacks
---------

An optional callback parameter can be provided where the importer can receive a POST request with the batch summary (:class:`ImportBatchSummary <libs.sdk.src.destiny_sdk.imports.ImportBatchSummary>`) once the batch has finished processing.

Collision Handling
------------------

If an imported reference has the same identifier as an existing reference, the collision will be handled according to the :class:`CollisionStrategy <libs.sdk.src.destiny_sdk.enhancements.CollisionStrategy>`.

The default strategy is to do nothing and notify the importer in the batch's :attr:`failure_details <libs.sdk.src.destiny_sdk.imports.ImportBatchSummary.failure_details>`. This allows the importer to "follow up" these records with an alternate strategy if desired.

Identifier collisions are identified on the combination of ``identifier_type`` and ``identifier``, with ``other_identifier_name`` also used if ``identifier_type`` is ``"other"``.

Enhancement updates are performed on the combination of ``enhancement_type`` and ``source``.

.. _jsonl: https://jsonlines.org
