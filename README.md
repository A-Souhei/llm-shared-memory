# Biblion

Persistent semantic knowledge base for LLM agents. Backed by Redis and Ollama embeddings.

## Quick Start

```bash
# Install dependencies
uv sync

# Run the server (default port: 18765)
uv run biblion
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| REDIS_URL | redis://localhost:6379 | Redis endpoint |
| COLLECTION_PREFIX | biblion | Prefix for Redis key namespacing |
| EMBEDDING_URL | http://localhost:11434 | Ollama-compatible embedding server |
| EMBEDDING_MODEL | nomic-embed-text:latest | Embedding model name |
| DEDUP_THRESHOLD | 0.95 | Cosine similarity threshold for deduplication |
| SEARCH_MIN_SCORE | 0.45 | Minimum score threshold for search results |
| MAX_CANDIDATES | 50 | Max search results before re-ranking |
| SIMILARITY_WEIGHT | 0.7 | Weight for similarity in scoring |
| USAGE_WEIGHT | 0.2 | Weight for usage count in scoring |
| QUALITY_WEIGHT | 0.1 | Weight for quality in scoring |
| DEFAULT_QUALITY | 0.5 | Default quality (0–1) when not specified |
| SLACK_WEBHOOK_URL | _(none)_ | Optional Slack webhook for notifications |
| HOST | 0.0.0.0 | Server host |
| PORT | 18765 | Server port |

## API Endpoints

### Knowledge Base (`/biblion`)

| Method | Path | Description |
|---|---|---|
| GET | /health | Health check |
| GET | /biblion/status | Service readiness status |
| GET | /biblion/list | List entries (optional: ?project_id=&type=) |
| POST | /biblion/search | Search entries by query |
| POST | /biblion/write | Write a new entry |
| DELETE | /biblion/clear | Clear entries (optional: ?project_id=) |
| DELETE | /biblion/{id} | Delete a specific entry |

### Bridge (`/bridge`)

Multi-agent coordination over Redis pub/sub.

| Method | Path | Description |
|---|---|---|
| GET | /bridge/session | Resolve session_id to bridge_id |
| POST | /bridge/set-master | Register as master node |
| POST | /bridge/set-friend | Join a bridge as friend node |
| POST | /bridge/leave | Leave the bridge |
| POST | /bridge/heartbeat | Send keepalive ping |
| GET | /bridge/info | List all nodes and their status |
| POST | /bridge/push-task | Queue a task for a friend node |
| GET | /bridge/tasks | Fetch pending tasks (friend) |
| POST | /bridge/share-context | Push a finding/result to shared context |
| GET | /bridge/context | Read recent shared context entries |

### Memento (`/biblion/memento`)

Session snapshots, scoped per project, stored without deduplication.

| Method | Path | Description |
|---|---|---|
| POST | /biblion/memento/save | Save a session memento |
| GET | /biblion/memento/list | List mementos for a project (newest first) |
| DELETE | /biblion/memento/clear | Delete all mementos for a project |

### Code Indexer (`/indexer`)

Semantic search over indexed source code.

| Method | Path | Description |
|---|---|---|
| GET | /indexer/status | Indexer readiness status |
| GET | /indexer/projects | List indexed projects with stats |
| GET | /indexer/progress | Active indexing job progress |
| POST | /indexer/ingest | Ingest files into the code index |
| POST | /indexer/search | Semantic search over indexed code |
| DELETE | /indexer/clear | Clear index for a project |

## Memento

Mementos are session snapshots an agent saves before context compaction. They capture process — commands run, workflow steps, decisions, what to avoid — so the next session can pick up where the last one left off.

MCP tools:

| Tool | Description |
|---|---|
| `memento_save` | Save a distilled session to the knowledge base |
| `memento_load` | Load recent mementos for a project (newest first) |
| `memento_clear` | Delete all mementos for a project (irreversible) |

## Entry Types

- `structure` — Codebase architecture, module layouts, directory patterns
- `pattern` — Design patterns, conventions, best practices
- `dependency` — Library versions, imports, package information
- `api` — API signatures, function references, method definitions
- `config` — Configuration files, environment setup, deployment settings
- `workflow` — Procedures, processes, common tasks, multi-step patterns

## Docker Compose

All services are defined in `docker-compose.yml`. A `.env` file is needed for Tailscale:

```bash
# .env
TS_AUTHKEY=tskey-auth-...
```

Start everything:

```bash
docker compose up -d
```

Services:

| Service | Port | Description |
|---|---|---|
| qdrant | 6333/6334 | Vector DB (used by indexer) |
| ollama | 11434 | Embedding model server (GPU-accelerated) |
| redis | 23790 | Primary storage backend (redis-stack) |
| biblion | 18765 | REST API server |
| webui | 18766 | Web dashboard |
| ts-biblion | — | Tailscale sidecar for biblion |
| ts-webui | — | Tailscale sidecar for webui |

## MCP Server

The `biblion-mcp` CLI exposes all tools to any MCP-compatible agent. See `MCP_SETUP.md` for full setup instructions.

```bash
# Install (once)
uv sync

# Add to Claude Code
claude mcp add biblion -- biblion-mcp

# Point at a remote server
claude mcp add biblion -e BIBLION_API_URL=http://my-server:18765 -- biblion-mcp
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

The biblion service always starts successfully. If Redis or the embedding server is unreachable at startup, the service will remain operational but write and search endpoints will return HTTP 503 until connectivity is restored. The `/biblion/status` endpoint always responds and indicates the current readiness state.
