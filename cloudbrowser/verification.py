from __future__ import annotations

import hashlib
import json
from fractions import Fraction

from .artifacts import Artifacts
from .crew_models import ExpectedOutput
from .media import Media


class Verifier:
    @staticmethod
    def matches(path, kind):
        return (path.suffix in {".txt", ".md", ".json", ".srt", ".vtt"} if kind == "text"
                else path.suffix in {".mp4", ".mov", ".m4v", ".webm", ".mkv"})

    def __init__(self, artifacts: Artifacts, media: Media):
        self.artifacts, self.media = artifacts, media

    async def inspect(self, artifact_id: str, expected: ExpectedOutput | None = None) -> dict:
        path = self.artifacts.path(artifact_id)
        with path.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        result = {"artifact_id": artifact_id, "size": path.stat().st_size, "sha256": digest}
        if not result["size"]:
            raise ValueError("Output artifact is empty.")
        if expected and (result["size"] < expected.min_size_bytes
                         or expected.max_size_bytes is not None and result["size"] > expected.max_size_bytes):
            raise ValueError("Output file size does not match workflow requirement.")
        if path.suffix in {".txt", ".md", ".json", ".srt", ".vtt"}:
            text = path.read_text(encoding="utf-8")
            if not text.strip():
                raise ValueError("Text artifact contains no content.")
            if path.suffix == ".json":
                json.loads(text)
            if expected and expected.kind != "text":
                raise ValueError("Expected video output, received a text artifact.")
            if expected and expected.text_contains and expected.text_contains not in text:
                raise ValueError("Required text is absent from output.")
            result.update({"kind": "text", "content": text[:12000]})
        else:
            probe = await self.media.probe(path)
            video = next((s for s in probe.get("streams", []) if s["codec_type"] == "video"), None)
            if not video:
                raise ValueError("Output contains no video stream.")
            duration = float(probe["format"].get("duration", 0))
            fps = float(Fraction(video.get("avg_frame_rate", "0/1")))
            if duration <= 0 or fps <= 0:
                raise ValueError("Video duration and frame rate must be positive.")
            result.update({"kind": "video", "width": video["width"], "height": video["height"],
                           "fps": fps, "duration_seconds": duration,
                           "has_audio": any(s.get("codec_type") == "audio" for s in probe.get("streams", []))})
            if expected:
                if expected.kind != "video":
                    raise ValueError("Expected text output, received video.")
                for dimension in ("width", "height", "fps"):
                    target = getattr(expected, dimension)
                    if target is not None and abs(result[dimension] - target) > .01:
                        raise ValueError(f"Output {dimension} does not match workflow requirement.")
                if expected.duration_seconds is not None and abs(duration - expected.duration_seconds) > expected.duration_tolerance:
                    raise ValueError("Video duration does not match workflow requirement.")
                if expected.has_audio is not None and result["has_audio"] != expected.has_audio:
                    raise ValueError("Video audio-stream requirement is not met.")
            # Decode the entire local file; readable headers alone do not prove an intact video.
            await self.media._run("ffmpeg", "-hide_banner", "-loglevel", "error", "-xerror", "-nostdin",
                                  *self.media._input(path), "-f", "null", "-", timeout=600)
        return result
