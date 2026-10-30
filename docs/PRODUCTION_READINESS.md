# Cloudbrowser v5.0 — Production Readiness and Acceptance Evidence

**Audit date:** 2026-10-30  
**Repository:** `StrategyG/Cloudbrowser`  
**Policy:** `IMPLEMENTED` = code exists; `TESTED` = actual automated test executed; `VERIFIED` = stated evidence supports the *specified* acceptance claim; `BLOCKED` = missing provider/runtime/assets; `NOT IMPLEMENTED` = capability is absent.

## Verdict

**Current scope: SINGLE-OWNER PILOT. NOT GENERAL PRODUCTION-READY.**

Main branch baseline CI at audit start: GitHub Actions run **41043555850**, conclusion **success**, for earlier commit `3d30ef674ae0…`. Existing Studio synthetic pipeline CI run **41042400976**, conclusion **success**, included Blender rig preparation, reimport skin QA, Godot render and H.264 output (24 frames, 640×360). These are **CI signals on synthetic assets**, not evidence of a 12-minute ARUSIA episode, a production deployment or a complete v5.0 OS.

The new v5 P0 branch adds request-key binding, transactional recovery, non-secret readiness, documentation and tests. These **must be checked against the final branch HEAD** before a PASS is claimed. The CI run for an earlier commit is not evidence for later commits.

## Actual capability ledger

| Capability | Current status | Evidence / limitation |
| --- | --- | --- |
| Telegram owner gateway | IMPLEMENTED / unit-tested | `telegram.py`, `tests/test_telegram.py`; real bot token/remote call not exercised here |
| Web dashboard and authenticated API | IMPLEMENTED / TESTED | `web.py`, `tests/test_web.py` |
| Supervisor/tool loop | IMPLEMENTED, bounded | `agent.py`; not a generalized strategic planner |
| Typed DAG, local A2A and review | IMPLEMENTED / TESTED | `crew_models.py`, `crew.py`, `scripts/smoke_a2a.py` |
| Official A2A service/peer | IMPLEMENTED / unit-tested | `a2a_server.py`, `a2a_peer.py`; no live remote partner acceptance |
| Playwright Chromium | IMPLEMENTED / smoke-tested | `browser.py`, `scripts/smoke_browser.py`; one persistent owner profile |
| Tool permission and owner approval | IMPLEMENTED / TESTED | `policy.py`, `agent.py`, `tests/test_decisions.py` |
| Durable jobs / reconciliation | IMPLEMENTED / TESTED locally | SQLite WAL. P0 atomic recovery under new tests; not distributed recovery |
| Request-key replay conflict check | IMPLEMENTED on P0 branch, CI pending at writing | `store.py`, `web.py`, `tests/test_v5_p0.py` |
| Local Qwen GGUF via external llama.cpp server | CONFIGURABLE, not end-to-end tested | One compatible Chat Completions URL; model binary/startup not managed |
| Multi-provider routing / locality fallback | NOT IMPLEMENTED | `llm.py` one endpoint; per-role model names do not equal provider adapters |
| Generic MCP client/tool fabric | NOT IMPLEMENTED | No generic MCP client under `cloudbrowser/` |
| PostgreSQL/Temporal/HA scheduling | NOT IMPLEMENTED | SQLite and one worker; no PostgreSQL migration |
| Browser multi-user isolation / tenant RBAC | NOT IMPLEMENTED | Single-owner mode only |
| MorphGLB editor + GLB Studio handoff | IMPLEMENTED / tested synthetic | `cloudbrowser/morphglb`, `studio_client.py`, `services/studio_v4` |
| Real character-level ARUSIA 12-minute episode | BLOCKED | No verified approved ARUSIA assets, motion-quality acceptance or shot orchestration |
| Structured observability / OpenTelemetry | PARTIAL / NOT IMPLEMENTED for OTel | SQLite events & health routes, no distributed traces |
| Long-term episodic/semantic RAG | NOT IMPLEMENTED as in-app memory | SQLite project briefs/history do not equal permissioned RAG |

## Acceptance tests: evidence register

The status below refers to **the full wording of each v5 acceptance test**, not to individual unit checks. No test is marked PASS if a required live provider/asset/process-crash step has not been executed.

| ID | Environment + actual available command | Expected | Observed evidence | Status / outstanding gate |
| --- | --- | --- | --- | --- |
| TEST-001 Telegram → Browser | CI: `python -m pytest -q tests/test_telegram.py tests/test_browser.py` | Real owner task invokes browser and verified result via Telegram | Unit fixtures test gateway/browser separately; no real bot E2E here | **BLOCKED**: live Telegram bot, allowed website, real end-to-end trace |
| TEST-002 Planning DAG | CI: `python -m pytest -q tests/test_crew.py tests/test_decisions.py` | Valid acyclic dependencies and verifiable subtask outputs | Typed `Workflow` graph and review logic tested in baseline CI | **TESTED** for bounded DAG; resource-aware parallel planner not implemented |
| TEST-003 Task recovery | CI: `python -m pytest -q tests/test_agent.py tests/test_decisions.py tests/test_v5_p0.py` | Forced worker restart retains consistent state and never replays uncertain effects | Existing recovery tests; new rollback injection case on P0 branch | **TESTED** for DB restart logic when current CI passes; live process kill/restart **BLOCKED** |
| TEST-004 Security enforcement | CI: `python -m pytest -q tests/test_decisions.py tests/test_web.py` | Out-of-permission tool rejected and logged | Existing policy/CSRF cases in CI | **TESTED** for defined tools; generic MCP denial **NOT IMPLEMENTED** |
| TEST-005 Human approval | CI: `python -m pytest -q tests/test_agent.py tests/test_decisions.py` | No protected mutation before owner approval | Existing exact approval gate regression cases | **TESTED** in-process; live remote-site side effects unverified |
| TEST-006 Idempotency | CI: `python -m pytest -q tests/test_v5_p0.py` | Same key/same payload one job; changed payload denied | P0 test added; final branch CI must be checked | **IMPLEMENTED; TESTED only after final CI success**. Provider-native exactly-once remains unsupported |
| TEST-007 Session isolation | No two-owner test command exists | Two users never share cookies, storage or files | Architecture has one persistent owner browser profile | **NOT IMPLEMENTED**: multi-user not enabled |
| TEST-008 Multi-agent coordination | CI: `python scripts/smoke_a2a.py` | Delegate, verify actual artifacts and respect dependencies | Baseline CI executes local A2A smoke successfully | **TESTED** for local; external peer interoperability unverified |
| TEST-009 Model routing | CI: `python -m pytest -q tests/test_llm_network_config.py tests/test_decisions.py` | Local and remote provider capability/egress isolation | Model ID routing is tested; no separate provider adapters or local GGUF live test | **BLOCKED** pending real local llama.cpp and provider contracts |
| TEST-010 MorphGLB integration | CI: `python -m pytest -q tests/test_morphglb.py tests/test_studio.py` | UI sends asset, gets job ID, tracks state, retrieves persisted result | Auth iframe, JS static contract, Studio API and artifact transfer tested; synthetic GLB render tested separately | **PARTIALLY TESTED**; full interactive browser-to-remote-UI E2E pending |
| TEST-011 ARUSIA pilot | CI: `docker run --rm --shm-size=1g --entrypoint python cloudbrowser-studio scripts/smoke_glb_render.py` (within Studio build) | One real approved ARUSIA character/shot, animation and MP4 verified | **Synthetic cube/rig** GLB to real Godot MP4 in earlier CI | **BLOCKED**: actual ARUSIA approved asset, pose/foot/visual assessment |
| TEST-012 Deploy | CI: `docker compose config -q`; `docker compose build`; `python scripts/smoke_browser.py` | Target stack startup, migration, restart, security smoke | Compose config/build and browser smoke tested | **PARTIALLY TESTED**; deployed server, DB migration, backup/restart/load tests missing |

## Release gates

**P0 merge gate:** final HEAD CI green for `test`, `studio` and `container`; P0 test file green; no regression in approval and recovery; manual diff review. **Do not merge on earlier SHA's green status.**

**P0 deployment gate:** operator runs `python -m cloudbrowser doctor`; verifies `/healthz` and `/readyz` on actual container; owner authentication, CSRF, private port binding and encrypted transport verified; creates a test goal with identical key twice and confirms one persisted job; restarts worker and checks interrupted/unknown results.

**P1 release gate:** valid typed policy for every external tool, local-model egress isolation, resource-lock/retry tests and durable restart reconciliation.

**P2/ARUSIA gate:** real approved character GLB, four-pose rig review, one-shot animated MP4, frame inspection, foot sliding and root motion QA, per-shot provenance and human acceptance.

## Commands and operator runbook

```bash
git clone https://github.com/StrategyG/Cloudbrowser.git
cd Cloudbrowser
python -m pip install -r requirements.lock -e '.[dev,studio]'
python -m ruff check .
python -m pytest -q tests/test_v5_p0.py tests/test_web.py tests/test_agent.py tests/test_decisions.py
docker compose config -q
docker compose build
# First configure secrets interactively: python -m cloudbrowser configure
# For full local Studio start: sh scripts/start_studio.sh (requires Docker and configured tokens).
# For operating readiness after startup: curl -fsS http://127.0.0.1:8000/readyz
```

Scripts and CI may require Playwright installation and FFmpeg; see `docs/DEPLOYMENT.md` and `.github/workflows/ci.yml`. **This document does not assert that the above operator commands ran on your server.**

## Release risks (remaining)

P0 fixes do not create PostgreSQL HA, MCP, tenant isolation, local model capability discovery, full-workflow cancel/resume, long-term RAG, automated natural motion QA or 12-minute ARUSIA episode production. Preserve owner approvals, keep the system behind a private authenticated gateway and treat external side effects as potentially ambiguous until reconciled.

---

## P0 lifecycle patch — incremental evidence register

Baseline `main` at branch creation: `6deeb419013fd6d905a619fd12c9d0491bf744ab`; parent CI run `41048285322` reported success. This only establishes the **pre-change** baseline.

| V5 acceptance mapping | Actual test command | Expected result | Status / evidence |
| --- | --- | --- | --- |
| TEST-003 recovery and controlled pause | `python -m pytest -q tests/test_v5_lifecycle.py tests/test_agent.py` | Paused jobs never replay queued effects; restart leaves terminal cancel terminal | Pending final feature-branch CI |
| TEST-004 / TEST-005 policy + approval | `python -m pytest -q tests/test_v5_lifecycle.py tests/test_decisions.py` | Stopping an unapproved browser mutation does not execute it; audit event recorded | Pending final feature-branch CI |
| TEST-006 request idempotency | `python -m pytest -q tests/test_v5_p0.py tests/test_v5_lifecycle.py` | Duplicate request yields same job; cancellation is stable | Pending final feature-branch CI |
| TEST-001 Telegram control subset | `python -m pytest -q tests/test_telegram.py` | Only private configured owner can pause/cancel; health masks secrets | Pending final feature-branch CI; live Telegram→browser acceptance still BLOCKED |
| TEST-012 deployment subset | `docker compose config -q` and `docker compose build` | No image/configuration regression | Pending final feature-branch CI; persistent deployment recovery still BLOCKED |

**Scope:** Incremental implementation of pause/cancel lifecycle only. The full TEST-001, TEST-003 (process-kill), TEST-007 multi-user, TEST-009 external routing, TEST-011 approved ARUSIA character pilot, and TEST-012 deployed HA recovery remain **BLOCKED** or **NOT IMPLEMENTED**, irrespective of unit test results.
