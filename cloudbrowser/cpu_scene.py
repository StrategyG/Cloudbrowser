"""Bounded multi-actor CPU-only 2D scene renderer (up to 5 actor layers).

Each actor is an ordered set of authored transparent PNG poses with an
independent linear x translation. This intentionally provides no 3D rig,
procedural IK or sound/lip-sync inference. FFmpeg receives only validated,
registered artifact files and constructed numeric expressions.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from PIL import Image

from .cpu_shot import _digest, _png
from .media import Media


async def render_cpu_scene(
    media: Media, *, background_id: str, actors: list[dict],
    duration: float = 5, width: int = 1280, height: int = 720, fps: int = 24,
) -> dict:
    Media._dimensions(width, height, fps)
    if not isinstance(duration, (float, int)) or not math.isfinite(duration) or not 1 <= duration <= 15:
        raise ValueError("Scene duration must be 1–15 seconds.")
    if not 1 <= len(actors) <= 5:
        raise ValueError("Provide 1–5 actor layers.")
    frame_count = round(duration * fps)
    if not 1 <= frame_count <= 900:
        raise ValueError("Scene frame budget exceeded.")

    sources: list[Path] = [_png(media, background_id)]
    clean_actors = []
    for actor in actors:
        ids = actor["pose_ids"]
        if not 1 <= len(ids) <= 4:
            raise ValueError("Each actor requires 1–4 PNG poses.")
        actor_width = actor.get("actor_width", 160)
        x0 = actor.get("start_x", 100)
        x1 = actor.get("end_x", 100)
        y = actor.get("y", 250)
        hold = actor.get("pose_hold_frames", 3)
        if not (isinstance(actor_width, int) and 32 <= actor_width <= min(width, 800)
                and isinstance(hold, int) and 1 <= hold <= 12
                and all(isinstance(v, int) for v in (x0, x1, y))
                and -actor_width <= x0 <= width and -actor_width <= x1 <= width
                and -height <= y <= height):
            raise ValueError("Actor layer position, size or pose interval invalid.")
        sources.extend(_png(media, artifact_id, actor=True) for artifact_id in ids)
        clean_actors.append({
            "poses": len(ids), "actor_width": actor_width, "start_x": x0,
            "end_x": x1, "y": y, "pose_hold_frames": hold,
        })
    if len(sources) > 21:
        raise ValueError("Scene exceeds 20 pose-image inputs.")
    # Prevent dozens of oversized pose PNGs from exhausting a small Codespace.
    total_pixels = 0
    for path in sources:
        with Image.open(path) as image:
            total_pixels += image.width * image.height
    if total_pixels > 48_000_000:
        raise ValueError("Scene source-image pixel budget exceeded.")

    payload = {"engine": "cpu-scene-v1",
               "inputs": [_digest(path) for path in sources],
               "actors": clean_actors, "frames": frame_count,
               "width": width, "height": height, "fps": fps}
    key = "cpu-scene:" + hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    cached_string = media.artifacts.store.get(key)
    if cached_string:
        try:
            cached = json.loads(cached_string)
            path = media.artifacts.path(cached["id"])
            if _digest(path) == cached["sha256"]:
                return {"artifact": media.artifacts.store.artifact(cached["id"]),
                        "duration_seconds": frame_count / fps, "fps": fps,
                        "actor_count": len(actors), "cache_hit": True,
                        "note": "Cached CPU 2D layered scene; visual QC required."}
        except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError):
            pass

    args = ["ffmpeg", "-hide_banner", "-loglevel", "error",
            "-nostdin", "-y", "-filter_complex_threads", "1"]
    for path in sources:
        args += ["-loop", "1", "-framerate", str(fps), *media._input(path)]
    filters = [f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
               f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=rgba[bg]"]
    source_index = 1
    previous = "bg"
    for actor_index, actor in enumerate(clean_actors):
        period = actor["poses"] * actor["pose_hold_frames"]
        denominator = max(1, frame_count - 1)
        motion = (f"{actor['start_x']}+({actor['end_x']}-{actor['start_x']})"
                  f"*min(n/{denominator},1)")
        for pose_index in range(actor["poses"]):
            label = f"a{actor_index}p{pose_index}"
            target = f"a{actor_index}o{pose_index}"
            filters.append(
                f"[{source_index}:v]scale={actor['actor_width']}:-2,"
                f"format=rgba[{label}]")
            source_index += 1
            low = pose_index * actor["pose_hold_frames"]
            high = (pose_index + 1) * actor["pose_hold_frames"] - 1
            enabled = f"between(mod(n\\,{period})\\,{low}\\,{high})"
            filters.append(f"[{previous}][{label}]overlay=x='{motion}':"
                           f"y={actor['y']}:enable='{enabled}':"
                           f"eval=frame:format=auto[{target}]")
            previous = target
    filters.append(f"[{previous}]format=yuv420p[out]")
    artifact_id, output, filename = media.artifacts.allocate("cpu_layered_scene.mp4")
    args += ["-filter_complex", ";".join(filters), "-map", "[out]",
             "-frames:v", str(frame_count), "-r", str(fps),
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
             "-threads", "2", "-movflags", "+faststart", str(output)]
    try:
        await media._run(*args, timeout=300)
        info = await media.probe(output)
        streams = [s for s in info.get("streams", []) if s.get("codec_type") == "video"]
        if len(streams) != 1:
            raise ValueError("Scene output must contain exactly one video stream.")
        video = streams[0]
        if (video.get("codec_name") != "h264"
                or (video.get("width"), video.get("height")) != (width, height)
                or video.get("r_frame_rate") != f"{fps}/1"):
            raise ValueError("Scene output codec/dimensions/FPS QC failed.")
        actual_duration = float(info.get("format", {}).get("duration", 0))
        if abs(actual_duration - frame_count / fps) > 0.1:
            raise ValueError("Scene duration QC failed.")
        artifact = media.artifacts.register(artifact_id, output, filename)
        media.artifacts.store.set(key, json.dumps(
            {"id": artifact_id, "sha256": _digest(output)}))
        return {"artifact": artifact, "duration_seconds": actual_duration,
                "fps": fps, "actor_count": len(actors), "cache_hit": False,
                "note": "CPU 2D layered scene; natural motion and visual QC not guaranteed."}
    except BaseException:
        output.unlink(missing_ok=True)
        raise
