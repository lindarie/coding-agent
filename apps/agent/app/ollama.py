from __future__ import annotations

from typing import Any

import httpx


class OllamaError(Exception):
    pass


class OllamaClient:
    def __init__(self, base_url: str, timeout: float = 600.0):
        self.base_url = base_url
        self._http = httpx.AsyncClient(
            base_url=base_url, timeout=httpx.Timeout(timeout, connect=10.0)
        )

    async def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        num_ctx: int = 16384,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        payload = {
            "model": model,
            "messages": messages,
            "tools": tools,
            "stream": False,
            "options": {"num_ctx": num_ctx, "temperature": temperature},
        }
        try:
            resp = await self._http.post("/api/chat", json=payload)
        except httpx.ConnectError as e:
            raise OllamaError(
                f"Cannot reach Ollama at {self.base_url}. On Linux the host Ollama must "
                f"listen on an address the container can reach (OLLAMA_HOST=0.0.0.0). ({e})"
            ) from e
        except httpx.TimeoutException as e:
            raise OllamaError(f"Ollama timed out: {e!r}") from e
        if resp.status_code != 200:
            detail = resp.text[:500]
            hint = f" Try: ollama pull {model}" if resp.status_code == 404 else ""
            raise OllamaError(f"Ollama returned {resp.status_code}: {detail}.{hint}")
        return resp.json()

    async def list_models(self) -> list[str]:
        resp = await self._http.get("/api/tags", timeout=5.0)
        resp.raise_for_status()
        return [m["name"] for m in resp.json().get("models", [])]

    async def aclose(self) -> None:
        await self._http.aclose()
