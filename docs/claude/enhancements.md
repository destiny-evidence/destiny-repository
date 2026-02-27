# Enhancements Guide

This document covers the enhancement system internals.

## Overview

Enhancements are metadata layers attached to references. Multiple enhancements of the same type can exist; they are merged during projection.

## Enhancement Types

See `libs/sdk/src/destiny_sdk/enhancements.py:EnhancementType` for the enum values. Each type corresponds to a different metadata category (bibliographic, abstract, annotations, etc.).

## Projection Logic

When projecting enhancements to search fields (`app/domain/references/models/projections.py:ReferenceSearchFieldsProjection`):

1. Sort by priority: canonical reference enhancements first, then by `created_at` descending
2. Iterate through sorted enhancements
3. For each field, first non-null value wins

This means:

- Enhancements on the canonical reference override duplicates' enhancements
- Among same-reference enhancements, most recent wins
- Fields are not merged; entire enhancement content is considered

## Pending Enhancements

`PendingEnhancement` tracks enhancement requests sent to robots. See `app/domain/references/models/models.py:PendingEnhancementStatus` for states. The lifecycle is: PENDING → PROCESSING → IMPORTING → INDEXING → COMPLETED (with FAILED/EXPIRED/DISCARDED as terminal error states).

## Related Files

- **SDK types**: `libs/sdk/src/destiny_sdk/enhancements.py`
- **Domain model**: `app/domain/references/models/models.py` (Enhancement, PendingEnhancement)
- **Projection**: `app/domain/references/models/projections.py`
- **Service**: `app/domain/references/services/enhancement_service.py`
