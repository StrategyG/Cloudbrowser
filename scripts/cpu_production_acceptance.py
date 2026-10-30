#!/usr/bin/env python3
"""Run a real GPU-free CPU shot/episode acceptance test on the current machine.

No provider login, browser, GPU, model weights, or external network required.
Reports measured performance of the actual runner; does not certify artistic
quality or production readiness on a different machine.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import resource
import shutil
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageDraw

from cloudbrowser.artifacts import Artifacts
from cloudbrowser.cpu_episode import assemble_cpu_episode
from cloudbrowser.cpu_shot import render_cpu_shot
from cloudbrowser.media import Media
from cloudbrowser.store import Store


def save_png(artifacts: Artifacts, name: str, png: Image.Image) -> str:
    artifact_id, path, filename = artifacts.allocate(name)
    png.save(path, format="PNG")
    artifacts.register(artifact_id, path, filename)
    return artifact_id


async def run(seconds: int, width: int, height: int, fps: int, repeat_cycles: int = 1) -> dict:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("ffmpeg and ffprobe must be installed.")
    began = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="cpu-accept-") as tmp:
        store = Store(Path(tmp))
        artifacts = Artifacts(Path(tmp), store)
        media = Media(artifacts)
        try:
            bg = Image.new("RGBA", (width, height), (28, 55, 91, 255))
            draw = ImageDraw.Draw(bg)
            draw.rectangle((0, height * 3 // 4, width, height), fill=(54, 97, 61, 255))
            background_id = save_png(artifacts, "background.png", bg)
            poses = []
            for i in range(2):
                pose = Image.new("RGBA", (100, 140), (0, 0, 0, 0))
                painter = ImageDraw.Draw(pose)
                painter.ellipse((25, 10, 80, 65), fill=(255, 182, 76, 255))
                painter.rectangle((35, 65, 72, 115), fill=(255, 110, 10, 255))
                painter.line((40, 115, 27 if i else 50, 137),
                             fill=(0, 0, 0, 255), width=8)
                painter.line((70, 115, 80 if i else 57, 137),
                             fill=(0, 0, 0, 255), width=8)
                poses.append(save_png(artifacts, f"pose{i}.png", pose))
            shot_ids = []
            for n in range(2):
                shot = await render_cpu_shot(
                    media, background_id=background_id, pose_ids=poses,
                    duration=seconds, width=width, height=height, fps=fps,
                    actor_width=110, start_x=30 if n == 0 else width // 2,
                    end_x=width // 2 if n == 0 else width - 115,
                    y=height // 2, pose_hold_frames=3,
                )
                shot_ids.append(shot["artifact"]["id"])
            episode = await assemble_cpu_episode(media, shot_ids=shot_ids * repeat_cycles)
            output_path = artifacts.path(episode["artifact"]["id"])
            await media._run(
                "ffmpeg", "-hide_banner", "-v", "error", "-xerror",
                "-nostdin", "-protocol_whitelist", "file,pipe",
                "-f", "mov", "-i", str(output_path),
                "-map", "0:v:0", "-f", "null", "-", timeout=180,
            )
            probe = await media.probe(output_path)
            elapsed = time.perf_counter() - began
            actual = float(probe["format"]["duration"])
            if abs(actual - 2 * seconds * repeat_cycles) > max(0.15, repeat_cycles * 0.04):
                raise RuntimeError("Final MP4 duration outside expected bounds.")
            child = resource.getrusage(resource.RUSAGE_CHILDREN)
            return {
                "passed": True,
                "gpu_required": False,
                "worker": "Cloudbrowser CPU FFmpeg",
                "environment": {
                    "cpus_visible": os.cpu_count(),
                    "width": width, "height": height, "fps": fps,
                },
                "shot_count": len(shot_ids) * repeat_cycles,
                "output_duration_seconds": actual,
                "elapsed_wall_seconds": round(elapsed, 2),
                "peak_child_rss_kib": child.ru_maxrss,
                "encoding": "h264 copy concat",
                "verified": "ffprobe and full video decode",
                "not_verified": "real Codespaces quotas, animation quality, GPU absence at kernel level",
            }
        finally:
            store.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shot-seconds", type=int, default=3, choices=range(1, 16))
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=360)
    parser.add_argument("--fps", type=int, default=24, choices=(24, 25, 30, 60))
    parser.add_argument("--repeat-cycles", type=int, default=1, choices=range(1, 61),
                        help="Repeat the two rendered shots for a long-episode stream-copy test")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = asyncio.run(run(args.shot_seconds, args.width, args.height, args.fps,
                             args.repeat_cycles))
    output = json.dumps(report, indent=2)
    print(output)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
