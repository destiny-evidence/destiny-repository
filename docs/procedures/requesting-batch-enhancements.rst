Requesting Enhancements
==================================

.. note:: This document is best understood in conjunction with :ref:`Robots Schemas <sdk_schemas:Robots>`. The schemas here, cross-referenced in this document, have significant supplementary documentation.

.. contents:: Table of Contents
    :depth: 2
    :local:

Enhancement Request Flow
-------------------------

Robots retrieve and process enhancement requests using a polling-based approach where the robot actively polls the repository for pending enhancement batches.


For Requesters
--------------
The requester calls the ``POST /enhancement-requests/`` endpoint with a :class:`EnhancementRequestIn <libs.sdk.src.destiny_sdk.robots.EnhancementRequestIn>` object, providing a robot ID and a list of reference IDs to enhance.

Once confirmed by the repository, the requester will receive a :class:`EnhancementRequestRead <libs.sdk.src.destiny_sdk.robots.EnhancementRequestRead>` object containing the request ID and the status of the request.

The requester can check the status of the request by calling ``GET /enhancement-requests/<request_id>/``, again returning a :class:`EnhancementRequestRead <libs.sdk.src.destiny_sdk.robots.EnhancementRequestRead>`.

Once processing is complete, the overall status will indicate whether the enhancement request succeeded or failed. Individual batch-level validation details are managed internally by the system and are not exposed to the original requester.

User Request Flow
~~~~~~~~~~~~~~~~~

.. mermaid::

    sequenceDiagram
        actor User
        participant Data Repository
        User->>Data Repository: POST /enhancement-requests/ : EnhancementRequestIn
        Data Repository-->>Data Repository: Register enhancement request
        Note over Data Repository: Request status: RECEIVED
        Data Repository-->>User: EnhancementRequestRead (request_id, status)
        Note over User: User can periodically check status
        User->>Data Repository: GET /enhancement-requests/<request_id>/ : Check status
        Data Repository-->>User: EnhancementRequestRead (updated status)
        Note over Data Repository: After all robot processing completes...
        Data Repository-->>Data Repository: Update request state to COMPLETED
        User->>Data Repository: GET /enhancement-requests/<request_id>/ : Final status check
        Data Repository-->>User: EnhancementRequestRead (COMPLETED status)

Enhancement Request Status Flow
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Enhancement requests progress through several statuses during their lifecycle:

- **RECEIVED**: Enhancement request has been received by the repository
- **ACCEPTED**: Enhancement request has been accepted by the robot
- **PROCESSING**: Enhancement request is being processed by the robot
- **IMPORTING**: Enhancements have been received by the repository and are being imported
- **INDEXING**: Enhancements have been imported and are being indexed
- **PARTIAL_FAILED**: Some enhancements failed to create
- **FAILED**: All enhancements failed to create or the robot encountered a global error
- **INDEXING_FAILED**: Enhancements have been imported but indexing failed
- **COMPLETED**: All enhancements have been successfully created and indexed

Requests typically transition from ``RECEIVED`` directly to ``PROCESSING`` when the robot polls for and receives the first batch. The status remains ``PROCESSING`` until all batches are completed, then moves to ``IMPORTING`` and eventually ``COMPLETED``.


For Robots
----------
See :doc:`Robot Registration <robot-registration>` for details on how robots are registered. Robots poll for batches of references assigned to them for enhancement (robot enhancement batches). Each batch is provided in the :attr:`reference_storage_url <libs.sdk.src.destiny_sdk.robots.RobotEnhancementBatch.reference_storage_url>` file.

Robot Implementation
~~~~~~~~~~~~~~~~~~~~

Robots actively poll the repository for robot enhancement batches using the SDK client.

Robot Processing Flow
^^^^^^^^^^^^^^^^^^^^^

.. mermaid::

    sequenceDiagram
        participant Data Repository
        participant Blob Storage
        participant Robot
        Note over Data Repository: Enhancement request is RECEIVED
        Robot->>Data Repository: POST /robot-enhancement-batches/ : Poll for batches
        Data Repository->>+Blob Storage: Store requested references and dependent data
        Data Repository->>Robot: RobotEnhancementBatch (batch of references)
        Note over Data Repository: Request status: PROCESSING
        Blob Storage->>Robot: GET reference_storage_url (download references)
        Robot-->>Robot: Process references and create enhancements
        alt More batches available
            Robot->>Data Repository: POST /robot-enhancement-batches/ : Poll for next batch
            Data Repository->>Robot: RobotEnhancementBatch (next batch)
            Note over Robot: Process additional batches...
        else No more batches
            Robot->>Data Repository: POST /robot-enhancement-batches/ : Poll for batches
            Data Repository->>Robot: HTTP 204 No Content
        end
        alt Batch success
            Robot->>+Blob Storage: PUT result_storage_url (upload enhancements)
            Robot->>Data Repository: POST /robot-enhancement-batches/<batch_id>/results/ : RobotEnhancementBatchResult
        else Batch failure
            Robot->>Data Repository: POST /robot-enhancement-batches/<batch_id>/results/ : RobotEnhancementBatchResult(error)
        end
        Note over Robot: Repeat...
        Blob Storage->>-Data Repository: Validate and import all enhancements
        Note over Data Repository: Update request state to IMPORTING → INDEXING → COMPLETED

Implementation Steps
^^^^^^^^^^^^^^^^^^^^

To implement a polling-based robot:

1. **Poll for batches**: Use :meth:`Client.poll_robot_enhancement_batch() <libs.sdk.src.destiny_sdk.client.Client.poll_robot_enhancement_batch>` to retrieve pending batches. The method returns a :class:`RobotEnhancementBatch <libs.sdk.src.destiny_sdk.robots.RobotEnhancementBatch>` object or ``None`` if no batches are available.

2. **Process references**: Download the references from the :attr:`reference_storage_url <libs.sdk.src.destiny_sdk.robots.RobotEnhancementBatch.reference_storage_url>`. Each line in the file is a JSON-serialized :class:`Reference <libs.sdk.src.destiny_sdk.references.Reference>` object, which can be parsed using :meth:`Reference.from_jsonl() <libs.sdk.src.destiny_sdk.references.Reference.from_jsonl>`.

3. **Create enhancements**: Process each reference and create :class:`Enhancement <libs.sdk.src.destiny_sdk.enhancements.Enhancement>` objects or :class:`LinkedRobotError <libs.sdk.src.destiny_sdk.robots.LinkedRobotError>` objects for failed references.

4. **Upload results**: Upload the results as a JSONL file to the :attr:`result_storage_url <libs.sdk.src.destiny_sdk.robots.RobotEnhancementBatch.result_storage_url>`. Each line should be either an enhancement or an error entry.

5. **Submit batch result**: Use :meth:`Client.send_robot_enhancement_batch_result() <libs.sdk.src.destiny_sdk.client.Client.send_robot_enhancement_batch_result>` to notify the repository that the batch is complete. Submit a :class:`RobotEnhancementBatchResult <libs.sdk.src.destiny_sdk.robots.RobotEnhancementBatchResult>` object.

6. **Continue polling**.

**Error Handling**

- **Batch-level errors**: If the entire batch fails (e.g., due to connectivity issues), set the ``error`` field in the :class:`RobotEnhancementBatchResult <libs.sdk.src.destiny_sdk.robots.RobotEnhancementBatchResult>`.
- **Reference-level errors**: For individual reference failures, include :class:`LinkedRobotError <libs.sdk.src.destiny_sdk.robots.LinkedRobotError>` entries in the result file and leave the batch result ``error`` field as ``None``.

**Status Monitoring and URL Refresh**

Robots can call ``GET /robot-enhancement-batches/<batch_id>/`` to refresh signed URLs for a specific batch if they expire. Note that the reference data however is not refreshed, it is point-in-time from the time of the initial enhancement request.

Requesters should use ``GET /enhancement-requests/<request_id>/`` to monitor the overall request status.
