# Bundled Studio / Godot service

This service is integrated with Cloudbrowser A2A 0.4. Start the combined stack from the repository
root with `sh scripts/start_studio.sh`. See [STUDIO.md](../../docs/STUDIO.md) for configuration,
owner approvals, job recovery, API tools, editor access and limitations.

The worker accepts PNG silhouette extrusion (2.5D) or strictly validated imported external GLB (one connected character mesh), Blender rig authoring/QA, Godot 4.7.2 offline movie
capture, and FFmpeg MP4 encoding. It supports one character, 15 seconds and 900 frames per job.
PNG does not provide full 3D reconstruction; externally imported GLB can contain actual 3D geometry and one compatible skin, but no voice generation, lip sync, production foot IK or multi-character
choreography is supplied. Mesh, rig and manifest require manual review.

Install runtime dependencies from `requirements.lock`; NetworkX is explicitly included.
The service runs as a nonroot user in Docker. Only one worker may own its SQLite workspace.

For service-only tests in a separate virtual environment:

```bash
pip install -r requirements.lock
STUDIO_DATA_ROOT=/tmp/studio-test-workspace python -m pytest -q tests
```

The latest clean-install service run passed 14 tests. Actual Godot/Blender render and visual
acceptance remain outstanding; see the repository validation record. TEST_REPORT.md preserves
the upstream package's earlier test record and its explicit limitations.
