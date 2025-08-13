FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Copy from the cache instead of linking since it's a mounted volume
ENV UV_LINK_MODE=copy

COPY libs/sdk ./libs/sdk

# Install the project's dependencies using the lockfile and settings
ARG UV_INSTALL_DEV=false
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    if [ "$UV_INSTALL_DEV" = "true" ]; then \
        uv sync --locked --no-install-project --dev; \
        else \
        uv sync --locked --no-install-project --no-dev; \
        fi

# Then, add the rest of the project source code and install it
# Installing separately from its dependencies allows optimal layer caching
COPY app/ ./app
COPY alembic.ini uv.lock pyproject.toml ./

RUN --mount=type=cache,target=/root/.cache/uv \
    if [ "$UV_INSTALL_DEV" = "true" ]; then \
        uv sync --locked --dev; \
        else \
        uv sync --locked --no-dev; \
        fi


# Place executables in the environment at the front of the path
ENV PATH="/app/.venv/bin:$PATH"

# Reset the entrypoint, don't invoke `uv`
ENTRYPOINT []

EXPOSE 8001
CMD ["fastapi",  "run", "app/main.py", "--port", "8000"]
