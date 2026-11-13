.. _enhancement-supersession:

Superseding Enhancements
========================

.. note:: This document is best understood in conjunction with :ref:`Robots Schemas <sdk_schemas:Robots>` and :doc:`Requesting Enhancements <requesting-batch-enhancements>`, which describes how robots receive references and return enhancements.

.. contents:: Table of Contents
    :depth: 2
    :local:

Why Supersede
-------------

By default, every :class:`Enhancement <libs.sdk.src.destiny_sdk.enhancements.Enhancement>` a robot returns is added alongside the ones already on the reference. A robot that is asked to enhance the same reference twice leaves two enhancements behind, and readers cannot tell which one is current.

Supersession lets a robot say that a new enhancement replaces an earlier one. Use it when:

- the robot is re-run on a reference it has already enhanced, for example after a new robot version or because the data it depends on has changed;
- an earlier enhancement was wrong and needs correcting;
- an earlier enhancement should no longer apply at all, in which case it is withdrawn with a :ref:`tombstone <enhancement-tombstones>`.

An enhancement and the enhancements that have replaced it form a chain. References show the latest enhancement of each chain. Earlier ones are kept in the repository for provenance, but are not currently available through the API.

.. mermaid::

    flowchart RL
        B["Enhancement B<br>supersedes A"] -->|replaces| A["Enhancement A"]
        C["Enhancement C<br>supersedes B"] -->|replaces| B
        C -.- N(["Shown on the reference"])

Who Can Supersede
-----------------

Only robots with the :attr:`enhancement_supersession_writer <libs.sdk.src.destiny_sdk.robots.RobotEntitlement.ENHANCEMENT_SUPERSESSION_WRITER>` entitlement can supersede enhancements.

Entitlements are set in the ``entitlements`` field when :doc:`registering or updating a robot <robot-registration>`. Changing them requires the ``robot.entitlement.writer`` scope or role. If you do not hold it, ask a repository administrator to grant the entitlement to your robot.

A robot should only supersede its own enhancements.

What Can Be Superseded
----------------------

The enhancement named in :attr:`supersedes <libs.sdk.src.destiny_sdk.enhancements.Enhancement.supersedes>` must be:

- **The latest in its chain.** An enhancement can be superseded once. To replace it again, supersede its replacement.
- **On the same reference.** The new enhancement's ``reference_id`` must equal the ``reference_id`` of the enhancement it supersedes.
- **Of the same enhancement type**, unless the new enhancement is a :ref:`tombstone <enhancement-tombstones>`. An annotation can replace an annotation, but not an abstract.

Every enhancement on a reference a robot receives is the latest in its chain, so any of them can be named in ``supersedes`` provided the other two rules hold.

.. note::

    References are provided in their :ref:`deduplicated form <deduplicated-projection>`, which includes the enhancements of the reference's duplicates. Those enhancements keep the ``reference_id`` of the duplicate they belong to. A robot cannot supersede them while enhancing the canonical reference, because results are only accepted for the references in the batch. Check that ``enhancement.reference_id`` equals ``reference.id`` before superseding.

How to Supersede
----------------

Supersession happens in the result file a robot uploads for a robot enhancement batch. The steps in :doc:`Requesting Enhancements <requesting-batch-enhancements>` are unchanged, apart from how the enhancement is built:

1. **Find the enhancement to replace** in the ``enhancements`` of the :class:`Reference <libs.sdk.src.destiny_sdk.references.Reference>` being processed. A robot will usually look for an enhancement with its own ``source``, the reference's own ``reference_id`` and the enhancement type it is about to return. If the robot keeps several enhancements of the same type on a reference, it needs its own way to tell them apart, such as the annotation scheme.

2. **Set** ``supersedes`` to that enhancement's ``id`` on the new :class:`Enhancement <libs.sdk.src.destiny_sdk.enhancements.Enhancement>`. If there is no enhancement to replace, leave ``supersedes`` unset and the enhancement starts a new chain.

3. **Upload and submit the result** as usual.

.. code-block:: python

    from destiny_sdk.enhancements import Enhancement, EnhancementContent
    from destiny_sdk.references import Reference
    from destiny_sdk.visibility import Visibility

    SOURCE = "my-robot"


    def build_enhancement(reference: Reference, content: EnhancementContent) -> Enhancement:
        previous = next(
            (
                enhancement
                for enhancement in reference.enhancements or []
                if enhancement.source == SOURCE
                and enhancement.reference_id == reference.id
                and enhancement.content.enhancement_type == content.enhancement_type
            ),
            None,
        )
        return Enhancement(
            reference_id=reference.id,
            source=SOURCE,
            visibility=Visibility.PUBLIC,
            supersedes=previous.id if previous else None,
            content=content,
        )

The resulting line in the result file looks like this:

.. code-block:: json

    {
        "reference_id": "0198a1c2-7b4e-7c3a-9f10-2d5e8a6b4c01",
        "source": "my-robot",
        "visibility": "public",
        "supersedes": "0198a1c3-0d2f-7e8b-8a41-6c9f1b3d5e02",
        "content": {
            "enhancement_type": "annotation",
            "annotations": [
                {
                    "annotation_type": "boolean",
                    "scheme": "my-robot:included",
                    "label": "included",
                    "value": true
                }
            ]
        }
    }

The ``supersedes`` field is available from version 0.17.4 of the SDK.

.. note::

    A result file can hold one entry per reference, so a robot can supersede or withdraw one enhancement per reference in each batch.

If the new enhancement is identical to the one it supersedes, it is discarded as an exact duplicate and the existing enhancement stays in place.

.. _enhancement-tombstones:

Tombstones
----------

A tombstone withdraws an enhancement without replacing it. It is an :class:`Enhancement <libs.sdk.src.destiny_sdk.enhancements.Enhancement>` whose content is a :class:`TombstoneEnhancement <libs.sdk.src.destiny_sdk.enhancements.TombstoneEnhancement>`, with ``supersedes`` set to the enhancement being withdrawn. An optional ``reason`` records why.

.. code-block:: json

    {
        "reference_id": "0198a1c2-7b4e-7c3a-9f10-2d5e8a6b4c01",
        "source": "my-robot",
        "visibility": "public",
        "supersedes": "0198a1c3-0d2f-7e8b-8a41-6c9f1b3d5e02",
        "content": {
            "enhancement_type": "tombstone",
            "reason": "Abstract was retracted by the publisher."
        }
    }

Once a chain is withdrawn, references show nothing from it: neither the tombstone nor the enhancements before it.

A tombstone must set ``supersedes``. Otherwise the same rules apply as for any superseding enhancement, except that a tombstone can withdraw an enhancement of any type.

A withdrawn chain cannot currently be continued by a robot. To add an enhancement to the reference later, leave ``supersedes`` unset and start a new chain.

:class:`TombstoneEnhancement <libs.sdk.src.destiny_sdk.enhancements.TombstoneEnhancement>` is available from version 0.17.6 of the SDK. Import files cannot contain tombstones or supersede enhancements.

After Superseding
-----------------

References returned by the API, search results and the reference files provided to robots all show the latest enhancement of each chain, and nothing from chains withdrawn by a tombstone. The latest enhancement carries the ``id`` of the one it replaced in its ``supersedes`` field.

The repository assigns the ``id`` of a new enhancement. A robot sees it the next time it receives the reference, which is when it can supersede that enhancement in turn.

A superseding enhancement is checked against :doc:`robot automations <robot-automation>` in the same way as any other new enhancement, so robots that depend on it may be asked to enhance the reference again. Those robots should supersede their own earlier enhancement when they do.

Errors
------

Results are checked when the repository imports them, after the robot has submitted the batch, so a broken rule is not reported in the response to the submission. The entry is not imported and the other entries in the batch are unaffected. The enhancement request finishes as ``PARTIAL_FAILED``, or ``FAILED`` if no entry was imported.

The repository records the reason against the entry's ``reference_id`` in the batch's validation result file. That file is not currently returned to robots, so ask a repository administrator if you need the reason for a failed entry. The reasons are:

.. list-table::
    :header-rows: 1
    :widths: 50 50

    * - Error
      - Cause
    * - ``Robot is not entitled to supersede enhancements.``
      - The robot does not have the ``enhancement_supersession_writer`` entitlement.
    * - ``Attempted to supersede non-existent enhancement ...``
      - No enhancement has the ``id`` given in ``supersedes``.
    * - ``... which has already been superseded. The head of its chain is ...`` or ``Enhancement ... has already been superseded.``
      - The enhancement is no longer the latest in its chain. This happens when the reference data is out of date, or when two results supersede the same enhancement.
    * - ``An enhancement can only supersede one on the same reference.``
      - The enhancement named in ``supersedes`` belongs to a different reference, such as a duplicate.
    * - ``A chain can only be continued by an enhancement of the same type, or withdrawn by a tombstone.``
      - The new enhancement's type differs from the one it supersedes.
    * - ``A tombstone must supersede the enhancement it withdraws.``
      - A tombstone was returned without ``supersedes``.
    * - ``Exact duplicate enhancement already exists on reference.``
      - The new enhancement is identical to the one it supersedes. The entry is discarded rather than failed.
