import type { AgentEvent, Health, RunDetail, RunRequest, RunSummary } from "./events";
import type {
  CreatedWorkspace,
  FileHistoryEntry,
  GitCommit,
  WorkspaceDetail,
  WorkspaceFileEntry,
} from "./workspaces";

export interface ClientOptions {
  /** e.g. "http://localhost:8000". Empty string = same origin (browser behind the nginx proxy). */
  baseUrl?: string;
  /** Bearer token, if AGENT_API_TOKEN is set on the agent. */
  token?: string;
  signal?: AbortSignal;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

function headers(opts: ClientOptions, json = false): Record<string, string> {
  const h: Record<string, string> = {};
  if (json) h["Content-Type"] = "application/json";
  if (opts.token) h["Authorization"] = `Bearer ${opts.token}`;
  return h;
}

async function getJson<T>(path: string, opts: ClientOptions): Promise<T> {
  const res = await fetch(`${opts.baseUrl ?? ""}${path}`, { headers: headers(opts), signal: opts.signal });
  if (!res.ok) throw new ApiError(res.status, await errorText(res));
  return (await res.json()) as T;
}

async function errorText(res: Response): Promise<string> {
  const text = await res.text();
  try {
    const detail = (JSON.parse(text) as { detail?: unknown }).detail;
    if (detail === undefined) return text;
    return typeof detail === "string" ? detail : JSON.stringify(detail); // FastAPI 422 detail is an array
  } catch {
    return text;
  }
}

export const getHealth = (o: ClientOptions = {}) => getJson<Health>("/api/health", o);
export const listWorkspaces = (o: ClientOptions = {}) => getJson<string[]>("/api/workspaces", o);
export interface HistoryQuery extends ClientOptions {
  /** Only this workspace. Omit for all. */
  workspace?: string;
  limit?: number;
}

function query(params: Record<string, string | number | undefined>): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") qs.set(k, String(v));
  const text = qs.toString();
  return text ? `?${text}` : "";
}

export const listRuns = (o: HistoryQuery = {}) =>
  getJson<RunSummary[]>(`/api/runs${query({ workspace: o.workspace, limit: o.limit })}`, o);
export const listFileHistory = (o: HistoryQuery = {}) =>
  getJson<FileHistoryEntry[]>(`/api/files${query({ workspace: o.workspace, limit: o.limit })}`, o);
export const listWorkspaceDetails = (o: ClientOptions = {}) =>
  getJson<WorkspaceDetail[]>("/api/workspaces/details", o);
export const listGitLog = (o: HistoryQuery = {}) =>
  getJson<GitCommit[]>(`/api/git-log${query({ workspace: o.workspace, limit: o.limit })}`, o);
export const listWorkspaceFiles = (workspace: string, o: ClientOptions = {}) =>
  getJson<WorkspaceFileEntry[]>(`/api/workspaces/${encodeURIComponent(workspace)}/files`, o);
export const getWorkspaceFile = (workspace: string, path: string, o: ClientOptions = {}) =>
  getJson<{ path: string; content: string }>(
    `/api/workspaces/${encodeURIComponent(workspace)}/file${query({ path })}`,
    o,
  );
export const getCommitDiff = (workspace: string, hash: string, o: ClientOptions = {}) =>
  getJson<{ diff: string }>(
    `/api/workspaces/${encodeURIComponent(workspace)}/git-log/${encodeURIComponent(hash)}`,
    o,
  );

/** Create an empty project directory. Rejects with ApiError (400 invalid name, 409 already exists). */
export async function createWorkspace(name: string, o: ClientOptions = {}): Promise<CreatedWorkspace> {
  const res = await fetch(`${o.baseUrl ?? ""}/api/workspaces`, {
    method: "POST",
    headers: headers(o, true),
    body: JSON.stringify({ name }),
    signal: o.signal,
  });
  if (!res.ok) throw new ApiError(res.status, await errorText(res));
  return (await res.json()) as CreatedWorkspace;
}
export const getRun = (id: string, o: ClientOptions = {}) => getJson<RunDetail>(`/api/runs/${id}`, o);

/** Start a run and yield AgentEvents as they arrive (Server-Sent Events over a POST). */
export async function* streamRun(req: RunRequest, opts: ClientOptions = {}): AsyncGenerator<AgentEvent> {
  const res = await fetch(`${opts.baseUrl ?? ""}/api/agent/run`, {
    method: "POST",
    headers: headers(opts, true),
    body: JSON.stringify(req),
    signal: opts.signal,
  });
  if (!res.ok || !res.body) throw new ApiError(res.status, await errorText(res));

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n"); // proxies may rewrite line endings
    let idx: number;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const frame = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const data = frame
        .split("\n")
        .filter((l) => l.startsWith("data:"))
        .map((l) => l.slice(5).trimStart())
        .join("\n");
      if (!data) continue;
      let ev: AgentEvent;
      try {
        ev = JSON.parse(data) as AgentEvent;
      } catch {
        throw new Error(`Unreadable event from server: ${data.slice(0, 200)}`);
      }
      yield ev;
    }
  }
}
