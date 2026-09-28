"""Runs shell commands for the agent, in a throw-away Docker container."""
from __future__ import annotations

import asyncio
import os
import signal
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from .config import Settings

MAX_CAPTURE = 64_000  # bytes of output kept (tail)


@dataclass
class CommandResult:
    exit_code: int | None
    output: str
    timed_out: bool
    duration_s: float


class Sandbox:
    def __init__(self, settings: Settings, project: Path):
        self.s = settings
        self.project = project.resolve()

    def _host_project_dir(self) -> str:
        rel = self.project.relative_to(self.s.workspace_root.resolve())
        return str(self.s.host_workspace_dir / rel)

    def _docker_argv(self, command: str, name: str) -> list[str]:
        return [
            "docker", "run", "--rm", "--name", name,
            "--network", self.s.sandbox_network,
            "--memory", self.s.sandbox_memory,
            "--cpus", self.s.sandbox_cpus,
            "--pids-limit", "256",
            "-e", "PYTHONDONTWRITEBYTECODE=1",
            "-v", f"{self._host_project_dir()}:/work:rw",
            "-w", "/work",
            self.s.sandbox_image,
            "sh", "-c", command,
        ]

    async def run(self, command: str, timeout: int | None = None) -> CommandResult:
        timeout = timeout or self.s.command_timeout
        name = f"agent-sandbox-{uuid.uuid4().hex[:10]}"
        if self.s.sandbox_mode == "docker":
            argv, cwd = self._docker_argv(command, name), None
        else:  # "local": no isolation, for development/tests only
            argv, cwd = ["sh", "-c", command], str(self.project)

        start = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
            )
        except FileNotFoundError as e:
            return CommandResult(None, f"Could not start command: {e}", False, 0.0)

        buf = bytearray()

        async def pump() -> None:
            assert proc.stdout is not None
            while chunk := await proc.stdout.read(4096):
                buf.extend(chunk)
                if len(buf) > MAX_CAPTURE:
                    del buf[: len(buf) - MAX_CAPTURE]
            await proc.wait()

        timed_out = False
        try:
            await asyncio.wait_for(pump(), timeout)
        except asyncio.TimeoutError:
            timed_out = True
            await self._kill(proc, name)
        except asyncio.CancelledError:
            await self._kill(proc, name)
            raise

        return CommandResult(
            exit_code=None if timed_out else proc.returncode,
            output=buf.decode("utf-8", errors="replace"),
            timed_out=timed_out,
            duration_s=round(time.monotonic() - start, 2),
        )

    async def _kill(self, proc: asyncio.subprocess.Process, name: str) -> None:
        if self.s.sandbox_mode == "docker":
            killer = await asyncio.create_subprocess_exec(
                "docker", "kill", name,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            await killer.wait()
        else:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            await asyncio.wait_for(proc.wait(), 5)
        except asyncio.TimeoutError:
            proc.kill()
