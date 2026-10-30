"""Actual offline backup/restore drill with checksums and corruption detection."""
from __future__ import annotations

import fcntl
import json
import sqlite3

import pytest

from studio.backup import create_backup, restore_backup, verify_backup


def source_workspace(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    db_file = root / "studio.sqlite3"
    with sqlite3.connect(db_file) as conn:
        conn.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, text TEXT)")
        conn.execute("INSERT INTO sample(text) VALUES (?)", ("KIO production evidence",))
    project = root / ("a" * 32)
    project.mkdir()
    (project / "mesh.glb").write_bytes(b"glTF fixture for backup-only")
    (project / "manifest.json").write_text('{"approval":"approved"}')
    # Render cache and SQLite runtime journals must not enter the archive.
    (project / "godot_runtime").mkdir()
    (project / "godot_runtime" / "temporary.txt").write_text("skip")
    (project / "render.avi").write_bytes(b"scratch")
    return root, project


def test_real_sqlite_backup_verify_and_restore(tmp_path):
    root, project = source_workspace(tmp_path)
    backup = tmp_path / "snapshot"
    with pytest.raises(ValueError, match="offline-confirmed"):
        create_backup(root, backup)
    result = create_backup(root, backup, offline_confirmed=True)
    assert result["verified"] is True
    assert result["files"] == 3
    assert verify_backup(backup)["files"] == 3
    assert not (backup / project.name / "godot_runtime").exists()
    assert not (backup / project.name / "render.avi").exists()
    target = tmp_path / "restored"
    with pytest.raises(ValueError, match="offline-confirmed"):
        restore_backup(backup, target)
    done = restore_backup(backup, target, offline_confirmed=True)
    assert done["verified"] is True
    with sqlite3.connect(target / "studio.sqlite3") as conn:
        assert conn.execute("SELECT text FROM sample").fetchone()[0] == "KIO production evidence"
    assert (target / project.name / "mesh.glb").read_bytes().startswith(b"glTF")
    with pytest.raises(ValueError, match="must not exist"):
        restore_backup(backup, target, offline_confirmed=True)


def test_backup_rejects_corruption_and_path_escape(tmp_path):
    root, project = source_workspace(tmp_path)
    backup = tmp_path / "copy"
    create_backup(root, backup, offline_confirmed=True)
    manifest_path = backup / "backup_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"][0]["path"] = "../escape"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="escapes workspace"):
        verify_backup(backup)
    manifest["files"][0]["path"] = ("a" * 32) + "/manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    (backup / project.name / "manifest.json").write_text("CORRUPTED")
    with pytest.raises(ValueError, match="integrity mismatch"):
        verify_backup(backup)


def test_backup_rejects_live_worker_or_symlinks(tmp_path):
    root, project = source_workspace(tmp_path)
    lease = root / "worker.lock"
    with lease.open("a+b") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            with pytest.raises(RuntimeError, match="worker is running"):
                create_backup(root, tmp_path / "blocked", offline_confirmed=True)
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
    (project / "outside.txt").symlink_to(tmp_path / "outside")
    with pytest.raises(ValueError, match="nonregular files"):
        create_backup(root, tmp_path / "unsafe", offline_confirmed=True)
