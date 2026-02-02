"""Tests for our elasticsearch models."""

import uuid

import pytest
from destiny_sdk.identifiers import ExternalIdentifierType

from app.domain.references.models.es import EnhancementDocument
from app.domain.references.models.models import LinkedExternalIdentifier
from app.domain.references.models.projections import (
    _IDENTIFIER_TYPE_TO_KEY,
    flatten_identifiers,
)
from tests.factories import (
    DOIIdentifierFactory,
    EnhancementFactory,
    OpenAlexIdentifierFactory,
    OtherIdentifierFactory,
    PubMedIdentifierFactory,
    RawEnhancementFactory,
)


def test_enhancement_content_clean_raises_runtime_error_if_raw_enhancement():
    raw_enhancement = EnhancementFactory.build(content=RawEnhancementFactory.build())

    enhancement_doc = EnhancementDocument.from_domain(raw_enhancement)

    with pytest.raises(RuntimeError, match="excluded enhancement"):
        enhancement_doc.content.clean()


@pytest.mark.parametrize(
    ("identifiers_fn", "expected"),
    [
        # None input
        (lambda _: None, None),
        # Empty list
        (lambda _: [], None),
        # Standard identifier types
        (
            lambda ref_id: [
                LinkedExternalIdentifier(
                    reference_id=ref_id,
                    identifier=DOIIdentifierFactory.build(identifier="10.1234/test"),
                ),
                LinkedExternalIdentifier(
                    reference_id=ref_id,
                    identifier=OpenAlexIdentifierFactory.build(identifier="W12345678"),
                ),
                LinkedExternalIdentifier(
                    reference_id=ref_id,
                    identifier=PubMedIdentifierFactory.build(identifier=123456),
                ),
            ],
            {"doi": "10.1234/test", "open_alex": "W12345678", "pmid": "123456"},
        ),
        # OTHER type uses other_identifier_name as key
        (
            lambda ref_id: [
                LinkedExternalIdentifier(
                    reference_id=ref_id,
                    identifier=OtherIdentifierFactory.build(
                        identifier="978-3-16-148410-0",
                        other_identifier_name="ISBN",
                    ),
                ),
            ],
            {"isbn": "978-3-16-148410-0"},
        ),
    ],
    ids=["none", "empty", "standard_types", "other_type"],
)
def test_flatten_identifiers(identifiers_fn, expected):
    """Test flatten_identifiers converts identifier lists to ES flattened dicts."""
    ref_id = uuid.uuid4()
    result = flatten_identifiers(identifiers_fn(ref_id))
    assert result == expected


def test_identifier_type_mapping_covers_all_types():
    """
    Ensure all ExternalIdentifierType values have an explicit mapping.

    If this test fails, a new identifier type was added to the SDK.
    You must add it to _IDENTIFIER_TYPE_TO_KEY in projections.py with
    an appropriate ES field name.
    """
    unmapped = [
        id_type
        for id_type in ExternalIdentifierType
        if id_type != ExternalIdentifierType.OTHER
        and id_type not in _IDENTIFIER_TYPE_TO_KEY
    ]

    assert not unmapped, (
        f"New ExternalIdentifierType(s) need mapping in _IDENTIFIER_TYPE_TO_KEY: "
        f"{unmapped}. This is a breaking change to the ES index - add explicit "
        f"key mappings in app/domain/references/models/projections.py"
    )
