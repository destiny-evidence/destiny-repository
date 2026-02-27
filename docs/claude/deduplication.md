# Deduplication Guide

This document provides guidance for working on the deduplication system.

## Overview

Deduplication ensures references aren't duplicated in the corpus. The main service is at `app/domain/references/services/deduplication_service.py`.

## Key Concepts

### DuplicateDetermination States

See `app/domain/references/models/models.py:DuplicateDetermination` for the enum. Key concepts:

- **CANONICAL** vs **DUPLICATE** - A canonical is the authoritative version; duplicates point to their canonical
- **EXACT_DUPLICATE** - Skipped on import (identical identifiers to existing reference)
- **DECOUPLED** - Requires manual review (multiple potential canonicals found, or chain too deep)
- **UNSEARCHABLE** - No usable identifiers for deduplication lookup

### Canonical vs Duplicate

A **canonical** reference is the authoritative version. **Duplicates** point to their canonical via `canonical_reference_id`. Only one decision per reference can be active (`active_decision=True`).

## Key Methods

| Method                                       | Purpose                                                    |
| -------------------------------------------- | ---------------------------------------------------------- |
| `find_exact_duplicate()`                     | Pre-import check for references with identical identifiers |
| `shortcut_deduplication_using_identifiers()` | Fast-path using trusted identifiers (OpenAlex, DOI)        |
| `nominate_candidate_canonicals()`            | Search-based candidate finding                             |
| `map_duplicate_decision()`                   | Applies persistence changes from decisions                 |

## Common Gotchas

### active_decision Constraint

Only one decision per reference can have `active_decision=True`. This is enforced by a partial unique index. When creating new decisions, the old active one must be deactivated.

### Chain Depth Limits

`MAX_REFERENCE_DUPLICATE_DEPTH` (see `app/core/constants.py`) limits how deep duplicate chains can go. If exceeded, the reference is marked DECOUPLED for manual review.

### DECOUPLED State

When `shortcut_deduplication_using_identifiers()` finds multiple potential canonical references, it marks the reference as DECOUPLED rather than guessing. This requires manual intervention.

### Identifier Trust Hierarchy

OpenAlex IDs (`W` prefix) are most trusted for deduplication shortcuts. DOIs are generally reliable but have edge cases (collisions, malformed values).

## Related Files

- **Domain model**: `app/domain/references/models/models.py` (Reference, ReferenceDuplicateDecision)
- **SQL model**: `app/domain/references/models/sql.py`
- **Tests**: `tests/unit/domain/references/services/test_deduplication_service.py`
