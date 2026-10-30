# CloudBrowser × Godot Integration

This feature branch is reserved for integration of CloudBrowser with the Godot-based animation pipeline.

## Intended architecture

- CloudBrowser handles AI-driven job orchestration and authorized user actions.
- Studio service handles PNG asset ingestion, GLB validation, rig approval, and scene manifests.
- Godot 4 handles preview, animation, and deterministic scene rendering.
- FFmpeg transcodes validated output to MP4.
- Telegram commands are restricted by chat allowlist and production actions require explicit approval.

## Acceptance gates

- No claim of full 3D reconstruction from a single PNG.
- Mesh, rig and shot-manifest validation must pass before rendering.
- Godot end-to-end rendering must be tested before production certification.
- CI validates Python tests, Docker configuration and Godot import/render smoke tests.

This document records the proposed integration; it does not claim those components are deployed.
