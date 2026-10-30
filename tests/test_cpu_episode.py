from __future__ import annotations

import shutil

import pytest
from PIL import Image

from cloudbrowser.artifacts import Artifacts
from cloudbrowser.cpu_episode import assemble_cpu_episode
from cloudbrowser.cpu_shot import render_cpu_shot
from cloudbrowser.media import Media
from cloudbrowser.store import Store
from cloudbrowser.tools import TOOL_MAP

pytestmark = [
    pytest.mark.media,
    pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
                       reason="FFmpeg and FFprobe required"),
]


def png_artifact(artifacts, filename: str, color: tuple[int, ...]) -> str:
    artifact_id, path, clean_name = artifacts.allocate(filename)
    Image.new("RGBA", (90, 90), color).save(path)
    artifacts.register(artifact_id, path, clean_name)
    return artifact_id


async def test_cpu_episode_stream_copy_with_audio_subtitles_and_cache(tmp_path):
    store = Store(tmp_path)
    artifacts = Artifacts(tmp_path, store)
    media = Media(artifacts)
    try:
        bg = png_artifact(artifacts, "bg.png", (15, 55, 75, 255))
        actor = png_artifact(artifacts, "actor.png", (255, 170, 0, 220))
        a = await render_cpu_shot(media, background_id=bg, pose_ids=[actor],
                                  duration=1, width=640, height=360, fps=24,
                                  actor_width=70, y=100)
        b = await render_cpu_shot(media, background_id=bg, pose_ids=[actor],
                                  duration=1, width=640, height=360, fps=24,
                                  actor_width=70, y=100, end_x=180)
        audio_id, audio_path, audio_name = artifacts.allocate("voice.wav")
        await media._run("ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                         "-f", "lavfi", "-i", "sine=frequency=400:duration=2", str(audio_path))
        artifacts.register(audio_id, audio_path, audio_name)
        subtitles = artifacts.write(
            "captions.srt", "1\n00:00:00,000 --> 00:00:01,000\nARUSIA\n"
                            "2\n00:00:01,000 --> 00:00:02,000\nKIO\n"
        )
        params = {"shot_ids": [a["artifact"]["id"], b["artifact"]["id"]],
                  "audio_id": audio_id, "subtitle_id": subtitles["id"]}
        result = await assemble_cpu_episode(media, **params)
        assert result["shot_count"] == 2
        assert not result["cache_hit"]
        probe = await media.probe(artifacts.path(result["artifact"]["id"]))
        streams = {s["codec_type"]: s for s in probe["streams"]}
        assert streams["video"]["codec_name"] == "h264"
        assert streams["audio"]["codec_name"] == "aac"
        assert streams["subtitle"]["codec_name"] == "mov_text"
        assert 1.9 < float(probe["format"]["duration"]) < 2.2
        cached = await assemble_cpu_episode(media, **params)
        assert cached["cache_hit"]
        assert cached["artifact"]["id"] == result["artifact"]["id"]
        assert "assemble_cpu_episode" in TOOL_MAP
    finally:
        store.close()


async def test_cpu_episode_rejects_incompatible_shots_and_unregistered_files(tmp_path):
    store = Store(tmp_path)
    artifacts = Artifacts(tmp_path, store)
    media = Media(artifacts)
    try:
        bg = png_artifact(artifacts, "bg.png", (0, 0, 0, 255))
        actor = png_artifact(artifacts, "actor.png", (255, 50, 0, 255))
        base = dict(background_id=bg, pose_ids=[actor], duration=1, actor_width=70)
        a = await render_cpu_shot(media, **(base | {"width": 640, "height": 360, "fps": 24}))
        b = await render_cpu_shot(media, **(base | {"width": 1280, "height": 720, "fps": 24}))
        with pytest.raises(ValueError, match="identical"):
            await assemble_cpu_episode(media, shot_ids=[a["artifact"]["id"], b["artifact"]["id"]])
        with pytest.raises(ValueError, match="registered"):
            await assemble_cpu_episode(media, shot_ids=["0" * 32])
        with pytest.raises(ValueError, match="1–120"):
            await assemble_cpu_episode(media, shot_ids=[])
        assert not list(artifacts.root.glob("*episode*.mp4"))
    finally:
        store.close()
