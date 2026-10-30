from __future__ import annotations

import asyncio
import contextlib
import json
import shutil
import tempfile
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .artifacts import Artifacts

FORMATS = {".mp4": "mov", ".mov": "mov", ".m4v": "mov", ".webm": "matroska",
           ".mkv": "matroska", ".png": "png_pipe", ".jpg": "jpeg_pipe", ".jpeg": "jpeg_pipe",
           ".mp3": "mp3", ".wav": "wav", ".ogg": "ogg", ".flac": "flac", ".m4a": "mov"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".png", ".jpg", ".jpeg"}


class Media:
    def __init__(self, artifacts: Artifacts):
        self.artifacts = artifacts

    async def _run(self, *args: str, timeout: int = 600) -> str:
        if not shutil.which(args[0]):
            raise ValueError(f"{args[0]} is not installed on the server.")
        proc = await asyncio.create_subprocess_exec(
            *args, stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            output, error = await asyncio.wait_for(proc.communicate(), timeout)
        except BaseException:
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), 5)
                except TimeoutError:
                    proc.kill()
                    await proc.wait()
            raise
        if proc.returncode:
            raise ValueError(f"Media processing failed: {error.decode(errors='replace')[-600:]}")
        return output.decode(errors="replace")

    def _input(self, path: Path) -> list[str]:
        fmt = FORMATS.get(path.suffix.lower())
        if not fmt:
            raise ValueError("Format media tidak didukung.")
        # Force a media demuxer; never interpret uploaded playlists or fetch URLs.
        return ["-protocol_whitelist", "file,pipe", "-f", fmt, "-i", str(path)]

    async def probe(self, path: Path) -> dict:
        output = await self._run(
            "ffprobe", "-v", "error", *self._input(path), "-show_format", "-show_streams",
            "-of", "json", timeout=30,
        )
        return json.loads(output)

    @staticmethod
    def _dimensions(width: int, height: int, fps: int) -> None:
        if not (320 <= width <= 1920 and 320 <= height <= 1920 and width * height <= 1920 * 1080
                and width % 2 == 0 and height % 2 == 0 and fps in {24, 25, 30, 60}):
            raise ValueError("Use even video dimensions up to 1080p and 24/25/30/60 FPS.")

    async def compose(self, clip_ids: list[str], audio_id: str = "", subtitle_id: str = "",
                      width: int = 1280, height: int = 720, fps: int = 30) -> dict:
        self._dimensions(width, height, fps)
        if not 1 <= len(clip_ids) <= 20:
            raise ValueError("Gunakan 1–20 klip.")
        artifact_id, output, filename = self.artifacts.allocate("cloudbrowser_video.mp4")
        total = 0.0
        try:
            with tempfile.TemporaryDirectory(prefix="render-", dir=self.artifacts.root) as temporary:
                work = Path(temporary)
                segments = []
                for i, clip_id in enumerate(clip_ids):
                    path = self.artifacts.path(clip_id)
                    if path.suffix.lower() not in VIDEO_SUFFIXES:
                        raise ValueError("Input klip harus berupa video atau gambar.")
                    image = path.suffix.lower() in {".png", ".jpg", ".jpeg"}
                    probe = await self.probe(path)
                    duration = 5.0 if image else float(probe.get("format", {}).get("duration", 0))
                    if not (0 < duration <= 120):
                        raise ValueError("Setiap klip harus memiliki durasi 0–120 detik.")
                    total += duration
                    if total > 1200:
                        raise ValueError("Durasi total maksimum 20 menit.")
                    segment = work / f"segment_{i:03}.mp4"
                    vf = (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                          f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}")
                    args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
                    if image:
                        args += ["-loop", "1"]
                    args += self._input(path)
                    args += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", str(duration),
                             "-map", "0:v:0", "-map", "1:a:0", "-vf", vf,
                             "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                             "-pix_fmt", "yuv420p", "-c:a", "aac", str(segment)]
                    await self._run(*args)
                    segments.append(segment)
                manifest = work / "clips.ffconcat"
                manifest.write_text("ffconcat version 1.0\n" + "".join(f"file '{p.name}'\n" for p in segments))
                combined = work / "combined.mp4"
                await self._run("ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                                "-protocol_whitelist", "file,pipe", "-f", "concat", "-safe", "1",
                                "-i", str(manifest), "-c", "copy", str(combined))
                args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *self._input(combined)]
                if audio_id:
                    audio = self.artifacts.path(audio_id)
                    args += self._input(audio)
                    args += ["-map", "0:v:0", "-map", "1:a:0", "-af", "apad"]
                if subtitle_id:
                    subtitle = self.artifacts.path(subtitle_id)
                    if subtitle.suffix != ".srt":
                        raise ValueError("Subtitle harus .srt.")
                    shutil.copyfile(subtitle, work / "captions.srt")
                    # Internal temporary path only; no user text in the filter expression.
                    args += ["-vf", f"subtitles=filename='{work / 'captions.srt'}'",
                             "-c:v", "libx264", "-preset", "veryfast"]
                else:
                    args += ["-c:v", "copy"]
                args += ["-c:a", "aac", "-t", str(total), "-movflags", "+faststart", str(output)]
                await self._run(*args)
            artifact = self.artifacts.register(artifact_id, output, filename)
            return {"artifact": artifact, "duration_seconds": total, "fps": fps,
                    "note": "Audio asli klip diganti dengan track audio yang dipilih, atau hening jika tidak ada."}
        except BaseException:
            output.unlink(missing_ok=True)
            raise

    async def storyboard(self, scenes: list[dict], fps: int = 30) -> dict:
        if not 1 <= len(scenes) <= 20:
            raise ValueError("Storyboard memerlukan 1–20 adegan.")
        self._dimensions(1280, 720, fps)
        artifact_id, output, filename = self.artifacts.allocate("storyboard_animatic.mp4")
        try:
            with tempfile.TemporaryDirectory(prefix="animatic-", dir=self.artifacts.root) as temporary:
                work = Path(temporary)
                font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
                title_font = ImageFont.truetype(font_path, 46) if Path(font_path).exists() else ImageFont.load_default(size=46)
                body_font = ImageFont.truetype(font_path, 30) if Path(font_path).exists() else ImageFont.load_default(size=30)
                segments = []
                for i, scene in enumerate(scenes):
                    duration = float(scene.get("duration", 5))
                    if not 1 <= duration <= 30:
                        raise ValueError("Durasi adegan storyboard harus 1–30 detik.")
                    image = Image.new("RGB", (1280, 720), "#101c30")
                    draw = ImageDraw.Draw(image)
                    draw.rectangle((0, 0, 24, 720), fill="#35d4b5")
                    draw.text((70, 55), f"SCENE {i + 1:02d}  /  STORYBOARD", fill="#35d4b5", font=body_font)
                    title = textwrap.fill(str(scene.get("title", "Adegan"))[:100], width=42)[:180]
                    text = textwrap.fill(str(scene.get("text", ""))[:700], width=66)[:700]
                    draw.multiline_text((70, 140), title, font=title_font, fill="white", spacing=12)
                    draw.multiline_text((70, 310), text, font=body_font, fill="#cbd5e1", spacing=12)
                    frame, segment = work / f"frame{i}.png", work / f"scene{i}.mp4"
                    image.save(frame)
                    await self._run("ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                                    "-loop", "1", *self._input(frame), "-t", str(duration), "-r", str(fps),
                                    "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(segment))
                    segments.append(segment)
                manifest = work / "scenes.ffconcat"
                manifest.write_text("ffconcat version 1.0\n" + "".join(f"file '{p.name}'\n" for p in segments))
                await self._run("ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                                "-protocol_whitelist", "file,pipe", "-f", "concat", "-safe", "1",
                                "-i", str(manifest), "-c", "copy", "-movflags", "+faststart", str(output))
            return {"artifact": self.artifacts.register(artifact_id, output, filename),
                    "note": "Animatic berupa kartu storyboard; bukan animasi karakter atau hasil Google Flow."}
        except BaseException:
            with contextlib.suppress(OSError):
                output.unlink(missing_ok=True)
            raise
