Reference Deduplication
=======================

.. contents:: Table of Contents
    :depth: 2
    :local:


Terminology & Concepts
----------------------

Duplicate references are grouped together. Each group has one canonical reference and zero or more duplicates.

When we search, we look for a canonical reference to which to attach the incoming reference as a duplicate. If we cannot find a canonical reference, the incoming reference becomes a canonical reference with no duplicates. We search for canonical references when we :doc:`Import a Reference <batch-importing>` (with work pending to also search when we ingest a relevant enhancement).

- A **canonical** reference is the primary reference of a group of duplicates. The choice of canonical reference is arbitrary, at least for now. The `Deduplicated Projection`_ is the same regardless of canonical choice. A canonical reference has an active duplicate decision of :attr:`Canonical <app.domain.references.models.models.DuplicateDetermination.CANONICAL>`.
- A **duplicate** reference is a reference which has been determined to be a duplicate of a canonical reference. A duplicate reference has an active duplicate decision of :attr:`Duplicate <app.domain.references.models.models.DuplicateDetermination.DUPLICATE>`.
- A **duplicate decision** is the outcome of the deduplication process for a given reference. A reference has at most one *active* duplicate decision, but may have multiple historical decisions. For instance, a canonical reference has an active decision of canonical. See :class:`ReferenceDuplicateDecision <app.domain.references.models.models.ReferenceDuplicateDecision>` for more.
- A **candidate** duplicate is a reference which has been identified as a potential canonical of an incoming reference, but has not yet been compared in detail.
- An **exact** duplicate is a reference which has an identical supersetting reference already present in the repository. These are not imported, but a duplicate decision is still registered for them with :attr:`Exact Duplicate <app.domain.references.models.models.DuplicateDetermination.EXACT_DUPLICATE>`.

It may also help to think of a group of duplicating references as a star graph. The canonical reference is the center of the star, and all duplicates point to it. Duplicates do not point to other duplicates (more on that in `Action Decision`_).

.. mermaid::

    flowchart BT
        D1(Duplicate)
        D2(Duplicate)
        D3(Duplicate)
        D4(Duplicate)
        D5(Duplicate)
        D6(Duplicate)
        D7(Duplicate)
        C[Canonical]

        D1 --> C
        D2 --> C
        D3 --> C
        D4 --> C
        D5 --> C
        D6 --> C
        D7 --> C


Note also that deduplication doesn't necessarily occur at import time, it may also be triggered manually or by a new enhancement.

High Level Process
------------------

.. mermaid::

    flowchart LR

        R[[Repository Process]]
        P[(Register Pending Decision)]
        T[Initiate Duplicate Decision]
        IS[[Identifier Shortcut]]
        CS[[Candidate Selection]]
        DD[[Deep Deduplication]]
        A[[Action Decision]]
        DP>Deduplicated Projection]

        T-->IS
        IS-->|Shortcut|A
        IS-->|No shortcut|CS
        CS-->|No candidates found|A
        CS-->|Candidates found|DD
        DD-->A
        R-->P
        P-.->|Queue|T
        A~~~DP


There are five key steps:

- `Identifier Shortcut`_ - a fast-path check to see if the incoming reference has any unique identifiers that match an existing reference.
- `Candidate Selection`_ - a high-recall, low-precision search to find potential canonical references.
- `Deep Deduplication`_ - a high-precision comparison of the incoming reference against each candidate to determine if it duplicates the candidate.
- `Action Decision`_ - deciding what to do with the reference based on the deduplication results.
- `Deduplicated Projection`_ - the output of the process, the final representation of the deduplicated reference.

Identifier Shortcut
-------------------

.. mermaid::

    flowchart LR

        D["Duplicate Decision"]
        I["Get Unique Identifiers"]
        E[("Search for Identifiers")]
        CS["Go to Candidate Selection"]
        C1{"Matches Found?"}
        A["Go to Action Decision"]
        M["Manual Review"]
        C2{"Multiple Matches?"}
        C3{"Different Canonicals?"}
        F["For each unmapped match"]

        D-->I-->E-->C1
        C1-->|No|CS
        C1-->|Yes|C2
        C2-->|Yes|C3
        C2-->|No|A
        C3-->|Yes|M
        C3-->|No|F
        F-->A
        F-->A
        F-->A
        F-->A
        F-->A

The identifier shortcut is a high precision, low-recall step that attempts to quickly determine the duplicate decision for an incoming reference based on its unique identifiers. These identifiers are configured by :attr:`trusted_unique_identifier_types <app.core.config.Settings.trusted_unique_identifier_types>`.

This is a very powerful operation that should be enabled with caution. It relies on both the uniqueness of the identifiers and the accuracy of the incoming data. An instance where it is suitable to be used is with OpenAlex IDs and OpenAlex imports, where we can verify both those assumptions.

There are a handful of possible outcomes, documented more fully in :meth:`shortcut_deduplication_using_identifiers() <app.domain.references.services.deduplication_service.DeduplicationService.shortcut_deduplication_using_identifiers>`, but in summary:

- If no matches are found or no unique identifiers exist, we proceed to `Candidate Selection`_.
- If any matches are found, we build a duplicate decision tree for **all** of them - any undeduplicated references that are matched are included.
- If the above is unresolvable, (i.e. we find more than one existing duplicate decision tree), we raise the decision for manual review. This provides an important sense-check of our core assumptions.

Candidate Selection
-------------------

.. mermaid::

    flowchart LR

        D["Duplicate Decision"]
        SF["Project Search Fields"]
        ES[("Search Against ES")]
        C{"One or more candidates?"}
        CR["Decision = Canonical"]
        DD["Deep Dedup"]

        D-->SF
        SF-->ES
        ES-->C
        C-->|Yes|DD
        C-->|No|CR


Candidate selection employs a high-recall, low-precision approach to identify potential canonical references. The goal is to ensure that all possible canonicals are considered, even if it means including some false positives.

If no candidates are found, the incoming reference is immediately designated as a canonical reference.

The search strategy is a work in progress, but will likely involve a combination of projected fields (defined in :class:`CandidateCanonicalSearchFields <app.domain.references.models.models.CandidateCanonicalSearchFields>`) and a fuzzy Elasticsearch query:

At this stage, only canonical references are considered as candidates.

.. automethod:: app.domain.references.repository.ReferenceESRepository.search_for_candidate_canonicals

Deep Deduplication
------------------

.. mermaid::

    flowchart LR

        D[Duplicate Decision]
        R[Get References]
        DD[[Perform Deep Dedup]]
        C[Canonical Found?]
        A[Proceed to Actioning]
        M([Raise for Manual Review])

        D-->R-->DD-->C
        C-->|Yes|A
        C-->|No|A
        C-->|"Ambiguous/Uncertain"|M


If candidate canonicals are found, each is compared in detail against the incoming reference to determine if they are true duplicates. This step prioritizes precision over recall, aiming to minimize false positives.

This algorithm is still being built out. For now, we have a placeholder that we will update in the future:

.. automethod:: app.domain.references.services.deduplication_service.DeduplicationService.__placeholder_duplicate_determinator


Manual Resolution
-----------------

Duplicate decisions that are :attr:`Decoupled <app.domain.references.models.models.DuplicateDetermination.DECOUPLED>` or :attr:`Unresolved <app.domain.references.models.models.DuplicateDetermination.UNRESOLVED>` can be handled here. This is not yet implemented.


Action Decision
---------------

Once the deduplication process is complete, the decision must be actioned. In essence, this involves activating the new decision unless there is a particular reason not to.

Special cases
^^^^^^^^^^^^^

The bold lines in the flowchart indicate what we expect to be nominal flow.

.. mermaid::

    flowchart LR

        N["New Decision (N)"]
        C1{"Active Decision Exists? (A)"}
        C2{A == N?}
        C3{A Canonical & N Duplicate?}
        C4{N is Canonical?}
        C5{N's Canonical is Canonical?}
        T[[Activate New Decision]]
        M([Mark for Manual Handling])

        N ==> C1
        C1 ==>|Yes| C2
        C1 -->|No| C4
        C2 ==>|Yes| T
        C2 -->|No| C3
        C3 ==>|Yes| T
        C3 -->|No| M
        C4 -->|No| C5
        C4 ==>|Yes| T
        C5 -->|No| M
        C5 ==>|Yes| T
        M ~~~ T

There are two cases where the new decision is not automatically activated:

1. The active decision is duplicate and the new decision is canonical or a duplicate of a different reference.

2. The new decision is canonical but its canonical reference is not.

Both of these *can* be handled automatically, but manual review allows us to highlight and understanding the frequency and nature of these cases. The commentary around these is changing frequently so not documenting in detail here, but please reach out if you want more information!

.. _deduplicated-projection:

Deduplicated Projection
-----------------------

The end product of deduplication is a rich database with each individual reference, linked together with their duplicate decision history. However, this is not the most convenient format for most use cases. To this end, the default view for interfacing with the repository is the deduplicated projection.

The deduplication projection is simply a consolidated :class:`Reference <libs.sdk.src.destiny_sdk.references.Reference>` object, with enhancements and identifiers of its duplicates included in the canonical reference. This is the view that is indexed into Elasticsearch, and likely the view that most robots and users will interact with.

Also note this projected view is reversible, data provenance is preserved through the ``reference_id`` field on each enhancement and identifier.

See also:

.. automethod:: app.domain.references.models.projections.DeduplicatedReferenceProjection.get_from_reference

.. _exact-duplicates:

Exact Duplicates
----------------

Exact duplicates are references which are wholly represented by an existing reference in the repository. This does not form part of the main deduplication flow, but provides an early-exit optimisation for importers and enhancement processors.

Exact duplication is performed on individual references, not the deduplicated projection. This preserves any implied contextual information from the incoming reference.

See also: :attr:`app.domain.references.services.deduplication_service.DeduplicationService.find_exact_duplicate`.


Function Reference
------------------

.. autoclass:: app.domain.references.services.deduplication_service.DeduplicationService
    :members:
    :undoc-members:
    :inherited-members:
