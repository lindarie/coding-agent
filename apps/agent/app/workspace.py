from __future__ import annotations

from pathlib import Path


def list_projects(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith("."))


def resolve_project(root: Path, name: str) -> Path:
    """Map a client-supplied workspace name/path to a directory under `root`."""
    root = root.resolve()
    name = name.strip()
    if name.startswith(str(root)):
        name = name[len(str(root)):]
    name = name.strip("/")
    if not name:
        raise ValueError("workspace must name a project directory")
    path = (root / name).resolve()
    if root not in path.parents:
        raise ValueError("workspace must be inside the workspace root")
    if not path.is_dir():
        raise FileNotFoundError(f"workspace '{name}' does not exist")
    return path
