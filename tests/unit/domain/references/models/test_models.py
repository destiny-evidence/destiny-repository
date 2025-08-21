"""Unit tests for the models in the references module."""

import uuid

import destiny_sdk
import pytest

from app.core.exceptions import SDKToDomainError, UnresolvableReferenceDuplicateError
from app.domain.references.models.models import (
    Enhancement,
    GenericExternalIdentifier,
    LinkedExternalIdentifier,
    Reference,
    Visibility,
)
from app.domain.references.models.validators import ReferenceCreateResult
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)


async def test_generic_external_identifier_from_specific_without_other():
    doi = destiny_sdk.identifiers.DOIIdentifier(
        identifier="10.1000/abc123", identifier_type="doi"
    )
    gen = GenericExternalIdentifier.from_specific(doi)
    assert gen.identifier == "10.1000/abc123"
    assert gen.identifier_type == "doi"
    assert gen.other_identifier_name is None


async def test_generic_external_identifier_from_specific_with_other():
    other = destiny_sdk.identifiers.OtherIdentifier(
        identifier="123", identifier_type="other", other_identifier_name="isbn"
    )
    gen = GenericExternalIdentifier.from_specific(other)
    assert gen.identifier == "123"
    assert gen.identifier_type == "other"
    assert gen.other_identifier_name == "isbn"


def test_reference_create_result_error_str_none():
    result = ReferenceCreateResult()
    assert result.error_str is None


def test_reference_create_result_error_str_multiple():
    result = ReferenceCreateResult(errors=["first error", " second error "])
    # strips and joins with blank line
    assert result.error_str == "first error\n\nsecond error"


@pytest.fixture
def anti_corruption_service(fake_repository) -> ReferenceAntiCorruptionService:
    return ReferenceAntiCorruptionService(fake_repository)


async def test_linked_external_identifier_roundtrip(
    anti_corruption_service,
):
    sdk_id = destiny_sdk.identifiers.PubMedIdentifier(
        identifier=1234, identifier_type="pm_id"
    )
    sdk_linked = destiny_sdk.identifiers.LinkedExternalIdentifier(
        identifier=sdk_id, reference_id=(u := uuid.uuid4())
    )
    domain = anti_corruption_service.external_identifier_from_sdk(sdk_linked)
    assert domain.identifier == sdk_id
    assert domain.reference_id == u

    back = anti_corruption_service.external_identifier_to_sdk(domain)
    assert isinstance(back, destiny_sdk.identifiers.LinkedExternalIdentifier)
    assert back.reference_id == sdk_linked.reference_id
    assert back.identifier == sdk_id


async def test_enhancement_request_roundtrip(
    anti_corruption_service: ReferenceAntiCorruptionService,
):
    rid = uuid.uuid4()
    req_in = destiny_sdk.robots.EnhancementRequestIn(
        reference_id=rid, robot_id=rid, enhancement_parameters={"param": 42}
    )
    domain = anti_corruption_service.enhancement_request_from_sdk(req_in)
    assert domain.reference_id == rid
    assert domain.robot_id == rid
    assert domain.enhancement_parameters == {"param": 42}

    sdk_read = anti_corruption_service.enhancement_request_to_sdk(domain)
    assert isinstance(sdk_read, destiny_sdk.robots.EnhancementRequestRead)
    assert sdk_read.reference_id == rid
    assert sdk_read.robot_id == rid
    assert sdk_read.enhancement_parameters == {"param": 42}


async def test_enhancement_unserializable_failure(
    anti_corruption_service: ReferenceAntiCorruptionService,
):
    """Test that an enhancement with unserializable parameters raises an error."""
    dodgy_enhancement = destiny_sdk.enhancements.LocationEnhancement(
        locations=[
            destiny_sdk.enhancements.Location(
                # Example where input is not JSON serializable.
                # Serializing makes the URL longer than max length,
                # deserializing then fails.
                landing_page_url=r"http://obfuscated.org/doing-cool-researÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€š\Â¬Ã…Â¾Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â§h-on-french-letters/1234"  # noqa: E501, RUF001
            )
        ],
    )
    with pytest.raises(SDKToDomainError):
        anti_corruption_service.enhancement_from_sdk(
            destiny_sdk.enhancements.Enhancement(
                reference_id=uuid.uuid4(),
                source="dummy",
                visibility="public",
                content=dodgy_enhancement,
            )
        )

    with pytest.raises(SDKToDomainError):
        anti_corruption_service.reference_from_sdk_file_input(
            destiny_sdk.references.ReferenceFileInput(
                identifiers=[
                    destiny_sdk.identifiers.DOIIdentifier(
                        identifier="10.1000/abc123", identifier_type="doi"
                    )
                ],
                enhancements=[
                    destiny_sdk.enhancements.EnhancementFileInput(
                        source="dummy",
                        visibility="public",
                        enhancement_type="location",
                        content=dodgy_enhancement,
                    )
                ],
            )
        )


class TestReferenceMerge:
    """Tests for the Reference.merge method."""

    @pytest.fixture
    def annotation(self) -> Enhancement:
        """Creates a simple annotation enhancement."""
        annotation = destiny_sdk.enhancements.BooleanAnnotation(
            annotation_type=destiny_sdk.enhancements.AnnotationType.BOOLEAN,
            scheme="test",
            label="test_label",
            value=True,
        )
        annotation_enhancement = destiny_sdk.enhancements.AnnotationEnhancement(
            enhancement_type=destiny_sdk.enhancements.EnhancementType.ANNOTATION,
            annotations=[annotation],
        )
        return Enhancement(
            id=uuid.uuid4(),
            source="test",
            visibility=Visibility.PUBLIC,
            content=annotation_enhancement,
            reference_id=uuid.uuid4(),
        )

    @pytest.fixture
    def abstract(self) -> Enhancement:
        abstract_enhancement = destiny_sdk.enhancements.AbstractContentEnhancement(
            abstract="Test abstract content",
            process=destiny_sdk.enhancements.AbstractProcessType.OTHER,
        )
        return Enhancement(
            id=uuid.uuid4(),
            source="test",
            visibility=Visibility.PUBLIC,
            content=abstract_enhancement,
            reference_id=uuid.uuid4(),
        )

    @pytest.fixture
    def doi_identifier(self) -> LinkedExternalIdentifier:
        """Creates a DOI identifier."""
        doi = destiny_sdk.identifiers.DOIIdentifier(
            identifier="10.1000/abc123", identifier_type="doi"
        )
        return LinkedExternalIdentifier(
            id=uuid.uuid4(),
            identifier=doi,
            reference_id=uuid.uuid4(),
        )

    @pytest.fixture
    def base_reference(self, doi_identifier, abstract) -> Reference:
        """Creates a base reference."""
        ref = Reference(id=uuid.uuid4())
        abstract.reference_id = ref.id
        doi_identifier.reference_id = ref.id
        ref.enhancements = [abstract]
        ref.identifiers = [doi_identifier]
        return ref

    @pytest.fixture
    def pmid_identifier(self) -> LinkedExternalIdentifier:
        """Creates a PubMed identifier."""
        pmid = destiny_sdk.identifiers.PubMedIdentifier(
            identifier=1234, identifier_type="pm_id"
        )
        return LinkedExternalIdentifier(
            id=uuid.uuid4(),
            identifier=pmid,
            reference_id=uuid.uuid4(),
        )

    @pytest.fixture
    def openalex_identifier(self) -> LinkedExternalIdentifier:
        """Creates an OpenAlex identifier."""
        oaid = destiny_sdk.identifiers.OpenAlexIdentifier(
            identifier="W12345", identifier_type="open_alex"
        )
        return LinkedExternalIdentifier(
            id=uuid.uuid4(),
            identifier=oaid,
            reference_id=uuid.uuid4(),
        )

    async def test_merge_empty_reference(self, base_reference):
        """Test merging an empty reference into another empty reference."""
        incoming = Reference(id=uuid.uuid4())
        incoming.enhancements = []
        incoming.identifiers = []

        delta_identifiers, delta_enhancements = base_reference.merge(incoming)

        assert len(delta_identifiers) == 0
        assert len(delta_enhancements) == 0
        assert len(base_reference.identifiers) == 1
        assert len(base_reference.enhancements) == 1

    async def test_merge_reference_with_new_identifiers(
        self, base_reference, doi_identifier, pmid_identifier
    ):
        """Test merging a reference with identifiers into an empty reference."""
        incoming = Reference(id=uuid.uuid4())
        incoming.enhancements = []
        incoming.identifiers = [doi_identifier, pmid_identifier]

        delta_identifiers, delta_enhancements = base_reference.merge(incoming)

        assert len(delta_identifiers) == 1
        assert len(delta_enhancements) == 0
        assert len(base_reference.identifiers) == 2
        assert len(base_reference.enhancements) == 1

        # Check that reference_id was updated to match base reference
        assert all(
            i.reference_id == base_reference.id for i in base_reference.identifiers
        )
        # Check that IDs were regenerated on the new identifier
        assert all(i.id != pmid_identifier.id for i in base_reference.identifiers)

    async def test_merge_reference_with_new_enhancements(
        self, base_reference, annotation
    ):
        """Test merging a reference with enhancements into an empty reference."""
        incoming = Reference(id=uuid.uuid4())
        incoming.identifiers = []
        incoming.enhancements = [annotation]

        delta_identifiers, delta_enhancements = base_reference.merge(incoming)

        assert len(delta_identifiers) == 0
        assert len(delta_enhancements) == 1
        assert len(base_reference.identifiers) == 1
        assert len(base_reference.enhancements) == 2

        # Check that reference_id was updated to match base reference
        assert all(
            e.reference_id == base_reference.id for e in base_reference.enhancements
        )
        # Check that IDs were regenerated
        assert all(e.id != annotation.id for e in base_reference.enhancements)

    async def test_merge_reference_with_duplicate_enhancements(
        self, base_reference, annotation
    ):
        """Test merging a reference with duplicate enhancements is handled correctly."""
        base_reference.enhancements.append(annotation)

        incoming = Reference(id=uuid.uuid4())
        incoming.identifiers = []
        incoming.enhancements = [
            Enhancement(
                id=uuid.uuid4(),
                source=annotation.source,
                visibility=annotation.visibility,
                content=annotation.content,
                reference_id=uuid.uuid4(),
            )
        ]

        delta_identifiers, delta_enhancements = base_reference.merge(incoming)

        assert len(delta_identifiers) == 0
        assert len(delta_enhancements) == 0
        assert len(base_reference.enhancements) == 2

    async def test_merge_reference_with_duplicate_identifiers(
        self, base_reference, doi_identifier
    ):
        """Test merging a reference with duplicate identifiers is handled correctly."""
        incoming = Reference(id=uuid.uuid4())
        incoming.enhancements = []
        incoming.identifiers = [
            LinkedExternalIdentifier(
                id=uuid.uuid4(),
                identifier=doi_identifier.identifier,
                reference_id=uuid.uuid4(),
            )
        ]

        delta_identifiers, delta_enhancements = base_reference.merge(incoming)

        assert len(delta_identifiers) == 0
        assert len(delta_enhancements) == 0
        assert len(base_reference.identifiers) == 1

    async def test_merge_reference_with_clashing_unique_identifiers(
        self, base_reference, pmid_identifier, openalex_identifier
    ):
        """Test merging references with clashing unique identifiers raises an error."""
        base_reference.identifiers.append(pmid_identifier)

        incoming = Reference(id=uuid.uuid4())
        incoming.enhancements = []

        different_pmid = destiny_sdk.identifiers.PubMedIdentifier(
            identifier=5678, identifier_type="pm_id"
        )
        incoming.identifiers = [
            LinkedExternalIdentifier(
                id=uuid.uuid4(),
                identifier=different_pmid,
                reference_id=uuid.uuid4(),
            )
        ]

        with pytest.raises(UnresolvableReferenceDuplicateError):
            base_reference.merge(incoming)

    async def test_merge_different_unique_identifier_types(
        self, base_reference, pmid_identifier, openalex_identifier
    ):
        """Test merging references with different unique identifier types is allowed."""
        base_reference.identifiers.append(pmid_identifier)

        incoming = Reference(id=uuid.uuid4())
        incoming.enhancements = []
        incoming.identifiers = [openalex_identifier]

        delta_identifiers, delta_enhancements = base_reference.merge(incoming)

        assert len(delta_identifiers) == 1
        assert len(base_reference.identifiers) == 3
