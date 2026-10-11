"""Integration tests for SQL interface."""

import datetime
from uuid import uuid7

import pytest
from destiny_sdk.imports import ImportRecordStatus
from destiny_sdk.visibility import Visibility
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import SQLIntegrityError
from app.domain.imports.models.models import (
    ImportBatchStatus,
    ImportResultStatus,
)
from app.domain.imports.models.sql import (
    ImportBatch,
    ImportRecord,
    ImportResult,
)
from app.domain.imports.repository import (
    ImportBatchSQLRepository,
    ImportRecordSQLRepository,
    ImportResultSQLRepository,
)
from app.domain.references.models.models import (
    DuplicateDetermination,
    Enhancement,
    EnhancementRequest,
    EnhancementRequestSearchStatus,
    EnhancementRequestStatus,
    PendingEnhancement,
    PendingEnhancementStatus,
    Reference,
    ReferenceDuplicateDecision,
    SearchQuery,
)
from app.domain.references.models.sql import (
    Enhancement as SQLEnhancement,
)
from app.domain.references.models.sql import (
    EnhancementRequest as SQLEnhancementRequest,
)
from app.domain.references.models.sql import (
    PendingEnhancement as SQLPendingEnhancement,
)
from app.domain.references.models.sql import (
    Reference as SQLReference,
)
from app.domain.references.repository import (
    EnhancementRequestSQLRepository,
    EnhancementSQLRepository,
    PendingEnhancementSQLRepository,
    ReferenceDuplicateDecisionSQLRepository,
    ReferenceSQLRepository,
)
from app.domain.robots.models.models import Robot
from app.domain.robots.models.sql import Robot as SQLRobot
from tests.factories import AbstractContentEnhancementFactory, EnhancementFactory


async def test_enhancement_interface(
    session: AsyncSession,
):
    """Test that enhancements are correctly persisted to the database."""
    reference = SQLReference.from_domain(
        Reference(
            id=uuid7(),
        )
    )
    session.add(reference)
    enhancement_in = Enhancement(
        id=uuid7(),
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

    # Check that expected fields are the same
    assert enhancement.id == enhancement_in.id
    assert enhancement.source == enhancement_in.source
    assert enhancement.reference_id == enhancement_in.reference_id
    assert enhancement.visibility == enhancement_in.visibility
    assert enhancement.content == enhancement_in.content

    # Assert the created_at and updated_at timestamps have been returned
    # from the database
    assert isinstance(enhancement.created_at, datetime.datetime)
    assert isinstance(enhancement.updated_at, datetime.datetime)


async def _add_reference(session: AsyncSession) -> Reference:
    reference = Reference(id=uuid7())
    session.add(SQLReference.from_domain(reference))
    await session.commit()
    return reference


def _enhancement(reference: Reference, **kwargs: object) -> Enhancement:
    return EnhancementFactory.build(
        reference_id=reference.id,
        content=AbstractContentEnhancementFactory.build(),
        **kwargs,
    )


async def test_enhancement_supersession_chain_head(session: AsyncSession):
    """The head of a chain is its newest successor, or the root without one."""
    reference = await _add_reference(session)
    repo = EnhancementSQLRepository(session)
    lone_root = await repo.add(_enhancement(reference))
    root = await repo.add(_enhancement(reference))
    first = await repo.add(_enhancement(reference, supersedes=root.id, root_id=root.id))
    second = await repo.add(
        _enhancement(reference, supersedes=first.id, root_id=root.id)
    )
    await session.commit()

    head_query = text(
        """
        SELECT COALESCE(
            (SELECT id FROM enhancement
             WHERE root_id = :root AND supersedes IS NOT NULL
             ORDER BY id DESC LIMIT 1),
            :root
        )
        """
    )
    head = await session.execute(head_query, {"root": root.id})
    assert head.scalar_one() == second.id
    lone_head = await session.execute(head_query, {"root": lone_root.id})
    assert lone_head.scalar_one() == lone_root.id

    assert root.root_id == root.id
    assert second.root_id == root.id


async def test_enhancement_supersedes_must_exist(session: AsyncSession):
    """A successor cannot supersede an enhancement that does not exist."""
    reference = await _add_reference(session)
    repo = EnhancementSQLRepository(session)
    root = await repo.add(_enhancement(reference))
    await session.commit()

    with pytest.raises(SQLIntegrityError) as exc_info:
        await repo.add(_enhancement(reference, supersedes=uuid7(), root_id=root.id))
    assert "fk_enhancement_supersedes" in str(exc_info.value.__cause__)
    await session.rollback()


async def test_enhancement_successor_id_must_follow_predecessor(
    session: AsyncSession,
):
    """A non-first successor must have an id greater than its predecessor's."""
    reference = await _add_reference(session)
    repo = EnhancementSQLRepository(session)
    early_id = uuid7()
    root = await repo.add(_enhancement(reference))
    first = await repo.add(_enhancement(reference, supersedes=root.id, root_id=root.id))
    await session.commit()

    with pytest.raises(SQLIntegrityError) as exc_info:
        await repo.add(
            _enhancement(reference, id=early_id, supersedes=first.id, root_id=root.id)
        )
    assert "ck_enhancement_supersedes_order" in str(exc_info.value.__cause__)
    await session.rollback()


async def test_enhancement_first_successor_may_precede_root(session: AsyncSession):
    """A first successor passes the ordering check even with an id below its root."""
    reference = await _add_reference(session)
    repo = EnhancementSQLRepository(session)
    early_id = uuid7()
    root = await repo.add(_enhancement(reference))

    first = await repo.add(
        _enhancement(reference, id=early_id, supersedes=root.id, root_id=root.id)
    )
    await session.commit()

    assert first.id < root.id


async def test_enhancement_cannot_supersede_itself(session: AsyncSession):
    """An enhancement cannot supersede itself within another root's chain."""
    reference = await _add_reference(session)
    repo = EnhancementSQLRepository(session)
    root = await repo.add(_enhancement(reference))
    await session.commit()
    self_id = uuid7()

    with pytest.raises(SQLIntegrityError) as exc_info:
        await repo.add(
            _enhancement(reference, id=self_id, supersedes=self_id, root_id=root.id)
        )
    assert "ck_enhancement_supersedes_order" in str(exc_info.value.__cause__)
    await session.rollback()


async def test_enhancement_successor_cannot_be_its_own_root(session: AsyncSession):
    """A successor cannot name itself as the root of its chain."""
    reference = await _add_reference(session)
    repo = EnhancementSQLRepository(session)
    root = await repo.add(_enhancement(reference))
    await session.commit()
    successor = _enhancement(reference, supersedes=root.id)
    successor.root_id = successor.id

    with pytest.raises(SQLIntegrityError) as exc_info:
        await repo.add(successor)
    assert "ck_enhancement_supersedes_root_id" in str(exc_info.value.__cause__)
    await session.rollback()


async def test_enhancement_non_root_must_supersede(session: AsyncSession):
    """An enhancement whose root_id is not its own id must set supersedes."""
    reference = await _add_reference(session)
    repo = EnhancementSQLRepository(session)
    root = await repo.add(_enhancement(reference))
    await session.commit()

    with pytest.raises(SQLIntegrityError) as exc_info:
        await repo.add(_enhancement(reference, root_id=root.id))
    assert "ck_enhancement_supersedes_root_id" in str(exc_info.value.__cause__)
    await session.rollback()


async def test_reference_get_with_duplicates(session: AsyncSession):
    """Test merging and getting references with duplicate relationships."""
    repo = ReferenceSQLRepository(session=session)
    dup_repo = ReferenceDuplicateDecisionSQLRepository(session=session)

    # 1. Create references
    ref_a = Reference(id=uuid7(), visibility=Visibility.PUBLIC)
    ref_b = Reference(id=uuid7(), visibility=Visibility.PUBLIC)
    ref_c = Reference(id=uuid7(), visibility=Visibility.PUBLIC)
    a_is_canonical = ReferenceDuplicateDecision(
        id=uuid7(),
        duplicate_determination=DuplicateDetermination.CANONICAL,
        reference_id=ref_a.id,
        active_decision=True,
    )
    b_duplicates_a = ReferenceDuplicateDecision(
        id=uuid7(),
        duplicate_determination=DuplicateDetermination.DUPLICATE,
        reference_id=ref_b.id,
        active_decision=True,
        canonical_reference_id=ref_a.id,
    )
    c_duplicates_a = ReferenceDuplicateDecision(
        id=uuid7(),
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
        await dup_repo.add(a_is_canonical.model_copy(update={"id": uuid7()}))
    await session.rollback()

    await dup_repo.add(
        a_is_canonical.model_copy(
            update={
                "id": uuid7(),
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
        duplicate_determination=DuplicateDetermination.UNSEARCHABLE,
        canonical_reference_id=None,
    )
    assert (
        await repo.get_by_pk(ref_b.id, preload=["canonical_reference"])
    ).canonical_reference is None

    await dup_repo.update_by_pk(c_duplicates_a.id, active_decision=False)


@pytest.mark.parametrize(
    ("result_statuses", "expected_status"),
    [
        ([], ImportBatchStatus.CREATED),
        ([ImportResultStatus.CREATED], ImportBatchStatus.CREATED),
        ([ImportResultStatus.STARTED], ImportBatchStatus.STARTED),
        (
            [
                ImportResultStatus.FAILED,
                ImportResultStatus.FAILED,
                ImportResultStatus.FAILED,
                ImportResultStatus.FAILED,
                ImportResultStatus.FAILED,
                ImportResultStatus.FAILED,
                ImportResultStatus.FAILED,
            ],
            ImportBatchStatus.FAILED,
        ),
        ([ImportResultStatus.COMPLETED], ImportBatchStatus.COMPLETED),
        (
            [ImportResultStatus.STARTED, ImportResultStatus.COMPLETED],
            ImportBatchStatus.STARTED,
        ),
        (
            [ImportResultStatus.FAILED, ImportResultStatus.COMPLETED],
            ImportBatchStatus.PARTIALLY_FAILED,
        ),
        (
            [ImportResultStatus.PARTIALLY_FAILED, ImportResultStatus.COMPLETED],
            ImportBatchStatus.PARTIALLY_FAILED,
        ),
    ],
)
async def test_import_batch_status_projection(
    session: AsyncSession,
    result_statuses: list[ImportResultStatus],
    expected_status: ImportBatchStatus,
):
    """Test ImportBatch status projection logic."""
    record_id = uuid7()
    record = ImportRecord(
        id=record_id,
        searched_at=datetime.datetime.now(tz=datetime.UTC),
        processor_name="test",
        processor_version="1.0",
        status=ImportRecordStatus.STARTED,
        expected_reference_count=-1,
        source_name="test",
    )
    session.add(record)
    batch_id = uuid7()
    batch = ImportBatch(
        id=batch_id,
        import_record_id=record_id,
        storage_url="https://example.com/bucket",
    )
    session.add(batch)
    for status in result_statuses:
        result = ImportResult(
            id=uuid7(),
            import_batch_id=batch_id,
            status=status,
            reference_id=None,
            failure_details=None,
        )
        session.add(result)
    await session.flush()
    await session.commit()

    repo = ImportBatchSQLRepository(session, ImportResultSQLRepository(session))
    assert (
        await repo.get_by_pk(batch_id, preload=["status"])
    ).status == expected_status


@pytest.mark.parametrize(
    ("pending_statuses", "expected_status"),
    [
        ([], None),  # No pending enhancements -> keep original status
        ([PendingEnhancementStatus.PENDING], EnhancementRequestStatus.RECEIVED),
        (
            [PendingEnhancementStatus.PROCESSING],
            EnhancementRequestStatus.PROCESSING,
        ),
        (
            [PendingEnhancementStatus.IMPORTING],
            EnhancementRequestStatus.PROCESSING,
        ),
        (
            [PendingEnhancementStatus.INDEXING],
            EnhancementRequestStatus.PROCESSING,
        ),
        (
            [PendingEnhancementStatus.COMPLETED],
            EnhancementRequestStatus.COMPLETED,
        ),
        (
            [PendingEnhancementStatus.FAILED],
            EnhancementRequestStatus.FAILED,
        ),
        (
            [
                PendingEnhancementStatus.COMPLETED,
                PendingEnhancementStatus.FAILED,
            ],
            EnhancementRequestStatus.PARTIAL_FAILED,
        ),
        (
            [
                PendingEnhancementStatus.COMPLETED,
                PendingEnhancementStatus.INDEXING_FAILED,
            ],
            EnhancementRequestStatus.PARTIAL_FAILED,
        ),
        (
            [
                PendingEnhancementStatus.FAILED,
                PendingEnhancementStatus.INDEXING_FAILED,
            ],
            EnhancementRequestStatus.PARTIAL_FAILED,
        ),
        (
            [
                PendingEnhancementStatus.PENDING,
                PendingEnhancementStatus.PROCESSING,
            ],
            EnhancementRequestStatus.PROCESSING,
        ),
        (
            [
                PendingEnhancementStatus.COMPLETED,
                PendingEnhancementStatus.IMPORTING,
            ],
            EnhancementRequestStatus.PROCESSING,
        ),
        (
            [
                PendingEnhancementStatus.PENDING,
                PendingEnhancementStatus.INDEXING_FAILED,
            ],
            EnhancementRequestStatus.PROCESSING,
        ),
    ],
)
async def test_enhancement_request_status_projection(
    session: AsyncSession,
    pending_statuses: list[PendingEnhancementStatus],
    expected_status: EnhancementRequestStatus | None,
):
    """Test EnhancementRequest status projection logic."""
    # A request holds at most one original pending enhancement per reference,
    # so give each pending enhancement its own reference. The status projection
    # aggregates over the request's pending enhancements regardless of which
    # reference they belong to.
    references = [
        SQLReference.from_domain(Reference(id=uuid7())) for _ in pending_statuses
    ]
    for reference in references:
        session.add(reference)

    # Create a robot first (required for foreign key constraint)
    robot_id = uuid7()
    robot = SQLRobot.from_domain(
        Robot(
            id=robot_id,
            name="Test Robot",
            description="A test robot",
            owner="test@example.com",
            client_secret="test-secret",
        )
    )
    session.add(robot)

    # Create an enhancement request
    request_id = uuid7()
    enhancement_request = SQLEnhancementRequest.from_domain(
        EnhancementRequest(
            id=request_id,
            reference_ids=[reference.id for reference in references],
            robot_id=robot_id,
            request_status=EnhancementRequestStatus.RECEIVED,
        )
    )
    session.add(enhancement_request)

    # Create pending enhancements with different statuses
    for reference, status in zip(references, pending_statuses, strict=True):
        pending_enhancement = SQLPendingEnhancement.from_domain(
            PendingEnhancement(
                id=uuid7(),
                reference_id=reference.id,
                robot_id=robot_id,
                enhancement_request_id=request_id,
                status=status,
                expires_at=datetime.timedelta(seconds=10),
            )
        )
        session.add(pending_enhancement)

    await session.flush()
    await session.commit()

    # Test the projection logic
    repo = EnhancementRequestSQLRepository(session)
    loaded_request = await repo.get_by_pk(request_id, preload=["status"])

    if expected_status is None:
        # Should keep original status when no pending enhancements
        assert loaded_request.request_status == EnhancementRequestStatus.RECEIVED
    else:
        assert loaded_request.request_status == expected_status


async def test_multiple_import_batch_status_projection(
    session: AsyncSession,
):
    """Test ImportBatch status projection logic for multiple batches."""
    record_id = uuid7()
    record = ImportRecord(
        id=record_id,
        searched_at=datetime.datetime.now(tz=datetime.UTC),
        processor_name="test",
        processor_version="1.0",
        status=ImportRecordStatus.STARTED,
        expected_reference_count=-1,
        source_name="test",
    )
    session.add(record)

    batch1_id = uuid7()
    batch1 = ImportBatch(
        id=batch1_id,
        import_record_id=record_id,
        storage_url="https://example.com/bucket1",
    )
    session.add(batch1)

    batch2_id = uuid7()
    batch2 = ImportBatch(
        id=batch2_id,
        import_record_id=record_id,
        storage_url="https://example.com/bucket2",
    )
    session.add(batch2)

    # Batch 1 results
    session.add_all(
        [
            ImportResult(
                id=uuid7(),
                import_batch_id=batch1_id,
                status=ImportResultStatus.COMPLETED,
                reference_id=None,
                failure_details=None,
            ),
            ImportResult(
                id=uuid7(),
                import_batch_id=batch1_id,
                status=ImportResultStatus.FAILED,
                reference_id=None,
                failure_details=None,
            ),
        ]
    )

    # Batch 2 results
    session.add_all(
        [
            ImportResult(
                id=uuid7(),
                import_batch_id=batch2_id,
                status=ImportResultStatus.STARTED,
                reference_id=None,
                failure_details=None,
            ),
            ImportResult(
                id=uuid7(),
                import_batch_id=batch2_id,
                status=ImportResultStatus.CREATED,
                reference_id=None,
                failure_details=None,
            ),
        ]
    )

    await session.flush()
    await session.commit()

    repo = ImportRecordSQLRepository(
        session, ImportBatchSQLRepository(session, ImportResultSQLRepository(session))
    )
    import_record = await repo.get_by_pk(
        record_id, preload=["batches", "ImportBatch.status"]
    )
    assert {batch.status for batch in (import_record.batches or [])} == {
        ImportBatchStatus.PARTIALLY_FAILED,
        ImportBatchStatus.STARTED,
    }


async def test_add_bulk_ignore_conflicts_deduplicates_originals_and_exempts_retries(
    session: AsyncSession,
):
    """
    The partial unique index dedupes original pending enhancements.

    Uniqueness is enforced per (enhancement_request_id, reference_id) for
    originals, so re-running a search collection creates no duplicates; retries
    (retry_of set) are exempt.
    """
    reference = SQLReference.from_domain(Reference(id=uuid7()))
    session.add(reference)
    robot_id = uuid7()
    session.add(
        SQLRobot.from_domain(
            Robot(
                id=robot_id,
                name="Test Robot",
                description="A test robot",
                owner="test@example.com",
                client_secret="test-secret",
            )
        )
    )
    request_id = uuid7()
    session.add(
        SQLEnhancementRequest.from_domain(
            EnhancementRequest(
                id=request_id,
                reference_ids=[reference.id],
                robot_id=robot_id,
                request_status=EnhancementRequestStatus.RECEIVED,
            )
        )
    )
    await session.flush()
    await session.commit()

    repo = PendingEnhancementSQLRepository(session)
    expires_at = datetime.datetime.now(tz=datetime.UTC) + datetime.timedelta(hours=1)

    original = PendingEnhancement(
        reference_id=reference.id,
        robot_id=robot_id,
        enhancement_request_id=request_id,
        expires_at=expires_at,
    )
    assert await repo.add_bulk_ignore_conflicts([original]) == 1

    # A re-run inserting the same (request, reference) original is skipped.
    duplicate = PendingEnhancement(
        reference_id=reference.id,
        robot_id=robot_id,
        enhancement_request_id=request_id,
        expires_at=expires_at,
    )
    assert await repo.add_bulk_ignore_conflicts([duplicate]) == 0

    # A retry for the same (request, reference) is exempt from the index.
    retry = PendingEnhancement(
        reference_id=reference.id,
        robot_id=robot_id,
        enhancement_request_id=request_id,
        retry_of=original.id,
        expires_at=expires_at,
    )
    assert await repo.add_bulk_ignore_conflicts([retry]) == 1

    await session.commit()
    count = (
        await session.execute(
            text(
                "SELECT count(*) FROM pending_enhancement "
                "WHERE enhancement_request_id = :rid"
            ),
            {"rid": request_id},
        )
    ).scalar_one()
    assert count == 2

    # The Core insert bypasses the ORM's flush-time defaults, so confirm the
    # non-nullable timestamps were stamped rather than left NULL.
    missing_timestamps = (
        await session.execute(
            text(
                "SELECT count(*) FROM pending_enhancement "
                "WHERE enhancement_request_id = :rid "
                "AND (created_at IS NULL OR updated_at IS NULL)"
            ),
            {"rid": request_id},
        )
    ).scalar_one()
    assert missing_timestamps == 0


async def test_add_bulk_ignore_conflicts_skips_references_absent_from_sql(
    session: AsyncSession,
):
    """Pending enhancements for unknown references are dropped, not fatal."""
    reference = SQLReference.from_domain(Reference(id=uuid7()))
    session.add(reference)
    robot_id = uuid7()
    session.add(
        SQLRobot.from_domain(
            Robot(
                id=robot_id,
                name="Test Robot",
                description="A test robot",
                owner="test@example.com",
                client_secret="test-secret",
            )
        )
    )
    request_id = uuid7()
    session.add(
        SQLEnhancementRequest.from_domain(
            EnhancementRequest(
                id=request_id,
                reference_ids=[reference.id],
                robot_id=robot_id,
                request_status=EnhancementRequestStatus.RECEIVED,
            )
        )
    )
    await session.flush()
    await session.commit()

    repo = PendingEnhancementSQLRepository(session)
    expires_at = datetime.datetime.now(tz=datetime.UTC) + datetime.timedelta(hours=1)
    missing_reference_id = uuid7()

    inserted = await repo.add_bulk_ignore_conflicts(
        [
            PendingEnhancement(
                reference_id=reference_id,
                robot_id=robot_id,
                enhancement_request_id=request_id,
                expires_at=expires_at,
            )
            for reference_id in (missing_reference_id, reference.id)
        ]
    )
    await session.commit()

    assert inserted == 1
    persisted = (
        (
            await session.execute(
                text(
                    "SELECT reference_id FROM pending_enhancement "
                    "WHERE enhancement_request_id = :rid"
                ),
                {"rid": request_id},
            )
        )
        .scalars()
        .all()
    )
    assert persisted == [reference.id]

    # Every reference missing means nothing to insert, still not fatal.
    assert (
        await repo.add_bulk_ignore_conflicts(
            [
                PendingEnhancement(
                    reference_id=uuid7(),
                    robot_id=robot_id,
                    enhancement_request_id=request_id,
                    expires_at=expires_at,
                )
            ]
        )
        == 0
    )


async def test_claim_search_request_reentrant_and_respects_terminal(
    session: AsyncSession,
):
    """claim_search_request re-enters from SEARCHING but refuses terminal states."""
    robot_id = uuid7()
    session.add(
        SQLRobot.from_domain(
            Robot(
                id=robot_id,
                name="Test Robot",
                description="A test robot",
                owner="test@example.com",
                client_secret="test-secret",
            )
        )
    )
    request_id = uuid7()
    session.add(
        SQLEnhancementRequest.from_domain(
            EnhancementRequest(
                id=request_id,
                reference_ids=[],
                robot_id=robot_id,
                search=SearchQuery(query_string="climate"),
                search_status=EnhancementRequestSearchStatus.PENDING,
            )
        )
    )
    await session.flush()
    await session.commit()

    repo = EnhancementRequestSQLRepository(session)

    # First claim: PENDING -> SEARCHING.
    assert await repo.claim_search_request(request_id) is True
    assert (
        await repo.get_by_pk(request_id)
    ).search_status == EnhancementRequestSearchStatus.SEARCHING

    # Re-entry: a task redelivered after a crash may reclaim a SEARCHING request.
    assert await repo.claim_search_request(request_id) is True

    # Terminal states are not claimable.
    await repo.update_by_pk(
        request_id, search_status=EnhancementRequestSearchStatus.COMPLETED
    )
    assert await repo.claim_search_request(request_id) is False
