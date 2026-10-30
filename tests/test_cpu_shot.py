from __future__ import annotations

import shutil

import pytest
from PIL import Image

from cloudbrowser.artifacts import Artifacts
from cloudbrowser.cpu_shot import render_cpu_shot
from cloudbrowser.media import Media
from cloudbrowser.store import Store
from cloudbrowser.tools import TOOL_MAP

pytestmark = [
    pytest.mark.media,
    pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
                       reason="FFmpeg and FFprobe are required"),
]


def png_artifact(artifacts, name: str, color: tuple[int, ...], *, mode="RGBA"):
    artifact_id, path, filename = artifacts.allocate(name)
    Image.new(mode, (100, 100), color).save(path)
    artifacts.register(artifact_id, path, filename)
    return artifact_id


async def test_cpu_sprite_shot_real_mp4_and_content_cache(tmp_path):
    store = Store(tmp_path)
    artifacts = Artifacts(tmp_path, store)
    media = Media(artifacts)
    try:
        background_id = png_artifact(artifacts, "bg.png", (25, 70, 120, 255))
        pose_1 = png_artifact(artifacts, "pose1.png", (255, 80, 0, 190))
        pose_2 = png_artifact(artifacts, "pose2.png", (70, 230, 80, 255))
        settings = dict(background_id=background_id, pose_ids=[pose_1, pose_2],
                        duration=1, width=640, height=360, fps=24,
                        actor_width=80, start_x=10, end_x=200, y=100,
                        pose_hold_frames=2)
        result = await render_cpu_shot(media, **settings)
        assert not result["cache_hit"]
        path = artifacts.path(result["artifact"]["id"])
        probe = await media.probe(path)
        streams = [s for s in probe["streams"] if s["codec_type"] == "video"]
        assert len(streams) == 1
        assert (streams[0]["width"], streams[0]["height"]) == (640, 360)
        assert streams[0]["r_frame_rate"] == "24/1"
        assert abs(float(probe["format"]["duration"]) - 1) < 0.1

        cached = await render_cpu_shot(media, **settings)
        assert cached["cache_hit"] is True
        assert cached["artifact"]["id"] == result["artifact"]["id"]

        changed = await render_cpu_shot(media, **(settings | {"end_x": 220}))
        assert changed["cache_hit"] is False
        assert changed["artifact"]["id"] != result["artifact"]["id"]
        assert "render_cpu_shot" in TOOL_MAP
        assert not TOOL_MAP["render_cpu_shot"].approval
    finally:
        store.close()


async def test_cpu_renderer_rejects_invalid_inputs_and_no_output(tmp_path):
    store = Store(tmp_path)
    artifacts = Artifacts(tmp_path, store)
    media = Media(artifacts)
    try:
        bg_id = png_artifact(artifacts, "background.png", (0, 0, 0, 255))
        opaque_id = png_artifact(artifacts, "not_transparent.png", (200, 0, 0), mode="RGB")
        transparent_id = png_artifact(artifacts, "actor.png", (255, 0, 0, 130))
        with pytest.raises(ValueError, match="alpha"):
            await render_cpu_shot(media, background_id=bg_id, pose_ids=[opaque_id])
        with pytest.raises(ValueError, match="duration"):
            await render_cpu_shot(media, background_id=bg_id,
                                  pose_ids=[transparent_id], duration=float("nan"))
        with pytest.raises(ValueError, match="bounds"):
            await render_cpu_shot(media, background_id=bg_id, pose_ids=[transparent_id],
                                  start_x=-900)
        with pytest.raises(ValueError, match="frame budget|duration"):
            await render_cpu_shot(media, background_id=bg_id,
                                  pose_ids=[transparent_id], duration=16)

        bad_id, path, filename = artifacts.allocate("bad.png")
        path.write_text("#EXTM3U\nhttp://169.254.169.254/latest/meta-data/\n")
        artifacts.register(bad_id, path, filename)
        with pytest.raises(ValueError, match="Invalid PNG"):
            await render_cpu_shot(media, background_id=bad_id,
                                  pose_ids=[transparent_id])
        assert not list(artifacts.root.glob("*.mp4"))
    finally:
        store.close()


async def test_cpu_cache_does_not_reuse_tampered_media(tmp_path):
    store = Store(tmp_path)
    artifacts = Artifacts(tmp_path, store)
    media = Media(artifacts)
    try:
        bg_id = png_artifact(artifacts, "bg.png", (0, 0, 0, 255))
        pose_id = png_artifact(artifacts, "actor.png", (255, 200, 0, 255))
        params = {"background_id": bg_id, "pose_ids": [pose_id], "duration": 1,
                  "width": 640, "height": 360, "fps": 24, "y": 100}
        first = await render_cpu_shot(media, **params)
        artifacts.path(first["artifact"]["id"]).write_bytes(b"corrupted file")
        second = await render_cpu_shot(media, **params)
        assert not second["cache_hit"]
        assert second["artifact"]["id"] != first["artifact"]["id"]
        assert artifacts.path(second["artifact"]["id"]).stat().st_size > 100
    finally:
        store.close()
