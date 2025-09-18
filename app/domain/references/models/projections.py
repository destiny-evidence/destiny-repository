"""Projection functions for reference domain data."""

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

        # Define non-terminal statuses
        non_terminal_statuses = {
            PendingEnhancementStatus.PENDING,
            PendingEnhancementStatus.ACCEPTED,
            PendingEnhancementStatus.IMPORTING,
            PendingEnhancementStatus.INDEXING,
        }

        # All pending -> received
        if pending_enhancement_status_set == {PendingEnhancementStatus.PENDING}:
            enhancement_request.request_status = EnhancementRequestStatus.RECEIVED

        # If there are any non-terminal statuses, result should be PROCESSING
        elif non_terminal_statuses & pending_enhancement_status_set:
            enhancement_request.request_status = EnhancementRequestStatus.PROCESSING

        # Only terminal statuses remain - check their combination
        elif pending_enhancement_status_set == {PendingEnhancementStatus.COMPLETED}:
            enhancement_request.request_status = EnhancementRequestStatus.COMPLETED

        elif pending_enhancement_status_set == {PendingEnhancementStatus.FAILED}:
            enhancement_request.request_status = EnhancementRequestStatus.FAILED

        # Any other combination of terminal statuses -> partial failed
        else:
            enhancement_request.request_status = EnhancementRequestStatus.PARTIAL_FAILED

        return enhancement_request
