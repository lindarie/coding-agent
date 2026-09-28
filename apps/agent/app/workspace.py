from __future__ import annotations

import os
import re
from pathlib import Path

# Kept in sync with WORKSPACE_NAME_PATTERN in packages/api-types/src/workspaces.ts
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
NAME_HELP = "Use 1-64 characters: letters, digits, '.', '_' or '-', starting with a letter or digit"
IGNORED_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "dist", "build", ".idea", ".vscode",
}
MAX_WORKSPACE_FILES = 500
MAX_WORKSPACE_FILE_BYTES = 1_000_000


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


def validate_name(name: str) -> str:
    """Return the trimmed name, or raise ValueError. Slashes, dots-only and hidden names are rejected."""
    name = (name or "").strip()
    if not NAME_RE.fullmatch(name):
        raise ValueError(NAME_HELP)
    return name


def create_project(root: Path, name: str) -> Path:
    """Create an empty project directory directly under `root` (created if missing)."""
    name = validate_name(name)
    root.mkdir(parents=True, exist_ok=True)
    root = root.resolve()
    path = root / name
    if path.parent != root:  # defence in depth; the regex already forbids separators
        raise ValueError("workspace must be inside the workspace root")
    try:
        path.mkdir()
    except FileExistsError:
        raise FileExistsError(f"workspace '{name}' already exists") from None
    return path


def list_project_files(project: Path) -> list[dict[str, str | int | bool]]:
    """List current workspace files without exposing git metadata or dependency folders."""
    project = project.resolve()
    entries: list[dict[str, str | int | bool]] = []
    for directory, dirnames, filenames in os.walk(project):
        base = Path(directory)
        dirnames[:] = sorted(
            name for name in dirnames
            if name not in IGNORED_DIRS and not (base / name).is_symlink()
        )
        for name in dirnames:
            path = base / name
            entries.append({"path": path.relative_to(project).as_posix(), "is_dir": True, "size": 0})
        for name in sorted(filenames):
            path = base / name
            if name in IGNORED_DIRS or path.is_symlink():
                continue
            entries.append({
                "path": path.relative_to(project).as_posix(),
                "is_dir": False,
                "size": path.stat().st_size,
            })
            if len(entries) >= MAX_WORKSPACE_FILES:
                return entries
        if len(entries) >= MAX_WORKSPACE_FILES:
            return entries[:MAX_WORKSPACE_FILES]
    return entries


def read_project_file(project: Path, relative_path: str) -> str:
    """Read a small text file after enforcing the same project boundary as agent tools."""
    project = project.resolve()
    relative = Path(relative_path)
    if not relative_path or relative.is_absolute() or any(part in IGNORED_DIRS for part in relative.parts):
        raise ValueError("invalid workspace file path")
    candidate = project / relative
    path = candidate.resolve()
    if project not in path.parents:
        raise ValueError("file must be inside the workspace")
    current = project
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("symbolic links cannot be read")
    if not path.is_file():
        raise FileNotFoundError("workspace file not found")
    if path.stat().st_size > MAX_WORKSPACE_FILE_BYTES:
        raise OverflowError("file is larger than 1 MB")
    raw = path.read_bytes()
    if b"\0" in raw[:2048]:
        raise UnicodeError("binary files cannot be previewed")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise UnicodeError("file is not valid UTF-8 text") from error
