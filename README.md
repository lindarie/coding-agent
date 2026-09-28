# coding-agent

A small self-hosted coding agent: a Python/FastAPI service runs a tool-calling loop against a local
[Ollama](https://ollama.com) model, edits a project in `workspace/`, and runs tests in a throw-away Docker
container.

## Setup

### Prerequisites

- **Docker Desktop** on Windows or macOS
- **Ollama** installed and running on the host: [ollama.com/download](https://ollama.com/download). The model runs locally;
  it is not included in the Docker images.

Check that Docker Compose is available with `docker compose version`, and that Ollama responds with `ollama list`.

### Start with Docker

1. Download a tool-capable model for Ollama:
   ```sh
   ollama pull qwen3:8b
   ```
2. From the repository root, build and start the services:
   ```sh
   docker compose up --build -d
   ```
3. Open the UI at <http://localhost:8080>
