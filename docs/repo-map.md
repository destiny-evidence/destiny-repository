# Repository Map

This is the root index for the DESTINY Repository codebase. Read this first when starting any task.

## Quick Links

| Task                              | Start Here                      |
| --------------------------------- | ------------------------------- |
| Understanding reference lifecycle | `app/domain/references/.doc.md` |
| Working on imports                | `app/domain/imports/.doc.md`    |
| Robot integration                 | `app/domain/robots/.doc.md`     |
| Database/ES/Blob storage          | `app/persistence/.doc.md`       |
| SDK development                   | `libs/sdk/.doc.md`              |
| Writing tests                     | `tests/.doc.md`                 |

## Top-Level Structure

```text
destiny-repository-clean/
├── app/                    # FastAPI backend application
├── cli/                    # Command-line interface
├── docs/                   # Sphinx documentation + Claude guidance
├── infra/                  # Deployment infrastructure (Terraform, scripts)
├── libs/                   # Shared libraries (SDK, importers, sample data)
├── tests/                  # Test suite (unit, integration, e2e)
└── ui/                     # Next.js frontend
```

## `app/` - Backend Application

The FastAPI backend, organized by Domain-Driven Design principles.

| Folder                   | Purpose                                              | `.doc.md`                                   |
| ------------------------ | ---------------------------------------------------- | ------------------------------------------- |
| `app/api/`               | API router registration, health endpoints            | -                                           |
| `app/core/`              | Configuration, constants, auth, telemetry            | -                                           |
| `app/domain/references/` | Reference CRUD, deduplication, enhancements, search  | [.doc.md](../app/domain/references/.doc.md) |
| `app/domain/imports/`    | Import batches, processing, status tracking          | [.doc.md](../app/domain/imports/.doc.md)    |
| `app/domain/robots/`     | Robot registration, authentication, batch processing | [.doc.md](../app/domain/robots/.doc.md)     |
| `app/migrations/`        | Alembic database migrations                          | -                                           |
| `app/persistence/`       | SQL, Elasticsearch, Blob storage layers              | [.doc.md](../app/persistence/.doc.md)       |
| `app/static/`            | Static data (taxonomies, data structures)            | -                                           |
| `app/system/`            | System-level services (dependencies, lifecycle)      | -                                           |
| `app/utils/`             | Shared utilities                                     | -                                           |

## `libs/` - Shared Libraries

| Folder                | Purpose                                                        | `.doc.md`                      |
| --------------------- | -------------------------------------------------------------- | ------------------------------ |
| `libs/sdk/`           | `destiny-sdk` PyPI package - Pydantic models, client utilities | [.doc.md](../libs/sdk/.doc.md) |
| `libs/eppi_importer/` | EPPI-Reviewer format importer                                  | -                              |
| `libs/fake_data/`     | Test data generation utilities                                 | -                              |
| `libs/samples/`       | Sample data files for testing                                  | -                              |

## `tests/` - Test Suite

| Folder               | Purpose                                  | `.doc.md`                   |
| -------------------- | ---------------------------------------- | --------------------------- |
| `tests/`             | Test infrastructure, fixtures, factories | [.doc.md](../tests/.doc.md) |
| `tests/unit/`        | Unit tests with fake repositories        | -                           |
| `tests/integration/` | Tests with real database                 | -                           |
| `tests/e2e/`         | End-to-end tests with testcontainers     | -                           |
| `tests/routers/`     | API router tests                         | -                           |

## `docs/` - Documentation

| Folder             | Purpose                                                       |
| ------------------ | ------------------------------------------------------------- |
| `docs/procedures/` | User-facing procedure guides (imports, search, robots, OAuth) |
| `docs/codebase/`   | Architecture and model documentation                          |
| `docs/sdk/`        | SDK usage documentation                                       |
| `docs/cli/`        | CLI usage documentation                                       |
| `docs/claude/`     | Claude-specific implementation guides                         |

## `cli/` - Command-Line Interface

Typer-based CLI for interacting with the DESTINY API. Used for robot registration, data operations, and administrative tasks.

## `ui/` - Frontend

Next.js application providing authentication UI and basic reference operations. Uses NextAuth for OAuth integration.

## `infra/` - Infrastructure

Terraform configurations and deployment scripts for Azure deployment.

## Key Configuration Files

| File                      | Purpose                                    |
| ------------------------- | ------------------------------------------ |
| `CLAUDE.md`               | Claude Code guidance and conventions       |
| `pyproject.toml`          | Python project configuration, dependencies |
| `docker-compose.yml`      | Local development stack                    |
| `.pre-commit-config.yaml` | Pre-commit hooks configuration             |
| `alembic.ini`             | Database migration configuration           |

## Common Starting Points

### "I need to fix a bug in..."

- **Reference handling** → `app/domain/references/service.py`
- **Deduplication** → `app/domain/references/services/deduplication_service.py`
- **Import processing** → `app/domain/imports/service.py`
- **Search** → `app/domain/references/repository.py` (ReferenceESRepository)
- **Robot batches** → `app/domain/references/services/enhancement_service.py`

### "I need to add a new..."

- **API endpoint** → Add to `app/domain/{domain}/routes.py`
- **Background task** → Add to `app/domain/{domain}/tasks.py`
- **SDK model** → Add to `libs/sdk/src/destiny_sdk/`
- **Database migration** → `uv run alembic revision --autogenerate -m "message"`

### "I need to understand..."

- **Domain models** → `app/domain/{domain}/models/models.py`
- **SQL schema** → `app/domain/{domain}/models/sql.py`
- **API contracts** → `libs/sdk/src/destiny_sdk/`
- **Test patterns** → `tests/.doc.md` and `tests/unit/domain/conftest.py`
