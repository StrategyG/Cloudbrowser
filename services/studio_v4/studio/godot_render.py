"""Isolated Godot 4 movie rendering + deterministic ffprobe validation.

Never use Godot --headless to capture rendered frames: it selects a dummy display.
Use an Xvfb virtual display with Godot's gl_compatibility renderer and Movie Maker.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

from .manifest import Manifest
from .settings import FFMPEG

PROJECT_TEMPLATE = Path(__file__).resolve().parent.parent / 'godot_project'


def prepare(folder: Path, manifest: Manifest) -> tuple[Path, int]:
    """Stages a separate Godot project per Studio project to avoid cross-job collision."""
    if manifest.approval != 'approved':
        raise ValueError('Cannot render unapproved manifest')
    folder = Path(folder).resolve()
    rig = folder / 'rigged.glb'
    if not rig.is_file():
        raise FileNotFoundError('Missing rigged.glb: rigging must pass prior to render')
    total_frames = sum(round(s.duration * manifest.fps) for s in manifest.shots)
    if total_frames < 1 or total_frames > 900:
        raise ValueError('Frame quota exceeded')
    workdir = folder / 'godot_runtime'
    if workdir.exists():
        shutil.rmtree(workdir)
    shutil.copytree(PROJECT_TEMPLATE, workdir, ignore=shutil.ignore_patterns('.godot', '*.import', '.DS_Store'))
    (workdir / 'assets').mkdir(exist_ok=True)
    shutil.copyfile(rig, workdir / 'assets' / 'character.glb')
    (workdir / 'manifest.json').write_text(manifest.model_dump_json(indent=2))
    # Runtime default viewport may differ from request, so override in project too.
    config = workdir / 'project.godot'
    config.write_text(config.read_text().replace('viewport_width=1280', f'viewport_width={manifest.width}')
                      .replace('viewport_height=720', f'viewport_height={manifest.height}'))
    return workdir, total_frames


def godot_commands(workdir: Path, manifest: Manifest, frames: int, godot: str = 'godot',
                   virtual_display: str = 'xvfb-run') -> tuple[list[str], list[str]]:
    """Explicitly separate headless resource import from visible virtual-display rendering."""
    root = str(Path(workdir).resolve())
    movie_path = str((Path(workdir).parent / 'render.avi').resolve())
    importer = [godot, '--headless', '--editor', '--path', root, '--import', '--quit']
    recorder = [virtual_display, '-a', '-s', f'-screen 0 {manifest.width}x{manifest.height}x24',
                godot, '--path', root, '--rendering-method', 'gl_compatibility',
                '--resolution', f'{manifest.width}x{manifest.height}',
                '--write-movie', movie_path, '--fixed-fps', str(manifest.fps),
                '--quit-after', str(frames), '--disable-vsync']
    return importer, recorder


def probe_video(file: Path, ffprobe: str = 'ffprobe') -> dict:
    command = [ffprobe, '-v', 'error', '-select_streams', 'v:0', '-count_frames',
               '-show_entries', 'stream=codec_name,width,height,avg_frame_rate,nb_read_frames',
               '-of', 'json', str(file)]
    result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise RuntimeError(f'ffprobe failed: {result.stderr[-1500:]}')
    info = json.loads(result.stdout)
    streams = info.get('streams', [])
    if len(streams) != 1:
        raise RuntimeError('Video contains no unique video stream')
    s = streams[0]
    try:
        n = int(s['nb_read_frames'])
        fps = Fraction(s['avg_frame_rate'])
        width, height = int(s['width']), int(s['height'])
    except (ValueError, KeyError, ZeroDivisionError) as exc:
        raise RuntimeError('Invalid ffprobe video metadata') from exc
    return {'frames': n, 'fps': str(fps), 'width': width, 'height': height,
            'codec': str(s.get('codec_name', 'unknown'))}


def validate_video(path: Path, manifest: Manifest, expected_frames: int,
                   codec: str, ffprobe: str = 'ffprobe') -> dict:
    if not path.is_file() or path.stat().st_size < 1024:
        raise RuntimeError('Video file missing or empty')
    meta = probe_video(path, ffprobe)
    if (meta['frames'], meta['width'], meta['height'], Fraction(meta['fps'])) != (
            expected_frames, manifest.width, manifest.height, Fraction(manifest.fps, 1)):
        raise RuntimeError(f'Video QA mismatch: {meta}, expected {expected_frames} frames, '
                           f'{manifest.width}x{manifest.height} @ {manifest.fps} fps')
    if meta['codec'] != codec:
        raise RuntimeError(f'Wrong video codec: {meta["codec"]} (expected {codec})')
    return meta


def render(folder: Path, run_command, godot_bin: str | None = None,
           ffprobe_bin: str | None = None, xvfb_bin: str | None = None) -> dict:
    folder = Path(folder).resolve()
    manifest = Manifest.model_validate_json((folder / 'manifest.json').read_text())
    workdir, frames = prepare(folder, manifest)
    godot = godot_bin or os.getenv('GODOT_BIN', 'godot')
    xvfb = xvfb_bin or os.getenv('XVFB_BIN', 'xvfb-run')
    ffprobe = ffprobe_bin or os.getenv('FFPROBE_BIN', 'ffprobe')
    importer, recorder = godot_commands(workdir, manifest, frames, godot, xvfb)
    movie = folder / 'render.avi'
    mp4 = folder / 'output.mp4'
    for stale in (movie, mp4):
        stale.unlink(missing_ok=True)
    run_command(importer, timeout=900)
    run_command(recorder, timeout=7200)
    avi_meta = validate_video(movie, manifest, frames, 'mjpeg', ffprobe)
    run_command([FFMPEG, '-hide_banner', '-loglevel', 'error', '-y', '-i', str(movie),
                 '-an', '-fps_mode', 'passthrough', '-c:v', 'libx264', '-preset', 'medium',
                 '-crf', '18', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(mp4)], timeout=1200)
    mp4_meta = validate_video(mp4, manifest, frames, 'h264', ffprobe)
    # Retain original AVI for debugging only on explicit opt-in.
    if os.getenv('STUDIO_KEEP_INTERMEDIATE_AVI', '0') != '1':
        movie.unlink(missing_ok=True)
    return {'engine': 'godot_4', 'deterministic_offline': True, 'frames': frames,
            'fps': manifest.fps, 'width': manifest.width, 'height': manifest.height,
            'encoded': True, 'video_bytes': mp4.stat().st_size,
            'avi_qa': avi_meta, 'mp4_qa': mp4_meta, 'rig_source': 'blender_glb'}
