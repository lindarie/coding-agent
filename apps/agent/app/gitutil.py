"""Every run works on its own git branch so changes are reviewable/revertable."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

DEFAULT_GITIGNORE = "__pycache__/\n*.pyc\n.pytest_cache/\nnode_modules/\n.venv/\ndist/\n"


async def _git(project: Path, *args: str) -> tuple[int, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "-c", "user.name=coding-agent",
            "-c", "user.email=coding-agent@localhost",
            "-c", "safe.directory=*",
            *args,
            cwd=str(project),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except FileNotFoundError:
        return 127, "git not installed"
    out, _ = await proc.communicate()
    return proc.returncode or 0, out.decode("utf-8", errors="replace").strip()


async def prepare_branch(project: Path, run_id: str) -> str | None:
    """Ensure a repo exists and switch to agent/<run_id>. Returns branch or None."""
    if not (project / ".git").exists():
        code, _ = await _git(project, "init", "-q")
        if code != 0:
            return None
        if not (project / ".gitignore").exists():
            (project / ".gitignore").write_text(DEFAULT_GITIGNORE)
        await _git(project, "add", "-A")
        await _git(project, "commit", "-q", "--allow-empty", "-m", "baseline before agent")
    branch = f"agent/{run_id}"
    code, _ = await _git(project, "checkout", "-q", "-b", branch)
    return branch if code == 0 else None


async def commit_changes(project: Path, message: str) -> str | None:
    """Commit everything; return `git diff --stat` for the commit, or None if no changes."""
    code, status = await _git(project, "status", "--porcelain")
    if code != 0 or not status:
        return None
    await _git(project, "add", "-A")
    code, _ = await _git(project, "commit", "-q", "-m", message[:200])
    if code != 0:
        return None
    _, stat = await _git(project, "show", "--stat", "--format=", "HEAD")
    return stat or None
