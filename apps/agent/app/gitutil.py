"""Every run works on its own git branch so changes are reviewable/revertable."""
from __future__ import annotations

import asyncio
import os
import re
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


async def list_commits(project: Path, limit: int = 50) -> list[dict[str, str | int]]:
    """Return recent commit subjects and timestamps for the workspace history view."""
    if not (project / ".git").exists():
        return []
    code, output = await _git(project, "log", f"-{limit}", "--format=%H%x00%ct%x00%s")
    if code != 0:
        return []
    commits = []
    for line in output.splitlines():
        parts = line.split("\x00", 2)
        if len(parts) != 3:
            continue
        commit_hash, timestamp, subject = parts
        if subject == "baseline before agent":
            continue
        try:
            commits.append({"hash": commit_hash, "timestamp": int(timestamp), "subject": subject})
        except ValueError:
            continue
    return commits


async def commit_diff(project: Path, commit_hash: str) -> str | None:
    """Return a bounded unified patch for a full commit hash."""
    if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", commit_hash):
        return None
    code, output = await _git(
        project, "show", "--no-ext-diff", "--no-color", "--format=", "--unified=3", commit_hash, "--"
    )
    if code != 0:
        return None
    limit = 200_000
    if len(output) > limit:
        return output[:limit] + "\n... diff truncated at 200,000 characters ..."
    return output
