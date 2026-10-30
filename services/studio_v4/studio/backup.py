"""Offline Studio workspace backup/verify/restore with integrity manifests.

Use only after stopping *both* Studio API and worker. SQLite uses its online
backup API for a coherent DB copy; the asset directory snapshot is consistent
only when no other process is writing. Backup files contain private assets and
must be stored in operator-managed encrypted storage.
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import tempfile
from pathlib import Path, PurePosixPath

EXCLUDED = {
    "studio.sqlite3-wal", "studio.sqlite3-shm", "worker.lock", "render.avi",
}
EXCLUDED_DIRS = {"godot_runtime", ".godot"}
MANIFEST = "backup_manifest.json"
DB = "studio.sqlite3"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


@contextlib.contextmanager
def worker_stopped(root: Path):
    """Refuse backup if the single worker holds the workspace lock."""
    lock = root / "worker.lock"
    if lock.is_symlink():
        raise ValueError("Unsafe worker lock symlink")
    with lock.open("a+b") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Studio worker is running; stop the stack first") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _db_check(db_file: Path) -> None:
    with contextlib.closing(sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("SQLite integrity check failed")
        if db.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("SQLite foreign key check failed")


def _files(root: Path):
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED_DIRS)
        for directory in dirs:
            item = Path(current) / directory
            if item.is_symlink():
                raise ValueError("Backup cannot include symbolic links")
        for name in sorted(files):
            item = Path(current) / name
            if item.is_symlink() or not stat.S_ISREG(item.lstat().st_mode):
                raise ValueError("Backup contains nonregular files")
            if name not in EXCLUDED and name != DB and name != MANIFEST:
                yield item


def _valid_relative(text: str) -> Path:
    if not isinstance(text, str) or not text or "\\" in text:
        raise ValueError("Invalid backup path")
    part = PurePosixPath(text)
    if part.is_absolute() or any(x in {"..", ".", ""} for x in part.parts):
        raise ValueError("Backup path escapes workspace")
    return Path(*part.parts)


def _inside(root: Path, relative: Path) -> Path:
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Backup contains symbolic link")
    if not current.is_file() or not stat.S_ISREG(current.stat().st_mode):
        raise ValueError("Backup file missing or invalid")
    return current


def verify_backup(folder: Path) -> dict:
    folder = Path(folder).resolve(strict=True)
    if not folder.is_dir():
        raise ValueError("Backup must be a directory")
    manifest_file = folder / MANIFEST
    if not manifest_file.is_file() or manifest_file.stat().st_size > 2_000_000:
        raise ValueError("Missing or oversized backup manifest")
    data = json.loads(manifest_file.read_text(encoding="utf-8"))
    if data.get("format") != "studio-offline-v1" or not isinstance(data.get("files"), list):
        raise ValueError("Unsupported backup format")
    paths = set()
    for entry in data["files"]:
        relative = _valid_relative(entry["path"])
        if relative.as_posix() in paths:
            raise ValueError("Duplicate file in backup manifest")
        paths.add(relative.as_posix())
        path = _inside(folder, relative)
        if path.stat().st_size != entry["size"] or sha256(path) != entry["sha256"]:
            raise ValueError("Backup integrity mismatch: " + relative.as_posix())
    if DB not in paths:
        raise ValueError("Backup missing SQLite database")
    _db_check(folder / DB)
    return {"verified": True, "files": len(paths), "bytes": sum(x["size"] for x in data["files"])}


def create_backup(root: Path, destination: Path, *, offline_confirmed: bool = False) -> dict:
    if not offline_confirmed:
        raise ValueError("Explicit --offline-confirmed required; stop Studio API and worker first")
    root = Path(root).resolve(strict=True)
    destination = Path(destination).absolute()
    if not (root / DB).is_file() or destination.exists():
        raise ValueError("Source database missing or backup destination already exists")
    if destination == root or root in destination.parents or destination in root.parents:
        raise ValueError("Keep backup outside the Studio workspace")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with worker_stopped(root):
        tmp = Path(tempfile.mkdtemp(prefix=".studio-backup-", dir=destination.parent))
        try:
            with contextlib.closing(sqlite3.connect(root / DB)) as source:
                with contextlib.closing(sqlite3.connect(tmp / DB)) as target:
                    source.backup(target)
            records = []
            for source in [tmp / DB, *_files(root)]:
                relative = Path(DB) if source == tmp / DB else source.relative_to(root)
                copy = tmp / relative
                if relative != Path(DB):
                    copy.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, copy)
                records.append({"path": relative.as_posix(), "size": copy.stat().st_size,
                                "sha256": sha256(copy)})
            (tmp / MANIFEST).write_text(json.dumps({
                "format": "studio-offline-v1", "files": sorted(records, key=lambda x: x["path"]),
            }, indent=2), encoding="utf-8")
            verified = verify_backup(tmp)
            tmp.rename(destination)
            return verified
        finally:
            if tmp.exists():
                shutil.rmtree(tmp)


def restore_backup(backup: Path, destination: Path, *, offline_confirmed: bool = False) -> dict:
    if not offline_confirmed:
        raise ValueError("Explicit --offline-confirmed required; stop all Studio services")
    backup = Path(backup).resolve(strict=True)
    destination = Path(destination).absolute()
    if destination.exists() or destination == backup or backup in destination.parents:
        raise ValueError("Restore destination must not exist and must be outside backup")
    result = verify_backup(backup)
    manifest = json.loads((backup / MANIFEST).read_text(encoding="utf-8"))
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".studio-restore-", dir=destination.parent))
    try:
        for entry in manifest["files"]:
            relative = _valid_relative(entry["path"])
            target = tmp / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(_inside(backup, relative), target)
            if sha256(target) != entry["sha256"]:
                raise ValueError("Restore verification failed")
        _db_check(tmp / DB)
        tmp.rename(destination)
    finally:
        if tmp.exists():
            shutil.rmtree(tmp)
    return result
