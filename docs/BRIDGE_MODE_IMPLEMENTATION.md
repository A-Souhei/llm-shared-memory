# Bridge Mode Implementation Guide

**Last Updated:** 2026-04-18  
**Status:** Technical Reference (v1.0)  
**Audience:** Developers, architects, operators  
**Scope:** Complete technical documentation for bridge mode implementation

> Bridge Mode enables distributed multi-agent coordination by linking multiple Alice instances across terminals and machines via Redis. This guide covers architecture, implementation, operations, and extension.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [Initialization & Setup](#3-initialization--setup)
4. [Node Management](#4-node-management)
5. [Redis Key Structure](#5-redis-key-structure)
6. [Database Schema](#6-database-schema)
7. [Task Routing & Delegation](#7-task-routing--delegation)
8. [Message Protocol](#8-message-protocol)
9. [State Management](#9-state-management)
10. [Error Handling](#10-error-handling)
11. [Configuration](#11-configuration)
12. [API Endpoints](#12-api-endpoints)
13. [CLI Integration](#13-cli-integration)
14. [Tool Integration](#14-tool-integration)
15. [Cross-Machine Support](#15-cross-machine-support)
16. [Security Model](#16-security-model)
17. [Workflow Examples](#17-workflow-examples)
18. [Limitations & Design Constraints](#18-limitations--design-constraints)
19. [Extension Points](#19-extension-points)
20. [Troubleshooting](#20-troubleshooting)

---

## 1. Overview

### What Is Bridge Mode?

Bridge mode links multiple opencode/vuhitracode CLI instances — on the same machine or across a network — into a single coordinated multi-agent session. One instance is designated the **master** (the human's terminal), and one or more are **friends** (subordinate workers). The master's Alice agent can dispatch tasks to friends, which run their own Alice agents in isolation on different directories.

From the user's perspective, bridge mode extends Alice's reach from one codebase to many. Alice on the master becomes a coordinator that can "reach into" other terminals and get work done there, then receive the results inline.

### Design Goals

| Goal                       | How It's Achieved                                                     |
| -------------------------- | --------------------------------------------------------------------- |
| **Transparent delegation** | Tasks dispatched to friends return inline — no "check back later"     |
| **Isolation**              | Friends run in sandboxed sessions scoped to their own directory       |
| **Resilience**             | Heartbeat-based liveness — no hard connection required                |
| **Simplicity**             | Redis as the only coordination primitive; no direct TCP between nodes |
| **Cross-machine**          | HTTP for task dispatch; Redis for pub/sub and state                   |

### Problem Statement

Traditional Alice operates on a single codebase in a single directory. In monorepos or multi-service projects, developers often need coordination across multiple codebases:

```
Before Bridge Mode:
  User at ~/frontend$ opencode
  Alice can only work on frontend

  (separate terminal needed for backend)
  User at ~/backend$ opencode
  Alice can only work on backend

After Bridge Mode:
  User at ~/frontend$ opencode --bridge master
  Alice now orchestrates work across multiple projects

  Friend at ~/backend$ opencode --bridge friend --bridge-id <master-id>
  Alice executes tasks received from master
```

Bridge Mode solves this by making Alice a distributed coordinator.

### Use Cases

- **Monorepo coordination**: Master on `packages/frontend`, friend on `packages/backend` — Alice can make changes to both simultaneously.
- **Cross-project work**: Different repos on different machines, delegated to the appropriate specialist.
- **Parallel execution**: Multiple friends working on independent subtasks simultaneously.
- **Multi-machine CI-like workflows**: Master orchestrates, friends execute in their environments.

---

## 2. Architecture

### High-Level System Design

```
┌────────────────────────────────────────────────────────────────────┐
│                      BRIDGE SESSION                                │
│                                                                    │
│  ┌──────────────────────────┐      ┌──────────────────────────┐   │
│  │   MASTER NODE            │      │   FRIEND NODE(s)         │   │
│  │                          │      │                          │   │
│  │  ┌────────────────────┐  │      │  ┌────────────────────┐  │   │
│  │  │   Alice (primary)  │  │      │  │  Alice (task only) │  │   │
│  │  │   coordinates      │  │      │  │  sandboxed session │  │   │
│  │  │   accepts input    │  │      │  │  input LOCKED      │  │   │
│  │  └────────┬───────────┘  │      │  └────────┬───────────┘  │   │
│  │           │ task tool    │      │           │ result        │   │
│  │  ┌────────▼───────────┐  │ HTTP │  ┌────────▼───────────┐  │   │
│  │  │  /bridge/dispatch  │──┼─────►│  │ /bridge/dispatch-  │  │   │
│  │  │  -task (outbound)  │  │      │  │  task (inbound)    │  │   │
│  │  └────────────────────┘  │      │  └────────────────────┘  │   │
│  │                          │      │                          │   │
│  │  ┌────────────────────┐  │      │  ┌────────────────────┐  │   │
│  │  │   Bridge.state     │  │      │  │   Bridge.state     │  │   │
│  │  │   role: "master"   │  │      │  │   role: "friend"   │  │   │
│  │  └────────────────────┘  │      │  └────────────────────┘  │   │
│  └──────────┬───────────────┘      └───────────┬──────────────┘   │
│             │                                  │                  │
│             │     ┌────────────────────┐       │                  │
│             └────►│       REDIS        │◄──────┘                  │
│                   │                    │                          │
│                   │  bridge:ID:master  │                          │
│                   │  bridge:ID:nodes   │  (heartbeats, node info) │
│                   │  bridge:ID:context │  (shared findings)       │
│                   │  bridge:ID:channel │  (pub/sub events)        │
│                   └────────────────────┘                          │
└────────────────────────────────────────────────────────────────────┘
```

### Role Definitions

| Role       | Description                                             | Input      | Task Capability                     |
| ---------- | ------------------------------------------------------- | ---------- | ----------------------------------- |
| **master** | The human's terminal. Alice coordinates and dispatches. | ✅ Enabled | Dispatches to friends via task tool |
| **friend** | Worker terminal. Alice runs sandboxed tasks.            | 🔒 Locked  | Executes tasks received from master |

### Coordination Layers

```
Layer 1: Redis pub/sub (bridge:ID:channel)
  └── Real-time events: node joined/left, input locked, task dispatched

Layer 2: Redis hashes/lists (bridge:ID:nodes, bridge:ID:context)
  └── Persistent state: node info, heartbeats, shared context entries

Layer 3: HTTP (node-to-node via nodeURL)
  └── Task dispatch: master → friend via POST /bridge/dispatch-task

Layer 4: SQLite (local bridge_node table)
  └── Crash recovery: remember bridge membership across restarts
```

---

## 3. Initialization & Setup

### Bootstrap Process

When opencode starts with `--bridge` flags, the TUI worker calls the REST API to set up the bridge role:

```
CLI start (--bridge master|friend)
    │
    ▼
TUI worker spawns
    │
    ▼
HTTP server started (always started when --bridge is set)
    │
    ├─ master: POST /bridge/set-master
    │           └── Bridge.setMaster() → writes Redis keys, starts heartbeat
    │
    └─ friend: POST /bridge/set-friend
                └── Bridge.setFriend() → joins Redis, starts heartbeat
```

### Crash Recovery (`Bridge.init()`)

On every startup, `Bridge.init()` checks the local SQLite `bridge_node` table for a previously active bridge membership:

```typescript
// packages/opencode/src/bridge/index.ts
async function _init() {
  const row = Database.use((db) =>
    db.select().from(BridgeNodeTable)
      .where(eq(BridgeNodeTable.directory, Instance.directory)).get(),
  )
  if (!row || row.status !== "active") return

  // Verify bridge still exists in Redis
  const pub = makeClient(row.coordinator ?? undefined)
  await pub.connect()
  const alive = await pub.exists(keys(row.bridge_id).master).catch(() => 0)
  await pub.quit().catch(() => {})

  if (!alive) {
    // Bridge gone — mark inactive and skip
    Database.use((db) => db.update(BridgeNodeTable).set({ status: "inactive" })...)
    return
  }

  // Bridge alive — restore membership
  if (row.role === "master") await setMaster(...)
  else await setFriend(...)
}
```

This lets opencode survive process restarts without losing bridge membership, as long as Redis is still running and the bridge master key exists.

### Redis Client Creation

Two Redis clients are created per node — one for pub/sub (subscribe only), one for everything else:

```typescript
function makeClient(coordinatorURL?: string): Redis {
  if (coordinatorURL) return new Redis(toRedisURL(coordinatorURL), { lazyConnect: true })
  const url = Env.get("REDIS_URL")
  if (url) return new Redis(url, { lazyConnect: true })
  const host = Env.get("REDIS_HOST") || "localhost"
  const port = parseInt(Env.get("REDIS_PORT") || "6379", 10) || 6379
  const password = Env.get("REDIS_PASSWORD")
  return new Redis({ host, port, ...(password ? { password } : {}), lazyConnect: true })
}
```

Priority order: `coordinatorURL` arg → `REDIS_URL` env → `REDIS_HOST`/`REDIS_PORT` env → localhost defaults.

---

## 4. Node Management

### `setMaster(input)`

Establishes this instance as the bridge master. Idempotent if already master for the same sessionID.

**Steps:**

1. Connect two Redis clients (pub + sub)
2. Write master metadata to `bridge:ID:master` hash
3. Write self node info to `bridge:ID:nodes` hash
4. Write session→bridge mapping to `bridge:sessions:sessionID`
5. Write limit and slug reverse-index keys
6. Subscribe to `bridge:ID:channel` for pub/sub events
7. Build initial `Info` snapshot
8. Upsert row into SQLite `bridge_node` table
9. Start heartbeat timer (15s interval)
10. Publish `node.joined` to channel
11. Emit `Bridge.Event.StateChanged` Bus event

### `setFriend(input)`

Joins an existing bridge as a friend node.

**Steps:**

1. Resolve `masterIDOrSlug` — if not a `ses_` prefixed ID, look up via `bridge:slug:SLUG` key
2. Verify master exists via `bridge:ID:master` hash
3. Validate: node count < limit, no duplicate directory
4. Connect two Redis clients
5. Write self node info to `bridge:ID:nodes`
6. Write session→bridge mapping
7. Subscribe to `bridge:ID:channel`
8. Upsert SQLite row
9. Start heartbeat timer
10. Publish `node.joined`
11. Emit `Bridge.Event.StateChanged`

> **Note:** The limit and directory-uniqueness checks in `setFriend` are non-atomic against concurrent joins (race window between read and write). This is acceptable for the expected node counts (default max: 3). A Redis Lua script would be needed to make them atomic.

### `leave()`

Cleanly exits the bridge. Re-entrant safe — atomically clears `bridgeID` and `role` at the top to prevent duplicate cleanup.

**Master leave sequence:**

1. Clear state atomically (`bridgeID = null`, `role = null`)
2. Stop heartbeat timer
3. Unsubscribe and quit sub client
4. Publish `bridge.closed` to channel (triggers all friends to leave)
5. Delete all Redis keys: `master`, `nodes`, `context`, `limit`, session keys, slug key
6. Quit pub client
7. Update SQLite row to `status: "inactive"`

**Friend leave sequence:**

1. Clear state atomically
2. Stop heartbeat timer
3. Unsubscribe and quit sub client
4. Delete own entry from `bridge:ID:nodes`
5. Delete own session key
6. Publish `node.left` to channel
7. Quit pub client
8. Update SQLite row to `status: "inactive"`

### Heartbeat / Liveness

Every **15 seconds**, each node updates its own `heartbeat` timestamp in the `bridge:ID:nodes` hash:

```typescript
function startHeartbeat(id: string, sessionID: string) {
  s.heartbeatTimer = setInterval(async () => {
    const raw = await cs.pubClient.hget(k.nodes, sessionID)
    const node = NodeInfo.safeParse(JSON.parse(raw))
    if (!node.success) return
    const updated = { ...node.data, heartbeat: Date.now() }
    await cs.pubClient.hset(k.nodes, sessionID, JSON.stringify(updated))
  }, 15_000)
}
```

**Stale node detection:** Nodes whose `heartbeat` is more than **60 seconds** old are filtered out by `buildInfo()` and `getNodes()`. No explicit eviction step is needed — stale nodes simply stop appearing in the active node list.

```typescript
.filter((n) => now - n.heartbeat < 60_000)  // 60-second stale window
```

### Input Locking (`setInputLocked`)

Only the master can lock/unlock a friend's input. This happens automatically when a friend joins:

```typescript
// In handleMessage, on "node.joined":
if (s.role === "master" && node.data.role === "friend") {
  setInputLocked(node.data.nodeID, true)
}
```

The lock state is published to the channel and received by the friend:

```typescript
// In handleMessage, on "input.locked":
if (parsed.data.nodeID === ls.sessionID) {
  state().inputLocked = parsed.data.locked
  Bus.publish(Event.InputLocked, { locked: parsed.data.locked })
}
```

The TUI reacts to `Event.InputLocked` to disable the prompt input widget.

---

## 5. Redis Key Structure

All keys are namespaced under `bridge:` to avoid collision with other opencode Redis usage.

| Key Pattern                   | Type    | Purpose                                                                      | TTL                     |
| ----------------------------- | ------- | ---------------------------------------------------------------------------- | ----------------------- |
| `bridge:{id}:master`          | Hash    | Master node metadata (sessionID, slug, title, directory, nodeURL, heartbeat) | None (deleted on leave) |
| `bridge:{id}:nodes`           | Hash    | All node info objects, keyed by sessionID. Values are JSON `NodeInfo`.       | None                    |
| `bridge:{id}:context`         | List    | Shared context entries (LPUSH, capped to 200 via LTRIM). Newest at index 0.  | None                    |
| `bridge:{id}:channel`         | Channel | Pub/sub channel for real-time events                                         | N/A (pub/sub)           |
| `bridge:{id}:limit`           | String  | Max node count for this bridge (integer as string)                           | None                    |
| `bridge:sessions:{sessionID}` | String  | Maps session ID → bridge ID (reverse lookup)                                 | None                    |
| `bridge:slug:{slug}`          | String  | Maps session slug → bridge ID (for friend `--bridge-id` with slug)           | None                    |

### Key Lifecycle

```
setMaster()      → writes master, nodes, sessions:sid, limit, slug:slug
setFriend()      → writes nodes:sid, sessions:sid  (reads master, nodes, limit)
leave() master   → deletes master, nodes, context, limit, all sessions:*, slug:slug
leave() friend   → deletes nodes[sid], sessions:sid
heartbeat        → updates nodes[sid].heartbeat (in-place hset)
shareContext()   → LPUSH context, LTRIM context 0 199, PUBLISH channel
```

---

## 6. Database Schema

### `bridge_node` Table

Defined in `packages/opencode/src/bridge/bridge.sql.ts`:

```typescript
export const BridgeNodeTable = sqliteTable(
  "bridge_node",
  {
    session_id: text()
      .primaryKey()
      .references(() => SessionTable.id, { onDelete: "cascade" }),
    bridge_id: text().notNull(),
    role: text().notNull(), // "master" | "friend"
    directory: text().notNull(),
    node_url: text().notNull(),
    status: text().notNull().default("active"), // "active" | "inactive"
    limit: integer().notNull().default(3),
    coordinator: text(), // null = use env defaults
    ...Timestamps, // created_at, updated_at (auto-managed)
  },
  (table) => [index("bridge_node_bridge_idx").on(table.bridge_id)],
)
```

| Column        | Type    | Description                                                                 |
| ------------- | ------- | --------------------------------------------------------------------------- |
| `session_id`  | TEXT PK | The opencode session ID for this node. FK to `session.id` (cascade delete). |
| `bridge_id`   | TEXT    | The master's session ID (same as `session_id` for masters).                 |
| `role`        | TEXT    | `"master"` or `"friend"`                                                    |
| `directory`   | TEXT    | Working directory for this node                                             |
| `node_url`    | TEXT    | HTTP base URL other nodes use to reach this one                             |
| `status`      | TEXT    | `"active"` or `"inactive"`                                                  |
| `limit`       | INTEGER | Max nodes for this bridge (stored for restore)                              |
| `coordinator` | TEXT    | Redis URL override, or NULL to use env vars                                 |
| `created_at`  | INTEGER | Unix ms timestamp                                                           |
| `updated_at`  | INTEGER | Unix ms timestamp                                                           |

**Index:** `bridge_node_bridge_idx` on `bridge_id` — used to find all nodes for a given bridge.

**Purpose of this table:** Crash recovery. If the opencode process dies and restarts, `Bridge.init()` reads this table to re-join the bridge without user intervention.

---

## 7. Task Routing & Delegation

### Detection

The task tool checks every prompt for the `[bridge_node: <nodeID>]` prefix:

```typescript
const bridgeMatch = params.prompt.match(/^\[bridge_node:\s*([^\]]+)\]\s*/)
if (bridgeMatch && Bridge.isActive() && Bridge.isMaster()) {
  const nodeID = bridgeMatch[1].trim()
  const prompt = params.prompt.slice(bridgeMatch[0].length) // strip prefix
  // → bridge dispatch path
}
```

If the prefix is absent or bridge is not active, the task runs locally as a normal subagent.

### Dispatch Protocol

```
Master (task tool)                         Friend (HTTP server)
     │                                           │
     │  POST /bridge/dispatch-task               │
     │  Headers:                                 │
     │    x-bridge-id: <bridgeID>                │
     │    x-opencode-directory: <friendDir>      │
     │  Body: { taskID, prompt, description }    │
     ├──────────────────────────────────────────►│
     │                                           │
     │                            Validate bridge ID (timing-safe)
     │                            Check taskID not already active
     │                            Create sandboxed session
     │                            Publish bridge.task.dispatched
     │                            Fire-and-forget: start Alice
     │                                           │
     │  HTTP 200: { taskID, sessionID, ok:true } │
     │◄──────────────────────────────────────────┤
     │                                           │
     │  Bridge.pollTaskResult(taskID, nodeID)    │  Alice runs...
     │  └── polls Redis context every 2s         │
     │  └── watches for task_result entry        │  Alice writes shareContext({
     │  └── checks nodeID still alive            │    type: "task_result",
     │  └── 5-minute deadline (no-nodeID path)   │    content: "task_id: X\n..."
     │                                           │  })
     │◄──────────────────────────────────────────┤
     │                                           │
     │  Returns inline result to caller          │
     ▼                                           ▼
```

### Polling Logic

`Bridge.pollTaskResult()` has two modes:

**With `nodeID` (normal dispatch):**

- No deadline — polls until result found OR node disappears from active list
- If `getNodes()` returns a list without the target nodeID → return `null` (node dead)
- Polls every 2 seconds

**Without `nodeID` (fallback):**

- 5-minute hard deadline
- Polls every 2 seconds until result or timeout

### Session Sandboxing

Tasks dispatched to friends run in a freshly created session with a restrictive permission set:

```typescript
const session = await Session.create({
  title: description,
  permission: [
    { permission: "external_directory", pattern: "*", action: "deny" },
    { permission: "read", pattern: "*", action: "deny" },
    { permission: "read", pattern: `${dir}/**`, action: "allow" },
    { permission: "edit", pattern: "*", action: "deny" },
    { permission: "edit", pattern: `${dir}/**`, action: "allow" },
    { permission: "glob", pattern: "*", action: "deny" },
    { permission: "glob", pattern: `${dir}/**`, action: "allow" },
    { permission: "grep", pattern: "*", action: "deny" },
    { permission: "grep", pattern: `${dir}/**`, action: "allow" },
    { permission: "bash", pattern: "*", action: "deny" },
    { permission: "bash", pattern: `${dir}/**`, action: "allow" },
  ],
})
```

All file access outside the friend's directory is denied at the permission layer. This is enforced regardless of what the dispatched prompt says.

### Duplicate Task Protection

`activeTaskIDs` is an in-memory `Set<string>` that tracks task IDs currently being processed. If the same `taskID` arrives again (e.g., master retried after a timeout), the friend returns HTTP 200 with `sessionID: "dup"` rather than running the task twice:

```typescript
if (activeTaskIDs.has(taskID)) {
  return c.json({ taskID, sessionID: "dup", success: true as const })
}
activeTaskIDs.add(taskID)
// ... process task ...
// activeTaskIDs.delete(taskID) on completion or error
```

---

## 8. Message Protocol

All messages are published to `bridge:{id}:channel` as JSON strings.

### Message Types

| Type              | Direction          | Payload                                                | Effect                                                                |
| ----------------- | ------------------ | ------------------------------------------------------ | --------------------------------------------------------------------- |
| `node.joined`     | Any → All          | `{ type, node: NodeInfo }`                             | Triggers `NodeJoined` Bus event; master auto-locks new friend's input |
| `node.left`       | Leaving node → All | `{ type, nodeID: string }`                             | Triggers `NodeLeft` Bus event                                         |
| `context.shared`  | Any → All          | `{ type, entry: ContextEntry }`                        | Triggers `ContextShared` Bus event                                    |
| `input.locked`    | Master → All       | `{ type, nodeID: string, locked: boolean }`            | Target node updates its `inputLocked` state                           |
| `task.dispatched` | Friend → All       | `{ type, targetNodeID, taskID, sessionID, agentName }` | Triggers `TaskDispatched` Bus event (UI notification)                 |
| `task.result`     | —                  | `{ type, taskID, nodeID, result, success }`            | Triggers `TaskResult` Bus event                                       |
| `bridge.closed`   | Master → All       | `{ type: "bridge.closed" }`                            | All friends call `leave()`                                            |

### Message Handler

The `handleMessage()` function receives all pub/sub messages. After handling each message type, it throttles info refresh to at most once per second:

```typescript
const now = Date.now()
if (now - cs.lastRefresh >= 1000) {
  cs.lastRefresh = now // pessimistically claim slot
  const updated = await refreshInfo()
  if (updated) Bus.publish(Event.StateChanged, updated)
}
```

The `bridge.closed` message skips the refresh step (bridge is being torn down).

### ContextEntry Schema

```typescript
ContextEntry = {
  nodeID: string, // session ID of the node that shared this
  role: "master" | "friend",
  directory: string, // working directory of the source node
  type: "finding" | "work_summary" | "task_result" | "status",
  content: string, // the actual content (max 500 chars in Alice prompts)
  timestamp: number, // Unix ms
}
```

Context entries are stored as a Redis list (newest-first, capped at 200 entries via LTRIM).

---

## 9. State Management

### In-Memory State (`Bridge.state`)

The `Bridge` namespace uses `Instance.state<State>()` — a per-directory reactive state container that automatically calls a cleanup function when the instance changes:

```typescript
interface State {
  bridgeID: string | null // null when not in a bridge
  role: "master" | "friend" | null
  sessionID: string | null // this node's own session ID
  slug: string | null // this node's slug (masters only)
  masterInput: string | null // the original --bridge-id argument (friends)
  pubClient: Redis | null // general-purpose Redis client
  subClient: Redis | null // subscribe-only Redis client
  heartbeatTimer: NodeJS.Timer | null
  info: Info | null // cached bridge state snapshot
  inputLocked: boolean // friend: is input currently locked?
  coordinator: string | null // Redis URL override
  lastRefresh: number // timestamp of last info refresh
  inProgress: Promise<Info> | null // deduplicate concurrent setMaster/setFriend
  pendingSessionID: string | null // for in-flight operation dedup
}
```

### Bus Events

Bridge state changes are broadcast to the local process via the `Bus` event system. The TUI subscribes to these to update the UI:

| Event                    | Payload                                          | Subscribers                             |
| ------------------------ | ------------------------------------------------ | --------------------------------------- |
| `bridge.state.changed`   | `Info`                                           | TUI: updates node count, friend list    |
| `bridge.node.joined`     | `NodeInfo`                                       | TUI: shows "friend joined" notification |
| `bridge.node.left`       | `{ nodeID, bridgeID }`                           | TUI: shows "friend left" notification   |
| `bridge.context.shared`  | `ContextEntry`                                   | TUI: can display shared findings        |
| `bridge.input.locked`    | `{ locked }`                                     | TUI: enables/disables prompt widget     |
| `bridge.task.dispatched` | `{ targetNodeID, taskID, sessionID, agentName }` | TUI: shows task dispatch status         |
| `bridge.task.result`     | `{ taskID, nodeID, result, success }`            | TUI: shows task completion              |

### TUI Context (SolidJS)

`BridgeContext` in `packages/opencode/src/cli/cmd/tui/context/bridge.tsx` is a SolidJS context that stores the TUI-local bridge state:

```typescript
type BridgeState = {
  role: "master" | "friend" | null
  bridgeID: string | null
  inputLocked: boolean
  nodeCount: number
}
```

The TUI initializes this context by calling `GET /bridge/info` on startup and subscribing to SSE Bus events.

### Web App Context

`packages/app/src/context/bridge.tsx` provides the same state for the web UI. It follows the same Bus event subscription pattern but uses React instead of SolidJS.

---

## 10. Error Handling

### Redis Errors

All Redis operations are wrapped in `.catch()` and logged as warnings. Redis errors do not crash the process:

```typescript
await cs.pubClient
  .hset(k.nodes, sessionID, JSON.stringify(updated))
  .catch((e) => log.warn("bridge: heartbeat failed", { error: String(e) }))
```

During `pollTaskResult`, transient Redis errors are swallowed and the poll continues:

```typescript
try {
  const entries = await getContext(s.bridgeID, 200)
  const match = entries.find(...)
  if (match) return match.content
} catch {
  // transient Redis error — keep polling
}
```

### Task Dispatch Errors

| Condition                                 | Behavior                                     |
| ----------------------------------------- | -------------------------------------------- |
| Invalid `nodeURL` scheme (not http/https) | Return error string to caller immediately    |
| Bridge session ended before dispatch      | Return error string                          |
| Friend returns non-2xx HTTP               | Return error string with status code         |
| `fetch()` throws (network error)          | Returns `null` → treated as dispatch failure |
| Friend rejects with `{ success: false }`  | Return "rejected task dispatch" error        |
| Dispatch HTTP timeout (10s)               | `AbortSignal.timeout(10_000)` on the fetch   |

### Task Timeouts

After dispatch succeeds, the master polls for the result:

- If `nodeID` is provided: no deadline, but stops if node disappears
- If `nodeID` is not provided: 5-minute hard deadline (`deadline = Date.now() + 300_000`)

When the poll returns `null` (timeout or node dead), the task tool returns:

```
Friend task timed out or was aborted before returning a result.
```

### `setMaster`/`setFriend` Concurrency

An `inProgress` promise prevents concurrent invocations for different sessions:

```typescript
if (s.inProgress) {
  if (s.pendingSessionID === input.sessionID) return s.inProgress // same session: share
  throw new Error("Bridge operation already in progress for a different session")
}
```

Same-session concurrent calls share the same in-flight promise (idempotent). Different-session concurrent calls throw immediately.

### `leave()` Re-entrancy

`leave()` atomically clears `bridgeID` and `role` at the top before any async work. This prevents duplicate cleanup if `leave()` is called again while the first call is awaiting Redis operations.

---

## 11. Configuration

### Environment Variables

| Variable           | Default       | Description                                                                                          |
| ------------------ | ------------- | ---------------------------------------------------------------------------------------------------- |
| `REDIS_URL`        | —             | Full Redis connection URL (`redis://...` or `rediss://...`). Takes priority over HOST/PORT.          |
| `REDIS_HOST`       | `localhost`   | Redis hostname. Used when `REDIS_URL` is not set.                                                    |
| `REDIS_PORT`       | `6379`        | Redis port. Used when `REDIS_URL` is not set.                                                        |
| `REDIS_PASSWORD`   | —             | Redis password for authenticated servers.                                                            |
| `BRIDGE_NODE_URL`  | auto-detected | Public HTTP URL this node advertises to others. Required for cross-machine. Format: `http://IP:PORT` |
| `BRIDGE_MAX_NODES` | `3`           | Maximum nodes per bridge (master + friends combined).                                                |

### `BRIDGE_NODE_URL` Resolution

```typescript
function nodeURL() {
  const override = Env.get("BRIDGE_NODE_URL")
  if (!override) return Server.url().toString() // auto: local server URL
  const raw = override.startsWith("http") ? override : `http://${override}`
  try {
    return new URL(raw).toString()
  } catch {
    return Server.url().toString() // fallback on invalid URL
  }
}
```

The auto-detected URL uses the local HTTP server's bound address — correct for same-machine use. For cross-machine, set `BRIDGE_NODE_URL` to the externally reachable address.

### `Bridge.available()`

Returns `true` if Redis configuration is present:

```typescript
export function available(): boolean {
  return !!(Env.get("REDIS_URL") || Env.get("REDIS_HOST") || Env.get("REDIS_PORT") || state().coordinator)
}
```

Note: `REDIS_PORT` alone (e.g., set to `"6379"`) is sufficient to mark bridge as available.

---

## 12. API Endpoints

All endpoints are mounted under `/bridge` in the Hono HTTP server (`packages/opencode/src/server/routes/bridge.ts`).

### `GET /bridge/info`

Returns current bridge state for this node.

**Response 200:**

```json
{
  "bridgeID": "ses_abc123",
  "masterID": "ses_abc123",
  "masterSlug": "my-session",
  "nodes": [
    {
      "nodeID": "ses_abc123",
      "role": "master",
      "sessionID": "ses_abc123",
      "slug": "my-session",
      "title": "My Project",
      "directory": "/home/user/project-a",
      "nodeURL": "http://127.0.0.1:4096/",
      "heartbeat": 1712345678000,
      "status": "active"
    }
  ],
  "limit": 3,
  "selfRole": "master",
  "selfNodeID": "ses_abc123"
}
```

Returns `null` if not in a bridge.

---

### `GET /bridge/nodes?bridgeID=<id>`

Returns the active node list for a bridge.

**Query params:** `bridgeID` (required)  
**Response 200:** Array of `NodeInfo`  
**Response 403:** Bridge not active or ID mismatch

---

### `GET /bridge/context?bridgeID=<id>&limit=<n>`

Returns shared context entries (newest first, up to `limit`, default 50, max 200).

**Query params:** `bridgeID` (required), `limit` (optional, 1-200)  
**Response 200:** Array of `ContextEntry`  
**Response 403:** Bridge not active or ID mismatch

---

### `POST /bridge/set-master`

Become the bridge master. Creates Redis keys and starts the bridge session.

**Request body:**

```json
{
  "sessionID": "ses_abc123",
  "slug": "my-session",
  "title": "My Project",
  "directory": "/home/user/project-a",
  "limit": 3,
  "coordinator": "redis://localhost:6379"
}
```

`limit` and `coordinator` are optional.

**Response 200:** Bridge `Info` object  
**Response 400:** Redis unavailable, already in bridge with different session, etc.

---

### `POST /bridge/set-friend`

Join an existing bridge as a friend.

**Request body:**

```json
{
  "masterIDOrSlug": "ses_abc123",
  "sessionID": "ses_def456",
  "slug": "friend-session",
  "title": "My Friend Project",
  "directory": "/home/user/project-b",
  "coordinator": "redis://localhost:6379"
}
```

`masterIDOrSlug` accepts either the raw session ID (`ses_...`) or a slug (resolved via `bridge:slug:` key).

**Response 200:** Bridge `Info` object  
**Response 400:** Bridge not found, full, or duplicate directory

---

### `POST /bridge/leave`

Leave the current bridge.

**Request body:**

```json
{ "bridgeID": "ses_abc123" }
```

`bridgeID` is optional — if provided, validated against current bridge ID before leaving.

**Response 200:** `{ "success": true }`  
**Response 403:** Bridge ID mismatch

---

### `POST /bridge/share-context`

Share a context entry with all bridge participants.

**Request body:**

```json
{
  "role": "friend",
  "directory": "/home/user/project-b",
  "type": "finding",
  "content": "Found 3 API endpoints missing authentication"
}
```

`type` must be one of: `"finding"`, `"work_summary"`, `"task_result"`, `"status"`

**Response 200:** `{ "success": true }`  
**Response 400:** Not in an active bridge

---

### `POST /bridge/lock-input`

Lock or unlock a friend's input. Master only.

**Request body:**

```json
{
  "targetNodeID": "ses_def456",
  "locked": true
}
```

**Response 200:** `{ "success": true }`  
**Response 403:** Not the master  
**Response 404:** Target node not found

---

### `POST /bridge/dispatch-task`

Receive a task dispatch from the master. Friend only.

**Headers:**

- `x-bridge-id: <bridgeID>` — validated timing-safely against this node's bridge ID
- `x-opencode-directory: <dir>` — informational (actual dir comes from Instance)

**Request body:**

```json
{
  "taskID": "550e8400-e29b-41d4-a716-446655440000",
  "prompt": "Analyze the payment module and list all exported functions",
  "description": "Analyze payment module"
}
```

**Response 200:** `{ "taskID": "...", "sessionID": "ses_xyz789", "success": true }`  
**Response 401:** Not a friend, or bridge ID mismatch

---

## 13. CLI Integration

### Flags

```bash
vuhitracode [options]
  --bridge <master|friend>     Start in bridge mode
  --coordinator <url>          Redis coordinator URL
  --bridge-id <sessionID>      Master session ID (required for friends)
```

Validation in `packages/opencode/src/cli/cmd/tui/thread.ts`:

```typescript
if (args.bridge === "friend" && !args["bridge-id"]) {
  UI.error("--bridge friend requires --bridge-id <master-session-id>")
  process.exitCode = 1
  return
}
```

### HTTP Server Auto-Start

When `--bridge` is set, the HTTP server always starts (regardless of other port/hostname flags):

```typescript
const shouldStartServer =
  !!args.bridge ||
  process.argv.includes("--port") ||
  // ...
```

This is required because task dispatch is HTTP-based — friends must expose `/bridge/dispatch-task`.

### TUI Initialization

The TUI receives bridge args and calls the appropriate setup endpoint during initialization:

```typescript
tui({
  args: {
    bridge: args.bridge as "master" | "friend" | undefined,
    coordinator: args.coordinator,
    bridgeID: args["bridge-id"],
  },
})
```

Internally the TUI calls `POST /bridge/set-master` or `POST /bridge/set-friend` on startup, populating the session details from the current session context.

---

## 14. Tool Integration

### `ping_bridge_session` Tool

Defined in `packages/opencode/src/tool/ping_bridge_session.ts`. Registered in the tool registry for use by Alice subagents.

**Purpose:** Check if a friend node is still alive during a long-running task.

**Usage:**

```
ping_bridge_session({ nodeID: "ses_def456" })
```

**Returns:**

- `{ alive: true }` — node found in active list with heartbeat < 60s old
- `{ alive: false, reason: "..." }` — node not found, bridge disconnected, or aborted

**Implementation:**

```typescript
const nodes = await Promise.race([Bridge.getNodes(id), aborted])
const node = nodes.find((n) => n.nodeID === params.nodeID)
if (node) return { alive: true }
return { alive: false, reason: "Node not found..." }
```

The tool respects the session's abort signal — if the parent task is cancelled, the ping is also cancelled immediately.

**When to use:** Call this periodically while waiting for a long dispatch to complete. If it returns `alive: false`, stop waiting and return failure rather than hanging until the 5-minute timeout.

### `getBridgeSettings()` Function

Defined in `packages/opencode/src/agent/agent.ts`. Injected into Alice's system prompt when bridge mode is active.

**For master Alice**, it injects:

- List of connected friend nodes with their directories and status
- Last 50 shared context entries
- Dispatch instructions (`[bridge_node: nodeID]` prefix format)
- Auto-dispatch rules (when to delegate vs. handle locally)
- Safety rules (never use file tools on friend directories)

**For friend Alice**, it injects:

- Reminder that input is disabled
- Constraints: stay in own directory, report results clearly
- Master's bridge ID for reference

Content is sanitized before injection — non-printable characters and shell metacharacters are stripped, content is truncated.

---

## 15. Cross-Machine Support

### Requirements

1. All nodes must share the same Redis instance (reachable by all)
2. Each node must expose its HTTP server on a network-reachable address
3. `BRIDGE_NODE_URL` must be set to the externally reachable HTTP address

### Setup Example

**Machine A (master, IP: 192.168.1.10):**

```bash
# .vuhitra/env.json
{
  "BRIDGE_NODE_URL": "http://192.168.1.10:4096",
  "REDIS_URL": "redis://192.168.1.10:6379"
}

# Start master
vuhitracode --bridge master --coordinator redis://192.168.1.10:6379
```

**Machine B (friend, IP: 192.168.1.20):**

```bash
# .vuhitra/env.json
{
  "BRIDGE_NODE_URL": "http://192.168.1.20:4096",
  "REDIS_URL": "redis://192.168.1.10:6379"
}

# Start friend (master-session-id shown in master terminal)
vuhitracode --bridge friend \
  --coordinator redis://192.168.1.10:6379 \
  --bridge-id <master-session-id>
```

### Docker Compose for Redis

```yaml
services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5
    volumes:
      - redis-data:/data

volumes:
  redis-data:
```

### Network Requirements

| Traffic                   | From      | To           | Port                            |
| ------------------------- | --------- | ------------ | ------------------------------- |
| Redis pub/sub + commands  | All nodes | Redis server | 6379 (default)                  |
| Task dispatch HTTP        | Master    | Each friend  | Friend's `BRIDGE_NODE_URL` port |
| (Optional) Result polling | Master    | Redis        | 6379                            |

Firewall must allow inbound connections on the opencode server port (default 4096) from other bridge nodes.

---

## 16. Security Model

### Bridge ID Validation (Timing-Safe)

The `/bridge/dispatch-task` endpoint validates the `x-bridge-id` header using a timing-safe comparison to prevent timing attacks:

```typescript
const safe = (a: string, b: string) =>
  a.length === b.length && timingSafeEqual(Buffer.from(a, "utf8"), Buffer.from(b, "utf8"))

if (!Bridge.isFriend() || !bid || !safe(incoming, bid)) {
  return c.json({ error: "Unauthorized" }, 401)
}
```

The bridge ID is the master's session ID — a random opaque identifier (format: `ses_...`). Any request without the correct bridge ID is rejected.

### File Access Restriction

Friend sessions are created with an explicit deny-all / allow-own-directory permission set. Even if a malicious prompt instructs the friend to access files outside its directory, the permission layer prevents it at the tool level.

### Input Lock

Friends cannot submit prompts to their own Alice while locked. The lock is set by the master and enforced in the TUI by disabling the input widget. It is also stored in the friend's `inputLocked` state and in the node's `status` field in Redis (`"locked"`).

### Redis Security

Redis has no authentication by default. Recommendations:

- Use Redis on a trusted private network
- Enable `requirepass` in `redis.conf`
- Include the password in coordinator URL: `redis://:password@host:6379`
- For cross-machine setups, route through a VPN

### Context Content Safety

`getBridgeSettings()` sanitizes context before injecting into prompts:

```typescript
const sanitize = (s: string) =>
  s
    .replace(/[^\x20-\x7E]/g, "") // strip non-printable
    .replace(/[()[\]{}\n\r`]/g, "") // strip shell/template metacharacters
    .slice(0, 200) // truncate to 200 chars per field
```

Context content is further limited to 500 chars per entry in the prompt rendering.

---

## 17. Workflow Examples

### Example 1: Simple Cross-Directory Task

```
User (at master terminal):
  "What's the authentication flow in the backend?"

Master Alice (internal):
  1. Sees friend node "backend-api" at /home/user/backend
  2. Recognizes task is about backend directory
  3. Uses task tool: [bridge_node: ses_def456] What's the authentication flow?

task tool (master side):
  → POST /bridge/dispatch-task to friend's nodeURL
  → Poll Redis context for task_id: <uuid>

Friend Alice (internal):
  1. Receives task from /bridge/dispatch-task
  2. Creates sandboxed session scoped to /home/user/backend
  3. Reads auth-related files, traces flow
  4. Calls Bridge.shareContext({ type: "task_result", content: "task_id: <uuid>\nAuth uses JWT..." })

task tool (master side):
  ← Finds task_result in context
  ← Returns inline: "task_id: <uuid>\nAuth uses JWT..."

Master Alice:
  Presents result to user directly
```

### Example 2: Parallel Work

```
User: "Add a /health endpoint to the backend and update the frontend to call it"

Master Alice:
  1. Dispatch to friend (backend): [bridge_node: backend-id] Add GET /health endpoint
  2. Handle frontend locally: Edit src/api/health.ts

(Both happen concurrently — task tool blocks per-call, but Alice can use parallel tool calls)

Results:
  - Friend result returned inline after backend Alice finishes
  - Local frontend edit completes independently
  - Master Alice assembles final response for user
```

### Example 3: Liveness Check During Long Task

```
Alice dispatches a complex refactor to friend:
  task({ prompt: "[bridge_node: ses_xyz] Refactor the entire payment module..." })

While waiting (in the scout/sentinel that dispatched):
  loop:
    ping_bridge_session({ nodeID: "ses_xyz" })
    → { alive: true }  # keep waiting

Friend process crashes:
  ping_bridge_session({ nodeID: "ses_xyz" })
  → { alive: false, reason: "Node ses_xyz not found in active nodes" }

Scout:
  → Stop waiting, return failure to Alice
  → Alice reports to user: "Friend node disconnected during task"
```

### Example 4: Friend Joining Sequence

```
Master terminal already running:
  bridgeID = "ses_abc123"
  Redis: bridge:ses_abc123:master = { sessionID, slug, ... }

Friend starts with: --bridge friend --bridge-id ses_abc123

TUI → POST /bridge/set-friend {
  masterIDOrSlug: "ses_abc123",
  sessionID: "ses_def456",
  ...
}

Bridge.setFriend():
  1. Reads bridge:ses_abc123:master → confirmed exists
  2. Reads bridge:ses_abc123:nodes → 1 node (master), limit=3, ok
  3. Checks directory uniqueness → ok
  4. HSET bridge:ses_abc123:nodes ses_def456 <NodeInfo JSON>
  5. SET bridge:sessions:ses_def456 ses_abc123
  6. Subscribe to bridge:ses_abc123:channel
  7. Upsert SQLite bridge_node row
  8. Start heartbeat timer
  9. PUBLISH bridge:ses_abc123:channel { type: "node.joined", node: <NodeInfo> }

Master receives "node.joined":
  → Bus.publish(Event.NodeJoined, node)
  → setInputLocked("ses_def456", true)   ← auto-lock
  → TUI shows "Friend joined: ses_def456 at /home/user/project-b"

Friend receives "input.locked" (bounced from master):
  → state().inputLocked = true
  → Bus.publish(Event.InputLocked, { locked: true })
  → TUI disables prompt input
```

---

## 18. Limitations & Design Constraints

| Limitation                         | Detail                                                                                                                                                      |
| ---------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Terminal sessions only**         | Bridge requires an interactive TUI instance. Headless/background processes are not supported.                                                               |
| **Different directories required** | Two nodes in the same directory are rejected with an error.                                                                                                 |
| **Master-only input**              | Only the master accepts user prompts. Friends display output only.                                                                                          |
| **Redis required**                 | No fallback coordination mechanism. Redis unavailability halts bridge communication.                                                                        |
| **5-minute task timeout**          | Hard ceiling for tasks without node tracking. Tasks with node tracking have no timeout but stop when the node disappears.                                   |
| **Non-atomic joins**               | The limit and directory-uniqueness checks in `setFriend` have a small race window under concurrent joins. Acceptable for default max nodes of 3.            |
| **No upstream memory sharing**     | Friends' local memory, indexer, and biblion are not visible to the master. Only shared context (explicitly pushed via `shareContext`) crosses the boundary. |
| **Context size limit**             | Redis context list is capped at 200 entries. Alice prompts include at most 50 entries. Content is truncated to 500 chars per entry.                         |
| **No direct friend-to-friend**     | Friends cannot dispatch to each other. Only master → friend task dispatch is supported.                                                                     |
| **Single master**                  | A bridge has exactly one master. There is no master failover or promotion.                                                                                  |
| **In-memory task dedup only**      | `activeTaskIDs` is in-memory — a friend process restart resets it, so a late-arriving duplicate dispatch after a restart would run.                         |

---

## 19. Extension Points

### Adding a New Message Type

1. Add handler branch in `handleMessage()` in `packages/opencode/src/bridge/index.ts`:

```typescript
} else if (msg.type === "my.new.event") {
  const parsed = z.object({ myField: z.string() }).safeParse(msg)
  if (parsed.success) Bus.publish(Event.MyNewEvent, parsed.data)
}
```

2. Define a new Bus event in the `Event` namespace:

```typescript
export const Event = {
  // ... existing events ...
  MyNewEvent: BusEvent.define("bridge.my.new.event", z.object({ myField: z.string() })),
}
```

3. Publish from wherever appropriate:

```typescript
await pub.publish(k.channel, JSON.stringify({ type: "my.new.event", myField: "hello" }))
```

4. Add the event type to the SDK types (`packages/sdk/js/src/v2/gen/types.gen.ts`) if needed for external consumers.

### Adding a New Context Entry Type

Extend the `type` enum in `ContextEntry`:

```typescript
export const ContextEntry = z.object({
  // ...
  type: z.enum(["finding", "work_summary", "task_result", "status", "my_new_type"]),
})
```

Update `getBridgeSettings()` in `agent.ts` to handle or display the new type as needed.

### Adding a New API Endpoint

Extend `BridgeRoutes` in `packages/opencode/src/server/routes/bridge.ts`:

```typescript
export const BridgeRoutes = lazy(() =>
  new Hono()
    // ... existing routes ...
    .post(
      "/my-endpoint",
      describeRoute({ summary: "...", operationId: "bridge.myEndpoint", responses: { ... } }),
      validator("json", z.object({ ... })),
      async (c) => {
        // implementation
      },
    ),
)
```

Then regenerate the SDK: `./packages/sdk/js/script/build.ts`

### Adding a Node Status

Extend `NodeStatus`:

```typescript
export const NodeStatus = z.enum(["active", "inactive", "locked", "my_status"])
```

Update `setInputLocked` or similar functions to write the new status value.

---

## 20. Troubleshooting

### "Bridge mode requires Redis. Set REDIS_URL or REDIS_HOST."

**Cause:** `Bridge.available()` returned `false` — no Redis config found and no `--coordinator` flag.

**Fix:** Set `REDIS_URL` in `.vuhitra/env.json` or pass `--coordinator redis://localhost:6379`.

---

### Friend can't find master: "Bridge master not found for slug: ..."

**Cause:** The `bridge:slug:<slug>` key doesn't exist in Redis — either the master hasn't started yet, or the slug was wrong.

**Fix:** Use the raw session ID (`ses_...`) shown in the master terminal rather than the slug, or verify the master is running and connected to the same Redis.

---

### Friend rejected: "Bridge ... is full (limit: 3)"

**Cause:** The bridge already has the maximum number of nodes.

**Fix:** Increase `BRIDGE_MAX_NODES` in the master's environment (requires master restart), or remove an existing friend node.

---

### Friend rejected: "A node with directory ... is already in this bridge"

**Cause:** Two nodes are attempting to join with the same working directory.

**Fix:** Each node must run in a distinct directory. Change the friend's working directory.

---

### Tasks timing out

**Causes:**

1. Friend's Alice is taking longer than 5 minutes
2. Friend crashed and heartbeat went stale

**Diagnosis:** Use `ping_bridge_session({ nodeID: "..." })` — if `alive: false`, the friend is gone.

**Fix for slow tasks:** Increase the poll deadline (currently hardcoded at 300s). For node-tracked polls, there is no timeout — the poll returns when the node disappears.

---

### Context not appearing on master

**Cause:** Friend's `shareContext()` failed silently, or context entries were pushed but exceeded the 200-entry cap and the relevant entry was evicted.

**Fix:** Check friend process logs for `"bridge: shareContext lpush/ltrim failed"`. Ensure the task result includes the `task_id:` prefix so `pollTaskResult` can match it.

---

### Bridge state not restored after restart

**Cause:** Either the SQLite row has `status: "inactive"`, or the Redis master key no longer exists.

**Diagnosis:**

```sql
-- Check local SQLite bridge_node table
SELECT * FROM bridge_node WHERE directory = '/your/dir';
```

**Fix:** Re-run the `--bridge` flags to rejoin. The `Bridge.init()` function will mark stale records inactive automatically.

---

### Master leaves but friends don't disconnect

**Cause:** The `bridge.closed` pub/sub message was lost (Redis pub/sub is fire-and-forget — no guarantee of delivery if the subscriber is briefly disconnected).

**Effect:** Friends will eventually stop appearing in node lists once their heartbeats go stale (60s window). They will continue running normally until manually stopped.

**Fix:** Friends should be stopped manually or will self-clean via heartbeat expiry.

---

### "Only master can lock input" 403

**Cause:** Calling `POST /bridge/lock-input` from a non-master node.

**Fix:** Only call this endpoint from the master's process.

---

### `BRIDGE_NODE_URL` being ignored

**Cause:** The env var may not be loading. Check the precedence: CLI `--coordinator` → `REDIS_URL` → `REDIS_HOST`/`REDIS_PORT`. `BRIDGE_NODE_URL` is separate and only affects the advertised HTTP address.

**Fix:** Verify the variable is set in the correct `.vuhitra/env.json` (in the project root) or as a shell environment variable before launching.

---

## 21. Quick Reference & Operational Procedures

### Quick Start

**Setup Redis:**

```bash
# Local Redis
docker run -d -p 6379:6379 redis:7-alpine

# Or use existing Redis
export REDIS_URL="redis://existing-server:6379"
```

**Terminal 1 — Master:**

```bash
cd ~/project-frontend
opencode --bridge master --coordinator redis://localhost:6379
# Note the session ID (ses_xxx) shown in output
```

**Terminal 2+ — Friends:**

```bash
cd ~/project-backend
opencode --bridge friend --coordinator redis://localhost:6379 --bridge-id <master-session-id>
```

### Common Operations

**Check Bridge Status:**

```bash
# From any node's terminal
curl http://localhost:4096/bridge/info | jq
```

**Share a Finding Across Bridge:**

```bash
# In any Alice session, call Bridge.shareContext
Bridge.shareContext({
  type: "finding",
  content: "Database migrations required before tests"
})
```

**Ping a Friend During Long Task:**

```typescript
const result = await ping_bridge_session({ nodeID: "ses_xyz" })
if (!result.alive) {
  return "Friend disconnected"
}
```

**Force a Friend to Leave:**

```bash
# From friend terminal: Ctrl+C and confirm

# Or remotely (Redis admin only):
redis-cli DEL bridge:sessions:ses_xyz
redis-cli HDEL bridge:ses_abc123:nodes ses_xyz
```

**Monitor Bridge Health:**

```bash
redis-cli
> SUBSCRIBE bridge:ses_abc123:channel
# Watch for heartbeats, node joins/leaves
```

### Deployment Checklist

- [ ] Redis server running and accessible from all nodes
- [ ] Network path open: all nodes → Redis port (6379)
- [ ] Network path open: master → each friend's HTTP port (4096)
- [ ] All nodes have synchronized system clocks (for heartbeat detection)
- [ ] `BRIDGE_NODE_URL` set correctly for cross-machine (if applicable)
- [ ] Test inter-node connectivity: `curl http://friend-ip:4096/bridge/ping`
- [ ] Run initial task dispatch to verify end-to-end flow
- [ ] Set up monitoring/alerting on Redis connection health

### Performance Tuning

| Adjustment                           | Effect                                            | When                                |
| ------------------------------------ | ------------------------------------------------- | ----------------------------------- |
| Increase `BRIDGE_HEARTBEAT_INTERVAL` | Lower CPU on nodes, slower failure detection      | Many nodes (>10) in bridge          |
| Decrease `BRIDGE_HEARTBEAT_TIMEOUT`  | Faster stale node detection, more false positives | Unreliable network                  |
| Increase `BRIDGE_MAX_NODES`          | Allow more friends per master                     | Planned scaling                     |
| Optimize Redis memory                | Prevent context list eviction                     | Large context entries or many tasks |

### Debugging Checklist

1. **Can nodes reach Redis?** → `redis-cli ping` from each node
2. **Are heartbeats updating?** → `redis-cli HGET bridge:nodes:xxx heartbeat`
3. **Is context being shared?** → `redis-cli LRANGE bridge:context:xxx 0 2`
4. **Did task dispatch succeed?** → Check HTTP 200 response from `/bridge/dispatch-task`
5. **Is friend waiting on result?** → `tail -f friend-logs.txt | grep "polling"`
6. **Is master polling for result?** → `tail -f master-logs.txt | grep "task result"`

---

## 22. Advanced Topics

### Crash Recovery & State Restoration

When an opencode process dies:

```
Bridge.init() runs on restart
  └── Read SQLite bridge_node table
      └── Check if node's Redis entry still exists
          └── Yes: Restore bridge membership automatically
          └── No: Mark SQLite entry as "inactive", skip
```

This means **bridge membership survives process restarts** as long as Redis is still running. The master key acts as the "anchor" — if the master's key is gone, friends will not rejoin.

To force a clean slate:

```bash
# 1. Delete all bridge state
redis-cli DEL bridge:ses_abc123:*
redis-cli DEL bridge:sessions:*
redis-cli DEL bridge:slug:*

# 2. Restart nodes (SQLite entries will be marked inactive)
```

### Custom Context Types

To add a new context type beyond `finding`, `work_summary`, `task_result`, `status`:

```typescript
// In packages/opencode/src/bridge/index.ts
export const ContextEntry = z.object({
  // ...
  type: z.enum(["finding", "work_summary", "task_result", "status", "metric", "alert"]),
  // ...
})

// In agent.ts, handle rendering
if (entry.type === "metric") {
  return `[METRIC] ${entry.content}`
}
```

### Handling Race Conditions

**Example: Two friends writing to same file simultaneously**

Bridge mode does NOT prevent this at the application level. Both friends can:

1. Read the same file
2. Make changes independently
3. Write back (last write wins)

**Mitigation:** Structure tasks to be non-overlapping:

- Master dispatches exclusive locks per task
- Friends check for locks before writing
- Or use file-level locking in the code itself

**Example:** Instead of both friends editing `config.json`:

```
Master:
  - Task 1 (friend1): "Edit config.payment_service section"
  - Task 2 (friend2): "Edit config.auth_service section"
  - Then: "Merge and validate config.json"
```

### Redis Persistence & Data Loss

By default, Redis stores data in-memory only. For production:

```bash
# Enable persistence in redis.conf
save 900 1              # Snapshot every 900s if 1+ key changed
appendonly yes          # Write-ahead log (AOF)
appendfsync everysec    # Fsync every second (trade-off: performance vs safety)

# Test recovery
docker-compose down
docker-compose up
# Bridge should restore successfully
```

### Monitoring & Observability

**Log Bridge Events:**

```typescript
// In Bridge.handleMessage()
console.log(`[BRIDGE] ${msg.type} from ${msg.nodeID} at ${Date.now()}`)
```

**Prometheus Metrics (example):**

```typescript
const bridgeTasksCompleted = new prometheus.Counter({
  name: "bridge_tasks_completed",
  help: "Total tasks completed across bridge",
  labels: ["status"],
})

// In friend's task completion handler
bridgeTasksCompleted.inc({ status: result.status })
```

**Health Endpoint:**

```typescript
// GET /bridge/health
{
  "status": "ok",
  "redis_connected": true,
  "role": "master",
  "active_friends": 2,
  "tasks_in_flight": 1,
  "uptime_seconds": 3600
}
```

---

## 23. Reference: TypeScript Types

### Key Interfaces

```typescript
// Bridge state
interface BridgeState {
  bridgeID: string | null
  role: "master" | "friend" | null
  sessionID: string | null
  pubClient: Redis | null
  subClient: Redis | null
  info: Info | null
  inputLocked: boolean
}

// Bridge info snapshot
interface Info {
  bridgeID: string
  masterID: string
  masterSlug?: string
  nodes: NodeInfo[]
  limit: number
  selfRole: "master" | "friend"
  selfNodeID: string
}

// Single node
interface NodeInfo {
  nodeID: string
  role: "master" | "friend"
  sessionID: string
  slug?: string
  title: string
  directory: string
  nodeURL: string
  heartbeat: number // Unix ms
  status: "active" | "inactive" | "stale" | "locked"
}

// Shared context entry
interface ContextEntry {
  nodeID: string
  role: "master" | "friend"
  directory: string
  type: "finding" | "work_summary" | "task_result" | "status"
  content: string
  timestamp: number // Unix ms
}

// Task dispatch result
interface TaskDispatchResult {
  taskID: string
  nodeID: string
  sessionID: string
  result?: unknown
  success: boolean
  error?: string
}
```

### Redis Commands Reference

```bash
# Inspect master
redis-cli HGETALL bridge:ses_abc123:master

# List all nodes in bridge
redis-cli HGETALL bridge:ses_abc123:nodes

# Get context entries
redis-cli LRANGE bridge:ses_abc123:context 0 49

# Monitor pub/sub
redis-cli SUBSCRIBE bridge:ses_abc123:channel

# Check session mapping
redis-cli GET bridge:sessions:ses_def456

# Check slug mapping
redis-cli GET bridge:slug:my-project
```

---

## 24. FAQ

**Q: Can a friend be in multiple bridges simultaneously?**  
A: No. A node can only have one `bridgeID` at a time. Joining a new bridge leaves the old one.

**Q: What happens if the master goes offline?**  
A: Friends continue running but can't receive new tasks. On the master's return, it re-joins with the same `bridgeID` and friends are automatically re-activated.

**Q: Can friends talk to each other?**  
A: Not directly via bridge. Friend-to-friend dispatch is not implemented. Workaround: master can dispatch sequentially or friends can use external coordination (shared files, webhooks, etc.).

**Q: Is context shared with the cloud/web app?**  
A: Not automatically. Context is stored in local Redis only. To share with the web app, implement a sync bridge that publishes to a central system.

**Q: How do I password-protect the bridge?**  
A: Set `REDIS_PASSWORD` env var (included in `REDIS_URL` as `redis://:password@host:6379`). Network-level firewalling is also recommended.

**Q: Can tasks access files outside their directory?**  
A: No. Friend sessions are created with permission boundaries. All file access outside the friend's directory is denied at the tool layer.

**Q: What's the maximum number of friends?**  
A: Default is 3 (`BRIDGE_MAX_NODES`). Can be increased at master startup, but be aware that heartbeat overhead grows linearly with node count.

**Q: Do tasks run in parallel?**  
A: Tasks are queued per friend and executed sequentially by that friend's Alice. Multiple friends execute in parallel independently.

**Q: How long can a task take?**  
A: Without explicit node tracking: 5 minutes (hard limit). With node tracking: no limit (task continues until result is found or node disappears).

---

## 25. Contributing & Future Work

### Known Limitations for Future Enhancement

1. **Master failover** — Currently no automatic promotion of a friend to master. Could implement via Zookeeper or distributed consensus.
2. **Direct friend-to-friend dispatch** — Could use a relay pattern (master mediates) or allow cross-friend messaging.
3. **Resource constraints** — No built-in CPU/memory limits per friend. Could add cgroup-based isolation.
4. **Encryption in transit** — Currently relies on network-level security. Could add TLS between nodes.
5. **Atomic task queuing** — Currently non-transactional. Could use Redis transactions for stronger guarantees.

### How to Extend

See [Section 19: Extension Points](#19-extension-points) for concrete examples of adding new message types, context types, and API endpoints.

---

_Sources: `packages/opencode/src/bridge/index.ts`, `packages/opencode/src/bridge/bridge.sql.ts`, `packages/opencode/src/server/routes/bridge.ts`, `packages/opencode/src/tool/ping_bridge_session.ts`, `packages/opencode/src/tool/task.ts`, `packages/opencode/src/agent/agent.ts`, `packages/opencode/src/cli/cmd/tui/thread.ts`, `packages/opencode/src/cli/cmd/tui/context/bridge.tsx`, `packages/docs/bridge.mdx`_

**Document Version:** 1.0  
**Generated:** 2026-04-18  
**Maintainer:** OpenCode Team  
**Status:** Production Ready
