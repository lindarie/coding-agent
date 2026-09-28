import { Component, useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import {
  getHealth,
  listWorkspaces,
  streamRun,
  type AgentEvent,
  type Health,
} from "@coding-agent/api-types";

function EventRow({ ev }: { ev: AgentEvent }) {
  switch (ev.type) {
    case "agent_started":
      return <div className="row muted">▶ run {ev.run_id} · {ev.model} · max {ev.max_iterations} iterations</div>;
    case "status":
      return <div className="row muted">… {ev.message}{ev.iteration ? ` (iteration ${ev.iteration})` : ""}</div>;
    case "agent_message":
      return <div className="row msg">{ev.content}</div>;
    case "tool_call":
      return (
        <div className="row tool">
          <b>🔧 {ev.tool}</b> <code>{JSON.stringify(ev.arguments ?? {}).slice(0, 300)}</code>
        </div>
      );
    case "tool_result":
      return (
        <details className={`row ${ev.success ? "ok" : "bad"}`}>
          <summary>{ev.success ? "✓" : "✗"} {ev.tool} result</summary>
          <pre>{ev.output}</pre>
        </details>
      );
    case "file_changed":
      return <div className="row file">📝 {ev.change} <code>{ev.path}</code> ({ev.bytes} bytes)</div>;
    case "command_started":
      return <div className="row cmd">$ <code>{ev.command}</code></div>;
    case "command_finished":
      return (
        <details className={`row ${ev.exit_code === 0 ? "ok" : "bad"}`} open={ev.exit_code !== 0}>
          <summary>
            exit {ev.timed_out ? "timeout" : ev.exit_code} · {ev.duration_s}s
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
class RowBoundary extends Component<{ ev: AgentEvent; children: ReactNode }, { err: Error | null }> {
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

export function App() {
  const [workspaces, setWorkspaces] = useState<string[]>([]);
  const [workspace, setWorkspace] = useState("");
  const [task, setTask] = useState("Add a fibonacci(n) function to mathutils.py and tests for it.");
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    listWorkspaces()
      .then((w) => {
        setWorkspaces(w);
        setWorkspace((cur) => cur || w[0] || "");
      })
      .catch((e: Error) => setError(e.message));
    getHealth().then(setHealth).catch(() => setHealth(null));
  }, []);

  useEffect(() => {
    // Braces matter: an effect must not return a value (React would call it as a cleanup function).
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events]);

  const run = useCallback(async () => {
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setEvents([]);
    setError(null);
    setRunning(true);
    try {
      for await (const ev of streamRun({ task, workspace }, { signal: ctrl.signal })) {
        setEvents((prev) => [...prev, ev]);
      }
    } catch (e) {
      if ((e as Error).name !== "AbortError") setError((e as Error).message);
    } finally {
      setRunning(false);
    }
  }, [task, workspace]);

  const stop = () => abortRef.current?.abort();

  return (
    <main>
      <header>
        <h1>coding-agent</h1>
        <span className={`pill ${health?.ollama ? "ok" : "bad"}`}>
          ollama {health ? (health.ollama ? "up" : "down") : "?"}
          {health && health.ollama && !health.model_available ? ` · model ${health.model} missing` : ""}
        </span>
      </header>

      <section className="controls">
        <select value={workspace} onChange={(e) => setWorkspace(e.target.value)} disabled={running}>
          {workspaces.length === 0 && <option value="">(no workspaces)</option>}
          {workspaces.map((w) => (
            <option key={w}>{w}</option>
          ))}
        </select>
        <textarea value={task} onChange={(e) => setTask(e.target.value)} rows={3} disabled={running} />
        {running ? (
          <button onClick={stop} className="stop">Stop</button>
        ) : (
          <button onClick={run} disabled={!task.trim() || !workspace}>Run agent</button>
        )}
      </section>

      {error && <div className="row bad">⚠ {error}</div>}
      <section className="log">
        {events.map((ev) => (
          <RowBoundary key={`${ev.run_id}-${ev.seq}`} ev={ev}>
            <EventRow ev={ev} />
          </RowBoundary>
        ))}
        <div ref={endRef} />
      </section>
    </main>
  );
}
