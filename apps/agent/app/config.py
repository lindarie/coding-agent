from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class Settings:
    ollama_url: str
    model: str
    num_ctx: int
    ollama_timeout: float
    max_iterations: int
    workspace_root: Path
    host_workspace_dir: Path
    db_path: Path
    sandbox_mode: str  # "docker" | "local"
    sandbox_image: str
    sandbox_network: str
    sandbox_memory: str
    sandbox_cpus: str
    command_timeout: int
    api_token: str


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    e = os.environ if env is None else env
    workspace_root = Path(e.get("WORKSPACE_ROOT", "/workspace"))
    return Settings(
        ollama_url=e.get("OLLAMA_URL", "http://host.docker.internal:11434").rstrip("/"),
        model=e.get("OLLAMA_MODEL", "qwen3:8b"),
        num_ctx=int(e.get("OLLAMA_NUM_CTX", "16384")),
        ollama_timeout=float(e.get("OLLAMA_TIMEOUT", "600")),
        max_iterations=int(e.get("MAX_ITERATIONS", "25")),
        workspace_root=workspace_root,
        # Path of the workspace on the *Docker host*. Needed because sandbox
        # containers are started as siblings through the host's Docker daemon.
        host_workspace_dir=Path(e.get("HOST_WORKSPACE_DIR", str(workspace_root))),
        db_path=Path(e.get("DB_PATH", "/data/agent.db")),
        sandbox_mode=e.get("SANDBOX_MODE", "docker"),
        sandbox_image=e.get("SANDBOX_IMAGE", "coding-agent-sandbox:latest"),
        sandbox_network=e.get("SANDBOX_NETWORK", "none"),
        sandbox_memory=e.get("SANDBOX_MEMORY", "1g"),
        sandbox_cpus=e.get("SANDBOX_CPUS", "1"),
        command_timeout=int(e.get("COMMAND_TIMEOUT", "120")),
        api_token=e.get("AGENT_API_TOKEN", ""),
    )


@lru_cache
def get_settings() -> Settings:
    return load_settings()
