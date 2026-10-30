# Upgrade Roadmap

## Objective
Upgrade Cloudbrowser from a capable single-owner autonomous browser platform into a more explicit, governable, production-grade agentic operating system aligned with the v5.0 target architecture.

## Phase 0 — Repository Stabilization and Audit

### Goals
- complete factual architecture audit
- document risks and boundaries
- identify code that already works and should not be replaced
- establish upgrade sequencing with minimal regression risk

### Deliverables
- architecture audit report
- security audit
- production readiness review
- initial gap analysis against v5.0 target

### Key actions
- confirm which modules are actual runtime components and which are exploratory
- identify exact deployment assumptions
- preserve working Telegram, browser, and job logic
- formalize what remains unsupported or unverified

### Exit criteria
- repo and architecture are mapped to real modules
- critical risk and limits are documented
- upgrade plan is grounded in evidence

---

## Phase 1 — Governance and Policy Formalization

### Goals
- create a formal governance layer
- separate policy enforcement from workflow execution
- move approval logic into explicit service boundaries

### Planned work
- create a `policy/` service layer with centralized policy decisions
- add role and capability definitions
- formalize tool authorization schema
- add approval policy registry and risk classification
- add audit log service and event correlation

### Key files to target
- `cloudbrowser/policy.py`
- `cloudbrowser/agent.py`
- `cloudbrowser/tools.py`
- `cloudbrowser/telegram.py`
- `cloudbrowser/store.py`

### Exit criteria
- no mutable action proceeds without explicit policy decision
- approval logic is centralized and testable
- policy denial is logged and traceable

---

## Phase 2 — Workflow State and Durable Execution Hardening

### Goals
- make task execution more explicit and durable
- formalize workflow state machine
- improve recoverability and rollback semantics

### Planned work
- formalize task lifecycle states and transitions
- add structured workflow records and migration system
- strengthen checkpointing and resume semantics
- implement idempotency keys for external effects
- add requeue and dead-letter handling

### Key files to target
- `cloudbrowser/store.py`
- `cloudbrowser/agent.py`
- `cloudbrowser/verification.py`
- `cloudbrowser/browser.py`
- `cloudbrowser/config.py`

### Exit criteria
- interrupted workflows resume in a controlled state
- retries do not duplicate external effects
- state transitions are durable and auditable

---

## Phase 3 — Agent Contracts and A2A Standardization

### Goals
- formalize agent-to-agent communication
- define capability registry and message schemas
- add contract validation for inter-agent messages

### Planned work
- define message contract types for task requests, execution results, validation, recovery, and approval
- implement A2A contract validation
- add agent registry and capability discovery
- ensure that all agent communication is policy-aware and evidence-bearing

### Key files to target
- `cloudbrowser/a2a_server.py`
- `cloudbrowser/a2a_peer.py`
- `cloudbrowser/crew.py`
- `cloudbrowser/crew_models.py`
- docs/A2A.md

### Exit criteria
- agent communication is strongly typed and verifiable
- no agent may act without registered capability and policy context
- failures propagate in a controlled and auditable way

---

## Phase 4 — Browser Runtime Hardening and Verification

### Goals
- improve browser state verification
- reduce stale-target and UI drift failures
- add stronger artifact evidence capture

### Planned work
- strengthen DOM and accessibility assertions
- validate snapshots before action execution
- bundle screenshot, DOM, and metadata for each execution step
- create browser QA checks before completion
- formalize failure classification workflow

### Key files to target
- `cloudbrowser/browser.py`
- `cloudbrowser/network.py`
- `cloudbrowser/verification.py`
- `cloudbrowser/tools.py`

### Exit criteria
- action success requires verification of page state
- browser tasks are evidence-backed and recoverable
- QA failures are classified instead of silently ignored

---

## Phase 5 — Observability and Production Operations

### Goals
- strengthen operational visibility
- enable root-cause analysis and health checks
- support production runbooks

### Planned work
- add structured logs with correlation IDs
- add metrics and execution telemetry
- add health endpoints and readiness checks
- add trace IDs to task and browser flows
- add dashboard views for active workflows, failures, and approvals

### Exit criteria
- operators can diagnose failures from a single trace chain
- workflow status is visible and auditable
- health monitoring is active for app, browser, and model provider components

---

## Phase 6 — Multi-Project and Multi-User Roadmap (Optional Future Stage)

### Goals
- move beyond single-owner deployment
- support strict project isolation and service separation

### Planned work
- tenant/project boundary enforcement
- per-user RBAC
- isolated browser profiles and session stores
- separate artifact catalogs and policy scopes
- stronger secret management and per-project trust boundaries

### Exit criteria
- users and projects are isolated by policy and storage boundary
- browser and tool access cannot cross project policy
- tenant operations are auditable and isolated

---

## Phase 7 — Studio / Creative / ARUSIA Production Layer

### Goals
- align the system with ARUSIA and studio production tasks
- harden render/asset validation and creative QA

### Planned work
- formalize asset registry and versioning
- standardize GLB, PNG, video, and manifest validation
- improve render QA before final approval
- integrate Blender/Godot/FFmpeg worker flows into explicit pipeline contracts
- add scene-level and shot-level verification strategies

### Key files to target
- `cloudbrowser/morphglb/`
- `cloudbrowser/studio_client.py`
- `services/studio_v4/`
- docs/STUDIO.md

### Exit criteria
- a staged pipeline exists from asset intake to final render approval
- output quality gates are explicit and auditable
- creative handoff is reviewable instead of implicit

---

## Prioritized Implementation Order

### P0 — immediate
- service isolation and governance layer
- workflow state model hardening
- policy engine formalization
- approval and audit logging
- browser verification improvements

### P1 — next
- A2A contract standardization
- checkpoint and rollback improvements
- observability and health endpoints
- CI pipeline and smoke tests

### P2 — stretch
- multi-project / tenant layer
- advanced studio QA and render validation
- full production artifact registry
- richer memory and learning layers

---

## Risk Register

| Risk | Severity | Mitigation |
| --- | --- | --- |
| External effect duplication | High | Idempotency keys, reconciliations, approval gates |
| Policy bypass | High | Centralized policy service, explicit contract validation |
| Browser drift | Medium | Screenshot/DOM validation and fallback action paths |
| Sensitive-data leakage | High | Privacy filtering, model routing, redaction |
| Workflow recovery failure | Medium | Checkpoint verification and durable state model |
| Render-quality uncertainty | Medium | QA gate and visual validation before final approval |

## Exit Criteria for the Upgrade
The repository should be considered successfully upgraded when all of the following are true:
- the system has a formal governance layer
- all workflow actions are stateful and policy-checked
- browser evidence is required for completion
- recovery and retry paths are tested
- approval gates are enforced for sensitive work
- multi-agent communication follows explicit contracts
- production telemetry is in place
- security and operational limits are documented and tested

## Verification Method
- run functional tests across task creation, approval, recovery, and browser execution
- verify policy denial conditions
- verify evidence capture and validation behavior
- verify interrupted jobs resume correctly
- verify human approval and override flows
- verify deployment and health checks in a clean environment

---
End of Upgrade Roadmap.

---

## v5.0 audited implementation plan (2026-10-30)

This section supersedes **priority ordering** where the generic phases above differ; it does not erase existing Phase 0–7 design. Evidence and per-finding severity live in [ARCHITECTURE_AUDIT.md](ARCHITECTURE_AUDIT.md), [SECURITY_AUDIT.md](SECURITY_AUDIT.md), and [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md).

### Increment P0-A — implemented on `feat/v5-p0-governance-foundation`

| Change | Code | Test / gate |
| --- | --- | --- |
| Payload-bound idempotency for dashboard and Telegram/A2A job keys | `store.py`, `web.py` | `tests/test_v5_p0.py`: duplicate same key one job; goal/project collision fails; database reopen |
| Atomic crash reconciliation | `store.py` | Failure-injection SQLite transaction rollback test; existing unknown-effect tests |
| Meaningful non-secret `/readyz` | `web.py` | Test worker-disabled = 503, DB status checked |
| Evidence-first gap and security register | `docs/*AUDIT.md`, `docs/PRODUCTION_READINESS.md` | Reviewer confirms evidence paths and statuses match CI |

**P0-A release rule:** use the CI result for the *final PR head* (not any earlier green commit), review the diff, and retain existing single-owner and human-approval protections. Do not claim generalized autonomous OS readiness.

### Remaining P0-B — not yet implemented

1. **Capability/risk policy registry:** default-deny previously unseen tools, read/write/destructive/publication classification, conditional owner approval with audit correlation ID. Must preserve current `action_policy` semantics until tests prove migration equivalent.
2. **Model locality safeguards:** opt-in provider adapters around existing `AIClient`; default **no external fallback** for a local model endpoint, provider health/capability detection with explicit egress tests.
3. **Operator preflight and structured audit:** startup health and diagnostics for configured worker, browser, model, Telegram without exposing credentials; redacted action and approval events.
4. **Recovery state contract:** explicit human reconciliation of unknown third-party effects, bounded retry policy and per-stage checkpoints. No automated replay of a crash-adjacent browser mutation.

### P1 — depends on P0-B

- **MCP client:** behind feature flag, version-pinned server connections, schema/allowlist verification, no dynamic privilege escalation, test read-only before any write tool.
- **PostgreSQL:** opt-in storage adapter and explicit one-way/rollback-tested migration from SQLite; no change to multi-worker topology before leases and transactional outbox are demonstrated.
- **Scheduler:** durable task leases, worker heartbeats, resource-lock fairness, dead-letter and bounded retry; parallelize only independent DAG nodes.
- **Browser action confirmation:** state-delta/evidence capture (URL, DOM and screenshot/trace) after a permitted operation, with unknown state on ambiguous effects.
- **Telegram:** backward-compatible `/newtask`, `/cancel`, `/pause`, `/health` aliases only after distinct pause/cancel state transitions exist.

### P2 — depends on P1 release gates

- Generalized MorphGLB asset ↔ job ↔ preview contract, artifact versions and QA provenance.
- ARUSIA episode DAG split into bounded shots because Studio `Manifest` currently enforces a 15-second / 900-frame limit. Separate character/world GLB assets and shot-level FFmpeg output.
- Objective animation QA: foot contact/sliding, rig pose consistency, frame defects and shot/lighting continuity. Real ARUSIA approved inputs and owner visual sign-off are mandatory.
- External Flow/CapCut integrations: official API where supported or permitted manual browser interaction; never assume free credits.

### P3 — only after real pilot evidence

Permission-scoped semantic/procedural memory, outcome-based replan suggestions, historical success rates and resource allocation. Never self-deploy source, policy or model-weight changes without tests and explicit approval.

### Dependency edges and stop conditions

`P0-A → P0-B (policy + egress) → P1 (MCP + DB leases) → P2 (asset/shot orchestration) → P3 (learning)`.

**Stop/review triggers:** test failure, policy regression, ambiguous external action, secrets in logs, failed migration, unverified ARUSIA asset, or incompatible GLB rig. Maintain separate `IMPLEMENTED`, `TESTED`, `VERIFIED`, `BLOCKED`, and `NOT IMPLEMENTED` records throughout.
