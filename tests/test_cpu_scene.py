from __future__ import annotations

import shutil

import pytest
from PIL import Image

from cloudbrowser.artifacts import Artifacts
from cloudbrowser.cpu_scene import render_cpu_scene
from cloudbrowser.media import Media
from cloudbrowser.store import Store
from cloudbrowser.tools import TOOL_MAP

pytestmark = [
    pytest.mark.media,
    pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
                       reason="FFmpeg / FFprobe unavailable"),
]


def new_png(artifacts, name, color, *, mode="RGBA"):
    artifact_id, path, filename = artifacts.allocate(name)
    Image.new(mode, (72, 100), color).save(path)
    artifacts.register(artifact_id, path, filename)
    return artifact_id


async def test_real_five_actor_cpu_scene_and_cache(tmp_path):
    store = Store(tmp_path)
    artifacts = Artifacts(tmp_path, store)
    media = Media(artifacts)
    try:
        bg = new_png(artifacts, "bg.png", (20, 80, 110, 255))
        actors = []
        for index in range(5):
            poses = [
                new_png(artifacts, f"actor{index}-a.png", (245, 30 + index * 20, 60, 240)),
                new_png(artifacts, f"actor{index}-b.png", (235, 35 + index * 20, 80, 210)),
            ]
            actors.append({"pose_ids": poses, "actor_width": 60,
                           "start_x": 5 + index * 110,
                           "end_x": 10 + index * 110,
                           "y": 145, "pose_hold_frames": 2})
        params = {"background_id": bg, "actors": actors,
                  "duration": 1, "width": 640, "height": 360, "fps": 24}
        first = await render_cpu_scene(media, **params)
        assert first["actor_count"] == 5
        probe = await media.probe(artifacts.path(first["artifact"]["id"]))
        video = next(s for s in probe["streams"] if s.get("codec_type") == "video")
        assert (video["width"], video["height"]) == (640, 360)
        assert video["r_frame_rate"] == "24/1"
        cached = await render_cpu_scene(media, **params)
        assert cached["cache_hit"]
        assert cached["artifact"]["id"] == first["artifact"]["id"]
        assert "render_cpu_scene" in TOOL_MAP
    finally:
        store.close()


async def test_cpu_scene_validates_resource_bounds(tmp_path):
    store = Store(tmp_path)
    artifacts = Artifacts(tmp_path, store)
    media = Media(artifacts)
    try:
        bg = new_png(artifacts, "bg.png", (0, 0, 0, 255))
        actor = new_png(artifacts, "actor.png", (200, 100, 30, 255))
        with pytest.raises(ValueError, match="1–5"):
            await render_cpu_scene(media, background_id=bg, actors=[], duration=1)
        with pytest.raises(ValueError, match="1–5"):
            await render_cpu_scene(media, background_id=bg, actors=[
                {"pose_ids": [actor]} for _ in range(6)
            ], duration=1)
        with pytest.raises(ValueError, match="invalid"):
            await render_cpu_scene(media, background_id=bg, actors=[
                {"pose_ids": [actor], "start_x": -10000}
            ], duration=1)
        with pytest.raises(ValueError, match="1–4"):
            await render_cpu_scene(media, background_id=bg, actors=[
                {"pose_ids": [actor] * 5}
            ], duration=1)
        opaque = new_png(artifacts, "opaque.png", (255, 0, 0), mode="RGB")
        with pytest.raises(ValueError, match="alpha"):
            await render_cpu_scene(media, background_id=bg, actors=[
                {"pose_ids": [opaque]}
            ], duration=1)
    finally:
        store.close()
