Requesting Enhancements
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
        User->>Data Repository: POST /enhancement-requests/ : EnhancementRequestIn
        Data Repository-->>Data Repository: Register enhancement request
        Data Repository->>+Blob Storage: Store requested references and dependent data
        Data Repository->>Robot: POST <robot_url>/ : RobotRequest
        Blob Storage->>-Robot: Get requested references and dependent data
        Robot-->>Robot: Create Enhancements
        alt Failure
            Robot->>Data Repository: POST /enhancement-requests/<request_id>/result/ : RobotResult(error)
        else Success
            Robot->>+Blob Storage: Upload created enhancements
            Robot->>Data Repository: POST /enhancement-requests/<request_id>/result/ : RobotResult(storage_url)
        end
        Blob Storage->>-Data Repository: Validate and import enhancements
        Data Repository->>+Blob Storage: Upload validation result file
        Data Repository-->>Data Repository: Update request state
        User->>Data Repository: GET /enhancement-requests/<request_id>/ : EnhancementRequestRead
        Blob Storage->>-User: Validation result file


For Requesters
--------------
The requester calls the ``POST /enhancement-requests/`` endpoint with a :class:`EnhancementRequestIn <libs.sdk.src.destiny_sdk.robots.EnhancementRequestIn>` object, providing a robot and list of reference IDs to enhance.

Once confirmed by the repository, the requester will receive a :class:`EnhancementRequestRead <libs.sdk.src.destiny_sdk.robots.EnhancementRequestRead>` object containing the request ID and the status of the request.

The requester can refresh the status of therequest by calling ``GET /enhancement-requests/<request_id>/``, again returning a :class:`EnhancementRequestRead <libs.sdk.src.destiny_sdk.robots.EnhancementRequestRead>`.

Once processing is complete, the requester can download the :attr:`validation_result_file <libs.sdk.src.destiny_sdk.robots.EnhancementRequestRead.validation_result_file>` from the blob storage URL provided in the request read object. This file will contain the results of the enhancement, including any errors encountered during processing, in a simple ``.txt`` format. Validations include:

- checking enhancement format
- checking that the enhancement is for a reference in the original request
- checking for any references in the original request that were not returned with an error or enhancement by the robot


For Robots
----------
Robots during registration should indicate their required enhancements and identifiers to derive requested enhancements. This process is yet to be fully defined but will live here: :doc:`Robot Registration <robot-registration>`. These are provided to the robot in the :attr:`reference_storage_url <libs.sdk.src.destiny_sdk.robots.RobotRequest.reference_storage_url>` file with the requested references.

Robots must implement the ``POST /batch/`` endpoint to handle enhancement requests. The endpoint should accept a :class:`RobotRequest <libs.sdk.src.destiny_sdk.robots.RobotRequest>` object.

There are no restrictions on how the robot processes the request, but it must return a :class:`RobotResult <libs.sdk.src.destiny_sdk.robots.RobotResult>` object.

The RobotResult must only populate ``error`` if there was a global issue that caused the enhancement request to fail. Errors to individual references should be provided as :class:`LinkedRobotError<libs.sdk.src.destiny_sdk.robots.RobotResult>` entries in the result file. Vice-versa, if error is not provided then the repository will assume the enhancement request was successful and will proceed to parse the result file.

The robot can call ``GET /enhancement-requests/<request_id>/``. It may want to for various reasons: to refresh signed URLs, to verify the final results of the enhancement request, or to understand which requests have already been fulfilled. Note that the reference data however is not refreshed, it is point-in-time from the time of the initial enhancement request.
