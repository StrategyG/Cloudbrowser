"""CPU-efficient, bounded assembly of approved MP4 shots into an episode.

Only registered local MP4 artifacts are accepted. Uniform H.264 streams are
concatenated with stream-copy (no second video encode). Optional sound is
encoded as AAC and optional SRT is embedded as selectable mov_text subtitles.
"""
from __future__ import annotations

import hashlib
import json
import math
import tempfile
from pathlib import Path

from .cpu_shot import _digest
from .media import Media


def _video_stream(probe: dict) -> dict:
    streams = [stream for stream in probe.get("streams", []) if stream.get("codec_type") == "video"]
    if len(streams) != 1:
        raise ValueError("Each shot must contain exactly one video stream.")
    video = streams[0]
    if video.get("codec_name") != "h264" or video.get("pix_fmt") != "yuv420p":
        raise ValueError("Episode input must be H.264 yuv420p MP4.")
    if len([s for s in probe.get("streams", []) if s.get("codec_type") == "audio"]) > 0:
        raise ValueError("Supply silent shot MP4s; add episode audio separately.")
    return video


async def assemble_cpu_episode(
    media: Media, *, shot_ids: list[str], audio_id: str = "",
    subtitle_id: str = "",
) -> dict:
    """Join a bounded episode with no video re-encode, using persistent SHA-256 cache.

    Inputs must be uniform in video parameters. Independent manual visual review
    and audio/sync verification remain release gates, not inferred from FFprobe.
    """
    if not 1 <= len(shot_ids) <= 120:
        raise ValueError("Supply 1–120 ordered registered MP4 shots.")
    if not isinstance(audio_id, str) or not isinstance(subtitle_id, str):
        raise ValueError("Invalid audio or subtitle ID.")
    paths: list[Path] = []
    durations: list[float] = []
    signature = None
    for artifact_id in shot_ids:
        path = media.artifacts.path(artifact_id)
        if path.suffix.lower() != ".mp4":
            raise ValueError("Episode shots must be registered MP4 files.")
        info = await media.probe(path)
        stream = _video_stream(info)
        dims = (int(stream.get("width", 0)), int(stream.get("height", 0)))
        rate = stream.get("r_frame_rate", "")
        if "/" not in rate:
            raise ValueError("Invalid shot frame rate.")
        try:
            numerator, denominator = map(int, rate.split("/"))
            fps = numerator / denominator
        except (ValueError, ZeroDivisionError) as exc:
            raise ValueError("Invalid shot frame rate.") from exc
        if not math.isfinite(fps) or fps not in {24, 25, 30, 60}:
            raise ValueError("Unsupported episode frame rate.")
        Media._dimensions(*dims, int(fps))
        params = tuple(stream.get(k) for k in
                       ("codec_name", "pix_fmt", "profile", "level", "time_base",
                        "sample_aspect_ratio", "r_frame_rate", "width", "height"))
        if signature is None:
            signature = params
        elif params != signature:
            raise ValueError("All shots must use identical video encoding parameters.")
        duration = float(info.get("format", {}).get("duration", 0))
        if not math.isfinite(duration) or not 0 < duration <= 15.5:
            raise ValueError("Each shot must last 0–15 seconds.")
        paths.append(path)
        durations.append(duration)
    total = sum(durations)
    if total > 1200:
        raise ValueError("Episode duration exceeds 20 minutes.")
    audio = None
    if audio_id:
        audio = media.artifacts.path(audio_id)
        if audio.suffix.lower() not in {".wav", ".mp3", ".flac", ".ogg", ".m4a"}:
            raise ValueError("Episode audio must be registered WAV/MP3/FLAC/OGG/M4A.")
    subtitle = None
    if subtitle_id:
        subtitle = media.artifacts.path(subtitle_id)
        if subtitle.suffix.lower() != ".srt":
            raise ValueError("Episode subtitles must be registered SRT.")

    inputs = paths + [item for item in (audio, subtitle) if item is not None]
    payload = {
        "engine": "cpu-episode-v1",
        "inputs": [_digest(path) for path in inputs],
        "shot_count": len(paths), "audio": bool(audio), "subtitle": bool(subtitle),
    }
    key = "cpu-episode:" + hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    cached_string = media.artifacts.store.get(key)
    if cached_string:
        try:
            cached = json.loads(cached_string)
            video_path = media.artifacts.path(cached["id"])
            if _digest(video_path) == cached["sha256"]:
                return {"artifact": media.artifacts.store.artifact(cached["id"]),
                        "shot_count": len(paths), "duration_seconds": total,
                        "cache_hit": True, "note": "Cached validated episode."}
        except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError):
            pass

    artifact_id, output, filename = media.artifacts.allocate("cpu_episode.mp4")
    try:
        with tempfile.TemporaryDirectory(prefix="cpu-episode-", dir=media.artifacts.root) as temp:
            work = Path(temp)
            names = []
            for i, path in enumerate(paths):
                name = f"shot_{i:03}.mp4"
                (work / name).symlink_to(path)
                names.append(name)
            manifest = work / "episode.ffconcat"
            manifest.write_text(
                "ffconcat version 1.0\n"
                + "".join(f"file '{name}'\n" for name in names),
                encoding="utf-8",
            )
            args = ["ffmpeg", "-hide_banner", "-loglevel", "error",
                    "-nostdin", "-y",
                    "-protocol_whitelist", "file,pipe",
                    "-f", "concat", "-safe", "1", "-i", str(manifest)]
            other_index = 1
            if audio:
                args += media._input(audio)
                audio_index = other_index
                other_index += 1
            if subtitle:
                args += ["-protocol_whitelist", "file,pipe", "-f", "srt",
                         "-i", str(subtitle)]
                subtitle_index = other_index
            args += ["-map", "0:v:0", "-c:v", "copy"]
            if audio:
                args += ["-map", f"{audio_index}:a:0", "-c:a", "aac",
                         "-b:a", "128k", "-af", "apad"]
            if subtitle:
                args += ["-map", f"{subtitle_index}:s:0", "-c:s", "mov_text"]
            args += ["-t", str(total), "-movflags", "+faststart", str(output)]
            await media._run(*args, timeout=600)
        result_probe = await media.probe(output)
        result_stream = _video_stream({
            "streams": [s for s in result_probe.get("streams", [])
                        if s.get("codec_type") == "video"]})
        if tuple(result_stream.get(k) for k in
                 ("codec_name", "pix_fmt", "profile", "level", "time_base",
                  "sample_aspect_ratio", "r_frame_rate", "width", "height")) != signature:
            raise ValueError("Episode video stream differs from source.")
        actual_duration = float(result_probe.get("format", {}).get("duration", 0))
        if abs(actual_duration - total) > max(0.25, 2 * len(paths) / fps):
            raise ValueError("Episode duration QC failed.")
        present = {s.get("codec_type") for s in result_probe.get("streams", [])}
        if audio and "audio" not in present:
            raise ValueError("Episode audio stream missing.")
        if subtitle and "subtitle" not in present:
            raise ValueError("Episode subtitle stream missing.")
        artifact = media.artifacts.register(artifact_id, output, filename)
        media.artifacts.store.set(key, json.dumps(
            {"id": artifact_id, "sha256": _digest(output)}))
        return {"artifact": artifact, "shot_count": len(paths),
                "duration_seconds": actual_duration, "cache_hit": False,
                "note": "Stream-copied H.264 episode. Visual and audio QC required."}
    except BaseException:
        output.unlink(missing_ok=True)
        raise
