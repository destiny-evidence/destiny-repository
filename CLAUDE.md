# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## Workflow Guidelines

- When changes require validation, include testing and/or manual verification as final steps in task lists
- Do not suggest commits or pushes; wait for the user to request them
- Be concise and technically correct; avoid sugar-coating

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
