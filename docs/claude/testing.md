# Testing Guide

This document provides guidance for working with tests in the DESTINY Repository.

## Test Organization

```text
tests/
    conftest.py          # Main fixtures (database, ES, auth mocks)
    factories.py         # factory_boy factories for test data
    unit/
        domain/
            conftest.py  # FakeRepository, FakeUnitOfWork
            references/  # Reference domain tests
            imports/     # Import domain tests
        persistence/     # Persistence layer tests
    integration/         # Tests with real database
    e2e/                 # End-to-end tests (testcontainers)
    routers/             # API router tests
```

## Running Tests

```bash
# Run all tests (excludes e2e by default)
uv run pytest

# Run a single test file
uv run pytest tests/unit/domain/references/services/test_deduplication_service.py

# Run a single test
uv run pytest tests/unit/domain/references/services/test_deduplication_service.py::test_function_name

# Run e2e tests (requires Docker)
uv run pytest tests/e2e --log-cli-level info

# Run with coverage
uv run pytest --cov=app
```

## Factories

Located in `tests/factories.py`. Uses `factory_boy` with `Faker`.

### Key Factories

| Factory                                   | Model                              | Notes                                            |
| ----------------------------------------- | ---------------------------------- | ------------------------------------------------ |
| `ReferenceFactory`                        | `Reference`                        | Creates reference with identifiers, enhancements |
| `RobotFactory`                            | `Robot`                            | Creates robot with credentials                   |
| `PendingEnhancementFactory`               | `PendingEnhancement`               | For testing enhancement processing               |
| `DOIIdentifierFactory`                    | `DOIIdentifier`                    | Uses Faker's doi provider                        |
| `OpenAlexIdentifierFactory`               | `OpenAlexIdentifier`               | Generates W-prefixed IDs                         |
| `BibliographicMetadataEnhancementFactory` | `BibliographicMetadataEnhancement` | Title, authors, year, etc.                       |

### Usage Example

```python
from tests.factories import ReferenceFactory, DOIIdentifierFactory

# Create a reference with default values
reference = ReferenceFactory()

# Create with specific values
reference = ReferenceFactory(
    identifiers=[
        LinkedExternalIdentifier(identifier=DOIIdentifierFactory())
    ]
)
```

## Fake Repository and Unit of Work

Located in `tests/unit/domain/conftest.py`.

### FakeRepository

In-memory repository mock for unit tests. Implements standard repository methods (`add`, `get_by_pk`, `update_by_pk`, `delete_by_pk`).

```python
@pytest.fixture
def fake_repo():
    return FakeRepository(init_entries=[existing_reference])
```

### FakeUnitOfWork

Wraps FakeRepository instances for testing services.

```python
@pytest.fixture
def fake_sql_uow(fake_repo):
    return FakeUnitOfWork(references=fake_repo)
```

## Fixtures

### Main conftest.py (`tests/conftest.py`)

- Database session fixtures
- Elasticsearch client fixtures
- Authentication/authorization mocks
- Test client fixtures

### Domain conftest.py (`tests/unit/domain/conftest.py`)

- `FakeRepository` class
- `FakeUnitOfWork` class
- Factory-based fixtures for common test data

## Writing New Tests

1. **Unit tests**: Use `FakeRepository` and `FakeUnitOfWork` to isolate business logic
2. **Integration tests**: Use real database fixtures from `tests/conftest.py`
3. **E2E tests**: Use testcontainers (requires Docker)

### Conventions

- Test files match source files: `service.py` -> `test_service.py`
- Use `pytest.mark.asyncio` for async tests
- Prefer factories over manual model construction
