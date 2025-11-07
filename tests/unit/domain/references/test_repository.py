from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.references.models.models import GenericExternalIdentifier
from app.domain.references.models.sql import ExternalIdentifier as SQLExternalIdentifier
from app.domain.references.models.sql import Reference as SQLReference
from app.domain.references.repository import ReferenceSQLRepository
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


async def test_find_with_identifiers_empty(session: AsyncSession):
    repo = ReferenceSQLRepository(session)
    result = await repo.find_with_identifiers([])
    assert result == []


async def test_find_with_identifiers_single_match_all(session: AsyncSession):
    repo = ReferenceSQLRepository(session)
    identifier = GenericExternalIdentifier(
        identifier_type="doi",
        identifier="10.1000/abc123",
        other_identifier_name=None,
    )
    ref, _ = await create_reference_with_identifiers(session, [identifier])
    result = await repo.find_with_identifiers([identifier], match="all")
    assert any(r.id == ref.id for r in result)


async def test_find_with_identifiers_multiple_match_all(session: AsyncSession):
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


async def test_find_with_identifiers_multiple_match_any(session: AsyncSession):
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


async def test_find_with_identifiers_preload(session: AsyncSession):
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
