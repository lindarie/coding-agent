"""The agent loop: ask Ollama -> run tool calls -> feed results back -> repeat."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, AsyncIterator

from . import gitutil
from .config import Settings
from .db import Store
from .events import Draft, build_event
from .ollama import OllamaClient, OllamaError
from .tools import TOOL_SPECS, ToolBox, ToolOutcome

SYSTEM_PROMPT = """You are an autonomous coding agent working inside ONE project directory.
You can list, read, search and write files, and run shell commands (tests, linters, builds) in an isolated sandbox whose working directory is the project root.

How to work:
1. Explore first: read the relevant files before changing anything.
2. Make small, focused changes. write_file replaces the whole file, so always send the complete new content.
3. After changing code, run the project's tests (or the most relevant command). If something fails, read the output, fix the cause and run again.
4. Stop only when the task is done and verified, or you are genuinely blocked. When you stop, answer in plain text WITHOUT calling a tool: say what you changed and the final test result.

Rules: paths are relative to the project root. Never touch .git. Do not guess file contents you have not read. Do not repeat an identical failing call - change your approach."""


def _preview(text: str, limit: int = 2000) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n[... {len(text) - limit} more characters]"


def _text_tool_calls(content: str) -> list[dict[str, Any]]:
    candidate = content.strip()
    if candidate.startswith("```") and candidate.endswith("```"):
        candidate = candidate[3:-3].strip()
        first_line, separator, body = candidate.partition("\n")
        if separator and first_line.strip().lower() in {"", "json"}:
            candidate = body.strip()
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, dict):
        return []

    name = payload.get("name")
    args = payload.get("arguments")
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return []
    tool_names = {tool["function"]["name"] for tool in TOOL_SPECS}
    if name not in tool_names or not isinstance(args, dict):
        return []
    return [{"function": {"name": name, "arguments": args}}]


class AgentRun:
    def __init__(
        self,
        *,
        run_id: str,
        task: str,
        workspace: str,
        project: Path,
        settings: Settings,
        client: OllamaClient,
        toolbox: ToolBox,
        store: Store,
        model: str,
        max_iterations: int,
    ):
        self.run_id, self.task, self.workspace = run_id, task, workspace
        self.project, self.settings, self.client = project, settings, client
        self.toolbox, self.store = toolbox, store
        self.model, self.max_iterations = model, max_iterations
        self._seq = 0

    def _emit(self, type_: str, **data: Any):
        self._seq += 1
        event = build_event(type_, self.run_id, self._seq, data)
        self.store.add_event(event)
        return event

    async def stream(self) -> AsyncIterator[Any]:
        yield self._emit(
            "agent_started", task=self.task, workspace=self.workspace,
            model=self.model, max_iterations=self.max_iterations,
        )
        yield self._emit("status", message="Analyzing prompt", phase="analyzing")
        status, summary, iterations, branch, diff_stat = "max_iterations", "", 0, None, None
        try:
            branch = await gitutil.prepare_branch(self.project, self.run_id)
            if branch:
                yield self._emit("status", message=f"Working on git branch {branch}")

            yield self._emit("status", message="Understanding project context", phase="context")
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Task: {self.task}\n\nCurrent project files:\n{self.toolbox.tree('.', 3)}",
                },
            ]

            for iteration in range(1, self.max_iterations + 1):
                iterations = iteration
                yield self._emit("status", message="Waiting for model", iteration=iteration)
                try:
                    reply = await self.client.chat(
                        self.model, messages, TOOL_SPECS, num_ctx=self.settings.num_ctx
                    )
                except OllamaError as e:
                    yield self._emit("error", message=str(e))
                    status, summary = "error", str(e)
                    break

                msg = reply.get("message") or {}
                content = (msg.get("content") or "").strip()
                calls = msg.get("tool_calls") or []
                if not calls:
                    calls = _text_tool_calls(content)
                    if calls:
                        content = ""
                assistant: dict[str, Any] = {"role": "assistant", "content": msg.get("content") or ""}
                if calls and not msg.get("tool_calls"):
                    assistant["content"] = ""
                if calls:
                    assistant["tool_calls"] = calls
                messages.append(assistant)

                if content:
                    yield self._emit("agent_message", content=content)
                if not calls:
                    status, summary = "completed", content or "(model finished without a message)"
                    break

                for call in calls:
                    fn = call.get("function") or {}
                    name = fn.get("name") or ""
                    args = fn.get("arguments") or {}
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    tool_phases = {
                        "list_files": ("context", "Exploring project files"),
                        "read_file": ("context", "Reading project files"),
                        "search_files": ("context", "Searching project files"),
                        "write_file": ("coding", "Writing code"),
                        "run_command": ("checking", "Running project checks"),
                    }
                    phase_update = tool_phases.get(name)
                    if phase_update:
                        phase, message = phase_update
                        yield self._emit("status", message=message, phase=phase, iteration=iteration)
                    yield self._emit("tool_call", tool=name, arguments=args, iteration=iteration)

                    outcome: ToolOutcome | None = None
                    async for item in self.toolbox.execute(name, args):
                        if isinstance(item, Draft):
                            yield self._emit(item.type, **item.data)
                        else:
                            outcome = item
                    outcome = outcome or ToolOutcome(False, "Tool produced no result")
                    yield self._emit(
                        "tool_result", tool=name, success=outcome.success, output=_preview(outcome.output)
                    )
                    messages.append({"role": "tool", "tool_name": name, "content": outcome.output})
            else:
                summary = f"Stopped after {self.max_iterations} iterations without a final answer."
        except Exception as e:  # unexpected bug: report it, keep the stream well-formed
            yield self._emit("error", message=f"{type(e).__name__}: {e}")
            status, summary = "error", f"{type(e).__name__}: {e}"

        if branch:
            try:
                yield self._emit("status", message="Committing project changes", phase="committing")
                diff_stat = await gitutil.commit_changes(self.project, f"agent: {self.task}")
            except Exception:
                diff_stat = None

        self.store.finish_run(self.run_id, status, summary)
        yield self._emit(
            "agent_finished", status=status, summary=summary,
            iterations=iterations, git_branch=branch, diff_stat=diff_stat,
        )
