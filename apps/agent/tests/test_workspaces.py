import pytest
import subprocess
from fastapi.testclient import TestClient

from app import config
from app.db import Store
from app.events import build_event
from app.workspace import create_project, validate_name


@pytest.mark.parametrize("bad", ["", "   ", ".hidden", "..", "-x", "a/b", "a\\b", "a b", "x" * 65, "é", "a\nb"])
def test_invalid_names(bad):
    with pytest.raises(ValueError):
        validate_name(bad)


@pytest.mark.parametrize("good", ["demo", "A", "my-app_2.0", "x" * 64, "  padded  "])
def test_valid_names(good):
    assert validate_name(good) == good.strip()


def test_create_project_creates_root_and_rejects_duplicates(tmp_path):
    root = tmp_path / "does-not-exist-yet"
    p = create_project(root, "proj")
    assert p.is_dir() and p.parent == root.resolve()
    with pytest.raises(FileExistsError):
        create_project(root, "proj")


def _file_event(store, run_id, seq, path, change="created", size=3):
    store.add_event(build_event("file_changed", run_id, seq, {"path": path, "change": change, "bytes": size}))


def test_store_workspace_stats_and_file_history(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    store.add_workspace("alpha")
    store.create_run("r1", "task one", "alpha", "m")
    store.create_run("r2", "task two", "beta", "m")
    _file_event(store, "r1", 1, "a.py")
    _file_event(store, "r1", 2, "a.py", "modified", 9)
    store.add_event(build_event("status", "r1", 3, {"message": "not a file event"}))
    _file_event(store, "r2", 1, "b.py")

    stats = store.workspace_stats()
    assert stats["alpha"]["created_at"] is not None and stats["alpha"]["run_count"] == 1
    assert stats["beta"]["created_at"] is None and stats["beta"]["run_count"] == 1  # run history without a create record

    alpha = store.list_file_events("alpha")
    assert [(f["path"], f["change"], f["bytes"]) for f in alpha] == [("a.py", "modified", 9), ("a.py", "created", 3)]
    assert alpha[0]["task"] == "task one" and alpha[0]["workspace"] == "alpha"
    assert {f["path"] for f in store.list_file_events()} == {"a.py", "b.py"}
    assert len(store.list_file_events(limit=1)) == 1
    assert [r["id"] for r in store.list_runs(workspace="beta")] == ["r2"]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "ws"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.setenv("SANDBOX_MODE", "local")
    monkeypatch.delenv("AGENT_API_TOKEN", raising=False)
    config.get_settings.cache_clear()
    from app.main import app

    with TestClient(app) as c:
        yield c
    config.get_settings.cache_clear()


def test_api_create_list_details(client, tmp_path):
    assert client.get("/api/workspaces").json() == []
    r = client.post("/api/workspaces", json={"name": " todo-app "})
    assert r.status_code == 201 and r.json()["name"] == "todo-app"
    assert (tmp_path / "ws" / "todo-app").is_dir()
    assert client.get("/api/workspaces").json() == ["todo-app"]

    (tmp_path / "ws" / "old-folder").mkdir()  # exists on disk but was never created via the API
    details = {w["name"]: w for w in client.get("/api/workspaces/details").json()}
    assert details["todo-app"]["created_at"] is not None and details["todo-app"]["run_count"] == 0
    assert details["old-folder"]["created_at"] is None
    first = client.get("/api/workspaces/details").json()[0]
    assert first["name"] == "todo-app"  # tracked workspaces sort first


def test_api_health_lists_installed_models(client, monkeypatch):
    async def list_models():
        return ["qwen3:8b", "deepseek-coder:6.7b"]

    async def list_tool_models(models):
        assert models == ["qwen3:8b", "deepseek-coder:6.7b"]
        return ["qwen3:8b"]

    monkeypatch.setattr(client.app.state.ollama, "list_models", list_models)
    monkeypatch.setattr(client.app.state.ollama, "list_tool_models", list_tool_models)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["models"] == ["qwen3:8b", "deepseek-coder:6.7b"]
    assert response.json()["tool_models"] == ["qwen3:8b"]


def test_api_rejects_bad_and_duplicate_names(client, tmp_path):
    assert client.post("/api/workspaces", json={"name": "demo"}).status_code == 201
    dup = client.post("/api/workspaces", json={"name": "demo"})
    assert dup.status_code == 409 and "already exists" in dup.json()["detail"]
    for bad in ["../evil", "a/b", ".git", "with space", "-flag"]:
        r = client.post("/api/workspaces", json={"name": bad})
        assert r.status_code == 400, bad
    assert client.post("/api/workspaces", json={}).status_code == 422
    assert sorted(p.name for p in (tmp_path / "ws").iterdir()) == ["demo"]  # nothing escaped or leaked


def test_api_files_and_runs_filters(client):
    store = client.app.state.store
    store.create_run("r1", "t1", "demo", "m")
    _file_event(store, "r1", 1, "x.py")
    assert client.get("/api/files").json()[0]["path"] == "x.py"
    assert client.get("/api/files", params={"workspace": "other"}).json() == []
    assert [r["id"] for r in client.get("/api/runs", params={"workspace": "demo"}).json()] == ["r1"]
    assert client.get("/api/runs", params={"workspace": "other"}).json() == []
    assert client.get("/api/files", params={"limit": 0}).status_code == 200  # clamped, not an error


def test_api_git_log_and_current_workspace_files(client, tmp_path):
    project = tmp_path / "ws" / "demo"
    project.mkdir(parents=True)
    source = project / "hello.py"
    source.write_text("print('before')\n")
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=project, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=project, check=True)
    subprocess.run(["git", "add", "hello.py"], cwd=project, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "baseline"], cwd=project, check=True)
    source.write_text("print('after')\n")
    subprocess.run(["git", "add", "hello.py"], cwd=project, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "agent: update greeting"], cwd=project, check=True)

    commits = client.get("/api/git-log", params={"workspace": "demo"}).json()
    assert len(commits) == 2
    assert commits[0]["subject"] == "agent: update greeting"
    assert commits[0]["workspace"] == "demo"
    diff = client.get(f"/api/workspaces/demo/git-log/{commits[0]['hash']}").json()["diff"]
    assert "-print('before')" in diff and "+print('after')" in diff

    files = client.get("/api/workspaces/demo/files").json()
    assert {entry["path"] for entry in files} == {"hello.py"}
    assert client.get("/api/workspaces/demo/file", params={"path": "hello.py"}).json()["content"] == "print('after')\n"
    assert client.get("/api/workspaces/demo/file", params={"path": "../outside.py"}).status_code == 400


def test_api_token_protects_new_endpoints(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "ws"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.setenv("AGENT_API_TOKEN", "s3cret")
    config.get_settings.cache_clear()
    from app.main import app

    with TestClient(app) as c:
        for method, path in [("post", "/api/workspaces"), ("get", "/api/workspaces/details"), ("get", "/api/files")]:
            kwargs = {"json": {"name": "x"}} if method == "post" else {}
            assert getattr(c, method)(path, **kwargs).status_code == 401
        ok = c.post("/api/workspaces", json={"name": "x"}, headers={"Authorization": "Bearer s3cret"})
        assert ok.status_code == 201
    config.get_settings.cache_clear()
