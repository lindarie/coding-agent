import { Component, type ReactNode } from "react";
import type { AgentEvent } from "@coding-agent/api-types";

function toolSummary(ev: Extract<AgentEvent, { type: "tool_call" }>): string {
  const path = typeof ev.arguments.path === "string" ? ev.arguments.path : "";
  const pattern = typeof ev.arguments.pattern === "string" ? ev.arguments.pattern : "";
  const command = typeof ev.arguments.command === "string" ? ev.arguments.command : "";
  switch (ev.tool) {
    case "read_file":
      return path ? `Reading file ${path}` : "Reading project file";
    case "write_file":
      return path ? `Writing file ${path}` : "Writing project file";
    case "list_files":
      return path ? `Listing files in ${path}` : "Listing project files";
    case "search_files":
      return pattern ? `Searching for ${pattern}` : "Searching project files";
    case "run_command":
      return command ? `Running command: ${command}` : "Running project command";
    default:
      return `Running ${ev.tool.replace(/_/g, " ")}`;
  }
}

export function EventRow({ ev }: { ev: AgentEvent }) {
  switch (ev.type) {
    case "agent_started":
      return <div className="row muted">▶ run {ev.run_id} · {ev.model} · max {ev.max_iterations} iterations</div>;
    case "status":
      return <div className="row muted">… {ev.message}{ev.iteration ? ` (iteration ${ev.iteration})` : ""}</div>;
    case "agent_message":
      return <div className="row msg">{ev.content}</div>;
    case "tool_call":
      return (
        <details className="row tool">
          <summary><b>{toolSummary(ev)}</b></summary>
          <details className="event-detail">
            <summary>Tool arguments</summary>
            <pre>{JSON.stringify(ev.arguments ?? {}, null, 2)}</pre>
          </details>
        </details>
      );
    case "tool_result":
      return (
        <details className={`row ${ev.success ? "ok" : "bad"}`}>
          <summary>{ev.success ? "✓" : "✗"} {ev.tool.replace(/_/g, " ")} {ev.success ? "completed" : "failed"}</summary>
          <pre>{ev.output}</pre>
        </details>
      );
    case "file_changed":
      return <div className="row file">{ev.change === "created" ? "Created" : "Updated"} file <code>{ev.path}</code> ({ev.bytes} bytes)</div>;
    case "command_started":
      return <div className="row cmd">Running command: <code>{ev.command}</code></div>;
    case "command_finished":
      return (
        <details className={`row ${ev.exit_code === 0 ? "ok" : "bad"}`} open={ev.exit_code !== 0}>
          <summary>
            Command {ev.timed_out ? "timed out" : ev.exit_code === 0 ? "completed" : "failed"} · {ev.duration_s}s
          </summary>
          <pre>{ev.output}</pre>
        </details>
      );
    case "error":
      return <div className="row bad">⚠ {ev.message}</div>;
    case "agent_finished":
      return (
        <div className={`row done ${ev.status === "completed" ? "ok" : "bad"}`}>
          <b>■ {ev.status}</b> after {ev.iterations} iterations
          {ev.git_branch && <div>branch: <code>{ev.git_branch}</code></div>}
          {ev.diff_stat && <pre>{ev.diff_stat}</pre>}
        </div>
      );
  }
}

/** A row that fails to render must never blank the whole page: show why, and the raw event. */
export class RowBoundary extends Component<{ ev: AgentEvent; children: ReactNode }, { err: Error | null }> {
  state = { err: null as Error | null };
  static getDerivedStateFromError(err: Error) {
    return { err };
  }
  render() {
    if (!this.state.err) return this.props.children;
    return (
      <details className="row bad" open>
        <summary>⚠ could not render "{this.props.ev.type}" event: {this.state.err.message}</summary>
        <pre>{JSON.stringify(this.props.ev, null, 2)}</pre>
      </details>
    );
  }
}
