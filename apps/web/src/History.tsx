import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import {
  getRun,
  getCommitDiff,
  getWorkspaceFile,
  listGitLog,
  listRuns,
  listWorkspaceDetails,
  listWorkspaceFiles,
  type GitCommit,
  type RunDetail,
  type RunSummary,
  type WorkspaceDetail,
  type WorkspaceFileEntry,
} from "@coding-agent/api-types";
import { EventRow, RowBoundary } from "./EventLog";

const when = (ts: number | null) => (ts ? new Date(ts * 1000).toLocaleString() : "—");
const took = (r: RunSummary) => (r.finished_at ? `${Math.max(0, Math.round(r.finished_at - r.created_at))}s` : "—");
const statusClass = (s: RunSummary["status"]) => (s === "completed" ? "ok" : s === "running" ? "muted" : "bad");
const promptFromSubject = (subject: string) => subject.startsWith("agent: ") ? subject.slice(7) : subject;
const diffLineClass = (line: string) =>
  line.startsWith("+++") || line.startsWith("---")
    ? "diff-meta"
    : line.startsWith("+")
      ? "diff-added"
      : line.startsWith("-")
        ? "diff-removed"
        : line.startsWith("@@")
          ? "diff-hunk"
          : "";

type HistorySection = "prompts" | "git" | "files";

interface Props {
  /** Bump to reload (after a run finishes or a workspace is created). */
  refreshKey: number;
}

export function HistoryView({ refreshKey }: Props) {
  const [filter, setFilter] = useState("");
  const [activeSection, setActiveSection] = useState<HistorySection>("prompts");
  const [workspaces, setWorkspaces] = useState<WorkspaceDetail[]>([]);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [commits, setCommits] = useState<GitCommit[]>([]);
  const [browseWorkspace, setBrowseWorkspace] = useState("");
  const [workspaceFiles, setWorkspaceFiles] = useState<WorkspaceFileEntry[]>([]);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState<string | null>(null);
  const [filesLoading, setFilesLoading] = useState(false);
  const [fileLoading, setFileLoading] = useState(false);
  const [filesRefreshKey, setFilesRefreshKey] = useState(0);
  const [openCommit, setOpenCommit] = useState<string | null>(null);
  const [commitDiff, setCommitDiff] = useState<string | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const requestSeq = useRef(0);
  const replayRef = useRef<HTMLElement>(null);
  const diffRequestSeq = useRef(0);
  const fileRequestSeq = useRef(0);

  const load = useCallback(async () => {
    const workspace = filter || undefined;
    try {
      const [w, r, gitLog] = await Promise.all([
        listWorkspaceDetails(),
        listRuns({ workspace, limit: 50 }),
        listGitLog({ workspace, limit: 100 }),
      ]);
      setWorkspaces(w);
      setRuns(r);
      setCommits(gitLog);
      setBrowseWorkspace((current) => current && w.some((entry) => entry.name === current) ? current : w[0]?.name ?? "");
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoaded(true);
    }
  }, [filter]);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  useEffect(() => {
    const request = ++fileRequestSeq.current;
    if (!browseWorkspace) {
      setWorkspaceFiles([]);
      setSelectedFile(null);
      setFileContent(null);
      return;
    }
    setFilesLoading(true);
    setSelectedFile(null);
    setFileContent(null);
    listWorkspaceFiles(browseWorkspace)
      .then((entries) => {
        if (fileRequestSeq.current === request) setWorkspaceFiles(entries);
      })
      .catch((e) => {
        if (fileRequestSeq.current === request) setError((e as Error).message);
      })
      .finally(() => {
        if (fileRequestSeq.current === request) setFilesLoading(false);
      });
    return () => {
      fileRequestSeq.current += 1;
    };
  }, [browseWorkspace, filesRefreshKey, refreshKey]);

  useEffect(() => {
    if (detail) replayRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [detail]);

  const openRun = useCallback(
    async (id: string) => {
      const mine = ++requestSeq.current; // ignore stale responses if the user clicks quickly
      if (openId === id) {
        setOpenId(null);
        setDetail(null);
        return;
      }
      setOpenId(id);
      setDetail(null);
      try {
        const d = await getRun(id);
        if (requestSeq.current === mine) setDetail(d);
      } catch (e) {
        if (requestSeq.current === mine) setError((e as Error).message);
      }
    },
    [openId],
  );

  const selectFile = async (path: string) => {
    const request = ++fileRequestSeq.current;
    setSelectedFile(path);
    setFileContent(null);
    setFileLoading(true);
    try {
      const file = await getWorkspaceFile(browseWorkspace, path);
      if (fileRequestSeq.current === request) setFileContent(file.content);
    } catch (e) {
      if (fileRequestSeq.current === request) setError((e as Error).message);
    } finally {
      if (fileRequestSeq.current === request) setFileLoading(false);
    }
  };

  const toggleCommit = async (commit: GitCommit) => {
    const key = `${commit.workspace}:${commit.hash}`;
    const request = ++diffRequestSeq.current;
    if (openCommit === key) {
      setOpenCommit(null);
      setCommitDiff(null);
      return;
    }
    setOpenCommit(key);
    setCommitDiff(null);
    setDiffLoading(true);
    try {
      const result = await getCommitDiff(commit.workspace, commit.hash);
      if (diffRequestSeq.current === request) setCommitDiff(result.diff);
    } catch (e) {
      if (diffRequestSeq.current === request) setError((e as Error).message);
    } finally {
      if (diffRequestSeq.current === request) setDiffLoading(false);
    }
  };

  const scope = filter ? (
    <>
      {" "}
      in <code>{filter}</code>
    </>
  ) : null;
  const sections: { id: HistorySection; label: string; count: number }[] = [
    { id: "prompts", label: "Prompts", count: runs.length },
    { id: "git", label: "Git log", count: commits.length },
    { id: "files", label: "Project files", count: workspaceFiles.length },
  ];

  return (
    <div className="history">
      {error && <div className="row bad">⚠ {error}</div>}

      <div className="filterbar">
        <label>
          Show history for{" "}
          <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="">All projects</option>
            {workspaces.map((w) => (
              <option key={w.name}>{w.name}</option>
            ))}
          </select>
        </label>
        <button className="secondary" onClick={() => {
          void load();
          setFilesRefreshKey((key) => key + 1);
        }}>
          Refresh
        </button>
      </div>

      <div className="history-layout">
        <nav className="history-nav" aria-label="History sections">
          {sections.map((section) => (
            <button
              key={section.id}
              className={activeSection === section.id ? "active" : ""}
              aria-current={activeSection === section.id ? "page" : undefined}
              onClick={() => setActiveSection(section.id)}
            >
              <span>{section.label}</span>
              <span className="history-nav-count">{section.count}</span>
            </button>
          ))}
        </nav>
        <div className="history-content">
          <section className="history-panel" hidden={activeSection !== "prompts"}>
      <h2>Prompts{scope}</h2>
      {runs.length === 0 ? (
        <p className="muted">{loaded ? "No prompts yet." : "Loading…"}</p>
      ) : (
        <div className="tablewrap">
          <table className="tbl">
            <thead>
              <tr>
                <th>Status</th>
                <th>Prompt</th>
                <th>Project</th>
                <th>Started</th>
                <th>Took</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id} className={r.id === openId ? "sel" : undefined}>
                  <td>
                    <span className={`pill ${statusClass(r.status)}`}>{r.status}</span>
                  </td>
                  <td className="task">
                    <button className="linklike" title={r.task} onClick={() => void openRun(r.id)}>
                      {r.task}
                    </button>
                  </td>
                  <td>
                    <code>{r.workspace}</code>
                  </td>
                  <td>{when(r.created_at)}</td>
                  <td>{took(r)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {openId && (
        <section className="replay" ref={replayRef}>
          <h3>
            Prompt <code>{openId}</code>
          </h3>
          {!detail ? (
            <p className="muted">Loading…</p>
          ) : (
            <>
              <div className="row muted">
                {detail.task} · {detail.model} · {detail.status}
              </div>
              <div className="log">
                {detail.events.length === 0 && <p className="muted">No events were recorded for this run.</p>}
                {detail.events.map((ev) => (
                  <RowBoundary key={`${ev.run_id}-${ev.seq}`} ev={ev}>
                    <EventRow ev={ev} />
                  </RowBoundary>
                ))}
              </div>
            </>
          )}
        </section>
      )}
          </section>

          <section className="history-panel" hidden={activeSection !== "git"}>
      <h2>Git log{scope}</h2>
      {commits.length === 0 ? (
        <p className="muted">{loaded ? "No commits yet. Prompt changes will appear here." : "Loading…"}</p>
      ) : (
        <div className="tablewrap">
          <table className="tbl">
            <thead>
              <tr>
                <th>When</th>
                <th>Project</th>
                <th>Commit</th>
                <th>SHA</th>
              </tr>
            </thead>
            <tbody>
              {commits.map((commit) => {
                const key = `${commit.workspace}:${commit.hash}`;
                const expanded = openCommit === key;
                return (
                  <Fragment key={key}>
                    <tr className={expanded ? "sel" : undefined}>
                      <td>{when(commit.timestamp)}</td>
                      <td><code>{commit.workspace}</code></td>
                      <td className="task">
                        <button className="linklike" title={commit.subject} onClick={() => void toggleCommit(commit)}>
                          {promptFromSubject(commit.subject)}
                        </button>
                      </td>
                      <td><code>{commit.hash.slice(0, 8)}</code></td>
                    </tr>
                    {expanded && (
                      <tr className="diff-row">
                        <td colSpan={4}>
                          {diffLoading ? <p className="muted">Loading code changes…</p> : commitDiff ? (
                            <pre className="git-diff">{commitDiff.split("\n").map((line, index) => (
                              <span key={index} className={diffLineClass(line)}>{line}{"\n"}</span>
                            ))}</pre>
                          ) : <p className="muted">This commit has no text changes.</p>}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
          </section>

          <section className="history-panel" hidden={activeSection !== "files"}>
      <h2>Project files</h2>
      <div className="browser-toolbar">
        <label>
          Project{" "}
          <select value={browseWorkspace} onChange={(e) => setBrowseWorkspace(e.target.value)}>
            {workspaces.map((w) => <option key={w.name} value={w.name}>{w.name}</option>)}
          </select>
        </label>
      </div>
      {!browseWorkspace ? (
        <p className="muted">Create a project to browse its files.</p>
      ) : (
        <div className="workspace-browser">
          <div className="file-list" aria-label="Project files">
            {filesLoading ? <p className="muted">Loading files…</p> : workspaceFiles.length === 0 ? (
              <p className="muted">This project is empty.</p>
            ) : workspaceFiles.map((entry) => {
              const parts = entry.path.split("/");
              const label = parts[parts.length - 1];
              const paddingLeft = `${0.5 + (parts.length - 1) * 1.1}rem`;
              return entry.is_dir ? (
                <div key={entry.path} className="file-entry directory" style={{ paddingLeft }} title={entry.path}>
                  <span aria-hidden="true">▸</span> {label}
                </div>
              ) : (
                <button
                  key={entry.path}
                  className={`file-entry ${selectedFile === entry.path ? "selected" : ""}`}
                  style={{ paddingLeft }}
                  title={`${entry.path} · ${entry.size.toLocaleString()} bytes`}
                  onClick={() => void selectFile(entry.path)}
                >
                  {label}
                </button>
              );
            })}
          </div>
          <div className="file-preview">
            {selectedFile ? (
              <>
                <div className="file-preview-title"><code>{selectedFile}</code></div>
                {fileLoading ? <p className="muted">Loading file…</p> : fileContent !== null ? (
                  <pre className="source-preview">{fileContent || "(empty file)"}</pre>
                ) : null}
              </>
            ) : <p className="muted">Select a file to view its current contents.</p>}
          </div>
        </div>
      )}
          </section>
        </div>
      </div>
    </div>
  );
}
