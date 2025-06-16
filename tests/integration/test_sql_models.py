"""Integration tests for SQL interface."""

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.references.models.models import Enhancement, Reference
from app.domain.references.models.sql import (
    Enhancement as SQLEnhancement,
)
from app.domain.references.models.sql import (
    Reference as SQLReference,
)


async def test_enhancement_interface(
    session: AsyncSession,
):
    """Test that the enhancement content type is set correctly."""
    reference = await SQLReference.from_domain(
        Reference(
            id=uuid.uuid4(),
        )
    )
    session.add(reference)
    enhancement_in = Enhancement(
        id=uuid.uuid4(),
        source="dummy",
        reference_id=reference.id,
        visibility="public",
        content={
            "enhancement_type": "annotation",
            "annotations": [
                {
                    "annotation_type": "boolean",
                    "scheme": "openalex:topic",
                    "value": True,
                    "label": "test_label",
                    "data": {"foo": "bar"},
                }
            ],
        },
    )
    sql_enhancement = await SQLEnhancement.from_domain(enhancement_in)
    session.add(sql_enhancement)
    await session.commit()

    # Check that we can query the JSONB content in psql
    result = await session.execute(
        text(
            """
            SELECT content->'enhancement_type' AS enhancement_type
            FROM enhancement
            WHERE id = :enhancement_id
            """
        ),
        {"enhancement_id": str(sql_enhancement.id)},
    )
    enhancement_type = result.scalar_one_or_none()
    assert enhancement_type == "annotation"

    # Check that the enhancement can be loaded from the database
    loaded_enhancement = await session.get(
        SQLEnhancement,
        sql_enhancement.id,
    )
    assert loaded_enhancement
    enhancement = await loaded_enhancement.to_domain()
    assert enhancement == enhancement_in
