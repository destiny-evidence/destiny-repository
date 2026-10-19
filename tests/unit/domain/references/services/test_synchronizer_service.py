"""Unit tests for the reference synchronizer service."""

from collections.abc import AsyncGenerator
from typing import cast
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid7

import pytest

from app.core.exceptions import ProjectionError
from app.domain.references.models.models import (
    DuplicateDetermination,
    LinkedDataProjection,
    Reference,
    ReferenceDuplicateDecision,
)
from app.domain.references.services.synchronizer_service import ReferenceSynchronizer
from tests.factories import (
    BibliographicMetadataEnhancementFactory,
    EnhancementFactory,
    LinkedDataEnhancementFactory,
    ReferenceFactory,
)


def _canonical(reference_id: UUID | None = None) -> Reference:
    """A canonical-like reference."""
    reference_id = reference_id or uuid7()
    return Reference(
        id=reference_id,
        duplicate_decision=ReferenceDuplicateDecision(
            reference_id=reference_id,
            duplicate_determination=DuplicateDetermination.CANONICAL,
            active_decision=True,
        ),
    )


def _duplicate(canonical_id: UUID, reference_id: UUID | None = None) -> Reference:
    """A determined duplicate pointing at ``canonical_id``."""
    reference_id = reference_id or uuid7()
    return Reference(
        id=reference_id,
        duplicate_decision=ReferenceDuplicateDecision(
            reference_id=reference_id,
            duplicate_determination=DuplicateDetermination.DUPLICATE,
            canonical_reference_id=canonical_id,
            active_decision=True,
        ),
    )


@pytest.fixture
def synchronizer() -> ReferenceSynchronizer:
    """A synchronizer with mocked units of work and a stubbed projection."""
    sync = ReferenceSynchronizer(sql_uow=AsyncMock(), es_uow=AsyncMock())
    # Project to the reference's id so we can assert which references were indexed.
    sync._to_indexable = AsyncMock(side_effect=lambda ref: ref.id)  # type: ignore[method-assign] # noqa: SLF001
    return sync


async def _drain(synchronizer: ReferenceSynchronizer) -> list[UUID]:
    """Run add_bulk against the generator and return what was indexed."""
    indexed: list[UUID] = []

    async def add_bulk(gen: AsyncGenerator) -> int:
        indexed.extend([item async for item in gen])
        return len(indexed)

    cast(AsyncMock, synchronizer.es_uow.references.add_bulk).side_effect = add_bulk
    return indexed


def _serve(synchronizer: ReferenceSynchronizer, *references: Reference) -> None:
    """Make get_by_pks return whichever of ``references`` are requested."""
    by_id = {ref.id: ref for ref in references}

    async def get_by_pks(
        pks: list[UUID],
        preload: object = None,  # noqa: ARG001
    ) -> list[Reference]:
        return [by_id[pk] for pk in pks if pk in by_id]

    cast(AsyncMock, synchronizer.sql_uow.references.get_by_pks).side_effect = get_by_pks


async def test_canonicals_indexed_directly(
    synchronizer: ReferenceSynchronizer,
) -> None:
    """Canonical-like references are indexed as themselves."""
    canonical = _canonical()
    _serve(synchronizer, canonical)
    indexed = await _drain(synchronizer)

    count = await synchronizer.bulk_sql_to_es([canonical.id])

    assert indexed == [canonical.id]
    assert count == 1


async def test_duplicate_redirects_to_canonical(
    synchronizer: ReferenceSynchronizer,
) -> None:
    """A passed-in duplicate causes its canonical to be re-indexed instead."""
    canonical = _canonical()
    duplicate = _duplicate(canonical.id)
    _serve(synchronizer, canonical, duplicate)
    indexed = await _drain(synchronizer)

    await synchronizer.bulk_sql_to_es([duplicate.id])

    assert indexed == [canonical.id]


async def test_multiple_duplicates_reindex_canonical_once(
    synchronizer: ReferenceSynchronizer,
) -> None:
    """Several duplicates of one canonical re-index that canonical a single time."""
    canonical = _canonical()
    duplicates = [_duplicate(canonical.id) for _ in range(3)]
    _serve(synchronizer, canonical, *duplicates)
    indexed = await _drain(synchronizer)

    await synchronizer.bulk_sql_to_es([d.id for d in duplicates])

    assert indexed == [canonical.id]


async def test_unprojectable_reference_is_skipped_and_reported(
    synchronizer: ReferenceSynchronizer,
) -> None:
    """The other references still index, then the failure is raised."""
    good, bad, other = _canonical(), _canonical(), _canonical()
    _serve(synchronizer, good, bad, other)
    indexed = await _drain(synchronizer)

    def project(ref: Reference) -> UUID:
        if ref.id == bad.id:
            msg = "boom"
            raise ProjectionError(msg)
        return ref.id

    cast(AsyncMock, synchronizer._to_indexable).side_effect = project  # noqa: SLF001

    with pytest.raises(ProjectionError, match=f"1 of 3 references.*{bad.id}"):
        await synchronizer.bulk_sql_to_es([good.id, bad.id, other.id])

    assert indexed == [good.id, other.id]


async def test_non_projection_error_aborts_bulk(
    synchronizer: ReferenceSynchronizer,
) -> None:
    """Only projection failures are isolated; anything else still aborts."""
    bad = _canonical()
    _serve(synchronizer, bad)
    await _drain(synchronizer)
    cast(AsyncMock, synchronizer._to_indexable).side_effect = RuntimeError("boom")  # noqa: SLF001

    with pytest.raises(RuntimeError):
        await synchronizer.bulk_sql_to_es([bad.id])


class TestToIndexable:
    """Linked data projection in ReferenceSynchronizer._to_indexable."""

    @pytest.fixture
    def projection_service(self) -> AsyncMock:
        service = AsyncMock()
        service.project.side_effect = [
            LinkedDataProjection(concepts={"c1"}, labels={"Label 1"}, countries={"GB"}),
            LinkedDataProjection(
                concepts={"c1", "c2"}, labels={"Label 2"}, countries={"KE"}
            ),
        ]
        return service

    async def test_unions_every_linked_data_enhancement(
        self, projection_service: AsyncMock
    ):
        reference_id = uuid7()
        reference = ReferenceFactory.build(
            id=reference_id,
            enhancements=[
                EnhancementFactory.build(
                    reference_id=reference_id,
                    content=LinkedDataEnhancementFactory.build(),
                ),
                EnhancementFactory.build(
                    reference_id=reference_id,
                    content=LinkedDataEnhancementFactory.build(),
                ),
            ],
            duplicate_references=[],
        )

        with patch(
            "app.domain.references.services.synchronizer_service."
            "_get_linked_data_projection_service",
            return_value=projection_service,
        ):
            result = await ReferenceSynchronizer._to_indexable(reference)  # noqa: SLF001

        assert projection_service.project.await_count == 2
        assert result.linked_data_projection == LinkedDataProjection(
            concepts={"c1", "c2"},
            labels={"Label 1", "Label 2"},
            countries={"GB", "KE"},
        )

    async def test_linked_data_failure_is_a_projection_error(self):
        reference_id = uuid7()
        reference = ReferenceFactory.build(
            id=reference_id,
            enhancements=[
                EnhancementFactory.build(
                    reference_id=reference_id,
                    content=LinkedDataEnhancementFactory.build(),
                ),
            ],
            duplicate_references=[],
        )
        projection_service = AsyncMock()
        projection_service.project.side_effect = ValueError("missing @context")

        with (
            patch(
                "app.domain.references.services.synchronizer_service."
                "_get_linked_data_projection_service",
                return_value=projection_service,
            ),
            pytest.raises(ProjectionError) as exc_info,
        ):
            await ReferenceSynchronizer._to_indexable(reference)  # noqa: SLF001

        assert isinstance(exc_info.value.__cause__, ValueError)

    async def test_no_linked_data_leaves_projection_empty(
        self, projection_service: AsyncMock
    ):
        reference_id = uuid7()
        reference = ReferenceFactory.build(
            id=reference_id,
            enhancements=[
                EnhancementFactory.build(
                    reference_id=reference_id,
                    content=BibliographicMetadataEnhancementFactory.build(),
                ),
            ],
            duplicate_references=[],
        )

        with patch(
            "app.domain.references.services.synchronizer_service."
            "_get_linked_data_projection_service",
            return_value=projection_service,
        ):
            result = await ReferenceSynchronizer._to_indexable(reference)  # noqa: SLF001

        projection_service.project.assert_not_awaited()
        assert result.linked_data_projection is None
