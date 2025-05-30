Requesting Enhancements in a Batch
==================================

.. note:: This document is best understood in conjunction with :ref:`Robots Schemas <sdk_schemas:Robots>`. The schemas here, cross-referenced in this document, have significant supplementary documentation.

.. contents:: Table of Contents
    :depth: 2
    :local:

.. mermaid::

    sequenceDiagram
        actor User
        participant Data Repository
        participant Blob Storage
        participant Robot
        User->>Data Repository: POST /references/enhancement/batch/ : BatchEnhancementRequestIn
        Data Repository-->>Data Repository: Register batch request
        Data Repository->>+Blob Storage: Store requested references and dependent data
        Data Repository->>Robot: POST <robot_url>/batch/ : BatchRobotRequest
        Blob Storage->>-Robot: Get requested references and dependent data
        Robot-->>Robot: Create Enhancements
        alt Failure
            Robot->>Data Repository: POST /robot/enhancement/batch/ : BatchRobotResult(error)
        else Success
            Robot->>+Blob Storage: Upload created enhancements
            Robot->>Data Repository: POST /robot/enhancement/batch/ : BatchRobotResult(storage_url)
        end
        Blob Storage->>-Data Repository: Validate and import enhancements
        Data Repository->>+Blob Storage: Upload validation result file
        Data Repository-->>Data Repository: Update batch request state
        User->>Data Repository: GET references/enhancement/batch/<batch_request_id> : BatchEnhancementRequestRead
        Blob Storage->>-User: Validation result file


For Requestors
--------------
The requestor calls the ``POST /references/enhancement/batch/`` endpoint with a :class:`BatchEnhancementRequestIn <libs.sdk.src.destiny_sdk.robots.BatchEnhancementRequestIn>` object, providing a robot and list of reference IDs to enhance.

Once confirmed by the repository, the requestor will receive a :class:`BatchEnhancementRequestRead <libs.sdk.src.destiny_sdk.robots.BatchEnhancementRequestRead>` object containing the batch request ID and the status of the request.

The requestor can refresh the status of the batch request by calling ``GET references/enhancement/batch/<batch_request_id>``, again returning a :class:`BatchEnhancementRequestRead <libs.sdk.src.destiny_sdk.robots.BatchEnhancementRequestRead>`.

Once processing is complete, the requestor can download the :attr:`validation_result_file <libs.sdk.src.destiny_sdk.robots.BatchEnhancementRequestRead.validation_result_file>` from the blob storage URL provided in the batch request read object. This file will contain the results of the batch enhancement, including any errors encountered during processing, in a simple ``.txt`` format. Validations include:

- checking enhancement format
- checking that the enhancement is for a reference in the original request
- checking for any references in the original request that were not returned with an error or enhancement by the robot

For Robots
----------
Robots during registration should indicate their required enhancements and identifiers to derive requested enhancements. This process is yet to be fully defined but will live here: :doc:`Robot Registration <robot-registration>`. These are passed in the :attr:`reference_storage_url <libs.sdk.src.destiny_sdk.robots.BatchRobotRequest.reference_storage_url>` file.

Robots must implement the ``POST /batch/`` endpoint to handle batch enhancement requests. The endpoint should accept a :class:`BatchRobotRequest <libs.sdk.src.destiny_sdk.robots.BatchRobotRequest>` object.

There are no restrictions on how the robot processes the batch request, but it must return a :class:`BatchRobotResult <libs.sdk.src.destiny_sdk.robots.BatchRobotResult>` object.

The BatchRobotResult must only populate ``error`` if there was a systematic issue that caused the entire batch, request or response to fail. Errors to individual references should be provided as :class:`LinkedRobotError<libs.sdk.src.destiny_sdk.robots.BatchRobotResult>` entries in the result file. Vice-versa, if error is not provided then the repository will assume the batch was successful and will proceed to parse the result file.

The robot can call ``GET references/enhancement/batch/<batch_request_id>``. It may want to for various reasons: to refresh signed URLs, to verify the final results of the batch enhancement request, or to understand which requests have already been fulfilled. Note that the reference data however is not refreshed, it is point-in-time from the time of the initial batch enhancement request.
