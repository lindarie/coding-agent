"""Tools the model can call. Every tool is an async generator that may yield
`Draft` events (file_changed, command_started, ...) and MUST end with a
`ToolOutcome`, which is what gets sent back to the model."""
from __future__ import annotations

import fnmatch
import inspect
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator

from .config import Settings
from .events import Draft
from .sandbox import Sandbox

IGNORED_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "dist", "build", ".idea", ".vscode",
}
MAX_READ_CHARS = 20_000
MAX_WRITE_BYTES = 1_000_000
MAX_LIST_ENTRIES = 300
MAX_SEARCH_MATCHES = 60
MAX_OUTPUT_CHARS = 8_000


class ToolError(Exception):
    """Expected failure; the message is shown to the model so it can recover."""


@dataclass
class ToolOutcome:
    success: bool
    output: str


def clip_tail(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return f"[... {len(text) - limit} earlier characters truncated ...]\n" + text[-limit:]


def _int(value: Any, default: int | None) -> int | None:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ToolError(f"Expected an integer, got {value!r}")


def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


TOOL_SPECS: list[dict[str, Any]] = [
    _fn(
        "list_files",
        "List files and directories in the project (relative paths, directories end with '/').",
        {
            "path": {"type": "string", "description": "Directory relative to project root. Default '.'"},
            "max_depth": {"type": "integer", "description": "Levels to show. Default 2"},
        },
        [],
    ),
    _fn(
        "read_file",
        "Read a text file. Optionally restrict to a 1-based inclusive line range (output is then line-numbered).",
        {
            "path": {"type": "string", "description": "File path relative to project root"},
            "start_line": {"type": "integer"},
            "end_line": {"type": "integer"},
        },
        ["path"],
    ),
    _fn(
        "search_files",
        "Search file contents with a regular expression. Returns 'path:line: text' matches.",
        {
            "pattern": {"type": "string", "description": "Regex (falls back to literal text if invalid)"},
            "path": {"type": "string", "description": "Directory or file to search. Default '.'"},
            "glob": {"type": "string", "description": "Filename filter, e.g. '*.py'"},
        },
        ["pattern"],
    ),
    _fn(
        "write_file",
        "Create or completely overwrite a file with the given content. Always provide the FULL file content.",
        {
            "path": {"type": "string", "description": "File path relative to project root"},
            "content": {"type": "string", "description": "Complete new file content"},
        },
        ["path", "content"],
    ),
    _fn(
        "run_command",
        "Run a shell command (tests, linters, build, scripts) in the sandbox with the project root as "
        "working directory. Returns exit code and combined stdout/stderr.",
        {
            "command": {"type": "string", "description": "e.g. 'pytest -q'"},
            "timeout": {"type": "integer", "description": "Seconds before the command is killed"},
        },
        ["command"],
    ),
]


class ToolBox:
    def __init__(self, project: Path, settings: Settings, sandbox: Sandbox):
        self.project = project.resolve()
        self.settings = settings
        self.sandbox = sandbox

    # ---- path safety -------------------------------------------------
    def resolve(self, rel: Any) -> Path:
        if not isinstance(rel, str) or not rel.strip():
            rel = "."
        rel = rel.strip()
        if rel.startswith(str(self.project)):  # tolerate absolute paths inside the project
            rel = rel[len(str(self.project)):] or "."
        path = (self.project / rel.lstrip("/") if rel.startswith("/") else self.project / rel).resolve()
        if path != self.project and self.project not in path.parents:
            raise ToolError(f"Path '{rel}' is outside the project directory")
        if ".git" in path.relative_to(self.project).parts:
            raise ToolError("The .git directory is off limits")
        return path

    def rel(self, path: Path) -> str:
        return path.relative_to(self.project).as_posix() or "."

    # ---- dispatch ----------------------------------------------------
    async def execute(self, name: str, args: dict[str, Any]) -> AsyncIterator[Draft | ToolOutcome]:
        handler = getattr(self, f"_tool_{name}", None)
        if handler is None:
            known = ", ".join(s["function"]["name"] for s in TOOL_SPECS)
            yield ToolOutcome(False, f"Unknown tool '{name}'. Available tools: {known}")
            return
        try:
            inspect.signature(handler).bind(**args)
        except TypeError as e:
            yield ToolOutcome(False, f"Invalid arguments for {name}: {e}")
            return
        try:
            async for item in handler(**args):
                yield item
        except ToolError as e:
            yield ToolOutcome(False, str(e))
        except Exception as e:  # never let a tool crash the loop
            yield ToolOutcome(False, f"{type(e).__name__}: {e}")

    def tree(self, rel: str = ".", max_depth: int = 2) -> str:
        base = self.resolve(rel)
        if not base.is_dir():
            raise ToolError(f"Not a directory: {rel}")
        entries: list[str] = []
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if d not in IGNORED_DIRS)
            depth = len(Path(dirpath).relative_to(base).parts)
            for d in dirnames:
                entries.append(self.rel(Path(dirpath, d)) + "/")
            for f in sorted(filenames):
                entries.append(self.rel(Path(dirpath, f)))
            if depth + 1 >= max_depth:
                dirnames[:] = []
            if len(entries) >= MAX_LIST_ENTRIES:
                entries = entries[:MAX_LIST_ENTRIES] + ["... (truncated)"]
                break
        return "\n".join(entries) if entries else "(empty directory)"

    # ---- tools -------------------------------------------------------
    async def _tool_list_files(self, path: str = ".", max_depth: Any = 2):
        yield ToolOutcome(True, self.tree(path, _int(max_depth, 2) or 2))

    async def _tool_read_file(self, path: str, start_line: Any = None, end_line: Any = None):
        p = self.resolve(path)
        if not p.is_file():
            raise ToolError(f"File not found: {path}")
        raw = p.read_bytes()
        if b"\0" in raw[:2048]:
            raise ToolError(f"{path} looks like a binary file")
        text = raw.decode("utf-8", errors="replace")
        start, end = _int(start_line, None), _int(end_line, None)
        if start is not None or end is not None:
            lines = text.splitlines()
            s = max((start or 1), 1)
            e = min((end or len(lines)), len(lines))
            text = "\n".join(f"{i}: {lines[i - 1]}" for i in range(s, e + 1))
        if len(text) > MAX_READ_CHARS:
            text = text[:MAX_READ_CHARS] + f"\n[... truncated, file has {len(raw)} bytes; use a line range]"
        yield ToolOutcome(True, text if text else "(empty file)")

    async def _tool_search_files(self, pattern: str, path: str = ".", glob: str | None = None):
        base = self.resolve(path)
        try:
            rx = re.compile(pattern)
        except re.error:
            rx = re.compile(re.escape(pattern))

        def candidates():
            if base.is_file():
                yield base
                return
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames[:] = sorted(d for d in dirnames if d not in IGNORED_DIRS)
                for f in sorted(filenames):
                    yield Path(dirpath, f)

        matches: list[str] = []
        for f in candidates():
            rel = self.rel(f)
            if glob and not (fnmatch.fnmatch(f.name, glob) or fnmatch.fnmatch(rel, glob)):
                continue
            try:
                if f.stat().st_size > 1_000_000:
                    continue
                raw = f.read_bytes()
            except OSError:
                continue
            if b"\0" in raw[:2048]:
                continue
            for n, line in enumerate(raw.decode("utf-8", errors="replace").splitlines(), 1):
                if rx.search(line):
                    matches.append(f"{rel}:{n}: {line.strip()[:200]}")
                    if len(matches) >= MAX_SEARCH_MATCHES:
                        break
            if len(matches) >= MAX_SEARCH_MATCHES:
                matches.append("... (match limit reached)")
                break
        yield ToolOutcome(True, "\n".join(matches) if matches else "No matches")

    async def _tool_write_file(self, path: str, content: str):
        p = self.resolve(path)
        if p == self.project or p.is_dir():
            raise ToolError(f"{path} is a directory")
        data = str(content).encode("utf-8")
        if len(data) > MAX_WRITE_BYTES:
            raise ToolError("File too large (limit 1 MB)")
        existed = p.exists()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        yield Draft("file_changed", {
            "path": self.rel(p),
            "change": "modified" if existed else "created",
            "bytes": len(data),
        })
        yield ToolOutcome(True, f"Wrote {len(data)} bytes to {self.rel(p)}")

    async def _tool_run_command(self, command: str, timeout: Any = None):
        if not isinstance(command, str) or not command.strip():
            raise ToolError("command must be a non-empty string")
        t = _int(timeout, None)
        t = min(max(t, 1), 900) if t else None
        yield Draft("command_started", {"command": command})
        res = await self.sandbox.run(command, t)
        output = clip_tail(res.output)
        yield Draft("command_finished", {
            "command": command,
            "exit_code": res.exit_code,
            "timed_out": res.timed_out,
            "duration_s": res.duration_s,
            "output": clip_tail(res.output, 4000),
        })
        if res.timed_out:
            body = f"Command timed out and was killed.\n{output}"
        else:
            body = f"exit code: {res.exit_code}\n{output}"
        yield ToolOutcome(res.exit_code == 0 and not res.timed_out, body)
