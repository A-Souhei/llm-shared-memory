import { homedir } from "os";
import { join, dirname } from "path";
import { readFileSync, writeFileSync, mkdirSync, unlinkSync } from "fs";
import { randomBytes } from "crypto";

export const BASE_URL = process.env.BIBLION_API_URL ?? "http://localhost:18765";
const TIMEOUT_MS = 30_000;

async function request(method: "GET" | "POST" | "DELETE", path: string, body?: unknown, params?: Record<string, string>): Promise<unknown> {
  const url = new URL(path, BASE_URL);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v != null) url.searchParams.set(k, v);
    }
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(url.toString(), {
      method,
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
    if (!res.ok) throw new Error(`${method} ${path} → ${res.status} ${res.statusText}`);
    return res.json();
  } catch (e) {
    if ((e as Error).name === "AbortError") throw new Error(`${method} ${path} timed out after ${TIMEOUT_MS / 1000}s`);
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

export function getJson(path: string, params?: Record<string, string>): Promise<unknown> {
  return request("GET", path, undefined, params);
}

export function postJson(path: string, body: unknown): Promise<unknown> {
  return request("POST", path, body);
}

export function deleteJson(path: string, params?: Record<string, string>): Promise<unknown> {
  return request("DELETE", path, undefined, params);
}

// ─── Session ──────────────────────────────────────────────────────────────────

const SESSION_FILE = process.env.BIBLION_SESSION_FILE ?? join(homedir(), ".biblion", "session_id");

export function loadSessionId(): string {
  if (process.env.BIBLION_SESSION_ID) return process.env.BIBLION_SESSION_ID;
  try { return readFileSync(SESSION_FILE, "utf8").trim(); } catch { return ""; }
}

export function saveSessionId(id: string): void {
  mkdirSync(dirname(SESSION_FILE), { recursive: true });
  writeFileSync(SESSION_FILE, id);
}

export function clearSessionId(): void {
  try { unlinkSync(SESSION_FILE); } catch { /* already gone */ }
}

export function newSessionId(): string {
  return "ses_" + randomBytes(6).toString("hex");
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
