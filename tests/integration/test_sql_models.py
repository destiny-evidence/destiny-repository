"""Integration tests for SQL interface."""

import uuid

import pytest
from destiny_sdk.visibility import Visibility
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import SQLIntegrityError
from app.domain.references.models.models import (
    DuplicateDetermination,
    Enhancement,
    Reference,
    ReferenceDuplicateDecision,
)
from app.domain.references.models.sql import (
    Enhancement as SQLEnhancement,
)
from app.domain.references.models.sql import (
    Reference as SQLReference,
)
from app.domain.references.repository import (
    ReferenceDuplicateDecisionSQLRepository,
    ReferenceSQLRepository,
)


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


async def test_reference_get_with_duplicates(session: AsyncSession):
    """Test merging and getting references with duplicate relationships."""
    repo = ReferenceSQLRepository(session=session)
    dup_repo = ReferenceDuplicateDecisionSQLRepository(session=session)

    # 1. Create references
    ref_a = Reference(id=uuid.uuid4(), visibility=Visibility.PUBLIC)
    ref_b = Reference(id=uuid.uuid4(), visibility=Visibility.PUBLIC)
    ref_c = Reference(id=uuid.uuid4(), visibility=Visibility.PUBLIC)
    a_is_canonical = ReferenceDuplicateDecision(
        id=uuid.uuid4(),
        duplicate_determination=DuplicateDetermination.CANONICAL,
        reference_id=ref_a.id,
        active_decision=True,
    )
    b_duplicates_a = ReferenceDuplicateDecision(
        id=uuid.uuid4(),
        duplicate_determination=DuplicateDetermination.DUPLICATE,
        reference_id=ref_b.id,
        active_decision=True,
        canonical_reference_id=ref_a.id,
    )
    c_duplicates_a = ReferenceDuplicateDecision(
        id=uuid.uuid4(),
        duplicate_determination=DuplicateDetermination.DUPLICATE,
        reference_id=ref_c.id,
        active_decision=True,
        canonical_reference_id=ref_a.id,
    )

    # 2. Add references to the database
    await repo.add(ref_a)
    await repo.add(ref_b)
    await repo.add(ref_c)
    await dup_repo.add(a_is_canonical)
    await dup_repo.add(b_duplicates_a)
    await dup_repo.add(c_duplicates_a)

    await session.commit()

    # 3. Test various gets
    ref_a_w_dupes = await repo.get_by_pk(ref_a.id, preload=["duplicate_references"])
    assert ref_a_w_dupes.duplicate_references
    assert len(ref_a_w_dupes.duplicate_references) == 2
    assert {r.id for r in ref_a_w_dupes.duplicate_references} == {ref_b.id, ref_c.id}

    ref_b_w_canonical = await repo.get_by_pk(ref_b.id, preload=["canonical_reference"])
    assert ref_b_w_canonical.canonical_reference
    assert ref_b_w_canonical.canonical_reference.id == ref_a.id

    ref_c_w_decision = await repo.get_by_pk(ref_c.id, preload=["duplicate_decision"])
    assert ref_c_w_decision.duplicate_decision
    assert ref_c_w_decision.duplicate_decision.id == c_duplicates_a.id

    # In particular this tests we don't recurse infinitely between dup and canon
    ref_a_w_all = await repo.get_by_pk(
        ref_a.id,
        preload=["duplicate_references", "canonical_reference", "duplicate_decision"],
    )
    assert ref_a_w_all.duplicate_references
    assert ref_a_w_all.duplicate_references[0].canonical_reference is None
    assert all(r.duplicate_decision for r in ref_a_w_all.duplicate_references)

    # 4. Test with variants on duplicate decision(s)
    with pytest.raises(SQLIntegrityError):
        await dup_repo.add(a_is_canonical.model_copy(update={"id": uuid.uuid4()}))
    await session.rollback()

    await dup_repo.add(
        a_is_canonical.model_copy(
            update={
                "id": uuid.uuid4(),
                "active_decision": False,
                "canonical_reference_id": ref_c.id,
                "duplicate_determination": DuplicateDetermination.DUPLICATE,
            }
        )
    )
    dd = (
        await repo.get_by_pk(ref_a.id, preload=["duplicate_decision"])
    ).duplicate_decision
    assert dd
    assert dd.duplicate_determination == DuplicateDetermination.CANONICAL
    await dup_repo.update_by_pk(b_duplicates_a.id, active_decision=False)
    assert (
        await repo.get_by_pk(ref_b.id, preload=["canonical_reference"])
    ).canonical_reference is None
    await dup_repo.update_by_pk(
        b_duplicates_a.id,
        active_decision=True,
        duplicate_determination=DuplicateDetermination.UNRESOLVED,
        canonical_reference_id=None,
    )
    assert (
        await repo.get_by_pk(ref_b.id, preload=["canonical_reference"])
    ).canonical_reference is None

    await dup_repo.update_by_pk(c_duplicates_a.id, active_decision=False)
