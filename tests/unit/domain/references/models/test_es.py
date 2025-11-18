"""Tests for our elasticsearch models."""

import destiny_sdk
import pytest

from app.domain.references.models.es import EnhancementDocument
from tests.factories import (
    EnhancementFactory,
)


def test_enhancement_content_clean_raises_runtime_error_if_raw_enhancement():
    raw_enhancement = EnhancementFactory.build(
        content=destiny_sdk.enhancements.RawEnhancement(
            something="we don't want in elasticsearch"
        )
    )

    enhancement_doc = EnhancementDocument.from_domain(raw_enhancement)

    with pytest.raises(RuntimeError, match="raw enhancement"):
        # Force call clean
        enhancement_doc.content.clean()
