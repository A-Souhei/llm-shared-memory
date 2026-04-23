# Biblion — Implementation Reference

> A persistent, semantic knowledge base for codebase understanding, built into an AI-assisted CLI (opencode/vuhitracode). This guide documents how Biblion works end-to-end: from API to storage, embedding, deduplication, scoring, and integration with LLM sessions.

---

## Table of Contents

1. [Overview](#1-overview)
2. [API Endpoints](#2-api-endpoints)
3. [Core Implementation](#3-core-implementation)
4. [Storage Backends](#4-storage-backends)
5. [Data Flow](#5-data-flow)
6. [Configuration](#6-configuration)
7. [Scoring & Ranking](#7-scoring--ranking)
8. [Canonicalization](#8-canonicalization)
9. [Metadata Storage](#9-metadata-storage)
10. [Deduplication](#10-deduplication)
11. [Credential Sanitization](#11-credential-sanitization)
12. [Multi-Project Support](#12-multi-project-support)
13. [Integration with LLM Sessions](#13-integration-with-llm-sessions)
14. [Memento Parallel System](#14-memento-parallel-system)
15. [Usage Examples](#15-usage-examples)
16. [Testing](#16-testing)
17. [Extension Points](#17-extension-points)

---

## 1. Overview

Biblion is a **global, semantic knowledge base** that lets AI agents capture and retrieve structured knowledge about codebases using vector embeddings. When agents explore a project they write findings to Biblion; when they start a new task they search Biblion to recover relevant context without re-exploring.

### Design Goals

- **Persistent** — survives across sessions; knowledge accumulates over time.
- **Semantic** — retrieval is by meaning, not exact keyword match.
- **Global** — one shared collection across all projects on the machine; every entry is tagged with its source project so knowledge can be shared or filtered per-project.
- **Backend-agnostic** — works with either Qdrant (vector DB) or Redis Stack (HNSW index). Switch by setting environment variables.
- **Safe by default** — content is sanitized of credentials before storage.

### High-Level Architecture

```
┌───────────────────────────────────────────────────────┐
│                   LLM / Agent Session                 │
│  biblion_write tool ──────────────► Biblion.write()   │
│  biblion_read permission ──────────► auto-injected    │
└────────────────────────────┬──────────────────────────┘
                             │ HTTP or in-process call
┌────────────────────────────▼──────────────────────────┐
│                    REST API (Hono)                    │
│  GET  /biblion/status                                 │
│  GET  /biblion/list                                   │
│  POST /biblion/search                                 │
│  POST /biblion/write                                  │
│  DELETE /biblion/clear                                │
│  DELETE /biblion/:id                                  │
└────────────────────────────┬──────────────────────────┘
                             │
┌────────────────────────────▼──────────────────────────┐
│              Biblion namespace (index.ts)              │
│  sanitize → canonicalize → embed → dedup → upsert    │
└──────────────┬────────────────────────┬───────────────┘
               │                        │
┌──────────────▼──────┐   ┌─────────────▼───────────────┐
│   Qdrant backend    │   │      Redis Stack backend     │
│  (default)          │   │  (preferred if REDIS_URL set)│
│  REST HTTP API      │   │  ioredis + FT.SEARCH / HNSW  │
└─────────────────────┘   └─────────────────────────────┘
               │                        │
┌──────────────▼────────────────────────▼───────────────┐
│         Embedding service (Ollama default)             │
│  POST /api/embeddings  →  float[] vector               │
└───────────────────────────────────────────────────────┘
```

### File Locations

| File                                                | Purpose                                         |
| --------------------------------------------------- | ----------------------------------------------- |
| `packages/opencode/src/biblion/index.ts`            | Core implementation — all logic lives here      |
| `packages/opencode/src/server/routes/biblion.ts`    | Hono REST routes                                |
| `packages/opencode/src/cache/scoring.ts`            | Shared scoring utilities (also used by Memento) |
| `packages/opencode/src/cache/canonicalize.ts`       | Content canonicalization and tag extraction     |
| `packages/opencode/src/project/vuhitra-settings.ts` | Settings persistence (`.vuhitra/settings.json`) |
| `packages/opencode/test/biblion/biblion.test.ts`    | Test suite                                      |
| `packages/docs/biblion.mdx`                         | End-user documentation                          |

---

## 2. API Endpoints

All endpoints are mounted under `/biblion`. The server typically runs on port `4096`.

### `GET /biblion/status`

Returns the current Biblion status.

**Response — ready:**

```json
{
  "type": "ready",
  "entry_count": 42,
  "token_count": 15000,
  "backend": "qdrant",
  "embedding_url": "http://localhost:11434",
  "embedding_model": "nomic-embed-text:latest",
  "backend_url": "http://localhost:6333"
}
```

**Response — disabled:**

```json
{
  "type": "disabled",
  "reason": "not_configured",
  "message": "biblion.enabled is false in settings"
}
```

Possible `reason` values: `not_configured` | `embedding_unreachable` | `backend_unreachable` | `error`

---

### `GET /biblion/list`

List stored entries. Optionally filter by project.

**Query params:**
| Param | Required | Description |
|-------|----------|-------------|
| `project_id` | No | Filter entries to a single project |

**Response:**

```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "type": "pattern",
    "tags": "pattern,typescript,error-handling",
    "content": "Error handling: wrap async ops in try-catch and log with context",
    "project_id": "my-api-service"
  }
]
```

Note: `project_path` is stripped from the response (internal field only).

---

### `POST /biblion/search`

Semantic similarity search over stored entries.

**Request body:**

```json
{
  "query": "authentication middleware",
  "limit": 5,
  "project_id": "my-api-service"
}
```

| Field        | Required | Default | Description                |
| ------------ | -------- | ------- | -------------------------- |
| `query`      | Yes      | —       | Natural language query     |
| `limit`      | No       | `5`     | Max results (1–100)        |
| `project_id` | No       | —       | Filter to specific project |

**Response:**

```json
[
  {
    "id": "550e8400-...",
    "type": "pattern",
    "content": "JWT verification middleware checks Authorization header...",
    "tags": ["pattern", "authentication", "typescript"],
    "score": 0.87
  }
]
```

`score` is a composite of similarity + usage frequency + quality (see §7).

---

### `POST /biblion/write`

Store a new knowledge entry.

**Request body:**

```json
{
  "type": "pattern",
  "content": "Error handling pattern: wrap all async operations in try-catch and log with context",
  "tags": ["error-handling", "async"],
  "session_id": "ses_abc123",
  "branch": "main"
}
```

| Field        | Required | Description                                                                             |
| ------------ | -------- | --------------------------------------------------------------------------------------- |
| `type`       | Yes      | Entry type: `structure` \| `pattern` \| `dependency` \| `api` \| `config` \| `workflow` |
| `content`    | Yes      | Knowledge text (max 50,000 chars). Sanitized automatically.                             |
| `tags`       | No       | Additional tags; merged with auto-generated tags                                        |
| `session_id` | No       | Session provenance                                                                      |
| `branch`     | No       | Git branch provenance                                                                   |

**Responses:**

- `200 { "success": true }` — written (or silently skipped as duplicate)
- `503 { "success": false, "reason": "not_configured" }` — Biblion not ready
- `500 { "success": false, "error": "Write failed" }` — unexpected error

---

### `DELETE /biblion/clear`

Delete entries by project or all entries.

**Query params:**
| Param | Required | Behavior |
|-------|----------|---------|
| `project_id` | No | If present, delete only that project's entries. If absent, delete **everything**. |

```bash
# Safe: delete only one project
DELETE /biblion/clear?project_id=my-api-service

# Dangerous: delete all entries from all projects
DELETE /biblion/clear
```

---

### `DELETE /biblion/:id`

Delete a single entry by UUID.

```bash
DELETE /biblion/550e8400-e29b-41d4-a716-446655440000
```

**Response:** `{ "success": true }` or `{ "success": false, "error": "..." }`

---

## 3. Core Implementation

All logic lives in `Biblion` namespace (`src/biblion/index.ts`). TypeScript namespaces act as modules here — no class instances, just exported functions over module-level state.

### `BiblionEntry` Interface

```typescript
interface BiblionEntry {
  type: "structure" | "pattern" | "dependency" | "api" | "config" | "workflow"
  content: string // Raw knowledge text
  branch: string // Git branch (provenance)
  session_id: string // Session that wrote this
  timestamp: number // Unix ms
  tags: string[] // Comma-joined when stored
  token_count: number // Estimated: ceil(content.length / 4)
  query?: string // Canonical query used for embedding
  answer?: string
  quality?: number // 0–1 (normalized from 0–10 user rating)
  used_count?: number // How many times retrieved
  created_at?: string // ISO timestamp
  problem?: string // Extracted for issue/resolution types
  context?: string
  solution?: string
  steps?: string[]
  project_id?: string // Auto-set from Instance.project.id
  project_path?: string // Auto-set from Instance.directory
}
```

### State Management

```typescript
const state = Instance.state<State>(
  () => ({ status: { type: "disabled", reason: "not_configured" }, redisClient: null, ... }),
  async (s) => { await s.redisClient?.quit() } // cleanup on Instance disposal
)
```

`Instance.state` is a per-project scoped state factory. State is reset when the project instance changes. This prevents stale state when switching projects.

### Core Functions

#### `Biblion.init()`

Called once at startup. Checks that both the embedding service and backend are reachable, ensures the vector collection/index exists, then transitions status to `"ready"`.

```
init()
  → checkServices()        # parallel health checks
  → store.ensureIndex()    # create collection if missing
  → store.count() + store.sumTokenCount()
  → status = { type: "ready", ... }
  → Bus.publish(Event.Updated, status)
```

If anything fails, status becomes `{ type: "disabled", reason: classifyReason(msg) }`.

#### `Biblion.write(entry)`

```
sanitize(content)
canonicalize(content, type, tags)   → { query, tags }
embed(query)                        → float[]
store.search(vector, 1)             → check for near-duplicate
if score >= dedupThreshold → skip
store.upsert([{ id, vector, payload }])
storeMetadata(id, ...)              # Redis meta key
Bus.publish(Event.Updated, ...)
Bus.publish(TuiEvent.ToastShow, ...)
return id
```

#### `Biblion.searchWithScores(query, topK, projectId?)`

```
embed(query)                        → float[]
store.search(vector, maxCandidates, projectId)
  → raw hits with similarity scores
fetch used_counts from Redis meta keys (parallel)
Scoring.scoreEntries(entries)       → sorted by composite score
incrementUsedCount(id) for top results  (non-blocking, fire-and-forget)
return top topK entries
```

#### `Biblion.search(query, topK)`

Thin wrapper over `searchWithScores` that formats results as strings:

```
[pattern] tags: auth,typescript
JWT verification middleware checks Authorization header...
```

#### `Biblion.list(projectId?)`

Passthrough to `store.list()`. Returns raw entries without re-ranking.

#### `Biblion.deleteEntry(id)`

Deletes from vector store, updates in-memory `entryCount`, publishes `Event.Updated`.

#### `Biblion.clear(projectId?)` / `Biblion.clearAll()`

`clear()` deletes entries for a specific project (defaults to `Instance.project.id`). `clearAll()` nukes everything. Both refresh counts from the store after deletion.

#### `Biblion.updateQuality(id, quality)`

Patches the `quality` field in-place without triggering deduplication. Used after user rates an entry via `Question.ask`.

---

## 4. Storage Backends

### Backend Selection

```typescript
function useRedis(): boolean {
  return !!(Env.get("REDIS_URL") || Env.get("REDIS_HOST"))
}

function activeBackend(): "qdrant" | "redis" {
  return useRedis() ? "redis" : "qdrant"
}
```

Redis takes priority when any Redis environment variable is set. Otherwise Qdrant is used.

A thin `store` dispatcher object forwards all calls to the active backend:

```typescript
const store = {
  ensureIndex, upsert, search, count, sumTokenCount,
  checkHealth, deleteAll, deleteByProject, delete, updateQuality, list
}
```

---

### Qdrant Backend

Qdrant is a standalone vector database with a REST API. Biblion communicates with it purely over HTTP — no SDK dependency.

**Collection:** `biblion_global` (single global collection, all projects share it)

**Initialization:**

```
GET /collections/biblion_global     → if 404, create it
PUT /collections/biblion_global     → { vectors: { size: dim, distance: "Cosine" } }
```

Dimension `dim` is determined by embedding a probe string and measuring the vector length. Result is cached in `_dimPromise`.

**Upsert:**

```
PUT /collections/biblion_global/points
Body: { points: [{ id: uuid, vector: float[], payload: { ... } }] }
```

**Search:**

```
POST /collections/biblion_global/points/search
Body: {
  vector: float[],
  limit: topK,
  with_payload: true,
  filter: { must: [{ key: "project_id", match: { value: projectId } }] }  // optional
}
```

Returns `{ result: [{ id, score, payload }] }` where `score` is cosine similarity (0–1).

**Scroll (for list/count/token-sum):**

Qdrant's scroll API pages through all points. Biblion iterates until `next_page_offset` is null.

**Delete:**

- Single: `POST /points/delete` with `{ points: [id] }`
- By project: `POST /points/delete` with `{ filter: { must: [...] } }`
- All: `POST /points/delete` with `{ filter: {} }`

**Quality update:**

```
POST /collections/biblion_global/points/payload
Body: { payload: { quality: 0.8 }, points: [id] }
```

---

### Redis Stack Backend

Redis Stack adds the `FT.SEARCH` module (RediSearch) and HNSW vector index support to standard Redis. Biblion uses `ioredis` and issues raw Redis commands via `client.call(...)`.

**Key structure:**

```
biblion_global:point:<uuid>   → HASH (all fields + binary vector)
biblion_global:meta:<uuid>    → HASH (used_count, quality, tags, query, ...)
```

**Index creation:**

```
FT.CREATE biblion_global
  ON HASH PREFIX 1 biblion_global:point:
  SCHEMA
    type        TAG
    tags        TEXT
    content     TEXT
    timestamp   NUMERIC
    token_count NUMERIC
    project_id  TAG
    project_path TEXT
    vector      VECTOR HNSW 6 TYPE FLOAT32 DIM <dim> DISTANCE_METRIC COSINE
```

The `HNSW 6` means HNSW algorithm with 6 construction params. If the index already exists the error is swallowed.

**Vector encoding:**

Vectors are stored as raw bytes (FLOAT32 little-endian):

```typescript
function encodeVector(vec: number[]): Buffer {
  const buf = Buffer.allocUnsafe(vec.length * 4)
  for (let i = 0; i < vec.length; i++) buf.writeFloatLE(vec[i], i * 4)
  return buf
}
```

**KNN Search:**

```
FT.SEARCH biblion_global
  "(*=>[KNN 50 @vector $vec AS score])"
  PARAMS 2 vec <binary-vector>
  RETURN 11 type tags content score quality used_count created_at query project_id project_path id
  SORTBY score
  DIALECT 2
```

With project filter:

```
"(@project_id:{my\-project})=>[KNN 50 @vector $vec AS score]"
```

**Score conversion:**

Redis KNN returns cosine _distance_ (0 = identical, 2 = opposite). Convert to similarity:

```typescript
const score = 1 - dist / 2
```

**Delete by project (Redis):**

Redis has no built-in delete-by-filter. Biblion uses FT.SEARCH to find keys in batches of 100, then `DEL`s them. Re-queries from offset 0 each time (safe because the matched set shrinks after each deletion).

**TAG escaping:**

RediSearch TAG fields require special characters to be backslash-escaped:

```typescript
function escapeRedisTag(val: string): string {
  return val.replace(/[,.<>{}\[\]"':;!@#$%^&*()\-+=~|/ \\]/g, "\\$&")
}
```

This applies to `project_id` values in KNN queries and FT.SEARCH filters.

---

## 5. Data Flow

### Write Operation

```
Agent calls biblion_write tool
         │
         ▼
  Biblion.write(entry)
         │
         ├─ sanitize(content)          Strip credentials from text
         │
         ├─ Canonicalize.createCanonicalResult(content, type, tags)
         │    ├─ extractQuery()        Build a canonical search query from content
         │    └─ extractTags()         Auto-detect languages, frameworks, concepts
         │
         ├─ embed(query)               POST /api/embeddings → float[]
         │
         ├─ store.search(vector, 1)    Find nearest neighbor
         │    └─ if score >= 0.95 → return undefined  (duplicate!)
         │
         ├─ store.upsert([point])      Write to Qdrant or Redis
         │
         ├─ storeMetadata(id, entry)   Write used_count/quality to Redis meta key
         │
         └─ Bus.publish(...)           Notify UI + update in-memory counts
```

### Search Operation

```
User or agent queries
         │
         ▼
  Biblion.searchWithScores(query, topK, projectId?)
         │
         ├─ embed(query)               POST /api/embeddings → float[]
         │
         ├─ store.search(vector, maxCandidates, projectId?)
         │    └─ Returns up to 50 candidates (configurable)
         │
         ├─ getUsedCount(id) × N       Fetch fresh counts from Redis meta keys (parallel)
         │
         ├─ Scoring.scoreEntries(hits)
         │    └─ score = sim*0.7 + normUsed*0.2 + normQuality*0.1
         │
         ├─ incrementUsedCount(id) × topK   (fire-and-forget, non-blocking)
         │
         └─ return top topK results
```

---

## 6. Configuration

### `.vuhitra/settings.json`

Biblion must be explicitly enabled:

```json
{
  "biblion": {
    "enabled": true
  }
}
```

All other cache tuning is also stored here:

| Key                       | Type    | Default | Description                                        |
| ------------------------- | ------- | ------- | -------------------------------------------------- |
| `biblion.enabled`         | boolean | `false` | Master switch                                      |
| `cache_similarity_weight` | 0–1     | `0.7`   | Weight of vector similarity in score               |
| `cache_usage_weight`      | 0–1     | `0.2`   | Weight of usage frequency in score                 |
| `cache_dedup_threshold`   | 0–1     | `0.95`  | Similarity above which writes are skipped          |
| `cache_min_similarity`    | 0–1     | `0.7`   | (Available for client filtering)                   |
| `cache_max_candidates`    | int     | `50`    | How many raw candidates to fetch before re-ranking |
| `cache_default_quality`   | 0–1     | `0.5`   | Initial quality when user doesn't rate             |

### Environment Variables

| Variable          | Default                   | Description                                    |
| ----------------- | ------------------------- | ---------------------------------------------- |
| `QDRANT_URL`      | `http://localhost:6333`   | Qdrant server URL                              |
| `QDRANT_API_KEY`  | —                         | Optional API key → sent as `api-key` header    |
| `REDIS_URL`       | —                         | Full Redis URL (takes priority over host/port) |
| `REDIS_HOST`      | `localhost`               | Redis hostname                                 |
| `REDIS_PORT`      | `6379`                    | Redis port                                     |
| `REDIS_PASSWORD`  | —                         | Redis auth password                            |
| `EMBEDDING_URL`   | `http://localhost:11434`  | Ollama (or compatible) server URL              |
| `EMBEDDING_MODEL` | `nomic-embed-text:latest` | Model used for embedding                       |

All config values are cached with module-level `let _x: T | undefined` + lazy init pattern — computed once on first call, never re-read from env mid-session.

### URL Sanitization

When status is reported or logged, URLs have credentials stripped:

```typescript
function safeUrl(raw: string): string {
  const u = new URL(raw)
  u.username = ""
  u.password = ""
  return u.toString()
}
```

This prevents `redis://:password@host:6379` from appearing in logs or the status response.

---

## 7. Scoring & Ranking

Scores are computed in `src/cache/scoring.ts` (shared with the Memento system).

### Formula

```
score = similarity × w_sim + normalizedUsedCount × w_use + normalizedQuality × w_qual
```

Default weights: `0.7 / 0.2 / 0.1` (overridable via settings).

### Components

**Similarity** (0–1): cosine similarity between the query embedding and the stored entry's embedding. This is the dominant signal.

**Normalized Used Count** (0–1): how often this entry has been retrieved. Uses log scale to prevent runaway dominance:

```typescript
function normalizeUsedCount(count: number, maxCount: number): number {
  return Math.log(1 + count) / Math.log(1 + maxCount)
}
```

`maxCount` is computed across all candidates in a single search call, so scores are relative within the result set.

**Normalized Quality** (0–1): user-provided rating, already normalized from 0–10 → 0–1 at write time.

### Ranking Process

```typescript
function scoreEntries<T>(entries: Array<{ entry: T; similarity: number }>): ScoredEntry<T>[] {
  const maxUsedCount = Math.max(1, ...entries.map((e) => e.entry.used_count ?? 0))
  const scored = entries.map((e) => ({
    entry: e.entry,
    score: calculateScore(e.similarity, e.entry.used_count, maxUsedCount, e.entry.quality),
    similarity: e.similarity,
    normalizedUsedCount: normalizeUsedCount(e.entry.used_count, maxUsedCount),
    normalizedQuality: Math.min(1, Math.max(0, e.entry.quality ?? 0.5)),
  }))
  return scored.sort((a, b) => b.score - a.score)
}
```

After ranking, `used_count` is incremented for the top-K results (fire-and-forget) so future searches benefit from the popularity signal.

---

## 8. Canonicalization

Before writing to the vector store, content is canonicalized by `Canonicalize.createCanonicalResult()` in `src/cache/canonicalize.ts`. This serves two purposes: (1) produce a compact, stable query string for embedding, and (2) auto-generate tags.

### Noise Removal

Before extraction, transient identifiers are stripped from content:

```
UUIDs, session IDs (ses_...), timestamps, URLs, emails, file paths, [REDACTED] markers
→ whitespace-normalized string
```

This ensures two entries with the same semantic content but different session IDs get similar embeddings (and are therefore caught by deduplication).

### Query Extraction

Each entry type produces its canonical query differently:

| Type                   | Strategy                                                      |
| ---------------------- | ------------------------------------------------------------- |
| `structure`            | CamelCase entity names (e.g. `UserSchema`) + inferred subtype |
| `pattern`              | kebab-case pattern names + inferred subtype                   |
| `issue` / `resolution` | First sentence of cleaned text (max 100 chars)                |
| `dependency`           | Package/module name tokens                                    |
| `api`                  | CamelCase or kebab names + "api" suffix                       |
| `config`               | `UPPER_CASE_KEYS` + "config" suffix                           |
| `workflow`             | First 6 meaningful words                                      |

All queries are truncated to 100 characters.

### Tag Extraction

Tags are auto-generated by scanning content for known vocabulary:

- **Languages**: typescript, javascript, python, rust, go, java, bash, sql, ...
- **Frameworks**: react, vue, next.js, express, django, drizzle, prisma, trpc, ...
- **Concepts**: async, authentication, caching, pagination, websocket, streaming, ...
- **Type tag**: always added first (e.g. `pattern`)
- **Inferred subtype**: e.g. `"error handling"` for patterns mentioning `error`

User-provided tags are merged with auto-generated tags; combined set is deduped and limited to 10.

### Additional Metadata Extraction

For `issue` / `resolution` types, the first and subsequent sentences are split into `problem` and `solution`.

For `procedure` / `workflow` types, comma/semicolon-delimited segments become `steps[]`.

---

## 9. Metadata Storage

Metadata (used_count, quality, tags, query, timestamps) is tracked differently per backend.

### Qdrant

All metadata is stored as part of the point's `payload`. Quality updates use Qdrant's partial payload update endpoint. `used_count` is stored in payload but not atomically incremented — Biblion reads then writes (acceptable for low-concurrency CLI use).

### Redis

Redis uses two separate hash keys per entry:

```
biblion_global:point:<uuid>   →  main entry (content, vector, all fields)
biblion_global:meta:<uuid>    →  metadata sidecar (used_count, quality, tags, query, ...)
```

The sidecar exists because:

- `used_count` needs atomic increment (`HINCRBY`) without triggering a full vector re-index.
- Quality updates need to sync to both the point hash (for FT.SEARCH projection) and the meta hash.

During search, fresh `used_count` values are fetched from meta keys in parallel:

```typescript
const usedCounts = useRedis()
  ? await Promise.all(hits.map((h) => getUsedCount(h.id)))
  : hits.map((h) => h.used_count ?? 0)
```

This ensures ranking always uses the latest count, not a stale value baked into the index.

---

## 10. Deduplication

Before writing, Biblion checks for near-duplicate entries:

```typescript
const similar = await store.search(vector, 1)
if (similar.length > 0 && similar[0].score >= VuHitraSettings.cacheDedupThreshold()) {
  log.info("dedup: biblion entry skipped (duplicate)", { score: similar[0].score })
  return // skip write, return undefined
}
```

**Threshold**: `0.95` by default (configurable). At 0.95 cosine similarity, two texts are nearly identical in meaning.

**Why embed the canonical query (not the raw content)?**

Deduplication compares the embedding of the _canonical query_ — the compact, noise-free form of the content. This means two entries with the same knowledge but written differently (different verbosity, different session IDs in the text) will still be caught as duplicates.

**What happens to callers when a duplicate is detected?**

`write()` returns `undefined`. The REST route returns `{ success: true }` (the skip is silent — the entry is already there). The `WriteTool` returns `"Biblion entry was not stored (duplicate or error)."`.

---

## 11. Credential Sanitization

All content is sanitized before embedding or storage via `Biblion.sanitize()`.

### What Gets Redacted

| Pattern                                | Replacement              | Example                                 |
| -------------------------------------- | ------------------------ | --------------------------------------- |
| `ENV_VAR=value` where key looks secret | `[REDACTED]`             | `API_KEY=abc123` → `API_KEY=[REDACTED]` |
| `Bearer <token>`                       | `Bearer [REDACTED]`      | JWT tokens in Authorization headers     |
| `Basic <token>`                        | `Basic [REDACTED]`       | Base64 credentials                      |
| 32+ character hex strings              | `[REDACTED]`             | API keys, hashes                        |
| 40+ character base64 strings           | `[REDACTED]`             | Encoded secrets                         |
| PEM private keys                       | `[REDACTED_PRIVATE_KEY]` | `-----BEGIN RSA PRIVATE KEY-----...`    |

### Secret Key Patterns Matched

The regex matches environment variable names matching:

- Uppercase + underscore + `TOKEN|SECRET|KEY|PASSWORD|PASSWD|PWD|CREDENTIAL|CERT|PRIVATE`
- Or explicit names: `API_KEY`, `ACCESS_KEY`, `SECRET_KEY`, `AUTH_TOKEN`, `PRIVATE_KEY`

### What Is Preserved

- Short identifiers (< 32 chars) that aren't in secret positions
- Normal prose and code
- UUIDs (8 chars per segment, total 36 chars with dashes — below the 32-char hex threshold)

### Why Sanitize Before Embedding?

Embedding happens on the canonical query, but the raw `content` is also stored in the payload. Sanitizing first ensures that even if the storage backend is compromised, credentials are not readable from payload fields.

---

## 12. Multi-Project Support

### Single Collection, Multiple Projects

All projects write to `biblion_global`. Each entry automatically records:

```typescript
payload.project_id = Instance.project.id // e.g. "my-api-service"
payload.project_path = Instance.directory // e.g. "/home/user/projects/my-api-service"
```

`project_path` is stored internally but stripped before returning through the REST API.

### Filtering

Both search and list support `project_id` filtering, pushed down to the backend:

**Qdrant:**

```json
{ "filter": { "must": [{ "key": "project_id", "match": { "value": "my-api-service" } }] } }
```

**Redis:**

```
(@project_id:{my\-api\-service})=>[KNN 50 @vector $vec AS score]
```

### Cross-Project Knowledge Sharing

Searching _without_ a `project_id` filter returns results from all projects. This is intentional — an agent working on project B can discover patterns that were established in project A.

### Safe Clearing

`Biblion.clear(projectId)` deletes only entries tagged with that project. Other projects' knowledge is untouched. `Biblion.clearAll()` is a separate, explicit operation.

---

## 13. Integration with LLM Sessions

### `biblion_write` Tool

Agents call `biblion_write` explicitly to record knowledge:

```typescript
export const WriteTool = Tool.define("biblion_write", {
  description: "Write an entry to the biblion knowledge base...",
  parameters: z.object({
    type: z.enum(["structure", "pattern", ...]),
    content: z.string(),
    tags: z.array(z.string()).optional(),
    quality: z.number().min(0).max(10).optional(),
  }),
  async execute(params, ctx) { ... }
})
```

After writing, the tool uses `Question.ask()` to prompt the user for a quality rating (0–10). The rating is then applied via `updateQuality()` without re-triggering deduplication.

Quality scale: `0 = poor`, `5 = average (default)`, `10 = excellent`. Stored normalized as `quality/10` (0–1).

### `biblion_read` Permission

`biblion_read` is **not a callable tool** — it is a permission. When a session is granted this permission, the system automatically injects relevant Biblion results into the session's context window before the model responds. Agents do not call a tool to read; the injection happens transparently.

This is architecturally important: read is passive (context injection) while write is active (explicit tool call).

### Bus Events

Biblion publishes two bus events:

| Event             | Payload                       | Use                                   |
| ----------------- | ----------------------------- | ------------------------------------- |
| `biblion.updated` | `BiblionStatus`               | UI refresh (entry count, token count) |
| `tui.toast.show`  | `{ title, message, variant }` | Toast notification in TUI             |

---

## 14. Memento Parallel System

Biblion has a sibling system called **Memento** for operational/procedural agent memory.

| Dimension       | Biblion                                               | Memento                                                             |
| --------------- | ----------------------------------------------------- | ------------------------------------------------------------------- |
| **Purpose**     | Codebase knowledge (structure, patterns, APIs)        | Agent operations (commands, fixes, logs)                            |
| **Entry types** | structure, pattern, dependency, api, config, workflow | issue, resolution, finding, command, procedure, script, branch, log |
| **Audience**    | Future agents exploring the same codebase             | Future agents facing the same operational task                      |
| **Lifetime**    | Long-lived (accumulated project knowledge)            | Medium-lived (operational procedures)                               |
| **Backend**     | Same: Qdrant or Redis Stack                           | Same: Qdrant or Redis Stack                                         |
| **Tool**        | `biblion_write`                                       | `memento_write`                                                     |
| **Read**        | `biblion_read` permission (auto-inject)               | `memento_read` permission (auto-inject)                             |

Both share the `Scoring` and `Canonicalize` utilities. The scoring formula and deduplication logic are identical. The difference is purely semantic — what kind of knowledge belongs in each.

---

## 15. Usage Examples

### curl Examples

```bash
# Check if Biblion is ready
curl http://localhost:4096/biblion/status

# Write a pattern entry
curl -X POST http://localhost:4096/biblion/write \
  -H "Content-Type: application/json" \
  -d '{
    "type": "pattern",
    "content": "Repository pattern: all DB access goes through src/db/repos/. Never query DB directly from route handlers.",
    "tags": ["architecture", "database", "typescript"]
  }'

# Search for authentication-related knowledge
curl -X POST http://localhost:4096/biblion/search \
  -H "Content-Type: application/json" \
  -d '{"query": "how is authentication handled", "limit": 3}'

# Search scoped to one project
curl -X POST http://localhost:4096/biblion/search \
  -H "Content-Type: application/json" \
  -d '{"query": "error handling", "limit": 5, "project_id": "my-api-service"}'

# List all entries for a project
curl "http://localhost:4096/biblion/list?project_id=my-api-service"

# Delete a specific entry
curl -X DELETE http://localhost:4096/biblion/550e8400-e29b-41d4-a716-446655440000

# Clear all entries for a project
curl -X DELETE "http://localhost:4096/biblion/clear?project_id=my-api-service"
```

### Docker Compose for Local Development

```yaml
services:
  qdrant:
    image: qdrant/qdrant:latest
    ports: ["6333:6333"]

  ollama:
    image: ollama/ollama:latest
    ports: ["11434:11434"]
    # Pull the embedding model first:
    # docker exec ollama ollama pull nomic-embed-text
```

With Redis Stack instead:

```yaml
services:
  redis:
    image: redis/redis-stack:latest
    ports: ["6379:6379"]
```

Set environment variable: `REDIS_URL=redis://localhost:6379`

### Programmatic Usage (TypeScript)

```typescript
import { Biblion } from "@/biblion"
import { Instance } from "@/project/instance"

await Instance.provide({
  directory: "/my/project",
  fn: async () => {
    Biblion.init()

    // Wait for ready (in practice: subscribe to Bus event)
    await new Promise((r) => setTimeout(r, 2000))

    // Write
    await Biblion.write({
      type: "pattern",
      content: "All async handlers use the AsyncLocalStorage context for request tracing.",
      tags: ["async", "tracing"],
      session_id: "ses_abc",
      branch: "main",
      timestamp: Date.now(),
    })

    // Search
    const results = await Biblion.searchWithScores("request tracing")
    console.log(results[0].content, "score:", results[0].score)
  },
})
```

---

## 16. Testing

Tests live in `packages/opencode/test/biblion/biblion.test.ts`. Run from the package directory:

```bash
cd packages/opencode
bun test test/biblion
```

### Test Strategy

Tests avoid mocks and test actual implementation. Two categories:

**Pure function tests** (no Instance/backend required):

```
Biblion.sanitize()      — credential redaction patterns
Biblion.classifyReason() — error message classification
```

These run without any external services.

**State-dependent tests** (require Instance context, no backend):

All state-dependent tests wrap in `Instance.provide({ directory: tmpdir })` to get a fresh, isolated state. Since Biblion is disabled by default (no `biblion.enabled: true` in settings), these tests verify graceful degradation:

- `search()` returns `[]` when disabled
- `searchWithScores()` returns `[]` when disabled
- `clearAll()` resolves without throwing
- `list()` returns `[]` when disabled
- `status()` returns `{ type: "disabled" }`

### What's Not Tested

Integration tests against live Qdrant/Redis are not in the test suite. The architecture is structured so pure functions can be tested in isolation and backend behavior is covered by the backend's own test suite.

### Test Fixture

```typescript
import { tmpdir } from "../fixture/fixture"

test("example", async () => {
  await using tmp = await tmpdir() // auto-cleanup via Symbol.asyncDispose
  await Instance.provide({
    directory: tmp.path,
    fn: async () => {
      // test here
    },
  })
})
```

---

## 17. Extension Points

### Adding a New Storage Backend

1. Implement the backend object with these methods:

```typescript
const myBackend = {
  async ensureIndex(signal?: AbortSignal): Promise<void>,
  async upsert(points: { id: string; vector: number[]; payload: Record<string, unknown> }[]): Promise<void>,
  async search(vector: number[], topK: number, projectId?: string): Promise<SearchHit[]>,
  async count(): Promise<number>,
  async sumTokenCount(): Promise<number>,
  async checkHealth(signal?: AbortSignal): Promise<void>,
  async deleteAll(): Promise<void>,
  async deleteByProject(projectId: string): Promise<void>,
  async delete(id: string): Promise<void>,
  async updateQuality(id: string, quality: number): Promise<void>,
  async list(projectId?: string): Promise<ListEntry[]>,
}
```

2. Add a detection condition to `useMyBackend()`.
3. Add it to the `store` dispatcher alongside `qdrant` and `redis`.
4. Add the relevant environment variables to the config table.

### Modifying the Scoring Formula

Edit `src/cache/scoring.ts`. The `calculateScore` function is stateless and pure:

```typescript
export function calculateScore(
  similarity: number,
  usedCount: number,
  maxUsedCount: number,
  quality: number,
  options?: { similarityWeight?: number; usageWeight?: number; qualityWeight?: number },
): number
```

Weights can be adjusted globally (by changing the `DEFAULT_*` constants) or per-call (via `options`), or exposed through additional VuHitraSettings keys.

### Adding New Entry Types

1. Add the new type to the `EntryType` union in `index.ts`.
2. Add a case in `Canonicalize.extractQuery()` for how to extract a canonical query from that type.
3. Add tagging/metadata extraction logic in `Canonicalize.createCanonicalResult()` if needed.
4. Update the Zod enum in `WriteTool` parameters and the REST route validator.

### Changing the Embedding Model

Set `EMBEDDING_MODEL` environment variable. The model must expose the Ollama `/api/embeddings` API. The vector dimension is auto-detected on first use — changing the model requires clearing the existing collection (the stored vectors will be incompatible).

### Extending Canonicalize Tag Vocabularies

`LANGUAGES`, `FRAMEWORKS`, and `CONCEPTS` arrays in `src/cache/canonicalize.ts` are plain string lists. Add entries to detect new keywords in content. The matching is case-insensitive word-boundary regex.

### Disabling Dedup Entirely

Set `cache_dedup_threshold` to `1.0` — no entry will ever reach 100% similarity with an existing one (even identical text has fractional float rounding differences), so all writes go through.

---

_Generated from source: `packages/opencode/src/biblion/index.ts` (1365 lines), `src/server/routes/biblion.ts`, `src/cache/scoring.ts`, `src/cache/canonicalize.ts`, `src/project/vuhitra-settings.ts`._
