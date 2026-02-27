# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## Workflow Guidelines

- When changes require validation, include testing and/or manual verification as final steps in task lists
- Do not suggest commits or pushes; wait for the user to request them
- Be concise and technically correct; avoid sugar-coating

## Repository Navigation and Local Folder Docs

This repository uses a lightweight "local docs" pattern to reduce thrash and speed up orientation:

- `docs/repo-map.md` is the **root index** of the repository.
- Each meaningful folder may contain a `.doc.md` that describes **what the folder is for**, the **key files**, and **how to work in it**.

### Required Reading Order

1. **At the start of any task**: read `docs/repo-map.md`.
2. **Before modifying code in a folder**: read that folder's `.doc.md` (if it exists).
3. **When exploring a folder you haven't touched yet**: read `.doc.md` first (if it exists) before scanning files.

### Creating and Updating `.doc.md`

#### When to Create

If you are about to make **non-trivial** changes in a folder and `.doc.md` does not exist, create it using the template below.

"Non-trivial" includes:

- Adding/removing/renaming files or modules
- Changing responsibilities, invariants, or data contracts
- Adding/changing test entry points or run commands
- Introducing new APIs, endpoints, CLI commands, pipelines, or workflows

#### When to Update

Update a folder's `.doc.md` **in the same commit** when your changes materially affect any of:

- Folder purpose or responsibilities
- Key entry points (main modules/classes/functions)
- Public surfaces (APIs/CLI/jobs)
- Invariants/assumptions (what must remain true)
- How to run tests / local dev / debugging
- Data contracts (schemas, record shapes, inputs/outputs)

Do **not** update `.doc.md` for trivial edits that don't change structure or usage (e.g., small refactors, formatting, comments).

#### Style Rules for `.doc.md`

- Keep it concise and factual; prefer bullets.
- Link to other `.doc.md` files and to code rather than duplicating detail.
- Avoid long prose. Target < 200-300 lines where possible.
- If something is uncertain, state it as a question/TODO rather than guessing.

### Standard `.doc.md` Template

Use this template when creating a new `.doc.md`:

```markdown
# <Folder name> (.doc.md)

## Purpose

- What this folder exists to do (1-3 bullets).
- What it explicitly does **not** do (optional).

## Responsibilities

- Bullet list of responsibilities / concerns owned here.

## Key Entry Points

- `<file>` - what it is / why it matters
- `<file>` - what it is / why it matters
- Include only the handful of files someone should read first.

## Important Invariants / Constraints

- Constraints that must remain true (ordering, idempotency, performance expectations, naming rules, etc.).
- Data assumptions (required fields, normalization rules, canonical forms).

## Public Surface Area

- APIs/endpoints exported from this folder
- CLI commands or job entry points
- Events/messages produced/consumed
- Config keys used here

## Typical Workflows

- "To do X..." steps (short). Prefer linking to code/tests over prose.

## Testing

- How to run unit tests relevant to this folder
- How to run integration/contract tests (if any)
- Fixtures or local dependencies (db, services) needed

## Debugging Notes

- Common failure modes and where to look (logs, key functions)
- Useful commands or flags (short)

## Related Docs

- Links:
  - `../path/to/.doc.md` - what to read it for
  - `docs/repo-map.md` - repo-wide map
  - Other relevant docs (design docs, ADRs, runbooks)

## TODO / Open Questions

- Short list of known gaps or questions (optional)
```

### Working Agreement

When a task spans multiple folders:

- Read each folder's `.doc.md` before modifying it.
- Update only the `.doc.md` files materially impacted by the change.
- Prefer adding links across docs rather than duplicating content.

## Project Overview

DESTINY Repository is a FastAPI-based backend for managing scholarly research references. It includes:

- A REST API for reference management, imports, enhancements, and search
- Background task processing via TaskIQ
- PostgreSQL for primary storage with SQLAlchemy ORM
- Elasticsearch for search and percolation queries
- MinIO/Azure Blob Storage for file storage
- A separate SDK package (`destiny-sdk`) published to PyPI
- A CLI for interacting with the API (`cli/`)
- A Next.js UI for authentication and basic operations (`ui/`)
- Sphinx documentation (`docs/`)

## Common Commands

```bash
# Start full development stack (recommended)
docker-compose up -d

# Install dependencies
uv sync

# Run development server (requires docker-compose services)
uv run fastapi dev

# Run all tests (excludes e2e by default)
uv run pytest

# Run e2e tests (requires Docker)
uv run pytest tests/e2e --log-cli-level info

# Run linting/formatting
uv run pre-commit run --all-files

# Generate database migration
uv run alembic revision --autogenerate -m "Migration message"

# Apply migrations
uv run alembic upgrade head
```

## Key Domain Concepts

### Reference Lifecycle

A **Reference** is a scholarly work (paper, article, etc.). References flow through:

1. **Import** - Ingested from external sources
2. **Enhancement** - Enriched with metadata
3. **Deduplication** - Matched against existing corpus
4. **Indexing** - Added to Elasticsearch for search

### Types and Enums

When you need to understand or modify type definitions:

- Read `libs/sdk/src/destiny_sdk/enhancements.py:EnhancementType` for enhancement types
- Read `libs/sdk/src/destiny_sdk/identifiers.py:ExternalIdentifierType` for identifier types

## Architecture

The codebase follows Domain-Driven Design (DDD) principles.

### Domain Structure

```text
app/domain/{domain_name}/
    routes.py      # FastAPI route handlers
    service.py     # Business logic and orchestration
    repository.py  # SQLAlchemy or Elasticsearch repository pattern
    tasks.py       # TaskIQ background tasks
    models/
        models.py      # Domain models (Pydantic)
        sql.py         # SQLAlchemy ORM models
        es.py          # Elasticsearch document models
        projections.py # Derived/computed models
    services/      # Sub-services (anti-corruption, enhancement, etc.)
```

Main domains: `references`, `imports`, `robots`

### Unit of Work Pattern

Services use decorator-based unit of work patterns for transaction management. Every operation with a persistence implementation must be inside exactly one unit of work.

- `@sql_unit_of_work` - wraps method in SQL transaction
- `@es_unit_of_work` - wraps method in Elasticsearch transaction

### Anti-Corruption Layer

Each domain has an `anti_corruption_service.py` that translates between SDK models and internal domain models. This decouples the SDK from internal representations, allowing independent evolution.

### SDK (`libs/sdk/`)

The SDK (`destiny-sdk`) provides Pydantic models for API contracts and client utilities. Published to PyPI independently.

### Persistence Layer

PostgreSQL is the source of truth. Elasticsearch is derived and can be rebuilt.

- `app/persistence/sql/` - SQLAlchemy async session management
- `app/persistence/es/` - Elasticsearch client and search
- `app/persistence/blob/` - File storage (MinIO locally, Azure Blob in production)

For database queries, prefer SQLAlchemy over raw psql - see `app/persistence/.doc.md` for session setup and ad-hoc query patterns.

## Topic-Specific Guidance

When working on user-facing features, consult the Sphinx documentation in `docs/`:

- Read `docs/procedures/` for batch importing, deduplication, reference flow, robot automation, search, OAuth
- Read `docs/codebase/` for architecture, models (references, imports, robots), persistence layers
- Read `docs/sdk/` for client usage, schemas, robot-client, labs
- Read `docs/cli/` for CLI usage and robot registration

When changes affect user-facing behavior, update the relevant Sphinx docs to match.

When working on implementation internals, read the relevant guide in `docs/claude/`:

- **Deduplication** (`deduplication.md`) - read when modifying duplicate detection, decision states, or canonical mapping
- **Enhancements** (`enhancements.md`) - read when modifying enhancement projection, pending states, or type handling
- **Imports** (`imports.md`) - read when modifying import batches, status transitions, or result handling
- **Robots** (`robots.md`) - read when modifying robot authentication or enhancement batch processing
- **Testing** (`testing.md`) - read when writing tests, using factories, or working with FakeRepository

## Code Style

- Linting: Ruff with `lint.select = ["ALL"]` (strict)
- Type checking: mypy with Pydantic plugin
- Pre-commit hooks enforce formatting, linting, and dead code detection (vulture)

Run `uv run pre-commit run --all-files` before committing.

## Key Files Reference

When modifying core functionality, start at these files:

- **Deduplication logic**: `app/domain/references/services/deduplication_service.py`
- **Reference CRUD**: `app/domain/references/service.py`
- **Import processing**: `app/domain/imports/service.py`
- **Search operations**: `app/domain/references/repository.py` (ReferenceESRepository)
- **Domain models**: `app/domain/references/models/models.py`
- **SQL models**: `app/domain/references/models/sql.py`
