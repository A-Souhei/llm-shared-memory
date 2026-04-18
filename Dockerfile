FROM python:3.12-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency files first (cache layer)
COPY pyproject.toml uv.lock* ./

# Install dependencies (cached unless pyproject.toml changes)
RUN uv sync --no-dev --frozen || uv sync --no-dev

# Copy source
COPY biblion/ ./biblion/

# Expose app port
EXPOSE 18765

CMD ["uv", "run", "biblion"]
