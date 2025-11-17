import datetime
import time
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.references.models.models import (
    GenericExternalIdentifier,
    PendingEnhancement,
    PendingEnhancementStatus,
)
from app.domain.references.models.sql import ExternalIdentifier as SQLExternalIdentifier
from app.domain.references.models.sql import (
    PendingEnhancement as SQLPendingEnhancement,
)
from app.domain.references.models.sql import Reference as SQLReference
from app.domain.references.repository import (
    PendingEnhancementSQLRepository,
    ReferenceSQLRepository,
)
from app.utils.time_and_date import utc_now
from tests.factories import ReferenceFactory


async def create_reference_with_identifiers(session: AsyncSession, identifiers):
    reference = ReferenceFactory.build()
    sql_reference = SQLReference.from_domain(reference)
    session.add(sql_reference)
    await session.flush()
    sql_identifiers = []
    for identifier in identifiers:
        sql_identifier = SQLExternalIdentifier(
            reference_id=sql_reference.id,
            identifier_type=identifier.identifier_type,
            identifier=identifier.identifier,
            other_identifier_name=identifier.other_identifier_name,
        )
        session.add(sql_identifier)
        sql_identifiers.append(sql_identifier)
    await session.commit()
    return sql_reference, sql_identifiers


class TestReferenceSQLRepository:
    async def test_find_with_identifiers_empty(self, session: AsyncSession):
        repo = ReferenceSQLRepository(session)
        result = await repo.find_with_identifiers([])
        assert result == []

    async def test_find_with_identifiers_single_match_all(self, session: AsyncSession):
        repo = ReferenceSQLRepository(session)
        identifier = GenericExternalIdentifier(
            identifier_type="doi",
            identifier="10.1000/abc123",
            other_identifier_name=None,
        )
        ref, _ = await create_reference_with_identifiers(session, [identifier])
        result = await repo.find_with_identifiers([identifier], match="all")
        assert any(r.id == ref.id for r in result)

    async def test_find_with_identifiers_multiple_match_all(
        self, session: AsyncSession
    ):
        repo = ReferenceSQLRepository(session)
        id1 = GenericExternalIdentifier(
            identifier_type="doi",
            identifier="10.1000/abc123",
            other_identifier_name=None,
        )
        id2 = GenericExternalIdentifier(
            identifier_type="pm_id",
            identifier="123456",
            other_identifier_name=None,
        )
        ref, _ = await create_reference_with_identifiers(session, [id1, id2])
        # Add another reference with only one identifier
        await create_reference_with_identifiers(session, [id1])
        result = await repo.find_with_identifiers([id1, id2], match="all")
        assert len(result) == 1
        assert result[0].id == ref.id

    async def test_find_with_identifiers_multiple_match_any(
        self, session: AsyncSession
    ):
        repo = ReferenceSQLRepository(session)
        id1 = GenericExternalIdentifier(
            identifier_type="doi",
            identifier="10.1000/abc123",
            other_identifier_name=None,
        )
        id2 = GenericExternalIdentifier(
            identifier_type="pm_id",
            identifier="123456",
            other_identifier_name=None,
        )
        ref1, _ = await create_reference_with_identifiers(session, [id1])
        ref2, _ = await create_reference_with_identifiers(session, [id2])
        result = await repo.find_with_identifiers([id1, id2], match="any")
        returned_ids = {r.id for r in result}
        assert ref1.id in returned_ids
        assert ref2.id in returned_ids

    async def test_find_with_identifiers_preload(self, session: AsyncSession):
        repo = ReferenceSQLRepository(session)
        identifier = GenericExternalIdentifier(
            identifier_type="doi",
            identifier="10.1000/abc123",
            other_identifier_name=None,
        )
        ref, _ = await create_reference_with_identifiers(session, [identifier])
        result = await repo.find_with_identifiers([identifier], preload=["identifiers"])
        assert any(r.id == ref.id for r in result)
        # Check that identifiers are loaded
        assert hasattr(result[0], "identifiers")
        assert result[0].identifiers is not None

    @pytest.mark.skip(
        "Long-running performance test - not suitable for regular test runs"
    )
    async def test_find_with_identifiers_performance(self, session: AsyncSession):
        """Test performance of find_with_identifiers with a large dataset."""
        repo = ReferenceSQLRepository(session)

        references = ReferenceFactory.build_batch(100000)
        session.add_all([SQLReference.from_domain(ref) for ref in references])
        await session.commit()

        test_identifiers = [
            GenericExternalIdentifier.from_specific(
                references[0].identifiers[0].identifier
            ),
            GenericExternalIdentifier.from_specific(
                references[50].identifiers[0].identifier
            ),
        ]

        for match, expected_count in [("any", 2), ("all", 0)]:
            # Time the query
            start_time = time.perf_counter()
            result = await repo.find_with_identifiers(
                test_identifiers,
                match=match,  # type:ignore[arg-type]
            )
            end_time = time.perf_counter()

            execution_time = end_time - start_time

            assert len(result) == expected_count

            assert (
                execution_time < 0.1
            ), f"Query took {execution_time:.4f}s, expected < 0.1s"


class TestPendingEnhancementSQLRepository:
    async def test_count_retry_depth_no_retries(
        self, session: AsyncSession, created_reference, created_robot
    ):
        """Test counting retry depth for a pending enhancement with no retries."""
        repo = PendingEnhancementSQLRepository(session)

        # Create a pending enhancement with no retries
        pe = PendingEnhancement(
            id=uuid.uuid4(),
            reference_id=created_reference.id,
            robot_id=created_robot.id,
            source="test",
            status=PendingEnhancementStatus.PENDING,
            expires_at=utc_now() + datetime.timedelta(hours=1),
        )
        sql_pe = SQLPendingEnhancement.from_domain(pe)
        session.add(sql_pe)
        await session.commit()

        depth = await repo.count_retry_depth(pe.id)
        assert depth == 0

    async def test_count_retry_depth_with_retries(
        self, session: AsyncSession, created_reference, created_robot
    ):
        """Test counting retry depth for a chain of retries."""
        repo = PendingEnhancementSQLRepository(session)

        # Create a chain: pe1 <- pe2 <- pe3
        pe1 = PendingEnhancement(
            id=uuid.uuid4(),
            reference_id=created_reference.id,
            robot_id=created_robot.id,
            source="test",
            status=PendingEnhancementStatus.EXPIRED,
            expires_at=utc_now() - datetime.timedelta(hours=1),
        )
        pe2 = PendingEnhancement(
            id=uuid.uuid4(),
            reference_id=pe1.reference_id,
            robot_id=pe1.robot_id,
            source="test",
            status=PendingEnhancementStatus.EXPIRED,
            expires_at=utc_now() - datetime.timedelta(minutes=30),
            retry_of=pe1.id,
        )
        pe3 = PendingEnhancement(
            id=uuid.uuid4(),
            reference_id=pe1.reference_id,
            robot_id=pe1.robot_id,
            source="test",
            status=PendingEnhancementStatus.PENDING,
            expires_at=utc_now() + datetime.timedelta(hours=1),
            retry_of=pe2.id,
        )

        for pe in [pe1, pe2, pe3]:
            sql_pe = SQLPendingEnhancement.from_domain(pe)
            session.add(sql_pe)
        await session.commit()

        assert await repo.count_retry_depth(pe1.id) == 0
        assert await repo.count_retry_depth(pe2.id) == 1
        assert await repo.count_retry_depth(pe3.id) == 2

    async def test_expire_pending_enhancements_past_expiry(
        self, session: AsyncSession, created_reference, created_robot
    ):
        """Test expiring pending enhancements."""
        repo = PendingEnhancementSQLRepository(session)

        expired_pe = PendingEnhancement(
            id=uuid.uuid4(),
            reference_id=created_reference.id,
            robot_id=created_robot.id,
            source="test",
            status=PendingEnhancementStatus.PROCESSING,
            expires_at=utc_now() - datetime.timedelta(minutes=5),
        )

        non_expired_pe = PendingEnhancement(
            id=uuid.uuid4(),
            reference_id=created_reference.id,
            robot_id=created_robot.id,
            source="test",
            status=PendingEnhancementStatus.PROCESSING,
            expires_at=utc_now() + datetime.timedelta(hours=1),
        )

        for pe in [expired_pe, non_expired_pe]:
            sql_pe = SQLPendingEnhancement.from_domain(pe)
            session.add(sql_pe)
        await session.commit()

        result = await repo.expire_pending_enhancements_past_expiry(
            now=utc_now(),
            statuses=[PendingEnhancementStatus.PROCESSING],
        )

        # Should only return and update the expired one
        assert len(result) == 1
        assert result[0].id == expired_pe.id
        assert result[0].status == PendingEnhancementStatus.EXPIRED

        # Verify database was updated
        updated_expired = await repo.get_by_pk(expired_pe.id)
        assert updated_expired.status == PendingEnhancementStatus.EXPIRED

        # Verify non-expired is still PROCESSING
        non_expired = await repo.get_by_pk(non_expired_pe.id)
        assert non_expired.status == PendingEnhancementStatus.PROCESSING
