# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
# ruff: noqa: T201, PTH123, S603, S607, D103, EXE001, EXE003, ERA001
"""Extract destiny users from Azure AD groups → CSV."""

import csv
import json
import subprocess
import sys

# Azure group ID -> Keycloak group. First entry wins on overlap.
# (developers supersets consumers).
GROUPS = [
    ("fc84309f-8d69-4ef5-8fa7-1132049aad6f", "developers"),
    ("1f65e215-659b-4406-a542-78e354cf6fff", "consumers"),
]

# Domains auto-redirected to Google SSO via the Future Evidence Foundation
# org in Keycloak; these users don't need a password-setup email.
GOOGLE_SSO_DOMAINS = {"covidence.org", "futureevidence.org", "aliveevidence.org"}

OUTPUT = "keycloak_migrate_users.csv"


def az_members(group_id: str) -> list[dict]:
    out = subprocess.run(
        ["az", "ad", "group", "member", "list", "--group", group_id, "-o", "json"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return json.loads(out)


users: dict[str, dict] = {}
for group_id, group_name in GROUPS:
    for m in az_members(group_id):
        email = (m.get("mail") or "").lower().strip()
        if not email:
            continue  # external users / non-user entries lack a usable email
        if email in users:
            continue  # earlier group wins
        users[email] = {
            "first_name": m.get("givenName") or "",
            "last_name": m.get("surname") or "",
            "group": group_name,
            "google_sso": email.rsplit("@", 1)[-1] in GOOGLE_SSO_DOMAINS,
        }

with open(OUTPUT, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["email", "first_name", "last_name", "group", "google_sso"])
    for email in sorted(users):
        u = users[email]
        w.writerow(
            [
                email,
                u["first_name"],
                u["last_name"],
                u["group"],
                "true" if u["google_sso"] else "false",
            ]
        )

print(f"Wrote {len(users)} users to {OUTPUT}", file=sys.stderr)
