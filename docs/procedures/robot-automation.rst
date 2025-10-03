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

        RO->>+DR: POST /enhancement-requests/automations/ : percolator query
        DR->>-ES: Register percolator query

        alt On Import Batch
            DR->>DR: Ingest References
            DR->>ES: Percolate new References
            DR->>DR: Create EnhancementRequests for matching robots
            loop Continuous polling
                R->>DR: POST /robot-enhancement-batches/ : Poll for work
                DR->>R: RobotEnhancementBatch (if pending enhancements available)
            end
        else On Batch Enhancement
            DR->>DR: Ingest Enhancements
            DR->>ES: Percolate new Enhancements
            DR->>DR: Create EnhancementRequests for matching robots
            loop Continuous polling
                R->>DR: POST /robot-enhancement-batches/ : Poll for work
                DR->>R: RobotEnhancementBatch (if pending enhancements available)
            end
        end

.. mermaid::

    flowchart TD
    subgraph Repository
            G_R([Reference]) --> G_R1[Ingest Reference]
            G_R1 --> G_AUTO{Robot Automation Percolation}
            G_AUTO --> G_REQ[Create EnhancementRequests]
            G_R1 --> G_P[(Persistence)]
            G_REQ --> G_P[(Persistence)]
            G_REPO_PROC[Ingest Enhancement] --> G_P
            G_REPO_PROC --> G_AUTO
        end
        subgraph "Robot(s)"
            G_POLL[Robot Polling] --> G_BATCH[Fetch RobotEnhancementBatch]
            G_P --> G_BATCH
            G_BATCH --> G_ROBOT_PROC[Process Batch]
            G_ROBOT_PROC --> G_UPLOAD[Upload Results]
            G_UPLOAD --> G_REPO[Notify Repository]
        end
        G_REPO --> G_REPO_PROC




Context
-------

Robot automations allow :doc:`Enhancement Requests <requesting-batch-enhancements>` to be automatically triggered based on criteria on incoming references or enhancements. This is achieved through a :attr:`percolator query <libs.sdk.src.destiny_sdk.robots.RobotAutomation.query>` registered by the robot owner in the data repository using the `/enhancement-requests/automations/` endpoint.

When references or enhancements match the automation criteria, the data repository creates `EnhancementRequest` objects for the matching robots. Robots can discover and process work through polling. When a robot polls for work, the repository creates a `RobotEnhancementBatch` on-demand containing available pending enhancements for that robot, up to a configurable batch size limit.

Percolation
-----------

The automation criteria is implemented as an `Elasticsearch percolator query <https://www.elastic.co/docs/reference/query-languages/query-dsl/query-dsl-percolate-query>`_. Percolation is the inverse of a traditional Elasticsearch search: the query is stored in the index, and the document is used to search. When writing a percolator query, the key question is: "What shape should new references and/or enhancements have to automatically request enhancements from this robot?".

Query context is implicit when the percolator query is registered - i.e. the top-level element of :attr:`RobotAutomationIn.query <libs.sdk.src.destiny_sdk.robots.RobotAutomationIn.query>` should not be ``query``.

Importantly, the percolator query matches on **changesets**. On a reference import, this is of course the entire reference, but on an enhancement import, it is the enhancement itself. The query may therefore need to handle both cases, as in the :ref:`example below <domain-inclusion-example>`. It is guaranteed that only one of reference or enhancement will be provided for each percolation document.

Safeguards
----------

There is a simple cycle-checker in place to prevent an enhancement request from triggering an automatic enhancement request for the same robot.

Cycles involving multiple robots are however possible, so caution should be taken when considering robot automation criteria.

Examples
--------

The following examples are used in DESTINY to orchestrate robot automations.

Request Missing Abstract
^^^^^^^^^^^^^^^^^^^^^^^^

This percolator query matches only on new references that do not have an abstract, and that do have a DOI (as the abstract robot requires DOIs to function).

.. code-block:: json

    {
        "bool": {
            "must": [
                {
                    "nested": {
                        "path": "reference.identifiers",
                        "query": {
                            "term": {"reference.identifiers.identifier_type": "DOI"}
                        },
                    }
                }
            ],
            "must_not": [
                {
                    "nested": {
                        "path": "reference.enhancements",
                        "query": {
                            "term": {
                                "reference.enhancements.content.enhancement_type": "abstract"
                            }
                        },
                    }
                }
            ],
        }
    }

.. _domain-inclusion-example:

Request Domain Inclusion Annotation
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This percolator query matches on new references that have an abstract, or new enhancements that are abstracts. This is an example of how the orchestration starts to piece together - if the above automation is executed, and an abstract is created, this automation will then be triggered.

.. code-block:: json

    {
        "bool": {
            "should": [
                {
                    "nested": {
                        "path": "reference.enhancements",
                        "query": {
                            "term": {
                                "reference.enhancements.content.enhancement_type": "abstract"
                            }
                        },
                    }
                },
                {
                    "term": {
                        "enhancement.content.enhancement_type": "abstract"
                    }
                }
            ],
            "minimum_should_match": 1,
        }
    }
