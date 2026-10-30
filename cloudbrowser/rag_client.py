"""Private RAG HTTP adapter: no arbitrary URLs, no cloud fallback, citation-only retrieval."""
from __future__ import annotations

import base64
import hashlib
from pathlib import Path

import httpx

from .config import Settings


class RAGClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self.enabled = bool(settings.rag_base_url and settings.rag_api_token)
        self.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(40, connect=5), follow_redirects=False, trust_env=False)

    async def close(self) -> None:
        await self.client.aclose()

    async def _request(self, route: str, data: dict) -> dict:
        if not self.enabled:
            raise ValueError("Private RAG service has not been configured.")
        try:
            response = await self.client.post(
                self.settings.rag_base_url.rstrip("/") + route,
                headers={"Authorization": "Bearer " + self.settings.rag_api_token},
                json=data)
        except httpx.HTTPError:
            raise ValueError("Private RAG service is unavailable.") from None
        if not response.is_success:
            raise ValueError(f"RAG request failed with HTTP {response.status_code}.")
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Malformed RAG response.")
        return payload

    async def search(self, project_id: str, query: str, limit: int = 5) -> dict:
        if not query.strip() or len(query) > 1000 or not 1 <= limit <= 10:
            raise ValueError("Invalid RAG query.")
        data = await self._request("/v1/search",
                                   {"project_id": project_id, "query": query, "limit": limit})
        chunks = data.get("chunks")
        if not isinstance(chunks, list) or len(chunks) > limit:
            raise ValueError("Invalid RAG evidence.")
        safe = []
        for chunk in chunks:
            if not isinstance(chunk, dict) or chunk.get("project_id") != project_id:
                raise ValueError("RAG project authorization mismatch.")
            safe.append({"source_id": str(chunk.get("source_id", ""))[:128],
                         "chunk_id": str(chunk.get("chunk_id", ""))[:128],
                         "sha256": str(chunk.get("sha256", ""))[:64],
                         "text": str(chunk.get("text", ""))[:1600],
                         "score": chunk.get("score"),
                         "project_id": project_id})
        return {"chunks": safe, "untrusted": True, "source": "private_rag"}

    async def ingest(self, project_id: str, artifact_id: str, path: Path) -> dict:
        if path.suffix.lower() not in {".pdf", ".md", ".txt"} or path.stat().st_size > 12 * 1024 * 1024:
            raise ValueError("Only PDF, Markdown or text artifacts <=12 MiB can be indexed.")
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        return await self._request("/v1/ingest", {
            "project_id": project_id, "source_id": artifact_id, "filename": path.name,
            "sha256": digest, "content_b64": base64.b64encode(content).decode("ascii")})
