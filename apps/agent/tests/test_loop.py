import asyncio
import shutil

import pytest

from app.config import load_settings
from app.db import Store
from app.loop import AgentRun
from app.sandbox import Sandbox
from app.tools import ToolBox


class FakeClient:
    """Plays back scripted Ollama replies."""

    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    async def chat(self, model, messages, tools, num_ctx=0, temperature=0):
        self.calls.append(list(messages))
        return {"message": self.replies.pop(0)}


def call(name, **args):
    return {"function": {"name": name, "arguments": args}}


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_full_loop_with_git(tmp_path):
    root = tmp_path / "ws"
    proj = root / "demo"
    proj.mkdir(parents=True)
    (proj / "a.txt").write_text("hello\n")
    s = load_settings({"WORKSPACE_ROOT": str(root), "SANDBOX_MODE": "local", "DB_PATH": str(tmp_path / "db.sqlite")})
    store = Store(s.db_path)
    store.create_run("r1", "t", "demo", "fake")
    client = FakeClient([
        {"role": "assistant", "content": "", "tool_calls": [call("read_file", path="a.txt")]},
        {"role": "assistant", "content": "", "tool_calls": [call("write_file", path="b.txt", content="bye\n")]},
        {"role": "assistant", "content": "", "tool_calls": [call("run_command", command="cat b.txt")]},
        {"role": "assistant", "content": "All done, b.txt created."},
    ])
    run = AgentRun(
        run_id="r1", task="make b.txt", workspace="demo", project=proj, settings=s, client=client,
        toolbox=ToolBox(proj, s, Sandbox(s, proj)), store=store, model="fake", max_iterations=10,
    )

    async def go():
        return [e async for e in run.stream()]

    events = asyncio.run(go())
    types = [e.type for e in events]
    assert types[0] == "agent_started" and types[-1] == "agent_finished"
    phases = [e.phase for e in events if e.type == "status" and e.phase]
    assert phases == ["analyzing", "context", "context", "coding", "checking", "committing"]
    for expected in ["tool_call", "tool_result", "file_changed", "command_started", "command_finished", "agent_message"]:
        assert expected in types
    assert [e.seq for e in events] == list(range(1, len(events) + 1))
    fin = events[-1]
    assert fin.status == "completed" and fin.git_branch == "agent/r1"
    assert "b.txt" in (fin.diff_stat or "")
    # tool result reached the model
    assert any(m.get("role") == "tool" and "bye" in m["content"] for m in client.calls[-1])
    # persisted
    saved = store.get_run("r1")
    assert saved["status"] == "completed" and len(saved["events"]) == len(events)


def test_iteration_limit(tmp_path):
    root = tmp_path / "ws"
    proj = root / "demo"
    proj.mkdir(parents=True)
    s = load_settings({"WORKSPACE_ROOT": str(root), "SANDBOX_MODE": "local", "DB_PATH": str(tmp_path / "db.sqlite")})
    store = Store(s.db_path)
    store.create_run("r2", "t", "demo", "fake")
    loop_reply = {"role": "assistant", "content": "", "tool_calls": [call("list_files")]}
    client = FakeClient([loop_reply] * 3)
    run = AgentRun(
        run_id="r2", task="loop", workspace="demo", project=proj, settings=s, client=client,
        toolbox=ToolBox(proj, s, Sandbox(s, proj)), store=store, model="fake", max_iterations=3,
    )

    async def go():
        return [e async for e in run.stream()]

    events = asyncio.run(go())
    assert events[-1].type == "agent_finished" and events[-1].status == "max_iterations"


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_loop_executes_json_tool_call_from_text(tmp_path):
    root = tmp_path / "ws"
    proj = root / "demo"
    proj.mkdir(parents=True)
    s = load_settings({"WORKSPACE_ROOT": str(root), "SANDBOX_MODE": "local", "DB_PATH": str(tmp_path / "db.sqlite")})
    store = Store(s.db_path)
    store.create_run("r3", "create a file", "demo", "fake")
    client = FakeClient([
        {
            "role": "assistant",
            "content": '''```json
{"name":"write_file","arguments":{"path":"created.py","content":"value = 1\\n"}}
```''',
        },
        {"role": "assistant", "content": "Created created.py."},
    ])
    run = AgentRun(
        run_id="r3", task="create a file", workspace="demo", project=proj, settings=s, client=client,
        toolbox=ToolBox(proj, s, Sandbox(s, proj)), store=store, model="fake", max_iterations=3,
    )

    async def go():
        return [event async for event in run.stream()]

    events = asyncio.run(go())
    assert (proj / "created.py").read_text() == "value = 1\n"
    assert any(event.type == "tool_call" and event.tool == "write_file" for event in events)
    assert events[-1].type == "agent_finished" and events[-1].status == "completed"
