"""RAG worker secure transport and local extraction; no model or DB simulated as ready."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("cloudbrowser_rag_v1",
                                               ROOT / "services/rag_v1/app.py")
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_rag_service_limits_and_metadata(monkeypatch):
    monkeypatch.setenv("RAG_API_TOKEN", "x" * 32)
    module.authenticate("Bearer " + "x" * 32)
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        module.authenticate("Bearer wrong")
    with pytest.raises(ValidationError):
        module.SearchRequest(project_id="other/project", query="query")
    with pytest.raises(ValidationError):
        module.SearchRequest(project_id="arusia", query="query", limit=15)
    with pytest.raises(ValueError):
        module.extract_text("../escape.txt", b"bad")
    with pytest.raises(ValueError):
        module.extract_text("untrusted.pdf", b"not a pdf")
    assert module.extract_text("note.md", b"# RUX\nGarage") == "# RUX\nGarage"
    assert module.healthz() == {"alive": True}


def test_rag_service_fails_readiness_without_local_model(monkeypatch):
    monkeypatch.delenv("RAG_DATABASE_URL", raising=False)
    monkeypatch.setenv("RAG_API_TOKEN", "x" * 32)
    monkeypatch.setattr(module, "_engine", None)
    readiness = module.readyz(None)
    assert readiness.status_code == 503
    assert b'"ready":false' in readiness.body
