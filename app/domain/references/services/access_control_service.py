"""Access control for references."""

from typing import NewType

from destiny_sdk.enhancements import EnhancementType

from app.core.entitlements import Entitlement
from app.domain.references.models.models import Enhancement, Reference
from app.domain.service import GenericAccessControlService

RedactedReference = NewType("RedactedReference", Reference)


class ReferenceAccessControlService(GenericAccessControlService):
    """Apply a principal's entitlements to reference reads and writes."""

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

    @property
    def may_write_raw_enhancements(self) -> bool:
        """Whether the principal may contribute raw enhancements to a reference."""
        return Entitlement.RAW_ENHANCEMENT_WRITER in self._entitlements

    def _redact_full_text(self, enhancements: list[Enhancement]) -> list[Enhancement]:
        """Drop full-text enhancements unless the principal is entitled to them."""
        if Entitlement.FULL_TEXT in self._entitlements:
            return enhancements
        return [
            enhancement
            for enhancement in enhancements
            if enhancement.content.enhancement_type is not EnhancementType.FULL_TEXT
        ]
