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

## Available tools

| Tool | Description |
|------|-------------|
| `bridge_set_master` | Register this agent as a bridge master |
| `bridge_set_friend` | Join an existing bridge as a friend |
| `bridge_leave` | Leave the bridge cleanly |
| `bridge_heartbeat` | Keep this node alive (call every ~15 s) |
| `bridge_push_task` | Queue a prompt for a friend node |
| `bridge_fetch_tasks` | Dequeue and return pending tasks (friend) |
| `bridge_share_context` | Push a finding or task result to shared context |
| `bridge_get_context` | Read recent shared context entries |
| `bridge_get_info` | Show all nodes, roles, and heartbeat status |
| `biblion_search` | *(coming soon)* Semantic search over the knowledge base |
| `biblion_write` | *(coming soon)* Write a knowledge entry |
| `biblion_list` | *(coming soon)* List knowledge base entries |
| `indexer_search` | *(coming soon)* Semantic search over indexed code |
| `indexer_ingest` | *(coming soon)* Index a codebase directory |
