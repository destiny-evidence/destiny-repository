"""Projection functions for import domain data."""

from app.core.exceptions import ProjectionError
from app.domain.base import GenericProjection
from app.domain.imports.models.models import (
    ImportBatch,
    ImportBatchStatus,
    ImportResultStatus,
)


class ImportBatchStatusProjection(GenericProjection[ImportBatch]):
    """Projection functions to hydrate import batch status."""

    @classmethod
    def get_from_status_set(
        cls,
        import_batch: ImportBatch,
        import_result_status_set: set[ImportResultStatus],
    ) -> ImportBatch:
        """Project the import batch status from a set of import result statuses."""
        # No results or nothing begun processing -> created
        if not import_result_status_set or import_result_status_set == {
            ImportResultStatus.CREATED
        }:
            import_batch.status = ImportBatchStatus.CREATED

        # Something in progress -> started
        elif {
            ImportResultStatus.STARTED,
            ImportResultStatus.RETRYING,
        } & import_result_status_set:
            import_batch.status = ImportBatchStatus.STARTED

        # Everything completed -> completed
        elif import_result_status_set == {ImportResultStatus.COMPLETED}:
            import_batch.status = ImportBatchStatus.COMPLETED

        # Everything failed -> failed
        elif import_result_status_set.issubset(
            {ImportResultStatus.FAILED, ImportResultStatus.PARTIALLY_FAILED}
        ):
            import_batch.status = ImportBatchStatus.FAILED

        # Some completed, some failed -> partially failed
        elif (
            ImportResultStatus.COMPLETED in import_result_status_set
            and {ImportResultStatus.FAILED, ImportResultStatus.PARTIALLY_FAILED}
            & import_result_status_set
        ):
            import_batch.status = ImportBatchStatus.PARTIALLY_FAILED

        # Some other state we haven't foreseen
        else:
            msg = f"Could not resolve import batch status. {import_result_status_set}."
            raise ProjectionError(msg)

        return import_batch
