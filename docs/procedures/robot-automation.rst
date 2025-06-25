Robot Automations
=================

.. contents:: Table of Contents
    :depth: 2
    :local:

.. mermaid::

    sequenceDiagram
        Actor RO as Robot Owner
        participant R as Robot
        participant DR as Data Repository
        participant ES as Elasticsearch

        RO->>+DR: POST /robot/automation/ : (robot_id, query)
        DR->>-ES: Register percolation query

        alt On Import Batch
            DR->>DR: Ingest References
            DR->>ES: Percolate new References
            loop For each matching robot
                DR->>R: Batch Enhancement Request with matching References
            end
        else On Batch Enhancement
            DR->>DR: Ingest Enhancements
            DR->>ES: Percolate new Enhancements
            loop For each matching robot
                DR->>R: Batch Enhancement Request with matching References
            end
        else On Single Enhancement
            DR->>DR: Ingest Enhancement
            DR->>ES: Percolate new Enhancement
            loop For each matching robot
                DR->>R: Single Enhancement Request with matching Reference
            end
        end

Context
=======

Percolation
===========

Safeguards
==========
