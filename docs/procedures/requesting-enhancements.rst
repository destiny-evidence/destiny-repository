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
        participant Processor
        participant LLM/Model
        SR Tool->>+Data Repository: Process Document(id, parameters)
        Data Repository->>+Processor: Process Document(document, parameters, task id)
        Processor-->>Data Repository: Enqueued
        Data Repository-->>-SR Tool: Task Details
        Processor->>+LLM/Model: Submit Prompt/Model Request
        LLM/Model-->>-Processor: Prompt/Model Response
        alt Success
            Processor->>Data Repository: Create Enhancement(task id, enhancement data)
        else Failure
            Processor->>-Data Repository: Task Failure(task id, failure details)
        end
        SR Tool->>+Data Repository: Request Document with Enhancements(id)
        Data Repository-->>-SR Tool: Document with enhancements
