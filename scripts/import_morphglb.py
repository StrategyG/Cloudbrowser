#!/usr/bin/env python3
"""Safely stage the reviewed MorphGLB 3.3.0 source archive into this repository."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import zipfile

EXPECTED_SHA256 = "c7455e6c70836e248f84b7d040911ec5e3763c49dd6c580b4a2be3355f1437be"
EXPECTED_ROOT = "MorphGLB_AI_Studio_v3.3.0/"
MAX_FILES = 120
MAX_UNPACKED = 25 * 1024 * 1024
SKIP_PARTS = {"node_modules", "__pycache__", ".git"}
SKIP_SUFFIXES = {".pyc", ".pyo"}
SKIP_NAMES = {".env", ".DS_Store"}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_members(zf: zipfile.ZipFile):
    infos = [i for i in zf.infolist() if not i.is_dir()]
    if len(infos) > MAX_FILES:
        raise ValueError(f"Archive has too many files: {len(infos)}")
    total = sum(i.file_size for i in infos)
    if total > MAX_UNPACKED:
        raise ValueError(f"Archive expands beyond {MAX_UNPACKED} bytes")
    selected = []
    for info in infos:
        name = info.filename
        if not name.startswith(EXPECTED_ROOT) or "\\" in name:
            raise ValueError(f"Unexpected archive path: {name!r}")
        rel = PurePosixPath(name[len(EXPECTED_ROOT):])
        if rel.is_absolute() or not rel.parts or any(p in ("", ".", "..") for p in rel.parts):
            raise ValueError(f"Unsafe archive path: {name!r}")
        mode = (info.external_attr >> 16) & 0xFFFF
        if stat.S_ISLNK(mode):
            raise ValueError(f"Symlink is not allowed: {name!r}")
        if any(p in SKIP_PARTS for p in rel.parts) or rel.name in SKIP_NAMES:
            continue
        if rel.suffix in SKIP_SUFFIXES:
            continue
        selected.append((info, rel))
    return selected


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--target", type=Path, default=Path("services/morphglb/upstream"))
    parser.add_argument("--allow-different-hash", action="store_true",
                        help="Allow a different archive hash after manual review.")
    args = parser.parse_args()
    archive = args.archive.resolve()
    if not archive.is_file():
        raise SystemExit(f"Archive not found: {archive}")
    actual = digest(archive)
    if actual != EXPECTED_SHA256 and not args.allow_different_hash:
        raise SystemExit(f"SHA-256 mismatch: {actual}")
    target = args.target.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise SystemExit(f"Target already exists; refusing overwrite: {target}")
    with zipfile.ZipFile(archive) as zf:
        members = safe_members(zf)
        with tempfile.TemporaryDirectory(prefix="morphglb-stage-", dir=target.parent) as tmp:
            stage = Path(tmp) / "payload"
            stage.mkdir()
            for info, rel in members:
                destination = stage.joinpath(*rel.parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, destination.open("xb") as dst:
                    shutil.copyfileobj(src, dst)
                os.chmod(destination, 0o644)
            required = ("README.md", "server.py", "ai/tripo_engine.py", "src/tripo-shell.html")
            missing = [name for name in required if not (stage / name).is_file()]
            if missing:
                raise SystemExit("Required MorphGLB files missing: " + ", ".join(missing))
            stage.rename(target)
    print(f"Staged {len(members)} files at {target}; archive sha256={actual}")
    print("This stages source only; it does not build, start, expose, or deploy the service.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
