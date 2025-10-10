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
        I ->>+ R: POST /imports/records/ : Register Import (query, importer metadata, result count)
        R -->> I: ImportRecord (record id)
        loop Each batch
            I ->> SP: Upload Enriched References File
            SP -->> I: Upload Success (file url)
            I ->>+ R: POST /imports/records/<record id>/batches/ : Register Batch (file url, import id)
            R -->> I: Batch Enqueued(batch id)
            R ->> SP: Download References File (file url)
            loop Each record in file, concurrently
                R ->> R: Process Record
                alt Record Success
                    R ->> R: Check if Exact Duplicate
                    alt Not an Exact Duplicate
                        R ->> R: Import Reference and Enhancements
                        R ->> R: Register ImportResult (success)
                        R -->> R: Register & Enqueue Deduplication
                    end
                else Record Failure
                    R ->> R: Register ImportResult (failure, failure details)
                end
            end
            I ->>R: GET /imports/records/<record id>/batches/<batch id>/ : Poll for import batch status
            I ->> S: Delete Enhancement Batch (file url)
        end
        I ->> R: POST /imports/records/<record_id>/finalise/ Finalise Import

In words, the interaction with the repository is as follows:

- The importer registers the import with the repository, providing metadata about the import.
- The importer uploads the enriched references file to a storage provider (e.g. Azure blob storage).
- The importer registers a batch with the repository, providing the URL of the enriched references file.
- In the background, the repository downloads the file from the storage provider and processes it. Each record is processed individually and asynchronously. Processing consists of:

  - Validating the reference.
  - Checking for :ref:`Exact Duplicates <exact-duplicates>`.
  - Importing the reference and its enhancements.
  - Queueing the reference for :doc:`Reference Deduplication <deduplication>`.

- The importer polls the repository for the status of the batch. A `ImportBatchSummary <libs.sdk.src.destiny_sdk.imports.ImportBatchSummary>`_ can be requested from `/imports/records/<record_id>/batches/<batch_id>/summary/` which shows the statuses of the underlying imports.
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

Sample
------

A complete working sample demonstrating the import process is also available:

  `import_from_bucket.py <https://github.com/destiny-evidence/destiny-repository/blob/main/libs/samples/import_from_bucket.py>`_

.. _jsonl: https://jsonlines.org
