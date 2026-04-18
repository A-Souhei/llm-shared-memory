# Biblion

Persistent semantic knowledge base for LLM agents. Backed by Qdrant vector DB and Ollama embeddings.

## Quick Start

```bash
# Install dependencies
uv sync

# Run the server (defaults: localhost:8765)
uv run biblion
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| QDRANT_URL | http://localhost:6333 | Qdrant endpoint |
| QDRANT_API_KEY | _(none)_ | Optional Qdrant API key |
| EMBEDDING_URL | http://localhost:11434 | Ollama-compatible embedding server |
| EMBEDDING_MODEL | nomic-embed-text | Embedding model name |
| DEDUP_THRESHOLD | 0.95 | Cosine similarity threshold for deduplication |
| MAX_CANDIDATES | 20 | Max search results before re-ranking |
| SIMILARITY_WEIGHT | 0.7 | Weight for similarity in scoring |
| USAGE_WEIGHT | 0.2 | Weight for usage count in scoring |
| QUALITY_WEIGHT | 0.1 | Weight for quality in scoring |
| DEFAULT_QUALITY | 5 | Default quality (0–10) when not specified |
| HOST | 0.0.0.0 | Server host |
| PORT | 8765 | Server port |

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | /health | Health check |
| GET | /biblion/status | Service readiness status |
| GET | /biblion/list | List entries (optional: ?project_id=&type=) |
| POST | /biblion/search | Search entries by query |
| POST | /biblion/write | Write a new entry |
| DELETE | /biblion/clear | Clear entries (optional: ?project_id=) |
| DELETE | /biblion/{id} | Delete a specific entry |

## Entry Types

The following entry types are supported:

- `structure` — Codebase architecture, module layouts, directory patterns
- `pattern` — Design patterns, conventions, best practices
- `dependency` — Library versions, imports, package information
- `api` — API signatures, function references, method definitions
- `config` — Configuration files, environment setup, deployment settings
- `workflow` — Procedures, processes, common tasks, multi-step patterns

## Docker Compose

```yaml
services:
  qdrant:
    image: qdrant/qdrant:latest
    ports:
      - "6333:6333"
    volumes:
      - qdrant_data:/qdrant/storage

  biblion:
    build: .
    ports:
      - "8765:8765"
    environment:
      QDRANT_URL: http://qdrant:6333
      EMBEDDING_URL: http://host.docker.internal:11434
    depends_on:
      - qdrant

volumes:
  qdrant_data:
```

## Dockerfile

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY . .
RUN uv sync --no-dev
CMD ["uv", "run", "biblion"]
```

## Service Status & Startup Behavior

The biblion service always starts successfully. If Qdrant or the embedding server is unreachable at startup, the service will remain operational but all write and search endpoints will return HTTP 503 (Service Unavailable) until connectivity is restored. The `/biblion/status` endpoint always responds and indicates the current readiness state.

## Bridge Mode (Coming Soon)

Bridge mode (Redis pub/sub multi-agent coordination) is planned — see `BRIDGE_MODE_IMPLEMENTATION.md`.
