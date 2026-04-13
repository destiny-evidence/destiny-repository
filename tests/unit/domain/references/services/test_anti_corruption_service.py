"""Tests for ReferenceAntiCorruptionService."""

import datetime
from unittest.mock import MagicMock
from uuid import uuid7

import destiny_sdk
import pytest
from destiny_sdk.enhancements import AbstractProcessType
from destiny_sdk.visibility import Visibility

from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)


class TestEnhancementFromSdk:
    """Tests for enhancement_from_sdk translation."""

    @pytest.fixture
    def service(self):
        return ReferenceAntiCorruptionService(blob_repository=MagicMock())

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
