from __future__ import annotations

import asyncio

import httpx

from .config import Settings


class AIClient:
    """Provider-neutral Chat Completions client; credentials are supplied on the server."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self.last_usage: dict | None = None
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(120, connect=15), follow_redirects=False)

    async def close(self) -> None:
        await self.client.aclose()

    async def complete(self, messages: list[dict], tools: list[dict], *, model: str | None = None) -> dict:
        self.last_usage = None
        headers = {"Authorization": f"Bearer {self.settings.ai_api_key}"} if self.settings.ai_api_key else {}
        payload = {"model": model or self.settings.ai_model, "messages": messages, "max_tokens": self.settings.ai_max_output_tokens,
                   "tools": tools, "tool_choice": "auto", "stream": False}
        url = self.settings.ai_base_url.rstrip("/") + "/chat/completions"
        for attempt in range(3):
            try:
                response = await self.client.post(url, headers=headers, json=payload)
            except httpx.HTTPError:
                # Exception strings can contain URLs/credentials; do not forward them.
                raise ValueError("Tidak dapat menghubungi API AI. Periksa endpoint, TLS dan jaringan server.") from None
            if response.status_code in {429, 502, 503, 504} and attempt < 2:
                retry = response.headers.get("retry-after", "")
                delay = min(10, float(retry)) if retry.isdigit() else 2 ** attempt
                await asyncio.sleep(delay)
                continue
            if not response.is_success:
                raise ValueError(f"API AI HTTP {response.status_code}. Periksa key, model, kuota dan dukungan tool calling.")
            try:
                data = response.json()
                self.last_usage = data.get("usage") if isinstance(data.get("usage"), dict) else None
                choice = data["choices"][0]
                if choice.get("finish_reason") in {"length", "content_filter"}:
                    raise ValueError("Incomplete model response.")
                message = choice["message"]
                if message.get("role") != "assistant":
                    raise ValueError
                if message.get("content") is not None and not isinstance(message["content"], str):
                    raise ValueError
                if not isinstance(message.get("tool_calls", []), list):
                    raise ValueError
                calls = message.get("tool_calls", [])
                seen = set()
                if len(calls) > 8:
                    raise ValueError
                for call in calls:
                    if (not isinstance(call, dict) or not isinstance(call.get("id"), str)
                            or not call["id"] or call["id"] in seen or call.get("type") != "function"
                            or not isinstance(call.get("function"), dict)
                            or not isinstance(call["function"].get("name"), str)
                            or not isinstance(call["function"].get("arguments"), str)):
                        raise ValueError
                    seen.add(call["id"])
                # Keep provider extensions such as reasoning_content for providers requiring it.
                return message
            except (ValueError, KeyError, IndexError, TypeError):
                raise ValueError("Format respons API tidak kompatibel dengan Chat Completions.") from None
        raise ValueError("API AI tidak tersedia.")
