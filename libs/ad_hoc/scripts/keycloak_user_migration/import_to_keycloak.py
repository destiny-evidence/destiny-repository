# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx"]
# ///
# ruff: noqa: T201, PTH123, S603, S607, D103, EXE001, EXE003, ERA001, S105
"""Import users from a CSV into the destiny Keycloak realm."""

import argparse
import csv
import subprocess
import sys

import httpx

KEYCLOAK = "https://auth.evidence-repository.org"
REALM = "destiny"
OP_USER = "op://Evidence Data Platforms/DESTINY Shared Keycloak Admin/username"
OP_PASS = "op://Evidence Data Platforms/DESTINY Shared Keycloak Admin/password"
EMAIL_LIFESPAN_SECS = 86400  # 24h


def op(ref: str) -> str:
    return subprocess.run(
        ["op", "read", ref], capture_output=True, text=True, check=True
    ).stdout.strip()


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("csv", help="CSV from export_from_azure.py")
parser.add_argument("--dry-run", action="store_true")
args = parser.parse_args()

token_resp = httpx.post(
    f"{KEYCLOAK}/realms/master/protocol/openid-connect/token",
    data={
        "grant_type": "password",
        "client_id": "admin-cli",
        "username": op(OP_USER),
        "password": op(OP_PASS),
    },
)
token_resp.raise_for_status()
token = token_resp.json()["access_token"]

api = httpx.Client(
    base_url=f"{KEYCLOAK}/admin/realms/{REALM}",
    headers={"Authorization": f"Bearer {token}"},
    timeout=30.0,
)

resp = api.get("/groups")
resp.raise_for_status()
groups = {g["name"]: g["id"] for g in resp.json()}
for required in ("developers", "consumers"):
    if required not in groups:
        sys.exit(f"missing keycloak group: {required}")

with open(args.csv) as f:
    rows = list(csv.DictReader(f))

print(f"Processing {len(rows)} users{' (DRY RUN)' if args.dry_run else ''}")

for row in rows:
    email = row["email"].strip().lower()
    group = row["group"]
    sso = row["google_sso"].lower() == "true"

    existing = api.get("/users", params={"email": email, "exact": "true"}).json()
    if existing:
        print(f"  skip   {email} (already exists)")
        continue

    if args.dry_run:
        action = "SSO, no email" if sso else "send password email"
        print(f"  WOULD  {email} -> {group}; {action}")
        continue

    create = api.post(
        "/users",
        json={
            "username": email,
            "email": email,
            "firstName": row["first_name"],
            "lastName": row["last_name"],
            "enabled": True,
            "emailVerified": True,
        },
    )
    create.raise_for_status()
    user_id = create.headers["Location"].rsplit("/", 1)[-1]

    api.put(f"/users/{user_id}/groups/{groups[group]}").raise_for_status()

    if not sso:
        api.put(
            f"/users/{user_id}/execute-actions-email",
            params={"lifespan": EMAIL_LIFESPAN_SECS},
            json=["UPDATE_PASSWORD"],
        ).raise_for_status()

    print(f"  ok     {email} -> {group}{' (SSO)' if sso else ' (emailed)'}")
