"""Setup fixtures for all tests."""

import asyncio
import datetime
import logging
import re
from collections.abc import AsyncGenerator, Callable
from typing import Any

import pytest
from alembic.command import upgrade
from jose import jwt
from pytest_httpx import HTTPXMock
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.persistence.sql.persistence import Base
from app.persistence.sql.session import AsyncDatabaseSessionManager, db_manager
from tests.db_utils import alembic_config_from_url, tmp_database

settings = get_settings()
MIGRATION_TASK: asyncio.Task | None = None

logging.getLogger("asyncio").setLevel("DEBUG")


@pytest.fixture(scope="session", autouse=True)
def anyio_backend() -> tuple[str, dict[str, Any]]:
    """Specify the anyio backend for async tests."""
    return "asyncio", {"use_uvloop": True}


@pytest.fixture(scope="session")
async def migrated_postgres_template() -> AsyncGenerator[str]:
    """
    Create temporary database and applies migrations.

    Has "session" scope, so is called only once per tests run.
    """
    async with tmp_database("pytest") as tmp_url:
        alembic_config = alembic_config_from_url(tmp_url)

        # It is important to always close the connections at the end of such migrations,
        # or we will get errors like `source database is being accessed by other users`

        upgrade(alembic_config, "head")
        if MIGRATION_TASK:
            await MIGRATION_TASK

        yield tmp_url


@pytest.fixture(scope="session")
async def sessionmanager_for_tests(
    migrated_postgres_template: str,
) -> AsyncGenerator[AsyncDatabaseSessionManager]:
    """Build shared session manager for tests."""
    db_manager.init(db_url=migrated_postgres_template)
    # can add another init (redis, etc...)
    yield db_manager
    await db_manager.close()


@pytest.fixture
async def session(
    sessionmanager_for_tests: AsyncDatabaseSessionManager,
) -> AsyncGenerator[AsyncSession]:
    """Yield the session for the test and cleanup tables."""
    engine = sessionmanager_for_tests._engine  # noqa: SLF001
    assert engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with sessionmanager_for_tests.session() as session:
        yield session
    # Clean tables. I tried
    # 1. Create new database using an empty `migrated_postgres_template` as template
    # (postgres could copy whole db structure)
    # 2. Do TRUNCATE after each test.
    # 3. Do DELETE after each test.
    # Doing DELETE FROM is the fastest
    # https://www.lob.com/blog/truncate-vs-delete-efficiently-clearing-data-from-a-postgres-table
    # BUT DELETE FROM query does not reset any AUTO_INCREMENT counters
    async with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())


@pytest.fixture
def fake_public_key() -> dict[str, str]:
    """Return a fake public key for testing auth functions."""
    return {
        "kty": "RSA",
        "e": "AQAB",
        "use": "sig",
        "kid": "B2xa7mmGZNlozVG3WuD0TKaBYa1pcOg1V4hwcJLP7rA",
        "alg": "RS256",
        "n": "kKDUcNhINFIRjuzK2pW1dYGF0iJjmy9Ux15TJwSEX7MeKplHp58HnM_--ZHRj4gEp-Gq9l7wNowdJEO72nITfnjQpyroSIimAY0hxMgv96v7dYS1mYLcPASYenXNWYXA0IrK5ZRb_6NacsA_yVOoeWDglwzEZFkgmyXpi2pI988FY8nDMAlC7KD4IlSTeOakW1zkdd6eQY7CeThIEGlL826vlR2aziAKRtiKBzgfY8Y50USoa7zWRfYqay9A_e_Y_lvj9vPa0fl9MKZpqbHEsN7MrNpMOpuJ6vajtp7JL12IBcgLH9Q80on73Isj6RYc3zS5_SllXS7NbxfJ0jZ7IQ",  # noqa: E501
    }


_fake_private_key = {
    "p": "-X2N5eWnp5Wr6rfhLuC30mKIoG1KXCjlZQMyP6QOCayMxhrhUM2ZeHtcl7ExMX0vRr2auQtWYlfPsnHEEbOCehehdoKWgZouCX_CLvBV484T_EIIvcnHp6fCJYpOnodbl6R7kT9if3wI672CAARdiMXmfj94xVj0pYyQZ_Mag5k",  # noqa: E501
    "kty": "RSA",
    "q": "lGbb-VSNfQdCFTki3ClQPCk2YdV4Vh9PVk8Sx9_oTheDGWCKuuhVjqooKedPmqMw1X23GCQwV3pqbKUEonY7BsryUG2MFLCzxJm-c45eWqmR-1rhnwnxHvlopAoSL2CPh4qVqMbGXJ3hJ5roU8KmLAop_DcS7NfvwGG4YInHaMk",  # noqa: E501
    "d": "P-w1uSJ-11EmnYsfJXlh2GvE39l_OMm0qOGR0v72Gu4p-R4CQ53QWYi840WF3_B4TlM5oubXOOS4xJyDXMtqvk1bu2cFf3mWFb1xHW51dPw4ifp74TurZ4OIeSez-Utaq1GM1-e4ucZTZcB-8Nbe8bbVzS1BaDDUbn5VON9jHNNda5jQQojcVNF_TRyREJ-kizz3CyveIjmeS6Lb9regIYfAZnrKCiEvhv1m6zhvvqxViz7nzp8D-Es2nrksqWUO-Eh8O9UmeqcHJi32V5PyTTxHP2IG5-x18Bn_cX7_ntZ8a9ollTjf6PoUZMGz_Dsybu7QfQkadgr0sEPODQ7wgQ",  # noqa: E501
    "e": "AQAB",
    "use": "sig",
    "kid": "B2xa7mmGZNlozVG3WuD0TKaBYa1pcOg1V4hwcJLP7rA",
    "qi": "PoZSlTkB3dVl4mp24kTx4EK4YrT-c7lclsUBArdWt6WhVPCKMjWT1NZ6-sTw4TmWb7a-lOCqXLkfBVMzLkfpR3wp-J_TNfnb9PGP8-cTIE0FAEG9Kpc7tDNj1VhqU1Bl7Yse-Sp1u3vRvSqZvouNfSmTR00_648PrZegTDLZV2A",  # noqa: E501
    "dp": "P90r3ZWT_QoLH-JB-kX7yBcA8lAHoN-3GMxgqHnOPhu1TWDEHHMEvhqV8R6igRCScYFHgeatDi98Myl8DyvsUmSKKFP1Que8sSHLC0jqM44k_4XHxw1H1lrTD9j_lwT_JSotl1iqVgfiILY5-NclOkWuYtLMj3fd6CK7NGC-gME",  # noqa: E501
    "alg": "RS256",
    "dq": "gg0WL416pRwsPF8i_p-x8dcIEnq6B3dO1stbIRBHC9CtEhs52IxtFiZmJjrQ1yq2TBHs19o3ByJ_i5Cd3CYSmmRWMEegYC1ujRdTAP--DmPWS9mcKfzTcxqNKlytDRnpDpZTi2IPSfEN9OBbQ7QsXiHWI3K8QhUGxaidpPR5bYk",  # noqa: E501
    "n": "kKDUcNhINFIRjuzK2pW1dYGF0iJjmy9Ux15TJwSEX7MeKplHp58HnM_--ZHRj4gEp-Gq9l7wNowdJEO72nITfnjQpyroSIimAY0hxMgv96v7dYS1mYLcPASYenXNWYXA0IrK5ZRb_6NacsA_yVOoeWDglwzEZFkgmyXpi2pI988FY8nDMAlC7KD4IlSTeOakW1zkdd6eQY7CeThIEGlL826vlR2aziAKRtiKBzgfY8Y50USoa7zWRfYqay9A_e_Y_lvj9vPa0fl9MKZpqbHEsN7MrNpMOpuJ6vajtp7JL12IBcgLH9Q80on73Isj6RYc3zS5_SllXS7NbxfJ0jZ7IQ",  # noqa: E501
}


@pytest.fixture
def fake_application_id() -> str:
    """Return a fake application id for testing."""
    return "test_application_id"


@pytest.fixture
def fake_tenant_id() -> str:
    """Return a fake tenant id for testing."""
    return "test_tenant_id"


@pytest.fixture
def generate_fake_token(
    fake_application_id: str,
    fake_tenant_id: str,
) -> Callable[[dict | None, str | None], str]:
    """Create a function that will return a fake token usint the supplied params."""

    def __generate_token(
        user_payload: dict | None = None, scope: str | None = None
    ) -> str:
        if user_payload is None:
            user_payload = {}
        payload = {
            "sub": "test_subject",
            "iat": datetime.datetime.now(datetime.UTC),
            "exp": datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=10),
            "aud": f"api://{fake_application_id}",
            "iss": f"https://sts.windows.net/{fake_tenant_id}/",
        }

        payload.update(user_payload)

        if scope:
            payload["roles"] = [scope]

        return jwt.encode(
            payload,
            _fake_private_key,
            algorithm="RS256",
            headers={"kid": _fake_private_key["kid"]},
        )

    return __generate_token


@pytest.fixture
def stubbed_jwks_response(httpx_mock: HTTPXMock, fake_public_key: dict) -> None:
    """Stub out the jwks respons to return the standard fake public key."""
    httpx_mock.add_response(
        url=re.compile(r"https://login.microsoftonline.com/"),
        json={"keys": [fake_public_key]},
    )
