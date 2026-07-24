"""Tests for ReferenceAntiCorruptionService."""

import datetime
from unittest.mock import AsyncMock
from uuid import uuid7

import destiny_sdk
import pytest
from destiny_sdk.enhancements import AbstractProcessType
from destiny_sdk.visibility import Visibility
from pydantic import HttpUrl

from app.domain.references.models.models import (
    EnhancementRequest,
    EnhancementRequestSearchStatus,
    EnhancementRequestStatus,
    EnhancementType,
    FullTextEnhancement,
    PendingEnhancementStatus,
    SearchQuery,
)
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)
from app.persistence.blob.models import BlobSignedUrlType
from tests.factories import (
    AbstractContentEnhancementFactory,
    EnhancementFactory,
    FullTextEnhancementFactory,
)


class TestEnhancementFromSdk:
    """Tests for enhancement_from_sdk translation."""

    @pytest.fixture
    def service(self):
        return ReferenceAntiCorruptionService(sign_url=AsyncMock())

    @pytest.fixture
    def sdk_enhancement(self):
        return destiny_sdk.enhancements.Enhancement(
            reference_id=uuid7(),
            source="test-source",
            visibility=Visibility.PUBLIC,
            content=destiny_sdk.enhancements.AbstractContentEnhancement(
                process=AbstractProcessType.OTHER,
                abstract="Test abstract content.",
            ),
            created_at=datetime.datetime.now(datetime.UTC),
        )

    def test_created_at_is_stripped(self, service, sdk_enhancement):
        """SDK-provided created_at should be ignored during translation."""
        domain_enhancement = service.enhancement_from_sdk(sdk_enhancement)

        assert domain_enhancement.created_at is None


class TestFullTextEnhancementToSdk:
    """Tests for the domain to SDK signing path on full-text enhancements."""

    async def test_signs_blob_and_propagates_url(self):
        signed = HttpUrl("https://example.com/signed.pdf?sig=abc")
        sign_url = AsyncMock(return_value=signed)
        service = ReferenceAntiCorruptionService(sign_url=sign_url)

        full_text = FullTextEnhancementFactory.build()
        enhancement = EnhancementFactory.build(content=full_text)

        sdk_enhancement = await service.enhancement_to_sdk(enhancement)

        sign_url.assert_awaited_once_with(full_text.blob, BlobSignedUrlType.DOWNLOAD)
        assert isinstance(
            sdk_enhancement.content, destiny_sdk.enhancements.FullTextEnhancement
        )
        assert sdk_enhancement.content.file_url == signed
        # Other fields round-trip from the domain object.
        assert sdk_enhancement.content.mime_type == full_text.mime_type
        assert sdk_enhancement.content.sha256_checksum == full_text.sha256_checksum

    async def test_non_full_text_does_not_call_signer(self):
        sign_url = AsyncMock()
        service = ReferenceAntiCorruptionService(sign_url=sign_url)

        enhancement = EnhancementFactory.build(
            content=AbstractContentEnhancementFactory.build()
        )

        await service.enhancement_to_sdk(enhancement)

        sign_url.assert_not_awaited()


class TestFullTextEnhancementFromSdk:
    """Tests for the SDK to domain hydration path on full-text enhancements."""

    @pytest.fixture
    def service(self):
        return ReferenceAntiCorruptionService(sign_url=AsyncMock())

    @pytest.fixture
    def sdk_full_text(self):
        return destiny_sdk.enhancements.FullTextEnhancement(
            file_url="https://example.com/papers/foo.pdf",
            byte_size=12345,
            sha256_checksum="a" * 64,
            mime_type="application/pdf",
            version=destiny_sdk.enhancements.DriverVersion.PUBLISHED_VERSION,
            is_oa=True,
            license="cc-by",
            source="openalex",
            source_url="https://example.com/source",
            retrieved_at=datetime.datetime.now(datetime.UTC),
        )

    def test_content_from_sdk_hydrates_with_full_metadata(self, service, sdk_full_text):
        """Remote blob hydrates from URL, all metadata preserved."""
        domain_ft = service.full_text_enhancement_content_from_sdk(sdk_full_text)

        assert isinstance(domain_ft, FullTextEnhancement)
        assert domain_ft.blob.is_remote
        assert domain_ft.blob.to_uri() == str(sdk_full_text.file_url)
        assert domain_ft.byte_size == sdk_full_text.byte_size
        assert domain_ft.sha256_checksum == sdk_full_text.sha256_checksum
        assert domain_ft.mime_type == sdk_full_text.mime_type
        assert domain_ft.version == sdk_full_text.version
        assert domain_ft.is_oa == sdk_full_text.is_oa
        assert domain_ft.license == sdk_full_text.license
        assert domain_ft.source == sdk_full_text.source
        assert str(domain_ft.source_url) == str(sdk_full_text.source_url)
        assert domain_ft.retrieved_at == sdk_full_text.retrieved_at

    def test_reference_from_sdk_file_input_routes_through_hydration(
        self, service, sdk_full_text
    ):
        """The file-input path runs FT content through the hydration codepath."""
        reference = service.reference_from_sdk_file_input(
            destiny_sdk.references.ReferenceFileInput(
                visibility=Visibility.PUBLIC,
                identifiers=[
                    destiny_sdk.identifiers.DOIIdentifier(identifier="10.1000/xyz"),
                ],
                enhancements=[
                    destiny_sdk.enhancements.EnhancementFileInput(
                        source="test-source",
                        visibility=Visibility.PUBLIC,
                        content=sdk_full_text,
                    ),
                ],
            )
        )

        domain_ft = reference.enhancements[0].content
        assert isinstance(domain_ft, FullTextEnhancement)
        assert domain_ft.enhancement_type == EnhancementType.FULL_TEXT
        assert domain_ft.blob.is_remote
        assert domain_ft.blob.to_uri() == str(sdk_full_text.file_url)


def _mojibake(value: str) -> str:
    """Reproduce the legacy import bug: UTF-8 bytes misdecoded as latin-1."""
    return value.encode("utf-8").decode("latin-1")


_CLEAN_TITLE = "Teachers’ training"  # noqa: RUF001
_CLEAN_DESCRIPTION = "Détails de l’étude"  # noqa: RUF001
_CLEAN_SUPPORTING = "supporting ’text’"  # noqa: RUF001


class TestEnhancementToSdkDemojibake:
    """Legacy import mojibake is repaired for display at the ACS seam (#781)."""

    @pytest.fixture
    def service(self):
        return ReferenceAntiCorruptionService(sign_url=AsyncMock())

    async def test_repairs_bibliographic_display_text(self, service):
        content = destiny_sdk.enhancements.BibliographicMetadataEnhancement(
            title=_mojibake(_CLEAN_TITLE),
            publisher=_mojibake("Éditeur Universitaire"),
            authorship=[
                destiny_sdk.enhancements.Authorship(
                    display_name=_mojibake("José Peña"),
                    position=destiny_sdk.enhancements.AuthorPosition.FIRST,
                )
            ],
            publication_venue=destiny_sdk.enhancements.PublicationVenue(
                display_name=_mojibake("Régional Review"),
                host_organization_name=_mojibake("Universität Zürich"),
            ),
        )
        enhancement = EnhancementFactory.build(content=content)

        sdk = await service.enhancement_to_sdk(enhancement)

        assert isinstance(
            sdk.content, destiny_sdk.enhancements.BibliographicMetadataEnhancement
        )
        assert sdk.content.title == _CLEAN_TITLE
        assert sdk.content.publisher == "Éditeur Universitaire"
        assert sdk.content.authorship is not None
        assert sdk.content.authorship[0].display_name == "José Peña"
        assert sdk.content.publication_venue is not None
        assert sdk.content.publication_venue.display_name == "Régional Review"
        assert (
            sdk.content.publication_venue.host_organization_name == "Universität Zürich"
        )

    async def test_repairs_abstract_text(self, service):
        content = destiny_sdk.enhancements.AbstractContentEnhancement(
            process=AbstractProcessType.OTHER,
            abstract=_mojibake("Über die Grénze — a café study"),
        )
        enhancement = EnhancementFactory.build(content=content)

        sdk = await service.enhancement_to_sdk(enhancement)

        assert isinstance(
            sdk.content, destiny_sdk.enhancements.AbstractContentEnhancement
        )
        assert sdk.content.abstract == "Über die Grénze — a café study"

    async def test_repairs_linked_data_literals_but_not_identifiers(self, service):
        # An @id carrying the mojibake byte pattern must survive untouched even
        # though it sits alongside repaired literals.
        unsafe_id = "https://id.example.org/" + _mojibake("Ünsafe")
        content = destiny_sdk.enhancements.LinkedDataEnhancement(
            vocabulary_uri=HttpUrl("https://vocab.example.org/v1"),
            data={
                "@context": "https://vocab.example.org/v1",
                "@id": unsafe_id,
                "name": _mojibake("Klíma"),
                "description": _mojibake(_CLEAN_DESCRIPTION),
                "supportingText": _mojibake(_CLEAN_SUPPORTING),
            },
        )
        enhancement = EnhancementFactory.build(content=content)

        sdk = await service.enhancement_to_sdk(enhancement)

        assert isinstance(sdk.content, destiny_sdk.enhancements.LinkedDataEnhancement)
        assert sdk.content.data["name"] == "Klíma"
        assert sdk.content.data["description"] == _CLEAN_DESCRIPTION
        assert sdk.content.data["supportingText"] == _CLEAN_SUPPORTING
        assert sdk.content.data["@id"] == unsafe_id
        assert sdk.content.data["@context"] == "https://vocab.example.org/v1"


class TestLinkedDataConceptFilterFromQueryParameter:
    """Tests for parsing concept filters from query parameter values."""

    @pytest.fixture
    def service(self) -> ReferenceAntiCorruptionService:
        return ReferenceAntiCorruptionService(sign_url=AsyncMock())

    def test_single_uri(self, service: ReferenceAntiCorruptionService) -> None:
        result = service.linked_data_concept_filter_from_query_parameter(
            "https://vocab.example.org/A",
        )
        assert result.concept_uris == ["https://vocab.example.org/A"]

    def test_comma_separated_uris(
        self, service: ReferenceAntiCorruptionService
    ) -> None:
        result = service.linked_data_concept_filter_from_query_parameter(
            "https://vocab.example.org/A,https://vocab.example.org/B",
        )
        assert result.concept_uris == [
            "https://vocab.example.org/A",
            "https://vocab.example.org/B",
        ]

    def test_trims_whitespace_around_each_uri(
        self, service: ReferenceAntiCorruptionService
    ) -> None:
        # URIs themselves never contain spaces; tolerate stray ones from clients.
        result = service.linked_data_concept_filter_from_query_parameter(
            "  https://vocab.example.org/A , https://vocab.example.org/B  ",
        )
        assert result.concept_uris == [
            "https://vocab.example.org/A",
            "https://vocab.example.org/B",
        ]

    def test_trailing_comma_raises(
        self, service: ReferenceAntiCorruptionService
    ) -> None:
        with pytest.raises(ValueError, match="Empty concept URI"):
            service.linked_data_concept_filter_from_query_parameter(
                "https://vocab.example.org/A,",
            )

    def test_empty_string_raises(self, service: ReferenceAntiCorruptionService) -> None:
        with pytest.raises(ValueError, match="Empty concept URI"):
            service.linked_data_concept_filter_from_query_parameter("")


class TestLinkedDataCountryFilterFromQueryParameter:
    """Tests for parsing country filters from query parameter values."""

    @pytest.fixture
    def service(self) -> ReferenceAntiCorruptionService:
        return ReferenceAntiCorruptionService(sign_url=AsyncMock())

    def test_uppercases_and_splits(
        self, service: ReferenceAntiCorruptionService
    ) -> None:
        result = service.linked_data_country_filter_from_query_parameter("us, gb,fr")
        assert result.country_codes == ["US", "GB", "FR"]

    def test_rejects_non_iso_2_shape(
        self, service: ReferenceAntiCorruptionService
    ) -> None:
        with pytest.raises(ValueError, match=r"should match pattern"):
            service.linked_data_country_filter_from_query_parameter("USA")

    def test_rejects_empty_value(self, service: ReferenceAntiCorruptionService) -> None:
        # Trailing comma → empty fragment fails the [A-Z]{2} pattern check.
        with pytest.raises(ValueError, match=r"should match pattern"):
            service.linked_data_country_filter_from_query_parameter("US,")


class TestLinkedDataCountryWBRegionFilterFromQueryParameter:
    """Tests for parsing WB region filters from query parameter values."""

    @pytest.fixture
    def service(self) -> ReferenceAntiCorruptionService:
        return ReferenceAntiCorruptionService(sign_url=AsyncMock())

    def test_uppercases_and_splits(
        self, service: ReferenceAntiCorruptionService
    ) -> None:
        result = service.linked_data_country_wb_region_filter_from_query_parameter(
            "eas, ecs"
        )
        assert result.region_ids == ["EAS", "ECS"]

    def test_rejects_unknown_region_id(
        self, service: ReferenceAntiCorruptionService
    ) -> None:
        with pytest.raises(ValueError, match=r"Input should be 'EAS'"):
            service.linked_data_country_wb_region_filter_from_query_parameter("XXX")


class TestSearchEnhancementRequest:
    """Tests for the search-based enhancement request conversions."""

    @pytest.fixture
    def service(self) -> ReferenceAntiCorruptionService:
        return ReferenceAntiCorruptionService(sign_url=AsyncMock())

    def test_to_sdk_reports_counts_and_statuses(
        self, service: ReferenceAntiCorruptionService
    ) -> None:
        request = EnhancementRequest(
            id=uuid7(),
            reference_ids=[],
            robot_id=uuid7(),
            request_status=EnhancementRequestStatus.PROCESSING,
            search=SearchQuery(query_string="climate"),
            search_status=EnhancementRequestSearchStatus.SEARCHING,
            n_matched=100,
        )
        read = service.search_enhancement_request_to_sdk(
            request,
            {
                PendingEnhancementStatus.COMPLETED: 3,
                PendingEnhancementStatus.FAILED: 1,
            },
        )
        assert read.id == request.id
        assert (
            read.search_status
            == destiny_sdk.robots.EnhancementRequestSearchStatus.SEARCHING
        )
        assert (
            read.request_status
            == destiny_sdk.robots.EnhancementRequestStatus.PROCESSING
        )
        assert read.n_matched == 100
        assert read.n_enhancements_requested == 4
        assert read.enhancement_status_counts == {"completed": 3, "failed": 1}
