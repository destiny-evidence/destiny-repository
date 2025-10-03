# DESTINY Repository

_Powering a comprehensive repository of climate and health research_

[Project Homepage](https://destiny-evidence.github.io/website/)

[Documentation](https://destiny-evidence.github.io/destiny-repository/)

[SDK](/libs/sdk/README.md)

## Setup

### Requirements

[uv](https://docs.astral.sh/uv) is used for dependency management and managing virtual environments. You can install uv either using pipx or the uv installer script:

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Installing Dependencies

Once uv is installed, install dependencies:

```sh
uv sync
```

### Configuration

A `.env` file is used to pass environment variables to the server. To avoid
accidental exposure of secrets, this file is ignored using the `.gitignore`
file. To set up a copy of the configuration (which should not require
modification to run the application), copy the example file:

```shell
cp .env.example .env
```

### Starting the development server

First you will need to start the auxiliary servers:

```sh
docker compose up -d
```

#### Database

Once the database server is running, run the migrations to setup the database.

```sh
uv run alembic upgrade head
```

#### MinIO

You also may need the MinIO fileserver. This requires the MinIO Client. Install instructions for Mac:

```sh
brew install minio-mc
```

This can be accessed at localhost:9001 or automatically seeded using the below:

#### Seeding the database

We have a database seed in `.db_seed` to give us some local data to work with and to test out migrations, load this in with

```sh
PGPASSWORD=localpass psql -U localuser -h 0.0.0.0 -p 5432 -d destiny_dev -f ".db_seed/local.sql"
```

##### Updating the database seed

After generating a database migration, you will need to update the data seed. Apply the migration locally, run the following command, and then commit the result.

```sh
PGPASSWORD=localpass pg_dump --data-only --exclude-table=alembic_version -U localuser -h 0.0.0.0 -p 5432 destiny_dev > .db_seed/local.sql
```

#### Application

Run the development server:

```sh
uv run fastapi dev
```

Run the taskiq worker:

```sh
uv run taskiq worker app.tasks:broker --fs-discover --reload
```

Alternatively, you can run the development server and taskiq worker via docker:

```sh
docker compose --profile app up --build
```

#### Observability

The below command spins up a `SigNoz` deployment for local observability of traces and metrics. This exactly mimics our production setup, except for the observability platform itself.

```sh
COMPOSE_EXPERIMENTAL_GIT_REMOTE=1 docker compose -f docker-compose.signoz.yml up -d
```

To then run the application with observability:

```sh
docker compose -f docker-compose.yml -f docker-compose.observable.yml --profile app up
```

## Organisation

The initial project includes some folders to organise the code.

### Routers

Each set of RESTful actions should be contained in a router. These are
kept in the [app/routers](app/routers/) directory. To provide a worked example, we have provided an [example router](app/routers/example.py) until we have more than a skeleton project.

### Models

Each data class should be expressed as a Pydantic model.

These are stored in the [app/models](app/models/) directory.

### Migrations

Changes to the database structure are managed through Alembic migrations. To generate a migration, update a model (eg. add a column) and then auto generate the migration:

```sh
uv run alembic revision --autogenerate -m "Added column to model"
```

Your migration will be added to the [`app/migrations`](app/migrations/) directory.

While automatic migrations can be useful, ensure the migration `upgrade` and `downgrade` models are as you want/expect.

If you are adding a new model, ensure you import that model into the `app/migrations/env.py` file to ensure it is auto detected.

## Authentication

In development mode, we don't enforce authentication, but once deployed to production the service will require
a token from Azure Entra to call authenticated APIs (which will initially be all APIs).

A token can be acquired by an application running in a container app or VM when it has been configured with a role-assignment to the application. In terraform that would look like this:

```terraform
# Get the existing application that we want to access from our app.
data "azuread_application" "destiny_repo" {
  display_name = "DESTINY Repository"
}

# Get the service principal for that application.
resource "azuread_service_principal" "destiny_repo" {
  client_id = azuread_application.destiny_repo.client_id
  use_existing = true
}

# Create a user assigned identity for our client app
resource "azurerm_user_assigned_identity" "my_app" {
  location            = azurerm_resource_group.example.location # Replace the example!
  name                = "my_app"
  resource_group_name = azurerm_resource_group.example.name # Replace the example!
}

# Finally create the role assignment for the client app
resource "azuread_app_role_assignment" "example" {
  app_role_id         = azuread_service_principal.destiny_repo.app_role_ids["import"]
  principal_object_id = azurerm_user_assigned_identity.my_app.principal_id
  resource_object_id  = azuread_service_principal.destiny_repo.object_id
}
```

Then within the application code of the client app you can do something like this:

```python
import msal
import requests

auth_client = msal.ManagedServiceIdentityClient(
    {"ManagedIdentityIdType": "ClientId", "Id": "<CLIENT_ID>"},
    http_client=requests.Session()
)
auth_client.acquire_token_for_client(resource="<APPLICATION URL>")
```

In the above example `<CLIENT ID>` should be the client id of the user defined identity you created with terraform, and `<APPLICATION URL>` should be the URL for the DESTINY Repo application (it should start with `api://`).

To get a token for use in a development environment, there is a utility module:

```shell
uv run python -m app.utils.get_token
```

## Development

Before commiting any changes, please run the pre-commit hooks. This will ensure that the code is formatted correctly and minimise diffs to code changes when submitting a pull request.

Install the pre-commit hooks:

```sh
uv run pre-commit install
```

pre-commit hooks will run automatically when you commit changes. To run them manually, use:

```sh
uv run pre-commit run --all-files
```

See [.pre-commit-config.yaml](.pre-commit-config.yaml) for the list of pre-commit hooks and their configuration.

## Tests

Tests are in the [tests](/tests) directory. They are run using `pytest`

```sh
uv run pytest
```

End-to-end testing is run separately. Note they require your docker daemon to be running and visible.

```sh
uv run pytest tests/e2e
```

When first running, add the `--build` flag to build the application image. This can also be used to rebuild the image - not generally necessary as the code is mounted but is useful when things like Dockerfiles or uv dependencies change.
