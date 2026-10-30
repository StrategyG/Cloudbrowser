# Access and data boundaries

Cloudbrowser is a single-owner application for a dedicated server. Telegram commands require both
the configured numeric sender ID and the same private-chat ID. Groups, channels, forwarded bot
identities and other senders cannot dispatch work or approve actions.

The dashboard uses a PBKDF2 password hash, expiring signed HttpOnly/SameSite session cookies,
server-side logout revocation, Origin checks and CSRF tokens. Five failed login attempts per client
within five minutes trigger throttling. Use SSH forwarding or HTTPS for remote access. There is
no public CDP, VNC, terminal or arbitrary filesystem API.

The model sees website content and potentially sensitive screenshots. In vision mode screenshots
are sent to the chosen model API. Telegram receives requested screenshots, result files and
notifications. Page text, prompts, model replies and tool results are retained in the private
SQLite job history. Avoid opening unrelated private information in the shared agent browser.
Known configured secrets are redacted from persisted model history and notifications. This is
not a general-purpose DLP system. Manual dashboard keystrokes bypass AI history and are not logged
as input text; the target website still receives whatever the owner types.

Model tools are explicitly enumerated and validated. Approval mode gates every AI click, fill,
selection, keypress, coordinate click, drag and upload. In 0.3, auto mode also gates clicks, uploads,
keypresses, opaque canvas actions and remote delegation. Only fill/select may be preauthorized in
owner-controlled terminal configuration; these can still autosave or change data on a website.
The model cannot modify the approval policy or reconcile uncertain effects. Action records contain
a hash of the exact arguments, not entered text. A dispatch interrupted after it starts becomes
unknown and blocks further external mutations until the owner checks the website/peer and resolves
the record. An applied record means the tool returned, not that a business goal or render succeeded.
Prompts remain a fallible layer against malicious page instructions.

Browser requests reject private/loopback/link-local IPs, credential-bearing URLs and non-public web
ports. Top-level navigation requires configured domains. Public subresources are allowed so websites
can load CDNs; service workers are disabled and WebSocket destinations are checked. DNS resolution
checks and Playwright routing are application guardrails, **not a network sandbox**: DNS rebinding,
browser-internal networking and a compromised browser require an OS/network egress firewall.
Use a dedicated host/container without cloud metadata access or access to unrelated private services.
The local AI endpoint is a separately trusted admin configuration and is intentionally allowed to
use loopback/host-gateway HTTP; it is not a navigable browser destination.

Chromium runs with its sandbox enabled by default; Docker uses an unprivileged user and seccomp.
These controls reduce exposure but do not make arbitrary web content safe. Keep browser, image and
dependencies updated together. Uploaded/downloaded files are untrusted: FFmpeg uses fixed demuxers
and disabled network protocols, and uploaded scripts are never executed. Apply disk quotas and keep
media tooling patched. A configured file size limit is not a total disk quota.

Before sharing diagnostics, remove configuration, browser profiles, SQLite history, media and any
tokens from URLs. Report a vulnerability privately to the repository owner; do not attach secrets
to a public issue. No formal security audit or production certification is claimed.

## A2A boundaries

Agent definitions select fixed capability profiles; they cannot add arbitrary tools, change server
credentials or delegate recursively. External A2A uses a separate owner bearer key and is disabled
until configured. It is not a multi-tenant authorization system. Cards omit instructions and keys.
RPC calls are bounded, authenticated and versioned; client message IDs deduplicate new tasks.
Remote destinations must be admin configured, and discovery cannot change credential origins.
Unknown remote send outcomes are retained without automatic mutation replay.

Read-only model reviews remain fallible. Deterministic checks establish file integrity and declared
media properties; they do not prove narrative correctness, prevent every prompt injection, or
certify generated content quality. Review the original request as well as step completion.

Project briefs and prior exchanges are scoped by project; incoming A2A contexts get reserved
project identifiers rather than inheriting the active owner project. This is context separation,
not tenant isolation: one owner still controls the shared browser, artifact catalog, and bearer key.
Model output reservations survive restart. They limit output tokens and calls, not total money,
input/image-token charges, or website credits. Exact provider billing remains external.
