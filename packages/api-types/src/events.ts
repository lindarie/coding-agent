// Mirrors apps/agent/app/events.py — keep both in sync.

export interface BaseEvent {
  run_id: string;
  seq: number;
  ts: number;
}

export interface AgentStartedEvent extends BaseEvent {
  type: "agent_started";
  task: string;
  workspace: string;
  model: string;
  max_iterations: number;
}
export interface StatusEvent extends BaseEvent {
  type: "status";
  message: string;
  iteration?: number | null;
  phase?: "analyzing" | "context" | "coding" | "checking" | "committing" | null;
}
export interface ToolCallEvent extends BaseEvent {
  type: "tool_call";
  tool: string;
  arguments: Record<string, unknown>;
  iteration: number;
}
export interface ToolResultEvent extends BaseEvent {
  type: "tool_result";
  tool: string;
  success: boolean;
  output: string;
}
export interface FileChangedEvent extends BaseEvent {
  type: "file_changed";
  path: string;
  change: "created" | "modified";
  bytes: number;
}
export interface CommandStartedEvent extends BaseEvent {
  type: "command_started";
  command: string;
}
export interface CommandFinishedEvent extends BaseEvent {
  type: "command_finished";
  command: string;
  exit_code: number | null;
  timed_out: boolean;
  duration_s: number;
  output: string;
}
export interface AgentMessageEvent extends BaseEvent {
  type: "agent_message";
  content: string;
}
export interface ErrorEvent extends BaseEvent {
  type: "error";
  message: string;
}
export type FinishStatus = "completed" | "max_iterations" | "error";
export interface AgentFinishedEvent extends BaseEvent {
  type: "agent_finished";
  status: FinishStatus;
  summary: string;
  iterations: number;
  git_branch: string | null;
  diff_stat: string | null;
}

export type AgentEvent =
  | AgentStartedEvent
  | StatusEvent
  | ToolCallEvent
  | ToolResultEvent
  | FileChangedEvent
  | CommandStartedEvent
  | CommandFinishedEvent
  | AgentMessageEvent
  | ErrorEvent
  | AgentFinishedEvent;

export type AgentEventType = AgentEvent["type"];

export interface RunRequest {
  task: string;
  workspace: string;
  max_iterations?: number;
  model?: string;
}

export interface RunSummary {
  id: string;
  task: string;
  workspace: string;
  model: string;
  status: "running" | FinishStatus | "cancelled" | "interrupted";
  summary: string | null;
  created_at: number;
  finished_at: number | null;
}
export interface RunDetail extends RunSummary {
  events: AgentEvent[];
}
export interface Health {
  status: string;
  ollama: boolean;
  models: string[];
  tool_models: string[];
  model: string;
  model_available: boolean;
  sandbox_mode: "docker" | "local";
}
