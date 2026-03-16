# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "asyncpg",
#     "azure-identity",
# ]
# ///

# ruff: noqa: T201

"""
Remote helper script for deduplicate-eef-references.py.

Runs inside a container app via `az containerapp exec` to query the database
for EEF reference IDs. Not intended to be run directly.
"""

import asyncio
import json
import os

import asyncpg
from azure.identity import DefaultAzureCredential

SOURCE_NAME_PREFIX = "eef-eppi-review-export"


async def main() -> None:
    """Query the database for EEF reference IDs and print them."""
    db_config = json.loads(os.environ["DB_CONFIG"])
    token = (
        DefaultAzureCredential()
        .get_token("https://ossrdbms-aad.database.windows.net/.default")
        .token
    )
    conn = await asyncpg.connect(
        user=db_config["DB_USER"],
        password=token,
        host=db_config["DB_FQDN"],
        database=db_config["DB_NAME"],
        ssl="require",
    )
    rows = await conn.fetch(
        "SELECT r.id FROM reference r "
        "JOIN import_result ir ON ir.reference_id = r.id "
        "JOIN import_batch ib ON ir.import_batch_id = ib.id "
        "JOIN import_record i ON ib.import_record_id = i.id "
        "WHERE i.source_name LIKE $1",
        f"{SOURCE_NAME_PREFIX}%",
    )
    print("---BEGIN_RESULTS---")
    for row in rows:
        print(row["id"])
    print("---END_RESULTS---")
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
