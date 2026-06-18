"""Unit tests for ReferenceAccessControlService."""

from destiny_sdk.enhancements import EnhancementType

from app.core.entitlements import Entitlement
from app.domain.references.services.access_control_service import (
    ReferenceAccessControlService,
)
from tests.factories import (
    AbstractContentEnhancementFactory,
    EnhancementFactory,
    FullTextEnhancementFactory,
    ReferenceFactory,
)


def _reference_with_mixed_enhancements():
    full_text = EnhancementFactory(content=FullTextEnhancementFactory())
    abstract = EnhancementFactory(content=AbstractContentEnhancementFactory())
    return ReferenceFactory(enhancements=[full_text, abstract]), full_text, abstract


def test_redact_passes_through_when_principal_has_full_text():
    acl = ReferenceAccessControlService(entitlements=frozenset({Entitlement.FULL_TEXT}))
    reference, _, _ = _reference_with_mixed_enhancements()

    redacted = acl.redact_reference(reference)

    assert redacted.enhancements is not None
    assert len(redacted.enhancements) == 2
    assert {e.content.enhancement_type for e in redacted.enhancements} == {
        EnhancementType.FULL_TEXT,
        EnhancementType.ABSTRACT,
    }


def test_redact_strips_full_text_when_principal_lacks_entitlement():
    acl = ReferenceAccessControlService(entitlements=frozenset())
    reference, _, abstract = _reference_with_mixed_enhancements()

    redacted = acl.redact_reference(reference)

    assert redacted.enhancements is not None
    assert len(redacted.enhancements) == 1
    assert redacted.enhancements[0].id == abstract.id
    assert redacted.enhancements[0].content.enhancement_type == EnhancementType.ABSTRACT


def test_redact_returns_empty_list_when_only_full_text_present():
    acl = ReferenceAccessControlService(entitlements=frozenset())
    reference = ReferenceFactory(
        enhancements=[EnhancementFactory(content=FullTextEnhancementFactory())]
    )

    redacted = acl.redact_reference(reference)

    assert redacted.enhancements == []
