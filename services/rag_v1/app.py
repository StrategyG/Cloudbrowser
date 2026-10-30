"""Private CPU-first RAG service. No external LLM, credential or embedding API calls."""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import tempfile
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

SLUG = r"^[a-z][a-z0-9_-]{0,39}$"
SHA = r"^[a-f0-9]{64}$"
SOURCE = r"^[a-f0-9]{32}$"
MAX_BYTES = 12 * 1024 * 1024
MODEL_REVISION = os.environ.get("RAG_MODEL_REVISION", "v1")

app = FastAPI(title="Cloudbrowser Private RAG", docs_url=None, redoc_url=None,
              openapi_url=None)
_engine = None


class IngestRequest(BaseModel):
    project_id: str = Field(pattern=SLUG)
    source_id: str = Field(pattern=SOURCE)
    filename: str = Field(min_length=1, max_length=120)
    sha256: str = Field(pattern=SHA)
    content_b64: str = Field(max_length=16_800_000)


class SearchRequest(BaseModel):
    project_id: str = Field(pattern=SLUG)
    query: str = Field(min_length=2, max_length=1000)
    limit: int = Field(default=5, ge=1, le=10)


def authenticate(authorization: str = Header(default="")) -> None:
    token = os.environ.get("RAG_API_TOKEN", "")
    if len(token) < 32 or not hmac.compare_digest(authorization, "Bearer " + token):
        raise HTTPException(401, "Unauthorized.")


def extract_text(filename: str, content: bytes) -> str:
    if filename != Path(filename).name or "/" in filename or "\\" in filename:
        raise ValueError("Invalid document filename.")
    ext = Path(filename).suffix.lower()
    if ext in {".md", ".txt"}:
        return content.decode("utf-8")
    if ext != ".pdf" or not content.startswith(b"%PDF-"):
        raise ValueError("Only valid PDF, UTF-8 text or Markdown documents are accepted.")
    # Parse untrusted PDFs in this isolated worker, never in the Cloudbrowser gateway.
    from docling.document_converter import DocumentConverter

    with tempfile.TemporaryDirectory() as directory:
        local = Path(directory) / "upload.pdf"
        local.write_bytes(content)
        conversion = DocumentConverter().convert(str(local))
        try:
            return conversion.document.export_to_markdown()
        finally:
            conversion.input.release()


def split_document(text: str) -> list[str]:
    from llama_index.core.node_parser import SentenceSplitter

    if len(text) > 2_000_000:
        raise ValueError("Extracted document exceeds processing budget.")
    chunks = SentenceSplitter(chunk_size=450, chunk_overlap=60).split_text(text)
    if not chunks or len(chunks) > 2500:
        raise ValueError("Document is empty or has too many chunks.")
    return [chunk[:4000] for chunk in chunks if chunk.strip()]


class Engine:
    """Transactional per-project content replacement, cosine retrieval, no remote fallback."""

    def __init__(self):
        import psycopg
        from sentence_transformers import SentenceTransformer

        self.dsn = os.environ["RAG_DATABASE_URL"]
        model_path = Path(os.environ.get("RAG_EMBEDDING_MODEL_PATH", "/models/embedding"))
        if not model_path.is_dir():
            raise RuntimeError("Local embedding model directory is missing; no network fallback.")
        self.encoder = SentenceTransformer(str(model_path), local_files_only=True)
        if self.encoder.get_sentence_embedding_dimension() != 384:
            raise RuntimeError("Model must produce 384-dimensional embeddings.")
        self.revision = MODEL_REVISION
        self.db = psycopg
        with self.connect() as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            conn.execute("""CREATE TABLE IF NOT EXISTS rag_documents (
                project_id text NOT NULL, source_id text NOT NULL,
                filename text NOT NULL, sha256 text NOT NULL, model_revision text NOT NULL,
                chunk_count int NOT NULL, updated_at timestamptz NOT NULL DEFAULT now(),
                PRIMARY KEY (project_id, source_id))""")
            conn.execute("""CREATE TABLE IF NOT EXISTS rag_chunks (
                project_id text NOT NULL, source_id text NOT NULL, chunk_id text NOT NULL,
                model_revision text NOT NULL, sha256 text NOT NULL,
                text text NOT NULL, embedding vector(384) NOT NULL,
                PRIMARY KEY (project_id, source_id, chunk_id),
                FOREIGN KEY (project_id, source_id) REFERENCES rag_documents(project_id, source_id)
                    ON DELETE CASCADE)""")
            conn.execute("""CREATE INDEX IF NOT EXISTS rag_chunks_project_idx
                ON rag_chunks(project_id, model_revision)""")
            conn.execute("""CREATE INDEX IF NOT EXISTS rag_chunks_vector_idx
                ON rag_chunks USING hnsw (embedding vector_cosine_ops)""")

    def connect(self):
        from pgvector.psycopg import register_vector

        conn = self.db.connect(self.dsn, connect_timeout=5)
        try:
            register_vector(conn)
        except Exception:
            # pgvector may not yet be installed during bootstrap.
            conn.close()
            conn = self.db.connect(self.dsn, connect_timeout=5)
        return conn

    def ingest(self, request: IngestRequest) -> dict:
        from pgvector import Vector

        try:
            content = base64.b64decode(request.content_b64, validate=True)
        except (ValueError, binascii.Error):
            raise ValueError("Invalid base64 document.") from None
        if len(content) > MAX_BYTES or len(content) == 0:
            raise ValueError("Document is empty or exceeds 12 MiB.")
        if hashlib.sha256(content).hexdigest() != request.sha256:
            raise ValueError("Source SHA-256 mismatch.")
        # Ingest happens before DB transaction: expensive CPU work cannot hold table locks.
        extracted = extract_text(request.filename, content)
        chunks = split_document(extracted)
        vectors = self.encoder.encode(chunks, normalize_embeddings=True)
        if len(vectors) != len(chunks):
            raise ValueError("Embedding dimensions mismatch.")
        with self.connect() as conn:
            conn.execute("""INSERT INTO rag_documents
                (project_id,source_id,filename,sha256,model_revision,chunk_count)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT (project_id,source_id) DO UPDATE SET
                filename=EXCLUDED.filename, sha256=EXCLUDED.sha256,
                model_revision=EXCLUDED.model_revision,
                chunk_count=EXCLUDED.chunk_count, updated_at=now()""",
                (request.project_id, request.source_id, request.filename, request.sha256,
                 self.revision, len(chunks)))
            conn.execute("DELETE FROM rag_chunks WHERE project_id=%s AND source_id=%s",
                         (request.project_id, request.source_id))
            for index, (text, vector) in enumerate(zip(chunks, vectors, strict=True)):
                digest = hashlib.sha256(text.encode()).hexdigest()
                conn.execute("""INSERT INTO rag_chunks
                    (project_id,source_id,chunk_id,model_revision,sha256,text,embedding)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (request.project_id, request.source_id, f"{index:06}", self.revision,
                     digest, text, Vector(vector)))
        return {"project_id": request.project_id, "source_id": request.source_id,
                "sha256": request.sha256, "chunk_count": len(chunks),
                "model_revision": self.revision, "indexed": True}

    def search(self, request: SearchRequest) -> dict:
        from pgvector import Vector

        vector = Vector(self.encoder.encode(request.query, normalize_embeddings=True))
        with self.connect() as conn:
            rows = conn.execute("""SELECT project_id,source_id,chunk_id,sha256,
                text, 1 - (embedding <=> %s) AS score
                FROM rag_chunks WHERE project_id=%s AND model_revision=%s
                ORDER BY embedding <=> %s LIMIT %s""",
                (vector, request.project_id, self.revision, vector, request.limit)).fetchall()
        return {"chunks": [
            {"project_id": project, "source_id": source, "chunk_id": chunk,
             "sha256": digest, "text": text, "score": float(score)}
            for project, source, chunk, digest, text, score in rows]}


def engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = Engine()
    return _engine


@app.get("/healthz")
def healthz():
    return {"alive": True}


@app.get("/readyz")
def readyz(_: None = Depends(authenticate)):
    try:
        engine()
        return {"ready": True, "local_only": True, "embedding_revision": MODEL_REVISION}
    except Exception:
        return JSONResponse({"ready": False, "local_only": True}, status_code=503)


@app.post("/v1/ingest")
def ingest(request: IngestRequest, _: None = Depends(authenticate)):
    try:
        return engine().ingest(request)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@app.post("/v1/search")
def search(request: SearchRequest, _: None = Depends(authenticate)):
    return engine().search(request)
