"""Tests orchestration and media QA. They do not replace real Godot runtime tests."""
import json
import subprocess
from pathlib import Path

import pytest

from studio.godot_render import (prepare, godot_commands, probe_video, validate_video,
                                render as godot_render)
from studio.manifest import Manifest, Shot


def manifest(approved=True, fps=24):
    return Manifest(fps=fps, width=640, height=360,
                    shots=[Shot(character='KIO', action='walk', duration=1)],
                    approval='approved' if approved else 'pending')


def test_requires_approved_manifest_and_glb(tmp_path):
    path = tmp_path / 'rigged.glb'
    path.write_bytes(b'glTF...')
    with pytest.raises(ValueError, match='unapproved'):
        prepare(tmp_path, manifest(False))
    path.unlink()
    with pytest.raises(FileNotFoundError, match='rigged.glb'):
        prepare(tmp_path, manifest(True))


def test_isolated_godot_project_and_movie_frame_count(tmp_path):
    rig = tmp_path / 'rigged.glb'
    rig.write_bytes(b'glTF...')
    work, count = prepare(tmp_path, manifest(fps=60))
    assert count == 60
    assert (work / 'assets' / 'character.glb').read_bytes() == rig.read_bytes()
    assert json.loads((work / 'manifest.json').read_text())['approval'] == 'approved'
    assert 'viewport_width=640' in (work / 'project.godot').read_text()
    importer, recorder = godot_commands(work, manifest(fps=60), count)
    assert importer[:3] == ['godot', '--headless', '--editor']
    assert '--headless' not in recorder  # headless display cannot record a useful 3D video
    assert recorder[0] == 'xvfb-run'
    assert recorder[recorder.index('--write-movie') + 1].endswith('render.avi')
    assert recorder[recorder.index('--quit-after') + 1] == '60'
    assert recorder[recorder.index('--fixed-fps') + 1] == '60'


def test_ffprobe_real_video_and_fail_closed(tmp_path):
    avi = tmp_path / 'synthetic.avi'
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi',
                    '-i', 'color=c=blue:s=640x360:r=24:d=1', '-frames:v', '24',
                    '-c:v', 'mjpeg', '-q:v', '4', str(avi)], check=True, timeout=30)
    assert validate_video(avi, manifest(), 24, 'mjpeg')['frames'] == 24
    with pytest.raises(RuntimeError, match='QA mismatch'):
        validate_video(avi, manifest(), 25, 'mjpeg')
    with pytest.raises(RuntimeError, match='Wrong video codec'):
        validate_video(avi, manifest(), 24, 'h264')


def test_integration_ffmpeg_after_fake_godot(tmp_path):
    """Uses real ffmpeg conversion, with a fake Godot recorder; Godot itself not installed here."""
    (tmp_path / 'rigged.glb').write_bytes(b'glTF...')
    (tmp_path / 'manifest.json').write_text(manifest().model_dump_json())
    calls = []
    def fake_runner(command, timeout):
        calls.append(command)
        if '--headless' in command:
            return  # A stub for Godot's asset import phase.
        if '--write-movie' in command:
            movie = command[command.index('--write-movie') + 1]
            subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                            '-f', 'lavfi', '-i', 'color=c=blue:s=640x360:r=24:d=1',
                            '-frames:v', '24', '-c:v', 'mjpeg', '-q:v', '4', movie],
                           check=True, timeout=40)
            return
        subprocess.run(command, check=True, timeout=40)
    qa = godot_render(tmp_path, fake_runner)
    assert qa['engine'] == 'godot_4'
    assert qa['frames'] == 24
    assert qa['mp4_qa']['codec'] == 'h264'
    assert (tmp_path / 'output.mp4').stat().st_size > 1024
    assert not (tmp_path / 'render.avi').exists()
    assert len(calls) == 3
