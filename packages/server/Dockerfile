# The signalfloor API. The same image runs the HTTP server, the background worker and the
# database migrations. The command picks which. Build it from the repository root:
#
#   docker build -f packages/server/Dockerfile -t signalfloor-server .

FROM python:3.13-slim@sha256:2d44738ebf4ce5f63b9d9ea871e9c7cfdc0426f7b0c97cac915fd88ded1d86bb AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# Dependencies first, so a code change doesn't reinstall them. uv needs every workspace
# member's pyproject.toml to read the lock file, including the agent's, which isn't installed.
COPY pyproject.toml uv.lock ./
COPY packages/signalfloor/pyproject.toml packages/signalfloor/
COPY packages/server/pyproject.toml packages/server/
COPY packages/agent/pyproject.toml packages/agent/
RUN uv sync --locked --no-dev --package signalfloor-server --no-install-workspace

COPY packages/signalfloor packages/signalfloor
COPY packages/server packages/server
# --no-editable copies our packages into the virtual environment, so the runtime stage needs
# nothing but the environment.
RUN uv sync --locked --no-dev --package signalfloor-server --no-editable

FROM python:3.13-slim@sha256:2d44738ebf4ce5f63b9d9ea871e9c7cfdc0426f7b0c97cac915fd88ded1d86bb
RUN useradd --system --uid 10001 --no-create-home signalfloor
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1
USER 10001
EXPOSE 8000
ENTRYPOINT ["signalfloor-server"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
