import asyncio
import json

import httpx

from app.ollama import OllamaClient


def test_list_tool_models_filters_models_without_tool_capability():
    capabilities = {
        "qwen3:8b": ["completion", "tools"],
        "codestral:22b": ["completion"],
        "phi4:14b": ["completion"],
    }

    def respond(request):
        if request.url.path == "/api/tags":
            return httpx.Response(
                200,
                json={"models": [{"name": model} for model in capabilities]},
            )
        name = json.loads(request.content)["model"]
        return httpx.Response(200, json={"capabilities": capabilities[name]})

    async def go():
        client = OllamaClient("http://ollama")
        await client._http.aclose()
        client._http = httpx.AsyncClient(
            base_url="http://ollama", transport=httpx.MockTransport(respond)
        )
        try:
            assert await client.list_tool_models() == ["qwen3:8b"]
        finally:
            await client.aclose()

    asyncio.run(go())
