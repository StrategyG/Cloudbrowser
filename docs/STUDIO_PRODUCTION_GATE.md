# Studio Production Integrity & Recovery Gate

This document describes verified, bounded Studio production controls. **It does not certify commercial release, real ARUSIA character quality, natural locomotion, multi-tenant operations or uptime SLA.**

## 1. Runtime controls

**Approval:** Mesh, rig and manifest still require explicit owner authorization. Manifest approval stores an SHA-256 digest. The render API rejects a changed manifest before enqueue.

**Worker admission and completion:** The Studio worker now independently verifies, at the moment it starts a render, the registered source digest, rig digest, owner-approved manifest SHA-256, manifest approval state, and static motion preflight (including required named bones). It repeats the verification **after** Godot/FFmpeg completes. A mismatch marks the worker job and project failed rather than publishing an untrusted MP4.

**Output acceptance:** A completed video records the final MP4 SHA-256 and the input digests in `render_qa`. The Studio MP4 download endpoint refuses anything other than a `completed` project with matching MP4 checksum. It rejects stale output left by a failed job.

**Video QA:** In addition to ffprobe codec/frame count/dimensions/FPS checks, Studio decodes the first, middle and last MP4 frame and checks spatial grayscale variance to reject blank or uniform output. The report includes `frame_content_qa` and explicitly `motion_quality_certified: false`. This does **not** measure foot contact, physics, animation naturalness or character consistency.

**Crash recovery:** A restarted worker, after acquiring its exclusive workspace lock, marks interrupted `running` jobs **failed**. It never auto-replays unknown Blender/Godot effects. Inspect the project and its files, then explicitly use the existing retry action (subject to retry budget). Queued work that never started remains queued.

## 2. Offline Studio backup/restore

Studio volumes are not covered by GitHub repository commits. Back up the actual Studio workspace where `studio.sqlite3`, project folders, manifest files and GLBs reside. Use the included operator CLI after stopping **both** Studio API and Studio worker:

```bash
# From services/studio_v4 inside a trusted operator shell, with workspace stopped
python scripts/studio_backup.py backup --root /secure/studio-workspace \
  --backup /secure/backup/studio-2026-10-31 --offline-confirmed

python scripts/studio_backup.py verify \
  --backup /secure/backup/studio-2026-10-31

python scripts/studio_backup.py restore \
  --backup /secure/backup/studio-2026-10-31 \
  --destination /secure/studio-restored --offline-confirmed
```

- Backup uses SQLite's backup API to capture a transactionally consistent DB and copies regular project files with independent SHA-256 checksums.
- Temporary Godot runtime, render AVI, worker lease and SQLite WAL/SHM are excluded. Original sources, approved manifests, verified MP4, project reports and database are included.
- Restore always targets a **new, nonexistent** directory and validates each file and SQLite integrity before promotion. Old files are never overwritten. Symbolic links and traversal paths are rejected.
- Backup **is not encrypted or cryptographically signed**. Store it privately in encrypted storage with access control and independent retention; protect data in transit. The manifest detects accidental corruption but not a malicious actor who can rewrite both files and checksums.
- Offline consistency is the operator's responsibility: the CLI confirms the Studio worker lock is free, but it **cannot prove the API process is stopped**. Stop both services and prevent external writes before invoking it.
- This is a recovery *drill*, not a tested zero-downtime HA system. Validate restore with a separate operational smoke before changing traffic.

## 3. CI acceptance and remaining release gates

The Studio CI job runs the standard test suite and the real synthetic, locally executed GLB→Blender rig→Godot→MP4 smoke. The smoke now uses the actual mesh, rig and manifest approval handlers and checks the recorded MP4/input hashes.

**Still blocked for production certification:**
- Real approved ARUSIA character assets, scene consistency and single-shot visual acceptance.
- True motion verification from contact trajectories, collision/IK behavior and multiple character sequences.
- A production deployment at the target domain with metrics/alerts, documented rollback, restore rehearsal on the *actual* volume and measured recovery time.
- Multi-user isolation, distributed scheduling and production hardening for institutional use.
- A documented, validated operating budget for CPU-only render throughput.

**Recommended deployment gate:** run the smoke test with a real approved character, compare source/rig/manifest hashes before/after, inspect decoded frames and foot sliding, execute an offline backup/restore drill, and record an owner acceptance decision. Until then: **conditional single-owner pilot only**.
