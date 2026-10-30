# Decision workflow 0.3

Cloudbrowser keeps the model-created A2A team from 0.2 and strengthens the runtime that controls
its decisions. This release is a tested development package; live-model/browser benchmarks are
still required before comparing its reliability with ChatGPT Pro.

## Runtime sequence

1. Accept an owner task and retain its original goal and project.
2. The orchestrator defines measurable steps and dependencies before delegation; the contract freezes.
3. Before each model call, restore the goal, project brief, workflow progress and remaining limits.
4. Before an external mutation, apply server policy and record the exact request hash.
5. Execute once after any required owner approval. On ambiguous failure, pause for reconciliation.
6. Validate real artifacts, then ask a separate reviewer to compare them with the goal.
7. Recheck file hashes before dependencies and completion; run the final original-goal audit.
8. Report completed, incomplete, waiting_user or failed according to the observed evidence.

The final semantic reviewer is a model and can make mistakes. A nonempty script is not evidence
that a requested video was rendered. Workflow requirements, independent review and deterministic
media/file checks work together; no universal semantic correctness claim is made.

## Actions and recovery

Mode auto no longer disables every gate. Clicks, keyboard actions, uploads, canvas drags and remote
A2A submissions require an exact owner decision. Passive navigation/observation and local file/media
preparation can continue automatically. A server owner may preauthorize fill/select in the private
configuration; form actions can autosave, so this capability is disabled by default.

Action records transition through pending, approved, applying and applied. Rejected/canceled actions
did not proceed through this dispatcher. Applying actions interrupted by timeout, cancellation or
restart become unknown. The stored argument hash binds the request without retaining typed text.
Applied means the tool returned; artifact verification still determines job success.

Unknown effects block new external mutations across the shared browser/peer dispatcher. Local
preparation can continue. Inspect the website's generation/export history or the remote peer, then:

```text
/resolve_action ACTION_ID applied
/resolve_action ACTION_ID not_applied
/resume JOB_ID The existing clip is present; download it instead of generating again.
```

Use only the outcome established by inspection. Resolution is one-time and owner-only through
Telegram or the authenticated, CSRF-protected dashboard. The model has no resolution tool. An old
remote submission record is not deleted or automatically retried by this command.

## Project context

```text
/project arusia
/brief Five friends: Kio, Lumi, Arka, Mayor, RUX. Keep scripts and shot lists.
```

Project names are lowercase slugs, at most 40 characters. Briefs contain up to 8000 characters.
Use /brief with no argument to inspect it, or /brief - to clear it. Only completed exchanges from
the same project are used as prior conversation. The current goal and workflow are restored on
every role call even when older tool history is trimmed. A2A contexts use reserved a2a- project IDs.
This does not create separate browser profiles, artifact catalogs, or user permissions.

## Model routing and limits

Stop the server before editing its private configuration. Existing configurations gain these defaults:

```json
{
  "ai_max_output_tokens": 2048,
  "ai_context_chars": 65000,
  "max_model_calls": 60,
  "max_job_output_tokens": 122880,
  "max_repeated_tool_errors": 3,
  "auto_browser_actions": [],
  "role_models": {}
}
```

The owner may map orchestrator, writer, browser, editor or reviewer to a model name available at
the configured endpoint. Empty routing uses ai_model for every role. Endpoint, credentials and
tool scopes stay server-controlled. A role that receives screenshots requires a vision-capable
model when ai_vision is enabled. Models still need compatible function/tool calling.

All roles share job call/output budgets. Before each request, reserve ai_max_output_tokens; settle
against valid provider completion_tokens afterward. When usage is absent or a request is interrupted,
retain the full reservation. Prompt-token usage is recorded when reported, but is not part of this
output budget. This is not a currency, total-token, image-token, or website-credit spending cap.
Timeouts and HTTP retries can also have provider-side billing effects outside these logical counts.

ai_context_chars limits serialized textual messages and tool schemas. Image data are excluded from
this character count; image tokens still depend on the selected model. Required state too large
for this limit fails before any API request or call-budget charge. Configure the limit for the
model's actual context capacity; a character limit is not a tokenizer.

Model replies cut off by a length/content-filter finish reason are rejected. Three identical
consecutive tool failures yield for owner input by default. Resume clears that failure counter,
while model budgets, action uncertainty and frozen workflow requirements persist.

## Evidence

File review records include SHA-256 and size. Missing or changed files invalidate a passed review.
Declared video checks include dimensions, FPS, duration, audio-stream presence, size limits and
full FFmpeg decoding. Audio presence does not prove intelligible or correct speech.
Browser expectations may use url_origin for an exact scheme/host/port match; legacy url_contains
is a substring assertion and is weaker. Vision reviewers receive the current viewport when enabled.

See VALIDATION.md for actual checks and outstanding browser/account acceptance work.
