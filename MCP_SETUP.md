# Biblion MCP — Setup Guide

The biblion MCP server exposes bridge, knowledge base, and code index tools to any MCP-compatible AI agent. It communicates with the biblion REST API over HTTP, so the biblion server must be running before you connect.

## Prerequisites

1. **Biblion server running** — `biblion` (default port `18765`)
2. **Python ≥ 3.11** with the package installed:

```bash
cd /path/to/llm-shared-memory
pip install -e .        # or: uv sync
```

Confirm the entry point works:

```bash
biblion-mcp --help
# should print FastMCP usage
```

---

## Claude Code

Add the MCP server with one command:

```bash
claude mcp add biblion -- biblion-mcp
```

If `biblion-mcp` is not on your `PATH` (e.g. installed in a virtualenv), use the full path:

```bash
claude mcp add biblion -- /path/to/venv/bin/biblion-mcp
```

To point at a non-default biblion URL (e.g. a remote server):

```bash
claude mcp add biblion -e BIBLION_API_URL=http://my-server:18765 -- biblion-mcp
```

Verify it was added:

```bash
claude mcp list
```

To remove:

```bash
claude mcp remove biblion
```

> Tools appear as `bridge_set_master`, `bridge_push_task`, `biblion_search`, etc. in your Claude Code session.

---

## OpenCode / VuhitraCode

Add the server to `.opencode/config.json` (or `.vuhitra/config.json`) in your project root, or to the global config at `~/.config/opencode/config.json`:

```json
{
  "mcp": {
    "servers": {
      "biblion": {
        "type": "local",
        "command": "biblion-mcp",
        "env": {
          "BIBLION_API_URL": "http://localhost:18765"
        }
      }
    }
  }
}
```

Full path variant (when not on `PATH`):

```json
{
  "mcp": {
    "servers": {
      "biblion": {
        "type": "local",
        "command": "/path/to/venv/bin/biblion-mcp",
        "env": {
          "BIBLION_API_URL": "http://localhost:18765"
        }
      }
    }
  }
}
```

Restart opencode after editing the config. Tools are available immediately in the next session.

---

## Slack notifications (optional)

Set `SLACK_WEBHOOK_URL` so the server can notify you when bridge events need attention (task queued for friend, result ready for master, node joined/left):

**Claude Code:**

```bash
claude mcp add biblion \
  -e BIBLION_API_URL=http://localhost:18765 \
  -e SLACK_WEBHOOK_URL=https://hooks.slack.com/services/XXX/YYY/ZZZ \
  -- biblion-mcp
```

**OpenCode:**

```json
{
  "mcp": {
    "servers": {
      "biblion": {
        "type": "local",
        "command": "biblion-mcp",
        "env": {
          "BIBLION_API_URL": "http://localhost:18765",
          "SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/XXX/YYY/ZZZ"
        }
      }
    }
  }
}
```

Get a webhook URL at **api.slack.com → Your Apps → Incoming Webhooks**.

---

## How sessions work

`bridge_set_master` and `bridge_set_friend` auto-generate a session ID and save the active session to `~/.biblion/bridge_session.json`. All subsequent bridge tools read from this file, so you never have to pass `bridge_id` or `session_id` explicitly.

```
master agent                          friend agent
─────────────────────────────────     ─────────────────────────────────
bridge_set_master slug="backend"      bridge_set_friend "backend"
  → saved to ~/.biblion/...             → saved to ~/.biblion/...

bridge_push_task                      bridge_fetch_tasks
  to_node_id="ses_..."                  → returns prompts, clears queue
  prompt="Refactor auth module"
                                      bridge_share_context
bridge_get_context                      type="task_result"
  → reads friend's result               content="task_id: ...\nDone"
```

The working directory defaults to `$PWD` — no need to pass it manually.

## Available tools

| Tool | Notes |
|------|-------|
| `bridge_set_master` | Register as master; saves session locally |
| `bridge_set_friend` | Join a bridge by ID or slug; saves session locally |
| `bridge_leave` | Leave and clear the local session |
| `bridge_heartbeat` | Keep this node alive (~15 s interval) |
| `bridge_get_info` | Show all nodes, roles, and heartbeat age |
| `bridge_push_task` | Queue a prompt for a friend |
| `bridge_fetch_tasks` | Dequeue all pending tasks (friend) |
| `bridge_share_context` | Push a finding / task result to shared context |
| `bridge_get_context` | Read recent shared context entries (master reads results here) |
| `biblion_search` | *(coming soon)* Semantic search over the knowledge base |
| `biblion_write` | *(coming soon)* Write a knowledge entry |
| `biblion_list` | *(coming soon)* List knowledge base entries |
| `indexer_search` | *(coming soon)* Semantic search over indexed code |
| `indexer_ingest` | *(coming soon)* Index a codebase directory |
