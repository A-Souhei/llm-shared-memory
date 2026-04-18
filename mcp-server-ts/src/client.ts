import { homedir } from "os";
import { join } from "path";
import { readFileSync, writeFileSync, mkdirSync, unlinkSync } from "fs";

export const BASE_URL = process.env.BIBLION_API_URL ?? "http://localhost:18765";

async function request(method: "GET" | "POST", path: string, body?: unknown, params?: Record<string, string>): Promise<unknown> {
  const url = new URL(path, BASE_URL);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v != null) url.searchParams.set(k, v);
    }
  }
  const res = await fetch(url.toString(), {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`${method} ${path} → ${res.status} ${res.statusText}`);
  return res.json();
}

export function getJson(path: string, params?: Record<string, string>): Promise<unknown> {
  return request("GET", path, undefined, params);
}

export function postJson(path: string, body: unknown): Promise<unknown> {
  return request("POST", path, body);
}

// ─── Session ──────────────────────────────────────────────────────────────────

const SESSION_FILE = process.env.BIBLION_SESSION_FILE ?? join(homedir(), ".biblion", "session_id");

export function loadSessionId(): string {
  if (process.env.BIBLION_SESSION_ID) return process.env.BIBLION_SESSION_ID;
  try { return readFileSync(SESSION_FILE, "utf8").trim(); } catch { return ""; }
}

export function saveSessionId(id: string): void {
  mkdirSync(join(homedir(), ".biblion"), { recursive: true });
  writeFileSync(SESSION_FILE, id);
}

export function clearSessionId(): void {
  try { unlinkSync(SESSION_FILE); } catch { /* already gone */ }
}

export function newSessionId(): string {
  return "ses_" + Math.random().toString(36).slice(2, 14).padEnd(12, "0");
}

export async function resolveSession(): Promise<{ bridgeId: string; sessionId: string }> {
  const sessionId = loadSessionId();
  if (!sessionId) throw new Error("No active session. Call bridge_set_master or bridge_set_friend first.");
  let data: Record<string, unknown>;
  try {
    data = await getJson("/bridge/session", { session_id: sessionId }) as Record<string, unknown>;
  } catch (e) {
    throw new Error(`Could not resolve session (${e}). Call bridge_set_master or bridge_set_friend first.`);
  }
  if (!data["active"]) {
    throw new Error(`Bridge is no longer active (${data["reason"] ?? "unknown"}). Call bridge_set_master or bridge_set_friend to start a new one.`);
  }
  return { bridgeId: data["bridge_id"] as string, sessionId };
}

export async function getRole(): Promise<string> {
  const sessionId = loadSessionId();
  if (!sessionId) return "unknown";
  try {
    const data = await getJson("/bridge/session", { session_id: sessionId }) as Record<string, unknown>;
    return (data["role"] as string) ?? "unknown";
  } catch { return "unknown"; }
}
