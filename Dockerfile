FROM python:3.12-slim-bookworm AS base
WORKDIR /src

FROM base AS builder
RUN pip install poetry poetry-plugin-bundle
COPY pyproject.toml poetry.lock README.md ./
RUN poetry bundle venv --only=main /venv

FROM base AS final
COPY --from=builder /venv /venv
COPY app/ ./app
COPY alembic.ini .
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000
ENTRYPOINT ["/venv/bin/fastapi", "run", "app/main.py", "--port", "8000"]
