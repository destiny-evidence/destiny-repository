# Imports Guide

This document covers the import system internals.

## Overview

Imports bring external references into the system. The hierarchy is:

```text
ImportRecord (one per import job)
  └── ImportBatch (chunks of references)
        └── ImportResult (one per reference attempt)
```

## Import Flow

1. Create `ImportRecord` with metadata (source, processor, expected count)
2. Create `ImportBatch` entries for chunks of references
3. Process each batch, creating `ImportResult` for each reference
4. Reference goes through: import -> deduplication -> indexing

## Status Enums

See `app/domain/imports/models/models.py`:

### ImportRecordStatus

- **CREATED** - No processing started
- **STARTED** - Processing in progress
- **COMPLETED** - All batches processed

### ImportBatchStatus

- **CREATED** - No processing started
- **STARTED** - Processing in progress
- **FAILED** - Processing failed
- **PARTIALLY_FAILED** - Some references failed
- **COMPLETED** - All references processed

### ImportResultStatus

- **CREATED** - Not yet processed
- **STARTED** - Currently processing
- **COMPLETED** - Reference created successfully
- **PARTIALLY_FAILED** - Reference created but some enhancements/identifiers failed
- **FAILED** - Reference creation failed
- **RETRYING** - Failed but being retried

## Deadlock Handling

Import processing can encounter database deadlocks (`DeadlockDetectedError`). The service catches these and retries. See `app/domain/imports/service.py`.

## Related Files

- **Models**: `app/domain/imports/models/models.py`
- **Service**: `app/domain/imports/service.py`
- **Tasks**: `app/domain/imports/tasks.py`
- **Routes**: `app/domain/imports/routes.py`
