# Keycloak User Migration

One-shot migration of active Azure AD users (`destiny-repository-developers`,
`destiny-repository-ui-users`) into the `destiny` Keycloak realm.

## Prerequisites

- `uv` installed
- `az` CLI signed in to the `JT_AD` tenant (`az login`)
- `op` CLI signed in to 1Password (`op signin`)

## Workflow

1. **Extract Azure users to CSV.**

   ```sh
   uv run --script export_from_azure.py
   ```

   Writes `keycloak_migrate_users.csv` with columns:
   `email, first_name, last_name, group, google_sso`.

2. **Review the CSV.** Delete any rows you don't want to migrate.

3. **Dry-run the import.**

   ```sh
   uv run --script import_to_keycloak.py keycloak_migrate_users.csv --dry-run
   ```

4. **Run for real.**

   ```sh
   uv run --script import_to_keycloak.py keycloak_migrate_users.csv
   ```

   Idempotent: re-running skips users that already exist in Keycloak.
