import asyncio

from app.config import load_settings
from app.sandbox import Sandbox
from app.tools import ToolBox, ToolOutcome
from app.events import Draft


def make(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    s = load_settings({"WORKSPACE_ROOT": str(tmp_path), "SANDBOX_MODE": "local", "DB_PATH": str(tmp_path / "db")})
    return ToolBox(proj, s, Sandbox(s, proj)), proj


async def call(tb, name, **args):
    drafts, outcome = [], None
    async for item in tb.execute(name, args):
        if isinstance(item, Draft):
            drafts.append(item)
        else:
            outcome = item
    assert isinstance(outcome, ToolOutcome)
    return drafts, outcome


def test_write_read_list_search(tmp_path):
    tb, proj = make(tmp_path)

    async def go():
        d, o = await call(tb, "write_file", path="src/a.py", content="def f():\n    return 1\n")
        assert o.success and d[0].type == "file_changed" and d[0].data["change"] == "created"
        d, o = await call(tb, "write_file", path="src/a.py", content="x = 2\n")
        assert d[0].data["change"] == "modified"
        _, o = await call(tb, "read_file", path="src/a.py")
        assert o.output == "x = 2\n"
        _, o = await call(tb, "list_files")
        assert "src/a.py" in o.output
        _, o = await call(tb, "search_files", pattern=r"x\s*=", glob="*.py")
        assert "src/a.py:1" in o.output

    asyncio.run(go())


def test_path_escape_and_git_blocked(tmp_path):
    tb, proj = make(tmp_path)
    (tmp_path / "secret.txt").write_text("nope")

    async def go():
        for p in ["../secret.txt", "/etc/passwd", "a/../../secret.txt", ".git/config"]:
            _, o = await call(tb, "read_file", path=p)
            assert not o.success, p

    asyncio.run(go())


def test_bad_tool_and_args(tmp_path):
    tb, _ = make(tmp_path)

    async def go():
        _, o = await call(tb, "rm_rf")
        assert not o.success and "Unknown tool" in o.output
        _, o = await call(tb, "read_file", wrong=1)
        assert not o.success and "Invalid arguments" in o.output

    asyncio.run(go())


def test_run_command_local(tmp_path):
    tb, _ = make(tmp_path)

    async def go():
        d, o = await call(tb, "run_command", command="echo hi && exit 3")
        assert [x.type for x in d] == ["command_started", "command_finished"]
        assert not o.success and "exit code: 3" in o.output and "hi" in o.output
        d, o = await call(tb, "run_command", command="sleep 5", timeout=1)
        assert d[-1].data["timed_out"] and not o.success

    asyncio.run(go())
