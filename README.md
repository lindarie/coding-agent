# coding-agent

A small self-hosted coding agent: a Python/FastAPI service runs a tool-calling loop against a local
[Ollama](https://ollama.com) model, edits a project in `workspace/`, and runs tests in a throw-away Docker
container. A TypeScript CLI and React UI watch the run live through a typed event stream.

```
Browser / CLI ──HTTP + SSE──► web (nginx) ──► agent (FastAPI)
                                                 ├── Ollama (on the host)
                                                 ├── agent loop ── tools ── workspace/<project>  (own git branch per run)
                                                 └── Docker ── sandbox container: pytest / npm test / …
```

## Layout

```
apps/agent/          Python 3.12 · FastAPI · httpx · SQLite   (loop, tools, sandbox, git, API)
apps/web/            TypeScript · React · Vite               (control panel + CLI in cli/run.ts)
packages/api-types/  Shared event/request types + streaming client (used by UI and CLI)
workspace/           Projects the agent may modify (gitignored; demo/ is pre-seeded)
examples/demo/       Pristine demo project template (scripts/seed-demo.sh restores it)
docker/              agent, sandbox and web Dockerfiles + nginx template
```

## Quick start

1. **Ollama on the host** with a tool-capable model:
   ```sh
   ollama pull qwen3:8b
   ```
   On Linux the container reaches the host through `host.docker.internal`, so Ollama must not be bound to
   loopback only. For systemd installs add `Environment="OLLAMA_HOST=0.0.0.0"` via
   `systemctl edit ollama`, restart it, and firewall port 11434 from the outside world.
2. **Configure and start**
   ```sh
   cp .env.example .env        # optional; defaults work
   docker compose up --build
   ```
3. **Use it**
   - UI: <http://localhost:8080>
   - CLI (needs Node 20+ and `pnpm install` once):
     ```sh
     pnpm cli "Add a fibonacci function to mathutils.py and tests" --workspace demo
     ```
   - curl:
     ```sh
     curl -N localhost:8000/api/agent/run -H 'content-type: application/json' \
       -d '{"task":"Add a fibonacci function and tests","workspace":"demo"}'
     ```
4. **Review the result.** Each run works on branch `agent/<run_id>` inside the project and commits when done:
   ```sh
   cd workspace/demo && git log --stat -1
   ```

Reset the demo: `./scripts/seed-demo.sh`. Add projects by creating them in the UI (**Run** tab, "Create workspace"; names are
1-64 characters of letters, digits, `.`, `_`, `-`) or by putting directories under `workspace/` yourself. The **History** tab lists
workspaces, past runs (click one to replay its events) and every file the agent created or modified, filterable per workspace.
Directories created from the UI are owned by the agent container's user (root in Docker), like files written by the sandbox.

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/agent/run` | Body `{task, workspace, max_iterations?, model?}`. Streams events as SSE (`data: {json}`) |
| GET | `/api/workspaces` | Project directories under `workspace/` |
| POST | `/api/workspaces` | Body `{name}`. Creates an empty project directory (`400` invalid name, `409` already exists) |
| GET | `/api/workspaces/details` | Workspaces with `created_at` (null for folders not created via the API), `run_count`, `last_run_at` |
| GET | `/api/runs`, `/api/runs/{id}` | History and stored events (SQLite). `/api/runs` accepts `?workspace=&limit=` |
| GET | `/api/files` | Files the agent created/modified, newest first (`?workspace=&limit=`), from stored `file_changed` events |
| GET | `/api/health` | Ollama reachability, model availability |

### Events

Every event carries `run_id`, `seq`, `ts`, and a `type`:

`agent_started` · `status` · `tool_call` · `tool_result` · `file_changed` · `command_started` ·
`command_finished` · `agent_message` · `error` · `agent_finished`

Source of truth: `apps/agent/app/events.py` (Pydantic). TS mirror: `packages/api-types/src/events.ts`.

## Tools the model gets

`list_files`, `read_file`, `search_files`, `write_file` (path-confined to the project, `.git` blocked) and
`run_command` (executed in the sandbox image: no network, 1 GB RAM, 1 CPU, 256 pids, 120 s timeout by default).
The loop ends when the model answers without a tool call, or at `MAX_ITERATIONS`.

## Security — read this before exposing it

- The agent container mounts `/var/run/docker.sock` to spawn sandboxes. That is **root-equivalent on the host**.
  Model-written commands run inside the sandbox container, but treat the whole stack as trusted-user-only.
- **There is no login.** Ports bind to `127.0.0.1` by default. To reach it remotely use an SSH tunnel, Tailscale, or a
  reverse proxy with authentication (e.g. Caddy `basicauth`) in front of the web port. `AGENT_API_TOKEN` adds a bearer
  check on the API; nginx injects it for the UI, so protect the web port too.
- Sandbox network is off by default, so `pip install` / `npm install` fail. Use `SANDBOX_NETWORK=bridge` if you accept that.
  Add toolchains in `docker/sandbox.Dockerfile`.
- Files written by the sandbox are owned by root on the host.

## Development without Docker

```sh
pnpm install
cd apps/agent && pip install -r requirements-dev.txt && python -m pytest        # unit tests (fake Ollama)
# terminal 1
WORKSPACE_ROOT=$PWD/workspace DB_PATH=/tmp/agent.db SANDBOX_MODE=local OLLAMA_URL=http://localhost:11434 pnpm dev:agent
# terminal 2
pnpm dev:web            # http://localhost:5173, proxies /api to :8000
```
`SANDBOX_MODE=local` runs commands directly on your machine with **no isolation** — development only.

## Configuration

See `.env.example`. Notable: `OLLAMA_MODEL`, `OLLAMA_NUM_CTX` (raise for bigger projects), `MAX_ITERATIONS`,
`SANDBOX_NETWORK`, `BIND_ADDRESS`, `HOST_WORKSPACE_DIR` (absolute host path of `workspace/`; defaults to `$PWD/workspace`,
so run compose from the repo root).

## Known limits / next steps

- Ollama is called non-streaming, so a slow model shows "Waiting for model" until each step returns. Streaming
  tokens is a contained change in `ollama.py` + `loop.py` (add a `message_delta` event).
- A surgical `replace_in_file` tool would save tokens versus whole-file `write_file`.
- No cancel endpoint: closing the connection cancels the run and kills the sandbox container.
- Small models sometimes emit malformed tool calls; the loop reports the error back to the model rather than crashing.
- Ideas: run history view in the UI, approval gate before `run_command`, per-project sandbox images, WebSocket transport.
