# Cloudbrowser A2A 0.3

The model can now build a team of **agent definitions**, choose scoped specialties, create a workflow,
delegate tasks and request independent reviews. These are persistent runtime agents using the
configured AI API; definitions are validated data containing a name, instructions and a profile.
They do not grant arbitrary executable code or configuration changes.

The external wire protocol uses the official `a2a-sdk==1.3.0` with its A2A **1.0 JSON-RPC** binding.
Internal specialist tasks use the same SDK Task/Artifact data model and run inline under the parent
job's browser lease. Remote agents communicate over HTTP using the SDK transport. Both paths are
implemented and tested; a full A2A TCK certification is not claimed.

## What the AI builds

| Profile | Available capabilities |
| --- | --- |
| Writer | Read registered text, create scripts/prompts/SRT/JSON artifacts, ask the owner |
| Browser | Observe pages, navigate, click, type, upload registered files, drag timeline, ask the owner |
| Editor | Read/write text assets, create storyboard MP4s, compose clips/audio/subtitles, ask the owner |
| Reviewer | Read-only independent review using supplied output evidence; cannot create/modify the reviewed result |

The orchestrator has `a2a_create_agent`, `a2a_list_agents`, `a2a_set_workflow`,
`a2a_delegate_task`, `a2a_review_task`, `a2a_get_task`, `a2a_list_peers`, `a2a_send_remote`
and `a2a_get_remote_task` tools. Specialists cannot delegate recursively or add tools to themselves.
Creation is limited to eight agents by default; reuse existing agents for subsequent work.

Example Telegram instruction:

```text
Bangun tim A2A untuk video ARUSIA: penulis naskah, operator Google Flow,
editor dan reviewer. Buat workflow dengan bukti hasil tiap langkah.
Mulai dengan naskah video 30 detik. Jangan gunakan kredit Flow sebelum saya mengizinkan.
```

Use `/agents` to inspect the generated team and `/workflow <job_id>` for step/task/review status.
The dashboard also lists the created team. Job details API includes the workflow, specialist task
records, per-step reviews, final review, output IDs and shared model-call count.

## Completion rules

1. The model creates a workflow with 1–8 ordered steps, expected output type and optional numeric
   requirements. Dependencies must refer to earlier steps; cycles/duplicate IDs are rejected.
2. Delegation freezes that workflow's requirements. Each specialist execution has its own task,
   isolated conversation, selected tool schema and persisted outputs.
3. A distinct reviewer is required before downstream dependent work is allowed. Missing files,
   empty text, invalid JSON, wrong media type, dimensions, FPS or duration reject the output.
   Video validation also decodes the actual local file through FFmpeg; headers alone are insufficient.
4. A model review evaluates task quality using the original user request and actual evidence.
   Once all steps pass, an additional completion audit compares the whole workflow with the original
   goal, preventing a script-only plan from silently substituting for a requested finished video.
5. A final model reply alone cannot mark a workflow complete. Failed/missing review yields
   `incomplete`, with evidence retained for correction. All specialists share one logical model-call
   budget and job timeout; default budget is 60 calls including the parent and reviewers.

Model-based quality judgments can still be wrong, especially when the same model performs multiple
roles. Numeric/file verification is deterministic; narrative quality, factual meaning and visual
character consistency are not proven by a media metadata check. Real website and chosen-model
acceptance tests remain necessary. Agent creation alone does not establish ChatGPT Pro parity.

With `require_workflow=true` (default), production jobs require this workflow. An operator may set
`require_workflow=false` in private configuration for legacy/simple chat behavior; that mode does
not provide the workflow completion guarantee. Existing configuration files gain the new defaults
without removing existing bot/model settings or browser sessions.

## Human handoff, restart and concurrency

Specialist browser actions retain the parent's approve/auto mode. A specialist needing login,
CAPTCHA, permission or clarification yields `INPUT_REQUIRED` and releases the parent job's browser
lease. The owner can use the dashboard and resume the parent job with feedback. The specialist
continues its history using fresh page observations. Failed/completed specialist tasks receive a
new task ID for a corrected attempt; terminal protocol tasks are never restarted.

Local browser work remains serialized. This prevents two agents from clicking the same profile
at once and avoids an orchestrator waiting for a child behind itself in the single-worker queue.
Remote work may continue at the peer while Cloudbrowser polls. No automatic mutation replay occurs
after a lost network response or server restart. Unknown remote outcome requires peer-history review.

## Enable incoming external A2A

Local team building works with the ordinary model/Telegram setup. To expose A2A to other trusted
agent clients, stop the server and configure its canonical URL and a separate owner bearer key:

```bash
docker compose stop
docker compose run --rm cloudbrowser configure-a2a
docker compose up -d
```

Native equivalent: `python -m cloudbrowser configure-a2a`. Enter an HTTPS base URL without a trailing
endpoint path (or explicit loopback HTTP for a local test). Enter a private bearer key of at least
32 characters using hidden terminal input. `CLOUDBROWSER_A2A_API_KEY` can override the stored key.
Incoming A2A is off until a key is configured; do not share the dashboard password as an A2A key.
Use the TLS/SSH deployment guidance in `DEPLOYMENT.md`. This is one trusted owner principal, not
a public multi-tenant service. A caller with this key can queue work and incur configured API costs.

| Endpoint / operation | Support |
| --- | --- |
| `GET /.well-known/agent-card.json` | Public discovery when external A2A is configured; no credentials/instructions in the card |
| `POST /a2a/rpc` | Orchestrator JSON-RPC endpoint; bearer authentication required |
| `GET /a2a/agents/{id}/.well-known/agent-card.json` | Dynamic specialist discovery |
| `POST /a2a/agents/{id}/rpc` | Scoped writer/browser/editor endpoint; reviewer tasks are accessed via orchestrator review tools |
| `GET /a2a/artifacts/{id}` | Authenticated result file download |
| `SendMessage` | Blocking by default; `configuration.returnImmediately=true` returns a submitted task |
| `GetTask`, `ListTasks`, `CancelTask` | Durable task state, filtered/paginated listing and cancellation |
| Streaming / subscriptions / push notifications | Not advertised; unsupported operations return protocol errors |
| REST binding / gRPC / 0.3 compatibility | Not exposed in this version |

Clients must send **`A2A-Version: 1.0`** and **`Authorization: Bearer <private owner key>`**.
RPC payloads are bounded to 256 KiB and accept text only. No remote file URL is fetched from an
incoming message. Upload media through the authenticated dashboard or Telegram first.
Client-generated `messageId` values deduplicate new tasks. Continue non-terminal tasks with the
same `taskId`; after terminal completion/failure/cancellation start a new task.

A direct specialist endpoint reports that specialist's output, with `workflowReviewed=false`.
The calling orchestrator remains responsible for reviewing the whole goal. Orchestrator completion
sets that flag true only after the final workflow audit passes.

## Call registered remote agents

Configure `a2a_peers` in private server configuration, for example:

```json
{
  "a2a_peers": [
    {
      "id": "render-server",
      "card_url": "https://render.example.com/.well-known/agent-card.json",
      "api_key": "<private peer key entered on the server>"
    }
  ]
}
```

The model can choose a registered peer but cannot create an arbitrary destination or read its key.
Public endpoints require HTTPS/public web access; explicit loopback/host-gateway HTTP endpoints
are permitted for admin-configured local agents. Discovery rejects oversized cards, redirects and
RPC endpoints on a different origin, so credentials are not forwarded to a card-selected third party.
Remote returned artifact URLs remain untrusted references; they are not downloaded/executed automatically.
Both approve and auto modes require an exact owner decision for remote submission in version 0.3.

Remote sends are persisted before submission and never automatically retried after uncertain network
failure. Polling a known remote task is read-only. Repeating the same peer/task text in the same
parent job returns its existing record instead of triggering the external job again.

Version 0.3 also records uncertain submissions in the action ledger. The owner must inspect peer
history and resolve that ledger entry; resolution does not automatically resend a message or
change the peer's durable submission record. A deliberate new request may require a new parent
job. Incoming A2A contexts do not inherit the active owner's project brief or conversation history.
See `DECISIONS.md` for model routing, output budgets, and recovery commands.

## Evidence and limitations

Tests use the actual official SDK client/transport against the ASGI server, plus bounded specialist
model stubs and real FFmpeg output. This proves the tested protocol and orchestration paths, not the
quality of a particular live model or completion of Google Flow/CapCut account workflows.

Official references:
- https://a2a-protocol.org/v1.0.0/specification/
- https://github.com/a2aproject/a2a-python
- https://a2aproject.github.io/a2a-python/docs/migrations/v1_0/
