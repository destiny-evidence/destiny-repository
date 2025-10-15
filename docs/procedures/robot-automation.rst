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
            loop For each Reference in batch
                DR->>DR: Ingest Reference
                DR->>DR: Deduplicate Reference
                DR->>ES: Percolate new Reference
                loop For each matching robot
                    DR->>R: Enhancement Request with matching References
                end
                loop Continuous polling
                    R->>DR: POST /robot-enhancement-batches/ : Poll for work
                    DR->>R: RobotEnhancementBatch (if pending enhancements available)
                end
            end
        else On Batch Enhancement
            DR->>DR: Ingest Enhancements
            DR->>ES: Percolate new Enhancements
            loop For each matching robot
                DR->>R: Enhancement Request with matching References
            end
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

There are two scenarios that can trigger percolation:

- On deduplication, if the active decision has changed
- On added enhancement

Structure
---------

Each percolated document contains two fields: ``reference`` and ``changeset``. Both of these fields map to :class:`Reference <app.domain.references.models.models.Reference>` objects. ``reference`` is the complete reference, deduplicated, and ``changeset`` is the change that was just applied. The repository is append-only, and so is the ``changeset`` - it only represents newly available information to the reference.

Automations trigger on ``reference`` - note the implications of this below.

Some examples:

- After deduplicating a reference, if the reference is canonical, ``reference`` and ``changeset`` will be identical: the imported reference. Automations trigger on that reference.
- After deduplicating a reference, if the reference is a duplicate, ``reference`` will be the deduplicated view of its canonical reference, and ``changeset`` will be the duplicate reference. Automations trigger on the canonical reference.
- After adding an enhancement, ``reference`` will be the reference with the new enhancement applied, and ``changeset`` will be an empty reference just including the new enhancement. Automations trigger on the reference that was enhanced, canonical or not. ``reference`` is still deduplicated - if it is canonical, its duplicate's contents will be included.

For the exact structure of these inner documents, see :class:`ReferenceDomainMixin <app.domain.references.models.es.ReferenceDomainMixin>`.

Query
-----

Automation queries **must** specify a filter against ``changeset``, otherwise they risk matching against all documents.

Most use-cases will only need to lookup against ``changeset``, to trigger upon some new dependent information. ``reference`` is provided for more complex use-cases, such as triggering on a combination of existing and new information.

The active :class:`DuplicateDetermination <app.domain.references.models.models.DuplicateDetermination>` is included in both ``reference`` and ``changeset``, however note this will not capture the previous duplicate decision if it has just changed. This can be used to filter automations based on if a reference has been determined to be definitely canonical, for instance.


Safeguards
----------

There is a simple cycle-checker in place to prevent an enhancement request from triggering an automatic enhancement request for the same robot.

Cycles involving multiple robots are however possible, so caution should be taken when considering robot automation criteria.

Examples
--------

The following examples are used in DESTINY to orchestrate robot automations.

Request Missing Abstract
^^^^^^^^^^^^^^^^^^^^^^^^

This percolator query matches on references that don't have an abstract and have received a DOI.

.. code-block:: json

    {
        "bool": {
            "must": [
                {
                    "nested": {
                        "path": "changeset.identifiers",
                        "query": {
                            "term": {"changeset.identifiers.identifier_type": "DOI"}
                        }
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
                        }
                    }
                }
            ]
        }
    }

.. _domain-inclusion-example:

Request Domain Inclusion Annotation
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This percolator query matches on new references that have received an abstract. This is an example of how the orchestration starts to piece together - if the above automation is executed, and an abstract is created, this automation will then be triggered.

.. code-block:: json

    {
        "bool": {
            "must": [
                {
                    "nested": {
                        "path": "changeset.enhancements",
                        "query": {
                            "term": {
                                "changeset.enhancements.content.enhancement_type": "abstract"
                            }
                        },
                    }
                },
            ],
        }
    }
