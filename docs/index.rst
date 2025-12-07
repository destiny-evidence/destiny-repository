
.. toctree::
   :maxdepth: 1
   :caption: Contents:

   procedures/procedures
   codebase/codebase
   sdk/sdk
   cli/cli
   API <https://destiny-repository-prod-app.politesea-556f2857.swedencentral.azurecontainerapps.io/redoc>


DESTINY Climate and Health Repository
=====================================

Overview
--------

The DESTINY Repository is a living and comprehensive database of research data focused on climate and health. It is designed to continually store, enrich, and provide access to research data.

This documentation provides information on how to interact with the DESTINY Repository as an importer, robot or user.

Glossary
--------

- :class:`Reference <libs.sdk.src.destiny_sdk.references.Reference>`: The core data unit in the Repository, representing a piece of research.
- :class:`ExternalIdentifier <libs.sdk.src.destiny_sdk.identifiers.ExternalIdentifier>`: Data that identifies a reference. These can be internal DESTINY identifiers or external third-party identifiers.
- :class:`Enhancement <libs.sdk.src.destiny_sdk.enhancements.Enhancement>`: Data that enriches a Reference.
- :doc:`Importers <procedures/batch-importing>`: A process that brings References into the Repository from external sources. These references may contain Identifiers and Enhancements.
- :doc:`Robots <procedures/requesting-batch-enhancements>`: A process that adds Enhancements to References within the Repository. These are specialised, for instance there is a Robot for fetching abstract Enhancements.
- :doc:`Users / UIs <procedures/search>`: Individuals or interfaces that interact with the Repository to retrieve References.


Flowcharts
----------

.. mermaid::

   ---
   title: DESTINY Repository
   ---
   flowchart LR
      I([Importers])
      REPO[(Repository)]
      ROBOT([Robots])
      USER([Users / UIs])

      I-- Provide References -->REPO

      REPO-- Provide References -->ROBOT
      ROBOT-- Provide Enhancements -->REPO

      REPO-- Provide References -->USER

.. mermaid::

   ---
   title: DESTINY Repository Reference Flow
   ---
   sequenceDiagram
      participant I as Importer
      participant REPO as Repository
      participant ROBOT as Robot
      participant U as Users / UIs

      I->>REPO: Ingest Reference
      loop While Enhancements required
         REPO-->>REPO: Detect missing Enhancements
         REPO->>ROBOT: Provide Reference
         ROBOT->>REPO: Provide Enhancement
      end

      REPO->>U: Provide Reference
