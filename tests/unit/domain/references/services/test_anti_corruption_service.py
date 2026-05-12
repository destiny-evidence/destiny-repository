"""Tests for ReferenceAntiCorruptionService."""

import datetime
from unittest.mock import AsyncMock
from uuid import uuid7

import destiny_sdk
import pytest
from destiny_sdk.enhancements import AbstractProcessType
from destiny_sdk.visibility import Visibility
from pydantic import HttpUrl

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
