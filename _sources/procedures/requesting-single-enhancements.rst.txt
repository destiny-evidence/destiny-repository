Requesting Single Enhancements
==============================

.. note:: This document is a work in progress and may not be complete or accurate.

.. contents:: Table of Contents
    :depth: 2
    :local:

.. mermaid::

    sequenceDiagram
        actor User
        participant Data Repository
        participant Robot
        User->>+Data Repository: POST /enhancement-requests/single-requests/ : (id, parameters)
        Data Repository->>Data Repository : Register Request
        Data Repository->>+Robot: POST <robot_url> : Request Enhancement (id, parameters)
        Data Repository-->>-User: Enhancement request details
        Robot->>Robot : Create Enhancement
        alt Success
            Robot->>Data Repository: POST /enhancement-requests/single-requests/<request_id>/ : Create Enhancement(id, enhancement data)
        else Failure
            Robot->>-Data Repository: POST /enhancement-requests/single-requests/<request_id>/ : (id, failure details)
        end
        Data Repository->>Data Repository : Update Request State
        User->>+Data Repository: GET /enhancement-requests/single-requests/{enhancement_request_id}/
        Data Repository-->>-User: Enhancement request details
