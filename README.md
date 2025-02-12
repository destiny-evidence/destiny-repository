# DESTINY Repository

_Powering a comprehensive repository of climate and health research_

## Setup

### Requirements

[Poetry](https://python-poetry.org) is used for dependency management and managing virtual environments. You can install poetry either using pipx or the poetry installer script:

```sh
curl -sSL https://install.python-poetry.org | python3 -
```

### Installing Dependencies

Once Poetry is installed, install dependencies:

```sh
poetry install
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

First you will need to start the database server:

```sh
docker compose up -d
```

Once the database server is running, run the migrations to setup the database.

```sh
poetry run alembic upgrade head
```

Run the development server:

```sh
poetry run fastapi dev
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
poetry run alembic revision --autogenerate -m "Added column to model"
```

Your migration will be added to the [`app/migrations`](app/migrations/) directory.

While automatic migrations can be useful, ensure the migration `upgrade` and `downgrade` models are as you want/expect.

If you are adding a new model, ensure you import that model into the `app/migrations/env.py` file to ensure it is auto detected.

## Development

Before commiting any changes, please run the pre-commit hooks. This will ensure that the code is formatted correctly and minimise diffs to code changes when submitting a pull request.

Install the pre-commit hooks:

```sh
poetry run pre-commit install
```

pre-commit hooks will run automatically when you commit changes. To run them manually, use:

```sh
poetry run pre-commit run --all-files
```

See [.pre-commit-config.yaml](.pre-commit-config.yaml) for the list of pre-commit hooks and their configuration.

## Tests

Tests are in the [tests](/tests) directory. They are run using `pytest`

```sh
poetry run pytest
```
