from __future__ import annotations

import asyncio
import hmac
import uuid
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .config import get_settings
from .db import Store
from . import gitutil
from .loop import AgentRun
from .ollama import OllamaClient
from .sandbox import Sandbox
from .tools import ToolBox
from .workspace import create_project, list_project_files, list_projects, read_project_file, resolve_project


class RunRequest(BaseModel):
    task: str = Field(min_length=1, max_length=20_000)
    workspace: str = Field(min_length=1, description="Project directory name under the workspace root")
    max_iterations: int | None = Field(default=None, ge=1, le=200)
    model: str | None = None


class CreateWorkspaceRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64, description="New project directory name")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    app.state.store = Store(s.db_path)
    app.state.ollama = OllamaClient(s.ollama_url, s.ollama_timeout)
    app.state.busy = set()
    yield
    await app.state.ollama.aclose()


app = FastAPI(title="coding-agent", version="0.1.0", lifespan=lifespan)


def require_token(authorization: str | None = Header(default=None)) -> None:
    token = get_settings().api_token
    if token and not hmac.compare_digest(authorization or "", f"Bearer {token}"):
        raise HTTPException(status_code=401, detail="Missing or invalid bearer token")


@app.get("/api/health")
async def health(request: Request):
    s = get_settings()
    try:
        models = await request.app.state.ollama.list_models()
        tool_models = await request.app.state.ollama.list_tool_models(models)
        ollama_ok = True
    except Exception:
        models, tool_models, ollama_ok = [], [], False
    return {
        "status": "ok",
        "ollama": ollama_ok,
        "models": models,
        "tool_models": tool_models,
        "model": s.model,
        "model_available": s.model in models,
        "sandbox_mode": s.sandbox_mode,
    }


api = APIRouter(prefix="/api", dependencies=[Depends(require_token)])


@api.get("/workspaces")
async def workspaces() -> list[str]:
    return list_projects(get_settings().workspace_root)


@api.post("/workspaces", status_code=201)
async def create_workspace(req: CreateWorkspaceRequest, request: Request):
    """Create an empty project directory under the workspace root."""
    try:
        path = create_project(get_settings().workspace_root, req.name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))
    created_at = request.app.state.store.add_workspace(path.name)
    return {"name": path.name, "created_at": created_at}


@api.get("/workspaces/details")
async def workspace_details(request: Request):
    """Workspaces with creation time (if created via the API) and run activity, newest first."""
    stats = request.app.state.store.workspace_stats()
    out = []
    for name in list_projects(get_settings().workspace_root):
        st = stats.get(name, {})
        out.append({
            "name": name,
            "created_at": st.get("created_at"),
            "run_count": st.get("run_count", 0),
            "last_run_at": st.get("last_run_at"),
        })
    out.sort(key=lambda w: (w["created_at"] is None, -(w["created_at"] or 0), w["name"]))
    return out


@api.get("/git-log")
async def git_log(workspace: str | None = None, limit: int = 50):
    """Recent commits across workspaces, optionally scoped to one workspace."""
    s = get_settings()
    names = [workspace] if workspace else list_projects(s.workspace_root)
    if workspace:
        try:
            resolve_project(s.workspace_root, workspace)
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    count = min(max(limit, 1), 100)
    commits = []
    for name in names:
        try:
            project = resolve_project(s.workspace_root, name)
        except (FileNotFoundError, ValueError):
            continue
        commits.extend({**commit, "workspace": name} for commit in await gitutil.list_commits(project, count))
    commits.sort(key=lambda commit: commit["timestamp"], reverse=True)
    return commits[:count]


@api.get("/workspaces/{workspace}/git-log/{commit_hash}")
async def git_commit_diff(workspace: str, commit_hash: str):
    try:
        project = resolve_project(get_settings().workspace_root, workspace)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    diff = await gitutil.commit_diff(project, commit_hash)
    if diff is None:
        raise HTTPException(status_code=404, detail="Git commit not found")
    return {"diff": diff}


@api.get("/workspaces/{workspace}/files")
async def workspace_files(workspace: str):
    try:
        project = resolve_project(get_settings().workspace_root, workspace)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return list_project_files(project)


@api.get("/workspaces/{workspace}/file")
async def workspace_file(workspace: str, path: str):
    try:
        project = resolve_project(get_settings().workspace_root, workspace)
        content = read_project_file(project, path)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except OverflowError as e:
        raise HTTPException(status_code=413, detail=str(e))
    except UnicodeError as e:
        raise HTTPException(status_code=415, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"path": path, "content": content}


@api.get("/files")
async def file_history(request: Request, workspace: str | None = None, limit: int = 200):
    """Files created/modified by agent runs, newest first."""
    return request.app.state.store.list_file_events(workspace or None, min(max(limit, 1), 1000))


@api.get("/runs")
async def runs(request: Request, limit: int = 50, workspace: str | None = None):
    return request.app.state.store.list_runs(min(max(limit, 1), 200), workspace or None)


@api.get("/runs/{run_id}")
async def run_detail(run_id: str, request: Request):
    run = request.app.state.store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@api.post("/agent/run")
async def run_agent(req: RunRequest, request: Request):
    """Runs the agent and streams AgentEvents as Server-Sent Events (`data: {json}`)."""
    s = get_settings()
    try:
        project = resolve_project(s.workspace_root, req.workspace)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    busy: set = request.app.state.busy
    if project in busy:
        raise HTTPException(status_code=409, detail="A run is already active in this workspace")
    busy.add(project)

    store: Store = request.app.state.store
    run_id = uuid.uuid4().hex[:12]
    model = req.model or s.model
    store.create_run(run_id, req.task, project.name, model)

    run = AgentRun(
        run_id=run_id,
        task=req.task,
        workspace=project.name,
        project=project,
        settings=s,
        client=request.app.state.ollama,
        toolbox=ToolBox(project, s, Sandbox(s, project)),
        store=store,
        model=model,
        max_iterations=req.max_iterations or s.max_iterations,
    )

    async def stream():
        try:
            async for event in run.stream():
                yield f"data: {event.model_dump_json()}\n\n"
        except asyncio.CancelledError:  # client went away mid-run
            store.finish_run(run_id, "cancelled", "Client disconnected")
            raise
        finally:
            busy.discard(project)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


app.include_router(api)
