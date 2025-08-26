"""Integration tests for SQL interface."""

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.references.models.models import Enhancement, Reference, Visibility
from app.domain.references.models.sql import (
    Enhancement as SQLEnhancement,
)
from app.domain.references.models.sql import (
    Reference as SQLReference,
)
from app.domain.references.repository import ReferenceSQLRepository


async def test_enhancement_interface(
    session: AsyncSession,
):
    """Test that the enhancement content type is set correctly."""
    reference = SQLReference.from_domain(
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
    sql_enhancement = SQLEnhancement.from_domain(enhancement_in)
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
    enhancement = loaded_enhancement.to_domain()
    assert enhancement == enhancement_in


async def test_reference_merge_and_get_with_duplicates(session: AsyncSession):
    """Test merging and getting references with duplicate relationships."""
    repo = ReferenceSQLRepository(session=session)

    # 1. Create references
    ref_a = Reference(id=uuid.uuid4(), visibility=Visibility.PUBLIC)
    ref_b = Reference(
        id=uuid.uuid4(),
        visibility=Visibility.PUBLIC,
        duplicate_of=ref_a.id,
        canonical_reference=ref_a,
    )
    ref_c = Reference(
        id=uuid.uuid4(),
        visibility=Visibility.PUBLIC,
        duplicate_of=ref_a.id,
        canonical_reference=ref_a,
    )
    ref_d = Reference(
        id=uuid.uuid4(),
        visibility=Visibility.PUBLIC,
        duplicate_of=ref_c.id,
        canonical_reference=ref_c,
    )

    # 2. Add references to the database
    await repo.merge(ref_b)
    await repo.merge(ref_d)

    # 3. Test getting references and their relationships
    preload = ["canonical_reference", "duplicate_references"]

    # Get D and verify its relationships
    retrieved_d = await repo.get_by_pk(ref_d.id, preload=preload)
    assert retrieved_d.duplicate_of == ref_c.id
    assert retrieved_d.canonical_reference is not None
    assert retrieved_d.canonical_reference.id == ref_c.id
    assert not retrieved_d.duplicate_references

    # Verify deep relationships
    assert retrieved_d.canonical_reference.canonical_reference is not None
    assert retrieved_d.canonical_reference.canonical_reference.id == ref_a.id

    # Test merging updates
    # Merging B should update A and B
    ref_b_updated = await repo.get_by_pk(ref_b.id, preload=["canonical_reference"])
    ref_b_updated.visibility = Visibility.HIDDEN
    assert ref_b_updated.canonical_reference
    ref_b_updated.canonical_reference.visibility = Visibility.HIDDEN
    await repo.merge(ref_b_updated)
    retrieved_b_after_merge = await repo.get_by_pk(ref_b.id)
    assert retrieved_b_after_merge.visibility == Visibility.HIDDEN
    retrieved_a_after_merge = await repo.get_by_pk(ref_a.id)
    assert retrieved_a_after_merge.visibility == Visibility.HIDDEN

    # Merging C should update A and C, but not D
    ref_c_updated = await repo.get_by_pk(ref_c.id, preload=["canonical_reference"])
    ref_c_updated.visibility = Visibility.RESTRICTED
    assert ref_c_updated.canonical_reference
    ref_c_updated.canonical_reference.visibility = Visibility.RESTRICTED
    await repo.merge(ref_c_updated)
    retrieved_c_after_merge = await repo.get_by_pk(ref_c.id)
    assert retrieved_c_after_merge.visibility == Visibility.RESTRICTED
    retrieved_a_after_c_merge = await repo.get_by_pk(ref_a.id)
    assert retrieved_a_after_c_merge.visibility == Visibility.RESTRICTED

    # Merging D should update A, C, and D
    ref_d_updated = await repo.get_by_pk(ref_d.id, preload=["canonical_reference"])
    ref_d_updated.visibility = Visibility.HIDDEN
    assert ref_d_updated.canonical_reference
    ref_d_updated.canonical_reference.visibility = Visibility.HIDDEN
    assert ref_d_updated.canonical_reference.canonical_reference
    ref_d_updated.canonical_reference.canonical_reference.visibility = Visibility.HIDDEN
    await repo.merge(ref_d_updated)
    retrieved_d_after_merge = await repo.get_by_pk(ref_d.id)
    assert retrieved_d_after_merge.visibility == Visibility.HIDDEN
    retrieved_c_after_d_merge = await repo.get_by_pk(ref_c.id)
    assert retrieved_c_after_d_merge.visibility == Visibility.HIDDEN
    retrieved_a_after_d_merge = await repo.get_by_pk(ref_a.id)
    assert retrieved_a_after_d_merge.visibility == Visibility.HIDDEN
