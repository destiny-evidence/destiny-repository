DESTINY Reference Flow
======================

This document non-exhaustively describes the automated flow experienced by a DESTINY reference through the repository.

.. contents:: Table of Contents
    :depth: 2
    :local:


.. mermaid::

    flowchart TD
        R([Reference]) --> R1[Ingest Reference]
        R1 --> P[(Persistence)]
        R1 --> A{Abstract Automation}

        A --> |No abstract, has DOI| ABSTRACT_ROBOT[Abstract Robot]
        A --> |Has abstract| B{Domain Inclusion Automation}
        ABSTRACT_ROBOT --> R2[Ingest Abstract]
        R2 --> P
        R2 --> B

        B --> IN_OUT_ROBOT[Domain Inclusion Robot]
        IN_OUT_ROBOT --> R3[Ingest Domain Inclusion Annotation]
        R3 --> P
        R3 --> C{Taxonomy Automation}

        C -->|Is in domain| TAXONOMY_ROBOT[Taxonomy Robot]
        TAXONOMY_ROBOT --> R4[Ingest Taxonomy Annotations]
        R4 --> P
