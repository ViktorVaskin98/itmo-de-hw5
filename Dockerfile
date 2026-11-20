FROM python:3.13-slim AS build

COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-editable

FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PATH=/opt/venv/bin:$PATH

COPY --from=build /opt/venv /opt/venv
RUN useradd --uid 10001 --create-home hhlake && install -d -o hhlake /work
USER 10001
RUN python -c "import duckdb; duckdb.connect().execute('INSTALL httpfs')"

WORKDIR /work
CMD ["python", "-m", "hhlake.mapreduce", "--help"]
