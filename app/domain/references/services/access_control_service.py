"""Access control for references."""

from typing import NewType

from destiny_sdk.enhancements import EnhancementType

from app.api.auth import Entitlement
from app.domain.references.models.models import Reference
from app.domain.service import AccessControlService

RedactedReference = NewType("RedactedReference", Reference)


class ReferenceAccessControlService(AccessControlService):
    """Redact references for a principal's entitlements."""

    def redact(self, reference: Reference) -> RedactedReference:
        """
        Return the principal's redacted view of a reference.

        Drops enhancements the principal is not entitled to read.
        """
        return RedactedReference(
            reference.model_copy(
                update={
                    "enhancements": [
                        enhancement
                        for enhancement in (reference.enhancements or [])
                        if enhancement.content.enhancement_type
                        is not EnhancementType.FULL_TEXT
                        or Entitlement.FULL_TEXT in self._entitlements
                    ],
                }
            )
        )
