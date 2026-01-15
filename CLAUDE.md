# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DESTINY Repository is a FastAPI-based backend service for managing scholarly research references for systematic reviews. It includes:
- A REST API for reference management, imports, enhancements, and search
- Background task processing via TaskIQ (RabbitMQ locally, Azure Service Bus in production)
- PostgreSQL for primary storage with SQLAlchemy ORM
- Elasticsearch for search and percolation queries
- MinIO/Azure Blob Storage for file storage
- A separate SDK package (`destiny-sdk`) published to PyPI

## Common Commands

```bash
# Install dependencies
uv sync

# Run development server
uv run fastapi dev

# Run taskiq worker for background tasks
uv run taskiq worker app.tasks:broker --tasks-pattern 'app/**/tasks.py' --fs-discover --reload

# Run all tests (excludes e2e by default)
uv run pytest

# Run a single test file
uv run pytest tests/unit/domain/references/services/test_deduplication_service.py

# Run a single test
uv run pytest tests/unit/domain/references/services/test_deduplication_service.py::test_function_name

# Run e2e tests (requires Docker)
uv run pytest tests/e2e --log-cli-level info

# Run linting/formatting (pre-commit hooks)
uv run pre-commit run --all-files

# Generate database migration
uv run alembic revision --autogenerate -m "Migration message"

# Apply migrations
uv run alembic upgrade head
```

## Key Domain Concepts

### Reference Lifecycle
A **Reference** is a scholarly work (paper, article, etc.). References flow through:
1. **Import** - Ingested from external sources (OpenAlex, Crossref, user uploads)
2. **Enhancement** - Enriched with metadata (bibliographic, abstracts, annotations)
3. **Deduplication** - Matched against existing corpus to prevent duplicates
4. **Indexing** - Added to Elasticsearch for search

### Enhancements
Enhancements are layered metadata attached to references. Multiple enhancements of the same type stack, with **latest wins** for conflicting fields. Types:
- `bibliographic` - Title, authors, publication year, DOI
- `abstract` - Abstract text
- `annotation` - Labels, scores, classifications
- `location` - URLs, file locations

### Identifiers
External identifiers link references to source systems:
- **OpenAlex ID** (`W` prefix) - Globally unique, most trustworthy
- **DOI** - Generally reliable but has edge cases (collisions, malformed)
- **PMID** - PubMed identifier
- **ERIC** - Education database identifier

## Architecture

The codebase generally follows Domain-Driven Design (DDD) principles.

### Domain Structure

The codebase is organized under `app/domain/`:

```
app/domain/{domain_name}/
    routes.py      # FastAPI route handlers
    service.py     # Business logic and orchestration
    repository.py  # SQLAlchemy repository pattern
    tasks.py       # TaskIQ background tasks
    models/
        models.py      # Domain models (Pydantic)
        sql.py         # SQLAlchemy ORM models
        projections.py # Derived/computed models
    services/      # Sub-services (anti-corruption, enhancement, etc.)
```

Main domains: `references`, `imports`, `robots`

### Unit of Work Pattern

Services use decorator-based unit of work patterns for transaction management:
- `@sql_unit_of_work` - wraps method in SQL transaction
- `@es_unit_of_work` - wraps method in Elasticsearch transaction

### Anti-Corruption Layer

Each domain has an `anti_corruption_service.py` that handles translation between SDK models and internal domain models, ensuring clean boundaries between external API contracts and internal representations.

### SDK (`libs/sdk/`)

The SDK (`destiny-sdk`) is a separate package providing:
- Pydantic models for API request/response validation
- Client utilities for external consumers
- Published to PyPI independently

When modifying API contracts, update both SDK models and domain models.

### Persistence Layer

PostgreSQL is the source of truth. The Elasticsearch index is derived and can be rebuilt from PostgreSQL.

- `app/persistence/sql/` - SQLAlchemy async session management and repositories
- `app/persistence/es/` - Elasticsearch client and search operations
- `app/persistence/blob/` - File storage (MinIO locally, Azure Blob in production)

### Background Tasks

TaskIQ handles async job processing. Task definitions are in `app/domain/*/tasks.py`. The broker switches based on environment:
- Local: RabbitMQ via `AioPikaBroker`
- Production: Azure Service Bus via `AzureServiceBusBroker`
- Test: `InMemoryBroker`

## Testing

Tests are organized into:
- `tests/unit/` - Unit tests with mocked dependencies
- `tests/integration/` - Tests with real database connections
- `tests/e2e/` - End-to-end tests using testcontainers
- `libs/sdk/tests/` - SDK-specific tests

E2E tests require Docker and are excluded from default pytest runs.

## External Data Sources

- **OpenAlex** - Primary bibliographic data source. W IDs are globally unique.
- **Crossref** - DOI metadata. Watch for malformed DOIs and metadata quality issues.
- **PubMed** - Medical/life sciences literature.

## Code Style

- Linting: Ruff with `lint.select = ["ALL"]` (strict)
- Type checking: Pyright (preferred) or mypy with Pydantic plugin
- Pre-commit hooks enforce formatting, linting, and dead code detection (vulture)

Key ruff ignores applied in tests: relaxed type hints, docstrings, and magic values.

## Development Practices

- Prefer TDD: Write tests before implementing new functionality
- When adding new fields: update domain model (`models.py`), SQL model (`sql.py`), and create migration
- Use `uv run pyright <file>` to check types before committing

### Common Gotchas

- **active_decision**: Only one decision per reference can be active. Use partial unique index.
- **Enhancement stacking**: Multiple enhancements layer; latest created_at wins for each field.
- **Domain vs SQL models**: Domain models are Pydantic, SQL models are SQLAlchemy. Keep them in sync.

## Database Access

Use the postgres MCP tool for ad-hoc queries:
```
mcp__postgres__query with SQL
```

Useful queries:
```sql
-- Check deduplication decision distribution
SELECT duplicate_determination, COUNT(*) FROM reference_duplicate_decision WHERE active_decision GROUP BY 1;

-- Find UNRESOLVED decisions needing review
SELECT * FROM reference_duplicate_decision WHERE duplicate_determination = 'unresolved' AND active_decision LIMIT 10;
```

## Code Navigation

Prefer LSP over grep for targeted lookups:
- `documentSymbol` - Get all classes, methods, variables in a file with line numbers
- `goToDefinition` - Jump to where a symbol is defined
- `findReferences` - Find all usages of a symbol
- `hover` - Get type information for a symbol

For broader exploration (understanding a feature, finding related code), use the **Explore agent** which can search across multiple files and naming conventions.

## Key Files Reference

When working on specific features, start here:
- **Deduplication**: `app/domain/references/services/deduplication_service.py`
- **Reference CRUD**: `app/domain/references/service.py`
- **Imports**: `app/domain/imports/service.py`
- **Search**: `app/domain/references/repository.py` (ReferenceESRepository)
- **Models**: `app/domain/references/models/models.py` (domain), `sql.py` (persistence)