# Cloudbrowser v5.0 — Security and Governance Audit

**Date:** 2026-10-30. **Scope:** `StrategyG/Cloudbrowser` source, CI configuration, and tests; **not** a penetration test against a deployed server.

## Trust boundaries actually present

- **Telegram:** `cloudbrowser/telegram.py` checks the configured private owner before command/callback mutations. Secrets are configured on the server, not requested in chat.
- **Web:** `cloudbrowser/web.py` uses password-derived hashes, signed time-limited cookies, CSRF on mutations, origin checks, rate limiting and disabled public OpenAPI docs. User must supply HTTPS origin/security config for public deployment.
- **Browser:** `cloudbrowser/network.py` enforces URL restrictions, `browser.py` checks current element snapshot/action preconditions, and `policy.py` decides approval based on registered tools.
- **Action boundary:** `agent.py` persists actions and awaits owner approval for tools marked `approval=True`. `store.py` marks applying actions `unknown` on restart rather than silently replaying them.
- **External A2A/Studio:** token-gated routes with fixed transport configuration (`a2a_server.py`, `web.py`, `studio_client.py`).
- **MorphGLB:** HTML is served behind owner authentication with restrictive CSP sandbox and an opaque-origin iframe. Parent frame handles CSRF-protected asset transfers; the HTML is committed in a **public** GitHub repository.
- **Data/credentials:** `config.py` allows environment secret overrides; `save_settings` creates a temporary configuration file using `mkstemp` and atomically replaces it. This is filesystem protection, **not encrypted-at-rest secrets**.

## Findings (severity, evidence, impact, fix and test)

| ID | Severity | Evidence | Risk / impact | Required remediation | Verification |
| --- | --- | --- | --- | --- | --- |
| S-01 | CRITICAL for multi-user expansion | `browser.py` uses one `launch_persistent_context` with shared profile; `telegram.py` one owner | Cross-tenant cookie/file exposure if multi-user access is enabled without redesign | **Keep deployment single-owner**, refuse multi-tenant claims; introduce per-principal browser profiles, artifact scopes and RBAC before offering accounts | TEST-007: two-principal isolation |
| S-02 | HIGH | `store.py` keyed jobs historically returned any goal using the same global key | Request replay could be confused with an unrelated task | Bind request key to normalized goal and project, reject conflict, make transaction atomic | TEST-006 and P0 tests |
| S-03 | HIGH | `llm.py` always sends to configured endpoint, `role_models` shares one URL | Selecting a local model name alone does not prevent prompt transfer to a configured remote URL | Provider-locality assertions, explicit egress policy and opt-in cross-provider fallback | TEST-009 + blocked outbound traffic |
| S-04 | HIGH | `tools.py` has typed tools; `policy.py` trusts tool `approval` declarations | Future plugin may be mislabeled and accidentally skip approval | Central risk-class registry and explicit deny-by-default for unknown capabilities; code-level enforcement | Mutating unknown MCP tool denied in tests |
| S-05 | HIGH | `store.py` action ledger and `agent._checked_tool` | External effects can succeed just before a crash; exactly-once unsupported | Preserve unknown-effect lock and owner reconciliation; add provider-native idempotency only where supported | Forced interruption during remote/browser mutation; no duplicate effect |
| S-06 | MEDIUM | `store.recover` previously used separate writes across jobs, approvals, actions and usage | Partial recovery if DB write fails halfway | **P0:** atomic SQLite recovery transaction; fail without half-committing | Inject failure in approval update and assert total rollback |
| S-07 | HIGH for public internet deployments | `compose.yaml`, `compose.studio.yaml`, `web.py` | Misconfigured proxy/origin/TLS and unintended exposed ports could expose owner or Studio admin functions | Reverse proxy TLS, firewall, no public Studio/DB/debug endpoints, verify `public_origin` and secure cookies | Port scan, HTTPS redirect, CSRF/origin tests |
| S-08 | MEDIUM | `config.py` `config.json` stores settings and tokens on disk | Secrets are not encrypted at rest and rely on host filesystem permissions | Restricted OS account/mount, encrypted volume or secret manager; rotate compromised tokens | File mode inspection + secret scan + restore/rotation drill |
| S-09 | MEDIUM | `web.py` public `/healthz`/`/readyz` | Liveness alone can hide an inactive worker | **P0:** component-aware non-secret readiness with 503 on failure | Ready endpoint test with service disabled and live Compose |
| S-10 | HIGH | No generic MCP gateway in recursive source tree | Unverified third-party tool output may introduce prompt injection, SSRF and unsafe mutations when later connected | Implement schema validation, allowlist transports, permission classes, bounded untrusted outputs | MCP tool contract injection/SSRF/approval test |
| S-11 | MEDIUM | Browser DOM/webpage text enters agent observation; `agent.py` applies system guidance but models still read untrusted text | Prompt injection can attempt tool hijacking; prompt instructions alone are not sufficient | Keep runtime tool allowlist, action gate, URL checks; add adversarial prompts and evidence-bound verification | Browser prompt injection regression with attempted unauthorized tool |
| S-12 | MEDIUM | `services/studio_v4/studio/import_glb.py` validates GLB; Blender consumes parsed models | Malformed model/resource exhausts CPU/RAM or triggers importer bugs | Keep upload limits, topology checks, restricted GLB extensions, worker resource quotas and isolated runtime | Malformed GLB corpus, resource exhaustion test and worker kill |
| S-13 | LOW | `web.py` CSP sandbox isolates MorphGLB frame | Browser renderer bugs remain outside Python control | Maintain patched Chromium/Three.js dependencies, retain sandbox, ensure no `allow-same-origin` | CSP/iframe regression tests and dependency scan |

## Approval and recovery invariants

1. Tool registration is not permission. Server policy must explicitly authorize the execution context.
2. External account actions and Studio/A2A mutations require owner approval unless a specific **server-configured** exception is both safe and tested.
3. Every externally dispatched mutation has a durable ledger entry before dispatch. After uncertain failure, the only safe next step is reconciliation (not blind retry).
4. Secrets, cookie material and API keys must not appear in approval summaries, model prompts, artifact filenames or logs.
5. Unknown external MCP tools must be denied until typed schemas and risk levels are registered.
6. Validation and human approval are distinct. A structurally valid GLB is not guaranteed to animate naturally.

## Security verification evidence and open gates

- Existing tests: `tests/test_web.py`, `test_telegram.py`, `test_decisions.py`, `test_morphglb.py`, `test_studio.py`.
- P0 additions: `tests/test_v5_p0.py` tests request-key conflict, persistence, readiness and transactional crash recovery.
- Existing CI: `.github/workflows/ci.yml` verifies Python tests, container build, Studio code plus synthetic GLB → Blender → Godot MP4 smoke.
- **Not verified in this audit:** production TLS/ports, secret manager, real MFA, multi-user isolation, MCP security, external-provider idempotency, penetration testing.

**Security conclusion:** suitable for continued **single-owner, access-controlled pilot development** with a configured TLS gateway; **not security-certified** for general multi-user or autonomous high-risk operations. The P0 fixes close specific gaps but do not implement RBAC, OAuth, security event streaming or hardened production network policy.

---

## P0 lifecycle governance addendum

| ID | Severity | Evidence | Security impact | Change | Verification |
| --- | --- | --- | --- | --- | --- |
| LC-S01 | HIGH | `agent.py::stop` previously accepted completed jobs | Completed evidence could be relabeled as stopped | Explicit terminal-state guard; permanent `cancelled` cannot be resumed | `tests/test_v5_lifecycle.py::test_cancel_active_approval_is_terminal` |
| LC-S02 | HIGH | Owner-issued cancellation may occur while external side effect is in flight | Unknown effect cannot safely be retried | Existing `_checked_tool` action ledger remains authoritative and records `unknown`; no automatic replay during pause/cancel | `tests/test_decisions.py` |
| LC-S03 | MEDIUM | New operator API and Telegram mutation entry points | CSRF or unauthorized chat could interrupt jobs | Dashboard routes use `sessions.require` and CSRF middleware; Telegram uses existing exact private-owner guard | `tests/test_v5_lifecycle.py`, `tests/test_telegram.py` |

**Residual risks:** Python task cancellation is cooperative, not guaranteed preemption of an external process or remote API. Operator must reconcile any `unknown` action before submitting a replacement mutation. Web/API and Chromium still assume one owner. No role-based multi-tenant auth, cryptographic server-side secret vault, or guaranteed external exactly-once semantics have been added.
