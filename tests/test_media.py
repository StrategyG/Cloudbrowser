from __future__ import annotations

import shutil

import pytest

from cloudbrowser.artifacts import Artifacts
from cloudbrowser.media import Media
from cloudbrowser.store import Store

pytestmark = [pytest.mark.media, pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg not installed")]


async def test_real_mp4_storyboard_clip_assembly_audio_and_subtitles(tmp_path):
    store = Store(tmp_path)
    artifacts = Artifacts(tmp_path, store)
    media = Media(artifacts)
    try:
        storyboard = await media.storyboard([{"title": "Tes adegan", "text": "Kio membuka garasi.", "duration": 1}], fps=24)
        clip_id = storyboard["artifact"]["id"]
        probe = await media.probe(artifacts.path(clip_id))
        video = next(stream for stream in probe["streams"] if stream["codec_type"] == "video")
        assert (video["width"], video["height"]) == (1280, 720)
        assert video["r_frame_rate"] == "24/1"
        subtitle = artifacts.write("captions.srt", "1\n00:00:00,000 --> 00:00:00,900\nHalo ARUSIA\n")
        audio_id, audio, filename = artifacts.allocate("voice.wav")
        await media._run("ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-f", "lavfi",
                         "-i", "sine=frequency=440:duration=1", str(audio))
        artifacts.register(audio_id, audio, filename)
        result = await media.compose([clip_id], audio_id=audio_id, subtitle_id=subtitle["id"],
                                     width=640, height=360, fps=30)
        probe = await media.probe(artifacts.path(result["artifact"]["id"]))
        streams = {stream["codec_type"]: stream for stream in probe["streams"]}
        assert streams["video"]["width"] == 640
        assert streams["video"]["height"] == 360
        assert streams["video"]["r_frame_rate"] == "30/1"
        assert "audio" in streams
        assert .9 < float(probe["format"]["duration"]) < 1.2
    finally:
        store.close()


async def test_disguised_playlist_does_not_access_remote_media(tmp_path):
    store = Store(tmp_path)
    artifacts = Artifacts(tmp_path, store)
    artifact_id, path, filename = artifacts.allocate("disguised.mp4")
    path.write_text("#EXTM3U\n#EXTINF:1,\nhttp://169.254.169.254/latest/meta-data/\n")
    artifacts.register(artifact_id, path, filename)
    try:
        with pytest.raises(ValueError, match="Media processing failed"):
            await Media(artifacts).compose([artifact_id])
        assert not [p for p in artifacts.root.glob("*.mp4") if p != path]
    finally:
        store.close()


async def test_a2a_video_verifier_rejects_wrong_dimensions_and_fps(tmp_path):
    from cloudbrowser.crew_models import ExpectedOutput
    from cloudbrowser.verification import Verifier
    store = Store(tmp_path)
    artifacts = Artifacts(tmp_path, store)
    media = Media(artifacts)
    try:
        output = await media.storyboard([{"title": "QC", "text": "A2A verification", "duration": 1}], fps=24)
        verifier = Verifier(artifacts, media)
        artifact_id = output["artifact"]["id"]
        result = await verifier.inspect(artifact_id, ExpectedOutput(kind="video", width=1280, height=720, fps=24, duration_seconds=1))
        assert result["fps"] == 24
        assert not result["has_audio"]
        with pytest.raises(ValueError, match="audio-stream"):
            await verifier.inspect(artifact_id, ExpectedOutput(kind="video", has_audio=True))
        with pytest.raises(ValueError, match="width"):
            await verifier.inspect(artifact_id, ExpectedOutput(kind="video", width=1920))
        with pytest.raises(ValueError, match="fps"):
            await verifier.inspect(artifact_id, ExpectedOutput(kind="video", fps=60))
    finally:
        store.close()
