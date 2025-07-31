FROM python:3.12-slim-bookworm AS base
WORKDIR /app

FROM base AS builder

RUN pip install poetry poetry-plugin-bundle
COPY pyproject.toml poetry.lock README.md ./
COPY libs/sdk ./libs/sdk

ARG POETRY_INSTALL_DEV=false
RUN if [ "$POETRY_INSTALL_DEV" = "true" ]; then \
    poetry bundle venv --without docs --with dev /app/.venv; \
    else \
    poetry bundle venv --only=main /app/.venv; \
    fi

FROM base AS final
COPY --from=builder /app/.venv /app/.venv

COPY app/ ./app
COPY alembic.ini .
COPY pyproject.toml .
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000
ENTRYPOINT ["fastapi",  "run", "app/main.py", "--port", "8000"]
