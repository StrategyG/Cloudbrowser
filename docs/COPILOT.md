# Animation Copilot v1 — scoped prompt-to-A2A workflow

## What this implements

The authenticated Cloudbrowser Studio page `/studio` now contains a contextual prompt panel with **Chat**, **Plan**, **Edit**, and **Agent** modes. A submission creates a durable job in the existing Cloudbrowser queue; the panel displays progress, result text, A2A specialist state and links to the existing Workspace approval UI.

The modes deliberately **do not read the MorphGLB iframe DOM** or inject JavaScript into it. MorphGLB uses an opaque-origin CSP sandbox with no access to owner cookies or Cloudbrowser APIs. Scene context is instead provided by the owner through fields (selected label, notes, existing registered asset ID). A Studio project ID triggers an authenticated **server-side** `studio_get_project` metadata read. The returned state and bounded metadata are context evidence, not authority.

### Four reusable persistent A2A specialists

The first **Plan**, **Edit**, or **Agent** submission installs these deterministic role definitions through existing `Crew.create` (all subsequent submissions reuse exact definitions):

| Agent ID | A2A capability profile | Responsibility |
| --- | --- | --- |
| `copilot_story_director` | `writer` | Storyboard, shot breakdown, measurable acceptance plan and text deliverables. |
| `copilot_asset_engineer` | `editor` | Studio mesh/rig validation; no unrestricted arbitrary mesh editing. |
| `copilot_motion_director` | `editor` | Bounded Godot shot planning, motion constraints and supported renders. |
| `copilot_qa_reviewer` | `reviewer` | Independent evidence-based read-only QA; never self-approves a stage. |

Definitions are checked against the existing `max_agents` limit before registration. ID conflicts are refused rather than overwriting existing owner agents. These agents inherit parent-job model-call budgets, tool restrictions, project scope and approval gates. An **Agent** job instructs the orchestrator to define a measurable A2A DAG, delegate supported work, and request an independent reviewer. Actual task completion depends on the LLM calling those tools and the verifier accepting real evidence; registering agents alone does not prove the workflow completed.

### Input and API

Owner-authenticated and CSRF-protected endpoints:

- `GET /api/copilot/agents` — non-secret catalog, installed status and Studio configuration status.
- `POST /api/copilot/jobs` — typed request with `mode`, `prompt`, `project_id`, `idempotency_key`, optional `studio_project_id`, `artifact_id`, `target_name`, `scene_notes`. No arbitrary redirect, execution code or network endpoint input.
- `GET /api/jobs/{job_id}` — existing durable job outcome, workflow, task IDs, approvals and event ledger.

The prompt panel uses the currently selected Studio project and imported asset IDs where available; field input is still **manual/explicit** and is never a live scene inspection from the third-party iframe. A 32-character ID is validated before trusting the corresponding owner artifact or the Studio server response.

Client-generated idempotency keys prevent duplicate job enqueue when a submission is retried. Existing per-project request-key constraints reject reuse with a different goal or scope.

### Safety and hard boundaries

- Chat and Plan block all tools flagged as **approval-required**, at the `Agent._checked_tool` execution boundary (not only a model prompt), even if a general browser auto-mode is enabled.
- Edit requires a Studio service and a registered source artifact or an existing Studio project ID. All existing Studio mutations retain exact owner approval and QA. No direct geometry-editing or generic PNG→3D reconstruction tool has been added.
- Agent mode can coordinate existing A2A specialists, but cannot bypass any established stage approval or independent final verification.
- Source assets are immutable in the artifact ledger; Studio results are separate artifacts. A UI-level geometry undo/redo stack, patch diff preview, direct bone manipulation and automatic save from MorphGLB **remain future work**. Editing the original GLB in place is not supported.
- The parent uses `textContent` for all model outputs and scene data, and keeps CSP `frame-ancestors 'none'`; sessions remain HttpOnly, SameSite=Strict.
- Tool responses and owner-supplied scene context remain untrusted evidence to the LLM. Only real tool outputs support success claims.

### How to run

1. Configure the Cloudbrowser AI model with function/tool calling and a dashboard password, and optionally a Studio/Godot service using `python -m cloudbrowser configure-studio`.
2. Open authenticated `/studio` (including via the Google Sites launcher `/?open=studio`).
3. Import a PNG/GLB with MorphGLB, or inspect a known Studio project. Copy their IDs into the Copilot panel (the UI also fills IDs after a successful import/inspection).
4. Pick a mode, supply an explicit prompt and scene notes, then submit.
5. Monitor job status. Approve individual mesh, rig, manifest or render actions through Workspace/Telegram. Review QA poses, manifest and MP4 before accepting outputs.

Use `Plan` to make a reviewable plan before enabling `Edit` or `Agent`. The output is a **workflow and approval-gated production job**, not an unrestricted VS Code extension or an automatically re-rigged asset.

### Verification

```bash
python -m ruff check .
node --check cloudbrowser/static/copilot.js
python -m pytest -q tests/test_copilot.py tests/test_studio.py tests/test_morphglb.py
```

This v1 does not imply verified institutional or 24/7 production readiness. Existing end-to-end RAG, failover, backup/restore and live ARUSIA asset acceptance gates remain separate.
