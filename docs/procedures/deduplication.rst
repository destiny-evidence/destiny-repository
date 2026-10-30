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


There are six key steps:

- `Exact Duplicates`_ - an early-exit check to see if the incoming reference is an exact duplicate of an existing reference. This occurs outside the main deduplication flow.
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

Only references whose active decision is canonical or unsearchable are considered as candidates. An unsearchable reference could not be searched for itself, but a later arrival may still match it.

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

Automatic decisions are switched on by :attr:`enable_automatic_deduplication_decisions <app.core.config.FeatureFlags.enable_automatic_deduplication_decisions>`, which defaults off. While it is off, the placeholder below decides instead and no assessment is recorded:

.. automethod:: app.domain.references.services.deduplication_service.DeduplicationService._placeholder_duplicate_determinator

When it is on, the reference is assessed, the assessment is recorded with purpose ``deduplication`` and the configured policy generation, and the acting policy turns it into a decision. All three happen in one transaction, and a decision made from an assessment links to it through ``deduplication_assessment_id``.

The acting policy is a stand-in until the first automatic policy is agreed:

.. automethod:: app.domain.references.services.deduplication_service.decide_from_assessment

Each automatic decision lands in one of two non-decisions when it cannot be ``CANONICAL`` or ``DUPLICATE``, and its detail says why:

- :attr:`Unsearchable <app.domain.references.models.models.DuplicateDetermination.UNSEARCHABLE>`: no complete candidate set was retrieved. The reference lacks the metadata to search on, the search was truncated by its document cap or server-side timeout, or every attempt failed on infrastructure (for example Elasticsearch timing out). Truncation is final, as a retry would stop again; infrastructure failures are retried a bounded number of times first. If the decision cannot be written either, for example while Elasticsearch is down, it stays pending. A defect in deduplication itself is raised without retrying and also leaves the decision pending. The decision is active, so the reference can take duplicates, and it can be rerun through the invoke API.
- :attr:`Unresolved <app.domain.references.models.models.DuplicateDetermination.UNRESOLVED>`: candidates were retrieved and scored, but no determination could be reached. The detail carries a :class:`reason code <app.domain.references.models.models.DeduplicationUnresolvedReason>`, including when the only clearing candidate no longer accepts duplicates. It is inactive, replaces nothing, has no side effects and is not retried; how often each reason occurs is measured rather than reviewed case by case.

Both are distinct from a ``DECOUPLED`` decision, which is a proposal blocked at `Action Decision`_.

The decisions a policy generation produced can be listed by joining through the assessment:

.. code-block:: sql

    SELECT d.*
    FROM reference_duplicate_decision d
    JOIN deduplication_assessment a ON a.id = d.deduplication_assessment_id
    WHERE a.policy_generation = :generation;


Manual Resolution
-----------------

The ``POST /references/duplicate-decisions/`` endpoint provides an interface to manually make duplicate decisions.

This may be useful if the automated process raises a reference for manual review, or if a user simply wants to manually deduplicate references.


Decision authority and precedence
---------------------------------

Every duplicate decision records both its authority and its trigger. Authority is
``person``, ``system``, or ``unclassified``; historical decisions remain
``unclassified`` unless their authority can be established. Triggers distinguish the
manual API, import processing, and invoke API requests. The ``enhancement`` trigger is
reserved: no path creates enhancement-triggered decisions today.

An automatic proposal never replaces an active ``person`` decision, even when the
proposed result is identical. The active decision is left unchanged and the proposal is
stored as an inactive ``DECOUPLED`` decision for review. Its detail records the proposed
determination and reason, while its proposed canonical ID is retained. A person can
still replace the active decision through the manual endpoint.

The protection covers only the reference whose own active decision would change. A
person-made canonical can still become the target of another reference's automatic
``DUPLICATE`` decision, because that leaves the canonical's own decision untouched.


Action Decision
---------------

Once the deduplication process is complete, the decision must be actioned. In essence, this involves activating the new decision unless there is a particular reason not to.

Special cases
^^^^^^^^^^^^^

The bold lines in the flowchart indicate what we expect to be nominal flow.

.. mermaid::

    flowchart LR

        N["New Decision (N)"]
        C0{"N names a non-canonical reference?"}
        C1{"Active Decision Exists? (A)"}
        CA{"N System & A Person?"}
        C2{A == N?}
        C3{A Canonical & N Duplicate?}
        C4{N is Canonical?}
        C6{Reference has duplicates?}
        T[[Activate New Decision]]
        M([Mark for Manual Handling])
        E["Reject with an error"]

        N ==> C0
        C0 -->|Yes| E
        C0 ==>|No| C1
        C1 ==>|Yes| CA
        C1 -->|No| C4
        CA -->|Yes| M
        CA ==>|No| C2
        C2 ==>|Yes| T
        C2 -->|No| C3
        C3 ==>|Yes| T
        C3 -->|No| M
        C4 ==>|Yes| T
        C4 -->|No| C6
        C6 -->|Yes| M
        C6 ==>|No| T
        M ~~~ T

There are three cases where the new decision is not automatically activated:

1. An automatic proposal would replace a person-made active decision. This applies even when the proposed result is identical.

2. The active decision is duplicate and the new decision is canonical, unsearchable or a duplicate of a different reference. This is a destructive change to the existing canonical reference, which may have implications for its enhancements, and needs to be reviewed in context.

3. The reference being marked as a duplicate already has duplicates pointing to it (which would create a chaining situation).

These are marked as ``DECOUPLED`` for manual review via the ``POST /references/duplicate-decisions/`` endpoint. The decoupled decision is stored inactive, so the reference keeps whichever decision was already active.

A proposal naming a canonical reference that is neither canonical nor unsearchable is not decoupled. It is rejected outright, and the manual endpoint returns ``422``.

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

Exact duplicates are references which are wholly represented (superset) by an existing reference in the repository. This does not form part of the main deduplication flow, but provides an early-exit optimisation for importers and enhancement processors.

Exact duplication is performed on individual references, not the deduplicated projection. This preserves any implied contextual information from the incoming reference.

See also: :attr:`app.domain.references.services.deduplication_service.DeduplicationService.find_exact_duplicate`.


Function Reference
------------------

.. autoclass:: app.domain.references.services.deduplication_service.DeduplicationService
    :members:
    :undoc-members:
    :inherited-members:
