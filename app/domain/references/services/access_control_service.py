"""Access control for references."""

from typing import NewType

from destiny_sdk.enhancements import EnhancementType

from app.api.auth import Entitlement
from app.domain.references.models.models import Enhancement, Reference
from app.domain.service import GenericAccessControlService

RedactedReference = NewType("RedactedReference", Reference)


class ReferenceAccessControlService(GenericAccessControlService):
    """Redact references for a principal's entitlements."""

    def redact_reference(self, reference: Reference) -> RedactedReference:
        """Return the principal's redacted view of a reference."""
        return RedactedReference(
            reference.model_copy(
                update={
                    "enhancements": self._redact_full_text(
                        reference.enhancements or []
                    ),
                }
            )
        )

    def _redact_full_text(self, enhancements: list[Enhancement]) -> list[Enhancement]:
        """Drop full-text enhancements unless the principal is entitled to them."""
        if Entitlement.FULL_TEXT in self._entitlements:
            return enhancements
        return [
            enhancement
            for enhancement in enhancements
            if enhancement.content.enhancement_type is not EnhancementType.FULL_TEXT
        ]
