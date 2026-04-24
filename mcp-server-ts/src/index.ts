#!/usr/bin/env node
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import {
  BASE_URL, getJson, postJson,
  loadSessionId, saveSessionId, clearSessionId, newSessionId,
  resolveSession, getRole,
} from "./client.js";

const server = new McpServer({
  name: "biblion",
  version: "0.1.0",
});

function ok(text: string) {
  return { content: [{ type: "text" as const, text }] };
}

// ─── Bridge — session setup ───────────────────────────────────────────────────

server.tool(
  "bridge_set_master",
  "Register this agent as the bridge master. Creates a new bridge session and saves the session ID locally.",
  {
    slug: z.string().default("").describe("Short human-readable name friends use to join (e.g. 'frontend')."),
    title: z.string().default("").describe("Display name shown in the web UI."),
    directory: z.string().default("").describe("Working directory of this agent (defaults to $PWD)."),
    node_url: z.string().default("").describe("Externally reachable HTTP URL — only needed cross-machine."),
    limit: z.number().int().default(3).describe("Max total nodes (master + friends). Default 3."),
    project_id: z.string().default("").describe("Project identifier, e.g. the repo name."),
    session_id: z.string().default("").describe("Override the auto-generated session ID (rarely needed)."),
  },
  async ({ slug, title, directory, node_url, limit, project_id, session_id }) => {
    const sid = session_id || newSessionId();
    const dir = directory || process.env.PWD || "";
    const data = await postJson("/bridge/set-master", { session_id: sid, slug, title, directory: dir, node_url, limit, project_id }) as Record<string, unknown>;
    saveSessionId(sid);
    const nodes = (data["nodes"] as unknown[]) ?? [];
    return ok(
      `Bridge created — session ID saved.\n` +
      `bridge_id: ${data["bridge_id"]}\n` +
      `slug: ${data["master_slug"] || "(none)"}\n` +
      `nodes: ${nodes.length}/${data["limit"]}\n` +
      `Share the bridge_id or slug so friends can join with bridge_set_friend.`
    );
  }
);

server.tool(
  "bridge_set_friend",
  "Join an existing bridge as a friend node. Saves the session ID locally.",
  {
    master_id_or_slug: z.string().describe("The master's bridge_id or slug to join."),
    slug: z.string().default("").describe("Short name for this friend node."),
    title: z.string().default("").describe("Display name shown in the web UI."),
    directory: z.string().default("").describe("Working directory of this friend agent (defaults to $PWD)."),
    node_url: z.string().default("").describe("Externally reachable HTTP URL — only needed cross-machine."),
    project_id: z.string().default("").describe("Project identifier for this friend's codebase."),
    session_id: z.string().default("").describe("Override the auto-generated session ID (rarely needed)."),
  },
  async ({ master_id_or_slug, slug, title, directory, node_url, project_id, session_id }) => {
    const sid = session_id || newSessionId();
    const dir = directory || process.env.PWD || "";
    const data = await postJson("/bridge/set-friend", { master_id_or_slug, session_id: sid, slug, title, directory: dir, node_url, project_id }) as Record<string, unknown>;
    saveSessionId(sid);
    const nodes = (data["nodes"] as Array<Record<string, string>>) ?? [];
    return ok(
      `Joined bridge — session ID saved.\n` +
      `bridge_id: ${data["bridge_id"]}\n` +
      `nodes: ${nodes.map(n => n["slug"] || n["node_id"]).join(", ")}`
    );
  }
);

server.tool(
  "bridge_leave",
  "Leave the current bridge and clear the local session ID. If master, the bridge is closed for all nodes.",
  {},
  async () => {
    const sessionId = loadSessionId();
    if (!sessionId) return ok("No active session.");
    try {
      const { bridgeId } = await resolveSession();
      await postJson("/bridge/leave", { bridge_id: bridgeId, session_id: sessionId });
    } catch { /* bridge already gone */ }
    clearSessionId();
    return ok("Left bridge. Local session ID cleared.");
  }
);

// ─── Bridge — daily use ───────────────────────────────────────────────────────

server.tool(
  "bridge_heartbeat",
  "Update this node's liveness timestamp. Call roughly every 15 seconds to stay visible.",
  {},
  async () => {
    const { bridgeId, sessionId } = await resolveSession();
    await postJson("/bridge/heartbeat", { bridge_id: bridgeId, session_id: sessionId });
    return ok("Heartbeat sent.");
  }
);

server.tool(
  "bridge_get_info",
  "Get the current bridge state: all nodes, their roles, directories, and heartbeat age.",
  {},
  async () => {
    const { bridgeId } = await resolveSession();
    const data = await getJson("/bridge/info", { bridge_id: bridgeId }) as Record<string, unknown>;
    if (!data) return ok("Bridge not found or no active nodes.");
    const nodes = (data["nodes"] as Array<Record<string, unknown>>) ?? [];
    const lines = [
      `Bridge ${data["bridge_id"]} (slug: ${data["master_slug"] || "-"}) — ${nodes.length}/${data["limit"]} nodes`
    ];
    for (const n of nodes) {
      const ageS = Math.floor((Date.now() - (n["heartbeat"] as number)) / 1000);
      lines.push(`  [${n["role"]}] ${n["slug"] || n["node_id"]}  dir=${n["directory"]}  project=${n["project_id"] || "-"}  heartbeat=${ageS}s ago  status=${n["status"]}`);
    }
    return ok(lines.join("\n"));
  }
);

server.tool(
  "bridge_push_task",
  "Push a task (prompt) to a friend node's queue.",
  {
    to_node_id: z.string().describe("The target friend's node_id. Use bridge_get_info to list nodes."),
    prompt: z.string().describe("The full prompt / instructions for the friend to execute."),
    description: z.string().default("").describe("Short summary shown in the Slack notification."),
  },
  async ({ to_node_id, prompt, description }) => {
    const { bridgeId, sessionId } = await resolveSession();
    const data = await postJson("/bridge/push-task", { bridge_id: bridgeId, from_session_id: sessionId, to_node_id, prompt, description }) as Record<string, unknown>;
    return ok(`Task queued. task_id=${data["task_id"]}`);
  }
);

server.tool(
  "bridge_fetch_tasks",
  "Fetch and consume all tasks queued for this node. Clears the queue after reading.",
  {},
  async () => {
    const { bridgeId, sessionId } = await resolveSession();
    const data = await getJson("/bridge/fetch-tasks", { bridge_id: bridgeId, session_id: sessionId });
    const tasks = Array.isArray(data) ? data as Array<Record<string, unknown>> : [];
    if (!tasks.length) return ok("No pending tasks.");
    const lines = [`${tasks.length} task(s) received:`];
    for (const t of tasks) {
      lines.push(`\n--- task_id=${t["task_id"]} (${t["description"] || ""}) ---`);
      lines.push(t["prompt"] as string);
    }
    return ok(lines.join("\n"));
  }
);

server.tool(
  "bridge_share_context",
  "Share a context entry with all bridge participants.",
  {
    type: z.string().describe("One of: finding, work_summary, task_result, status."),
    content: z.string().describe('The content to share. For task results prefix with the task_id: "task_id: <id>\\n<result>".'),
    directory: z.string().default("").describe("Override directory."),
  },
  async ({ type, content, directory }) => {
    const { bridgeId, sessionId } = await resolveSession();
    const role = await getRole();
    await postJson("/bridge/share-context", { bridge_id: bridgeId, session_id: sessionId, role, type, content, directory });
    return ok(`Context shared (type=${type}).`);
  }
);

server.tool(
  "bridge_get_context",
  "Read recent shared context entries from the bridge (newest first).",
  {
    limit: z.number().int().default(20).describe("Number of entries to return (1-200, default 20)."),
  },
  async ({ limit }) => {
    const { bridgeId } = await resolveSession();
    const data = await getJson("/bridge/context", { bridge_id: bridgeId, limit: String(limit) });
    const entries = Array.isArray(data) ? data as Array<Record<string, unknown>> : [];
    if (!entries.length) return ok("No context entries.");
    const lines = [`${entries.length} entries (newest first):`];
    for (const e of entries) {
      const ageS = Math.floor((Date.now() - (e["timestamp"] as number ?? 0)) / 1000);
      lines.push(`\n[${e["type"]}] ${e["role"] ?? "?"} @ ${e["directory"] ?? "-"} (${ageS}s ago)`);
      const c = e["content"] as string;
      lines.push(c.length > 500 ? c.slice(0, 500) + "…" : c);
    }
    return ok(lines.join("\n"));
  }
);

// ─── Biblion tools ────────────────────────────────────────────────────────────

server.tool(
  "biblion_search",
  "Search the semantic knowledge base for relevant entries.",
  {
    query: z.string().describe("Natural language query describing what you're looking for."),
    limit: z.number().int().default(5).describe("Max results (1-50, default 5)."),
    project_id: z.string().default("").describe("Narrow to a specific project, or leave empty for all."),
  },
  async ({ query, limit, project_id }) => {
    const results = await postJson("/biblion/search", { query, limit, project_id }) as Array<Record<string, unknown>>;
    if (!results.length) return ok("No results found.");
    const lines = [`${results.length} result(s):`];
    for (const r of results) {
      lines.push(`\n[${r["type"]}] score=${(r["score"] as number).toFixed(3)}  project=${r["project_id"] || "-"}  tags=${(r["tags"] as string[] ?? []).join(",")}`);
      const c = r["content"] as string;
      lines.push(c.length > 800 ? c.slice(0, 800) + "…" : c);
    }
    return ok(lines.join("\n"));
  }
);

server.tool(
  "biblion_write",
  "Write a knowledge entry to the biblion knowledge base.",
  {
    type: z.string().describe("Entry type: structure, pattern, dependency, api, config, or workflow."),
    content: z.string().describe("The knowledge to store (max 50 000 chars)."),
    tags: z.array(z.string()).default([]).describe("Optional list of tags."),
    project_id: z.string().default("").describe("Project this entry belongs to."),
  },
  async ({ type, content, tags, project_id }) => {
    const data = await postJson("/biblion/write", { type, content, tags, project_id }) as Record<string, unknown>;
    if (data["success"]) return ok(`Entry written. id=${data["id"]}`);
    return ok(`Write rejected: ${data["reason"] ?? "unknown"}`);
  }
);

server.tool(
  "biblion_list",
  "List all knowledge base entries, optionally filtered by project and/or type.",
  {
    project_id: z.string().default("").describe("Filter to a specific project, or leave empty for all."),
    type: z.string().default("").describe("Filter by entry type (structure, pattern, dependency, api, config, workflow)."),
  },
  async ({ project_id, type }) => {
    const params: Record<string, string> = {};
    if (project_id) params["project_id"] = project_id;
    if (type) params["type"] = type;
    const entries = await getJson("/biblion/list", params) as Array<Record<string, unknown>>;
    if (!entries.length) return ok("No entries found.");
    const lines = [`${entries.length} ${entries.length === 1 ? "entry" : "entries"}:`];
    for (const e of entries) {
      lines.push(`  [${e["type"]}] ${(e["id"] as string).slice(0, 8)}  project=${e["project_id"] || "-"}  tags=${e["tags"] || ""}`);
      const preview = (e["content"] as string).slice(0, 120).replace(/\n/g, " ");
      lines.push(`    ${preview}${(e["content"] as string).length > 120 ? "…" : ""}`);
    }
    return ok(lines.join("\n"));
  }
);

// ─── Memento tools ───────────────────────────────────────────────────────────

server.tool(
  "memento_save",
  "Save a cleaned session memento for the current project. Call this when the user asks to save a memento or before compaction. Distill the session into: commands used, operations/workflow steps, and notes on what worked or to avoid. project_id is required.",
  {
    project_id: z.string().describe("Project this memento belongs to (required, non-empty)."),
    content: z.string().describe("Cleaned session process in markdown: commands used, workflow steps, notes. Max 50 000 chars."),
  },
  async ({ project_id, content }) => {
    const data = await postJson("/biblion/memento/save", { project_id, content }) as Record<string, unknown>;
    if (data["success"]) return ok(`Memento saved. id=${data["id"]}`);
    return ok(`Memento save failed: ${data["reason"] ?? "unknown"}`);
  }
);

server.tool(
  "memento_load",
  "Load recent session mementos for the current project. Call this at the start of a session to restore process context lost during compaction.",
  {
    project_id: z.string().describe("Project to load mementos for (required)."),
    limit: z.number().int().default(3).describe("Number of mementos to return, newest first (default 3)."),
  },
  async ({ project_id, limit }) => {
    const entries = await getJson("/biblion/memento/list", { project_id }) as Array<Record<string, unknown>>;
    if (!entries.length) return ok(`No mementos found for project=${project_id}.`);
    const shown = entries.slice(0, limit);
    const lines = [`${entries.length} memento(s) for project=${project_id} (showing ${shown.length}):`];
    for (const e of shown) {
      lines.push(`\n--- [${e["created_at"] ?? ""}] id=${(e["id"] as string).slice(0, 8)} ---`);
      const c = e["content"] as string;
      lines.push(c.length > 2000 ? c.slice(0, 2000) + "…" : c);
    }
    return ok(lines.join("\n"));
  }
);

server.tool(
  "memento_clear",
  "Delete all mementos for a project. Use with caution — this is irreversible.",
  {
    project_id: z.string().describe("Project whose mementos to delete (required)."),
  },
  async ({ project_id }) => {
    const data = await fetch(`${BASE_URL}/biblion/memento/clear?project_id=${encodeURIComponent(project_id)}`, { method: "DELETE" });
    const json = await data.json() as Record<string, unknown>;
    return ok(`Cleared ${json["deleted"] ?? 0} memento(s) for project=${project_id}.`);
  }
);

// ─── Indexer tools ────────────────────────────────────────────────────────────

server.tool(
  "indexer_search",
  "Search indexed source code by semantic similarity.",
  {
    query: z.string().describe("What you're looking for in the codebase."),
    project_id: z.string().describe("The project to search (required — code index is per-project)."),
    top_k: z.number().int().default(5).describe("Number of code chunks to return (1-50, default 5)."),
  },
  async ({ query, project_id, top_k }) => {
    const data = await postJson("/indexer/search", { query, project_id, top_k }) as Record<string, unknown>;
    const results = Array.isArray(data["results"]) ? data["results"] as Array<Record<string, unknown>> : [];
    if (!results.length) return ok("No results found.");
    const lines = [`${results.length} chunk(s):`];
    for (const r of results) {
      lines.push(`\n${r["file_path"]}:${r["start_line"]}  score=${(r["score"] as number).toFixed(3)}`);
      const t = r["text"] as string;
      lines.push(t.length > 600 ? t.slice(0, 600) + "…" : t);
    }
    return ok(lines.join("\n"));
  }
);

server.tool(
  "indexer_ingest",
  "Ingest a directory into the code index for semantic search. Uses git ls-files when available, falls back to directory walk.",
  {
    directory: z.string().describe("Absolute path to the directory to index."),
    project_id: z.string().describe("Project identifier for this codebase."),
  },
  async ({ directory, project_id }) => {
    const { readdir, stat, readFile } = await import("fs/promises");
    const { execFile } = await import("child_process");
    const { promisify } = await import("util");
    const path = await import("path");
    const execFileAsync = promisify(execFile);

    const EXTENSIONS = new Set([".py",".ts",".tsx",".js",".jsx",".go",".rs",".java",".c",".cpp",".h",".hpp",".cs",".rb",".swift",".kt",".md",".txt",".yaml",".yml",".toml",".json",".sh"]);
    const SKIP_DIRS = new Set(["node_modules","__pycache__",".venv","venv",".mypy_cache",".pytest_cache","dist","build",".next","target"]);
    const MAX_BYTES = 512 * 1024;

    let relPaths: string[] = [];
    try {
      const { stdout: rootOut } = await execFileAsync("git", ["rev-parse", "--show-toplevel"], { cwd: directory, timeout: 10000 });
      const repoRoot = rootOut.trim();
      const { stdout } = await execFileAsync("git", ["ls-files", "--cached", "-z"], { cwd: directory, timeout: 10000 });
      relPaths = stdout.split("\0").filter(Boolean).map(p => {
        try { return path.relative(directory, path.resolve(repoRoot, p)); } catch { return ""; }
      }).filter(Boolean);
    } catch {
      const walk = async (dir: string): Promise<string[]> => {
        const results: string[] = [];
        for (const entry of await readdir(dir, { withFileTypes: true })) {
          if (entry.isDirectory()) {
            if (!SKIP_DIRS.has(entry.name) && !entry.name.startsWith(".")) {
              results.push(...await walk(path.join(dir, entry.name)));
            }
          } else {
            results.push(path.relative(directory, path.join(dir, entry.name)));
          }
        }
        return results;
      };
      relPaths = await walk(directory);
    }

    const files: { path: string; content: string; mtime: number }[] = [];
    await Promise.all(relPaths.map(async rel => {
      if (!EXTENSIONS.has(path.extname(rel).toLowerCase())) return;
      const abs = path.join(directory, rel);
      try {
        const st = await stat(abs);
        if (st.size > MAX_BYTES) return;
        const content = await readFile(abs, "utf8");
        files.push({ path: rel, content, mtime: st.mtimeMs });
      } catch { /* skip unreadable */ }
    }));

    if (!files.length) return ok(`No indexable files found in ${directory}.`);

    const data = await postJson("/indexer/ingest", { project_id, files, all_paths: files.map(f => f.path) }) as Record<string, unknown>;
    let msg = `Ingested project_id=${project_id}: ${data["indexed"] ?? "?"} indexed, ${data["skipped"] ?? "?"} skipped, ${data["deleted"] ?? "?"} deleted.`;
    const errors = data["errors"] as string[] | undefined;
    if (errors?.length) msg += "\nServer errors: " + errors.slice(0, 5).join("; ");
    return ok(msg);
  }
);

// ─── Start ────────────────────────────────────────────────────────────────────

const transport = new StdioServerTransport();
await server.connect(transport);
