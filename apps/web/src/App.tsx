import { useCallback, useEffect, useRef, useState } from "react";
import {
  createWorkspace,
  getHealth,
  listWorkspaces,
  streamRun,
  WORKSPACE_NAME_HELP,
  WORKSPACE_NAME_PATTERN,
  type AgentEvent,
  type Health,
} from "@coding-agent/api-types";
import { EventRow, RowBoundary } from "./EventLog";
import { HistoryView } from "./History";

type Tab = "run" | "history";
type AgentProgressPhase = "analyzing" | "context" | "coding" | "checking" | "committing";
type AgentProgressStep = AgentProgressPhase | "finished";

const progressSteps = [
  { id: "analyzing", label: "Analyzing prompt" },
  { id: "context", label: "Understanding context" },
  { id: "coding", label: "Writing code" },
  { id: "checking", label: "Running checks" },
  { id: "committing", label: "Committing" },
  { id: "finished", label: "Finished" },
] as const;

function AgentProgress({
  events,
  selectedPhase,
  onSelectPhase,
}: {
  events: AgentEvent[];
  selectedPhase: AgentProgressStep | null;
  onSelectPhase: (phase: AgentProgressStep) => void;
}) {
  const completed = new Set<AgentProgressPhase>();
  let current: AgentProgressPhase | null = null;
  let finishStatus: string | null = null;
  for (const event of events) {
    if (event.type === "status" && event.phase) {
      if (current && current !== event.phase) completed.add(current);
      current = event.phase;
    }
    if (event.type === "agent_finished") finishStatus = event.status;
  }

  if (finishStatus === "completed" && current) completed.add(current);
  const runFailed = finishStatus === "error";
  const runStopped = finishStatus === "max_iterations";
  const runCompleted = finishStatus === "completed";
  const active = finishStatus ? "finished" : current;
  const selected = selectedPhase ?? active ?? "analyzing";
  const phaseEvents: AgentEvent[] = [];
  let eventPhase: AgentProgressPhase = "analyzing";
  for (const event of events) {
    if (event.type === "status" && event.phase) eventPhase = event.phase;
    if (event.type === "agent_finished" ? selected === "finished" : selected === eventPhase) {
      phaseEvents.push(event);
    }
  }
  const selectedLabel = progressSteps.find((step) => step.id === selected)?.label ?? "Agent activity";

  return (
    <section className="agent-progress-section" aria-label="Agent progress">
      <div className="agent-progress-wrap">
        <ol className="agent-progress">
          {progressSteps.map((step, index) => {
            const failed = (step.id === current || step.id === "finished") && runFailed;
            const stopped = (step.id === current || step.id === "finished") && runStopped;
            const done = step.id !== "finished" && completed.has(step.id as AgentProgressPhase);
            const isFinished = step.id === "finished" && runCompleted;
            const isActive = step.id === active && !finishStatus;
            const isSelected = step.id === selected;
            const stateClass = done || isFinished ? "complete" : isActive ? "active" : failed ? "failed" : stopped ? "stopped" : "";
            return (
              <li key={step.id} className="agent-progress-step">
                <button
                  className={`agent-progress-button ${stateClass} ${isSelected ? "selected" : ""}`}
                  aria-pressed={isSelected}
                  onClick={() => onSelectPhase(step.id)}
                >
                  <span className="agent-progress-marker">{done || isFinished ? "✓" : index + 1}</span>
                  <span className="agent-progress-label">
                    {step.id === "finished" && runFailed
                      ? "Run failed"
                      : step.id === "finished" && runStopped
                        ? "Stopped"
                        : step.label}
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      </div>
      <section className="agent-phase-log" aria-label={`${selectedLabel} activity`}>
        <h2>{selectedLabel}</h2>
        {phaseEvents.length === 0 ? (
          <p className="muted">No activity recorded for this step yet.</p>
        ) : (
          <div className="log">
            {phaseEvents.map((event) => (
              <RowBoundary key={`${event.run_id}-${event.seq}`} ev={event}>
                <EventRow ev={event} />
              </RowBoundary>
            ))}
          </div>
        )}
      </section>
    </section>
  );
}

export function App() {
  const [tab, setTab] = useState<Tab>("run");
  const [workspaces, setWorkspaces] = useState<string[]>([]);
  const [workspace, setWorkspace] = useState("");
  const [selectedModel, setSelectedModel] = useState("");
  const [newName, setNewName] = useState("");
  const [showNewProject, setShowNewProject] = useState(false);
  const [creating, setCreating] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [task, setTask] = useState("Add a fibonacci(n) function to mathutils.py and tests for it.");
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [selectedProgressPhase, setSelectedProgressPhase] = useState<AgentProgressStep | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [historyKey, setHistoryKey] = useState(0);
  const abortRef = useRef<AbortController | null>(null);

  const refreshWorkspaces = useCallback(async (select?: string) => {
    const list = await listWorkspaces();
    setWorkspaces(list);
    setWorkspace((cur) => select ?? (list.includes(cur) ? cur : (list[0] ?? "")));
  }, []);

  useEffect(() => {
    refreshWorkspaces().catch((e: Error) => setError(e.message));
    getHealth().then(setHealth).catch(() => setHealth(null));
  }, [refreshWorkspaces]);

  const trimmed = newName.trim();
  const nameValid = WORKSPACE_NAME_PATTERN.test(trimmed);

  const create = useCallback(async () => {
    if (!WORKSPACE_NAME_PATTERN.test(trimmed)) {
      return;
    }
    setCreating(true);
    setError(null);
    setNotice(null);
    try {
      const created = await createWorkspace(trimmed);
      await refreshWorkspaces(created.name);
      setNewName("");
      setShowNewProject(false);
      setNotice(`Created project "${created.name}" and selected it.`);
      setHistoryKey((k) => k + 1);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setCreating(false);
    }
  }, [trimmed, refreshWorkspaces]);

  const run = useCallback(async () => {
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setEvents([]);
    setSelectedProgressPhase(null);
    setError(null);
    setNotice(null);
    setRunning(true);
    try {
      for await (const ev of streamRun({ task, workspace, model: selectedModel || undefined }, { signal: ctrl.signal })) {
        setEvents((prev) => [...prev, ev]);
      }
    } catch (e) {
      if ((e as Error).name !== "AbortError") setError((e as Error).message);
    } finally {
      setRunning(false);
      setHistoryKey((k) => k + 1); // the run (and its files) now show up in History
    }
  }, [task, workspace, selectedModel]);

  const stop = () => abortRef.current?.abort();

  return (
    <main>
      <header>
        <h1>Patchwork</h1>
        <span className={`pill ${health?.ollama ? "ok" : "bad"}`}>
          ollama {health ? (health.ollama ? "up" : "down") : "?"}
          {health && health.ollama && !health.model_available ? ` · model ${health.model} missing` : ""}
        </span>
      </header>

      <nav className="tabs">
        <button className={tab === "run" ? "tab active" : "tab"} onClick={() => setTab("run")}>
          Run{running ? " ●" : ""}
        </button>
        <button className={tab === "history" ? "tab active" : "tab"} onClick={() => setTab("history")}>
          History
        </button>
      </nav>

      {error && <div className="row bad">⚠ {error}</div>}
      {notice && <div className="row ok">✓ {notice}</div>}

      {tab === "run" ? (
        <>
          <section className="controls">
            <div className="project-row">
              <label className="project-select">
                <span>Project</span>
                <select value={workspace} onChange={(e) => setWorkspace(e.target.value)} disabled={running}>
                  {workspaces.length === 0 && <option value="">No projects yet</option>}
                  {workspaces.map((w) => <option key={w}>{w}</option>)}
                </select>
              </label>
              {!showNewProject && (
                <button
                  className="secondary"
                  onClick={() => setShowNewProject(true)}
                  disabled={running}
                >
                  New project
                </button>
              )}
            </div>
            {showNewProject && (
              <div className="project-create">
                <div className="newws">
                  <input
                    value={newName}
                    onChange={(e) => setNewName(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && trimmed && nameValid && !creating && !running) void create();
                    }}
                    placeholder="Project name, e.g. todo-app"
                    aria-label="New project name"
                    aria-invalid={Boolean(trimmed && !nameValid)}
                    aria-describedby={trimmed && !nameValid ? "project-name-help" : undefined}
                    className={trimmed && !nameValid ? "invalid" : undefined}
                    maxLength={64}
                    disabled={running || creating}
                  />
                  <button
                    onClick={() => void create()}
                    disabled={!trimmed || !nameValid || creating || running}
                  >
                    {creating ? "Creating…" : "Create"}
                  </button>
                  <button
                    className="secondary"
                    onClick={() => {
                      setNewName("");
                      setShowNewProject(false);
                    }}
                    disabled={creating}
                  >
                    Cancel
                  </button>
                </div>
                {trimmed && !nameValid && <div id="project-name-help" className="field-hint">{WORKSPACE_NAME_HELP}</div>}
              </div>
            )}
            <div className="prompt-composer">
              <textarea
                value={task}
                onChange={(e) => setTask(e.target.value)}
                rows={4}
                disabled={running}
                aria-label="Prompt"
              />
              <div className="prompt-composer-footer">
                <label className="prompt-model-select">
                  <span>Model</span>
                  <select
                    value={selectedModel}
                    onChange={(e) => setSelectedModel(e.target.value)}
                    disabled={running || !health?.ollama}
                    aria-label="Ollama model"
                  >
                    <option value="">Default ({health?.model ?? "loading"})</option>
                    {(health?.models ?? []).filter((model) => model !== health?.model).map((model) => (
                      <option key={model} value={model}>{model}</option>
                    ))}
                  </select>
                </label>
                {running ? (
                  <button onClick={stop} className="stop">Stop</button>
                ) : (
                  <button onClick={run} disabled={!task.trim() || !workspace}>Run agent</button>
                )}
              </div>
            </div>
          </section>

          {events.some((event) => event.type === "agent_started") && (
            <AgentProgress
              events={events}
              selectedPhase={selectedProgressPhase}
              onSelectPhase={setSelectedProgressPhase}
            />
          )}
        </>
      ) : (
        <HistoryView refreshKey={historyKey} />
      )}
    </main>
  );
}
