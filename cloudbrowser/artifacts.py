from __future__ import annotations

import re
import uuid
from pathlib import Path

from .store import Store


class Artifacts:
    def __init__(self, directory: Path, store: Store, max_mb: int = 100):
        self.root = directory / "artifacts"
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.store = store
        self.max_bytes = max_mb * 1024 * 1024

    def allocate(self, filename: str) -> tuple[str, Path, str]:
        filename = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename.replace("\\", "/")).name)[:120]
        filename = filename.strip(".") or "artifact.bin"
        suffix = Path(filename).suffix.lower()
        if not re.fullmatch(r"\.[a-z0-9]{1,10}", suffix):
            suffix = ".bin"
        artifact_id = uuid.uuid4().hex
        return artifact_id, self.root / (artifact_id + suffix), filename

    def register(self, artifact_id: str, path: Path, filename: str) -> dict:
        if path.stat().st_size > self.max_bytes:
            path.unlink(missing_ok=True)
            raise ValueError("File melebihi batas ukuran server.")
        return self.store.add_artifact(artifact_id, filename, path)

    def path(self, artifact_id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", artifact_id):
            raise ValueError("Invalid artifact ID.")
        path = Path(self.store.artifact(artifact_id)["path"])
        if path.is_symlink() or path.resolve().parent != self.root.resolve() or not path.is_file():
            raise ValueError("Artifact path is unavailable.")
        return path

    def write(self, filename: str, content: str) -> dict:
        if Path(filename).suffix.lower() not in {".txt", ".md", ".json", ".srt", ".vtt"}:
            raise ValueError("Text artifacts must use .txt, .md, .json, .srt or .vtt.")
        artifact_id, path, filename = self.allocate(filename)
        path.write_text(content, encoding="utf-8")
        return self.register(artifact_id, path, filename)
