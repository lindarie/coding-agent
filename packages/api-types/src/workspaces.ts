/** Mirrors NAME_RE in apps/agent/app/workspace.py; the server is the source of truth. */
export const WORKSPACE_NAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;
export const WORKSPACE_NAME_HELP =
  "Use 1-64 characters: letters, digits, '.', '_' or '-', starting with a letter or digit";

export interface CreatedWorkspace {
  name: string;
  created_at: number;
}

export interface WorkspaceDetail {
  name: string;
  /** Unix seconds. null for folders that were not created through the API (e.g. the seeded demo). */
  created_at: number | null;
  run_count: number;
  last_run_at: number | null;
}

export interface FileHistoryEntry {
  run_id: string;
  workspace: string;
  task: string;
  path: string;
  change: "created" | "modified";
  bytes: number;
  ts: number;
}

export interface GitCommit {
  hash: string;
  timestamp: number;
  subject: string;
  workspace: string;
}

export interface WorkspaceFileEntry {
  path: string;
  is_dir: boolean;
  size: number;
}