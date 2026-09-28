"""Event contract. Mirrored by packages/api-types/src/events.ts."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter


class _Base(BaseModel):
    run_id: str
    seq: int
    ts: float


class AgentStarted(_Base):
    type: Literal["agent_started"] = "agent_started"
    task: str
    workspace: str
    model: str
    max_iterations: int


class Status(_Base):
    type: Literal["status"] = "status"
    message: str
    iteration: int | None = None


class ToolCall(_Base):
    type: Literal["tool_call"] = "tool_call"
    tool: str
    arguments: dict[str, Any]
    iteration: int


class ToolResult(_Base):
    type: Literal["tool_result"] = "tool_result"
    tool: str
    success: bool
    output: str  # preview only; the model receives the full (capped) output


class FileChanged(_Base):
    type: Literal["file_changed"] = "file_changed"
    path: str
    change: Literal["created", "modified"]
    bytes: int


class CommandStarted(_Base):
    type: Literal["command_started"] = "command_started"
    command: str


class CommandFinished(_Base):
    type: Literal["command_finished"] = "command_finished"
    command: str
    exit_code: int | None
    timed_out: bool
    duration_s: float
    output: str


class AgentMessage(_Base):
    type: Literal["agent_message"] = "agent_message"
    content: str


class ErrorEvent(_Base):
    type: Literal["error"] = "error"
    message: str


class AgentFinished(_Base):
    type: Literal["agent_finished"] = "agent_finished"
    status: Literal["completed", "max_iterations", "error"]
    summary: str
    iterations: int
    git_branch: str | None = None
    diff_stat: str | None = None


AgentEvent = Annotated[
    Union[
        AgentStarted,
        Status,
        ToolCall,
        ToolResult,
        FileChanged,
        CommandStarted,
        CommandFinished,
        AgentMessage,
        ErrorEvent,
        AgentFinished,
    ],
    Field(discriminator="type"),
]

_adapter: TypeAdapter[AgentEvent] = TypeAdapter(AgentEvent)


@dataclass
class Draft:
    """An event emitted by a tool before the loop assigns run_id / seq / ts."""

    type: str
    data: dict[str, Any] = field(default_factory=dict)


def build_event(type_: str, run_id: str, seq: int, data: dict[str, Any]):
    return _adapter.validate_python(
        {"type": type_, "run_id": run_id, "seq": seq, "ts": time.time(), **data}
    )
