# Enhancements Guide

This document covers the enhancement system internals.

## Overview

Enhancements are metadata layers attached to references. Multiple enhancements of the same type can exist; they are merged during projection.

## Enhancement Types

See `libs/sdk/src/destiny_sdk/enhancements.py:EnhancementType`:

- **BIBLIOGRAPHIC** - Title, authors, publication year, DOI
- **ABSTRACT** - Abstract text
- **ANNOTATION** - Labels, scores, classifications (by scheme)
- **LOCATION** - URLs, file locations
- **REFERENCE_ASSOCIATION** - Links to other references
- **RAW** - Arbitrary unstructured data
- **FULL_TEXT** - Full text content (not yet implemented)

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

`PendingEnhancement` tracks enhancement requests sent to robots. States in `app/domain/references/models/models.py:PendingEnhancementStatus`:

- **PENDING** - Waiting to be processed
- **PROCESSING** - Currently being processed by robot
- **IMPORTING** - Being imported into the system
- **INDEXING** - Being indexed in Elasticsearch
- **INDEXING_FAILED** - Indexing failed
- **COMPLETED** - Successfully processed
- **FAILED** - Processing failed
- **DISCARDED** - Skipped (exact duplicate)
- **EXPIRED** - Lease expired during processing

## Related Files

- **SDK types**: `libs/sdk/src/destiny_sdk/enhancements.py`
- **Domain model**: `app/domain/references/models/models.py` (Enhancement, PendingEnhancement)
- **Projection**: `app/domain/references/models/projections.py`
- **Service**: `app/domain/references/services/enhancement_service.py`
