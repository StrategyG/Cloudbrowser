# Validation record

## 0.4 integration verification — 30 October 2026

- Root suite: **92 passed, 2 skipped**. Two skipped tests require actual Chromium.
- Separate clean Studio virtual environment from its lock file: **13 passed**.
- Ruff, frontend JS syntax, shell syntax and whitespace checks: passed.
- Real A2A 1.0 loopback HTTP, owner dashboard authentication and real result download: passed.
- Actual Studio ASGI service, PNG upload, mesh generation, QA, explicit stage approval and GLB import:
  passed. No network/Blender/Godot invocation is implied by the ASGI transport.
- Completed MP4 import and full FFmpeg decoding: passed with an actual scene-card MP4 and controlled
  remote service response. Godot's render was not exercised by this test.
- Owner approval before Studio mutation in auto mode, token isolation, scope restrictions,
  response/redirect limits and transactional enqueue rollback: passed.
- Docker and Blender/Godot binaries unavailable locally. Real rig/import/movie rendering and
  production animation QA are outstanding. Google Flow/CapCut and a live configured AI model
  were not used. GitHub publication/CI status is reported separately when an actual write is attempted.

The following is the retained 0.3 development record for comparison.

Development verification: 30 October 2026 (A2A 0.3 update). This records implementation evidence, not production
certification or successful use of a paid account.

| Check | Observed outcome |
| --- | --- |
| Python Ruff lint | PASS |
| Python compilation | PASS |
| Frontend JavaScript syntax (`node --check`) | PASS |
| Startup/entrypoint shell syntax (`sh -n`) | PASS |
| Compose/Actions/Dependabot YAML parsing | PASS; Docker Compose CLI validation runs in CI |
| Unit/component tests | **86 passed, 2 skipped** in the development environment |
| MP4 production | PASS: actual FFmpeg scene-card MP4, clip assembly, 640×360/30fps output, audio track, SRT subtitles; FFprobe verified streams and duration |
| Setup wizard | PASS with test-only credentials: model/key/bot/owner prompts, hidden secret input, private persisted configuration |
| Owner pairing | PASS with mocked Bot API: matching one-time code, private-chat identity, group rejection |
| Telegram dispatch | PASS with mocked Bot API: owner-only commands/callbacks, group rejection, deduplication, resume and mode handling |
| AI API contract | PASS with HTTPX MockTransport: endpoint, authorization, payload and invalid-response handling; **no live model request** |
| Job controls | PASS: approval required before click, one-time decision, rejection/pause, cancellation, shutdown during approval, recovery and fresh-state resume |
| Dashboard access | PASS: password, session, CSRF, Origin check, login throttling, logout revocation and authenticated files |
| Actual server HTTP smoke | PASS: Uvicorn listener, public liveness 200, protected state 401, login 200, authenticated state 200 and graceful shutdown; Telegram disabled and no live AI request |
| A2A official SDK / ASGI interoperability | PASS: discovery, authenticated JSON-RPC 1.0, blocking/nonblocking SendMessage, message ID deduplication, task polling/cancel, scoped specialist endpoints, actual artifact retrieval |
| A2A actual loopback HTTP smoke | PASS: official SDK client to Uvicorn over a local socket, dynamic writer discovery, SendMessage, task polling and real output download; deterministic model stub, no live AI/provider account |
| Model-built team orchestration | PASS with controlled model responses: create writer/reviewer, freeze workflow, delegate, save actual file, independent step review, whole-goal audit and shared call budget; final rejection prevents completion |
| A2A negative/recovery paths | PASS: scope escalation denied, dependency/cycle checks, missing output rejected, input-required continuation, configured-secret redaction, unknown remote submission not replayed, cross-origin card endpoints rejected |
| Action policy and uncertainty | PASS: protected mutations gated in auto mode, timeout/cancellation recorded as unknown, unknown actions block replay, owner resolution is one-time and dashboard auth/CSRF protected |
| Evidence freshness | PASS: modified/deleted artifacts invalidate review and block dependencies; mutation during final audit prevents completion; identical reviewed delegations do not repeat work |
| Project context | PASS: owner project brief/history restored by project; external A2A contexts do not inherit private owner project context; legacy jobs migrate without history loss |
| Model routing and budgets | PASS: owner-configured role routing shares call/output budgets; provider usage settles reservations; absent usage retains reservation; oversized required context and truncated responses are rejected |
| Repeated failures | PASS: identical tool errors yield after the configured threshold |
| Backward configuration migration | PASS: old model/bot settings load with new A2A defaults; existing state tables extended in place |
| Packaged Python wheel | PASS; 0.3 wheel built successfully and includes HTML/CSS/JS/icon assets |
| Local Chromium integration | **NOT RUN**: Playwright browser download did not produce a valid ZIP archive; no browser binary was available |
| Docker build/sandboxed Chromium | **NOT RUN locally**: Docker executable unavailable; a dedicated GitHub Actions job performs both checks |
| Repository publication / GitHub CI execution | **BLOCKED**: creating the reviewed upgrade branch through the GitHub connection returned HTTP 403 `Resource not accessible by integration`. Remote main was still the initial README-only commit 6604192. Repository contents were not changed; no remote workflow result is claimed. |
| Google Flow / CapCut live workflow | **NOT VERIFIED**: account login, provider availability/credits and end-to-end generation/export require configuration on the user's server |

The two skipped tests exercise actual Chromium DOM actions, stale observations, screenshots and
password-field handling. They run in CI with `CLOUDBROWSER_TEST_BROWSER=1` after Chromium installation.
CI is configured in `.github/workflows/ci.yml`; its result must be read from the actual workflow run,
not inferred from local lint/unit results. A Starlette TestClient deprecation warning appeared in
the local tests; it did not fail tests or affect the runtime HTTP client.

For server acceptance, run `doctor --live`, the sandbox smoke script, and a short account-backed
task in approve mode: login manually, create one authorized test clip, download it, assemble it,
and retrieve the MP4. This step requires the selected AI API and actual website accounts/quotas.
