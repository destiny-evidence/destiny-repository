Requesting Enhancements
=======================

.. note:: This document is a work in progress and may not be complete or accurate.

.. contents:: Table of Contents
    :depth: 2
    :local:

.. mermaid::

    sequenceDiagram
        participant SR Tool
        participant Data Repository
        participant Robot
        participant LLM/Model
        SR Tool->>+Data Repository: POST /references/enhancement/ : (id, parameters)
        Data Repository->>+Robot: POST <robot_url> : Process Document (id, parameters)
        Data Repository-->>-SR Tool: POST <callback_url> : Task Details
        Robot->>+LLM/Model: Submit Prompt/Model Request
        LLM/Model-->>-Robot: Prompt/Model Response
        alt Success
            Robot->>Data Repository: POST /robot/enhancement/ : Create Enhancement(id, enhancement data)
        else Failure
            Robot->>-Data Repository: POST /robot/enhancement/ : (id, failure details)
        end
        Data Repository-->>-SR Tool: POST <callback_url> : Task Details
