"""Projection functions for reference domain data."""

from app.core.exceptions import ProjectionError
from app.domain.base import GenericProjection
from app.domain.references.models.models import (
    EnhancementRequest,
    EnhancementRequestStatus,
    PendingEnhancementStatus,
)


class EnhancementRequestStatusProjection(GenericProjection[EnhancementRequest]):
    """Projection functions to hydrate enhancement request status."""

    @classmethod
    def get_from_status_set(
        cls,
        enhancement_request: EnhancementRequest,
        pending_enhancement_status_set: set[PendingEnhancementStatus],
    ) -> EnhancementRequest:
        """Project the enhancement request status from a set of pending statuses."""
        # No pending enhancements -> keep original status for backwards compatibility
        if not pending_enhancement_status_set:
            return enhancement_request

        # All pending -> received
        if pending_enhancement_status_set == {PendingEnhancementStatus.PENDING}:
            enhancement_request.request_status = EnhancementRequestStatus.RECEIVED

        # All completed -> completed
        elif pending_enhancement_status_set == {PendingEnhancementStatus.COMPLETED}:
            enhancement_request.request_status = EnhancementRequestStatus.COMPLETED

        # All failed -> failed
        elif pending_enhancement_status_set == {PendingEnhancementStatus.FAILED}:
            enhancement_request.request_status = EnhancementRequestStatus.FAILED

        # Any combination of terminal statuses involving failures -> partial failed
        elif {
            PendingEnhancementStatus.FAILED,
            PendingEnhancementStatus.INDEXING_FAILED,
            PendingEnhancementStatus.COMPLETED,
        } & pending_enhancement_status_set:
            enhancement_request.request_status = EnhancementRequestStatus.PARTIAL_FAILED

        # Something in progress -> processing
        elif {
            PendingEnhancementStatus.ACCEPTED,
            PendingEnhancementStatus.IMPORTING,
            PendingEnhancementStatus.INDEXING,
        } & pending_enhancement_status_set:
            enhancement_request.request_status = EnhancementRequestStatus.PROCESSING

        # Some other state we haven't foreseen
        else:
            msg = (
                f"Could not resolve enhancement request status. "
                f"{pending_enhancement_status_set}."
            )
            raise ProjectionError(msg)

        return enhancement_request
