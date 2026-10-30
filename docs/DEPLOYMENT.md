# Deployment and operation

## Network and persistence

Compose publishes the dashboard only on `127.0.0.1:8000`. Telegram long polling needs outbound HTTPS
to `api.telegram.org`; AI needs the configured API endpoint. Browser destinations and their public
CDNs must be reachable. Initial image/package installation also needs registry/package access.

The named `cloudbrowser_data` volume holds `config.json`, `state.sqlite3`, `browser-profile/`
and `artifacts/`. Configuration is mode 0600 and its directory is 0700. Secrets are stored in this
private server volume, not encrypted with a key-management service. Protect disk access and backups.
Use `docker compose stop` before a consistent backup. `docker compose down` preserves the volume;
deleting the volume loses configuration, sessions, job history and media.

File-size limits are enforced on upload/registration; browser downloads are checked when saved.
Place the volume on a disk with an appropriate quota and remove obsolete results as needed.
There is no automatic retention deletion or distributed/multi-user scheduler in this version.

## HTTPS dashboard on a domain

Point a domain at the server and put a TLS reverse proxy on the host in front of
`127.0.0.1:8000`. Keep the app port bound to loopback. Example host Caddy configuration:

```caddyfile
browser.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

Set the matching public origin when starting Compose; this also enables Secure session cookies:

```bash
export CLOUDBROWSER_PUBLIC_ORIGIN=https://browser.example.com
docker compose up -d
```

The same environment setting must be present on future `docker compose` invocations or be configured
through the service manager. With Secure cookies, use the HTTPS domain for dashboard login.
The app validates Origin against this explicit origin rather than trusting arbitrary forwarded headers.
Configure appropriate request-size/time limits in the proxy for your media uploads.

## Runtime secret overrides

Native/server-managed launches support these environment overrides:

| Name | Purpose |
| --- | --- |
| `CLOUDBROWSER_DATA_DIR` | Private configuration/state directory |
| `CLOUDBROWSER_AI_API_KEY` | API key from a server secret manager |
| `CLOUDBROWSER_TELEGRAM_BOT_TOKEN` | Bot token from a server secret manager |
| `CLOUDBROWSER_BIND_HOST` | Listener override; Docker sets `0.0.0.0` internally |
| `CLOUDBROWSER_PUBLIC_ORIGIN` | HTTPS origin; enables Secure cookies |

The first-run wizard remains the default. Secrets are never returned by dashboard state endpoints.
Compose does not forward arbitrary host secrets; wire explicit overrides through your deployment
secret manager if using them. Do not put credentials in git, browser URLs or shell command history.

## Browser host requirements

The image runs as `pwuser`; Chromium sandboxing remains enabled. Compose drops Linux capabilities
and uses Playwright's adapted seccomp profile for user namespaces. The host must support
unprivileged user namespaces under its kernel/AppArmor policy. Test the actual host:

```bash
docker compose run --rm --entrypoint python cloudbrowser /app/scripts/smoke_browser.py
```

If sandbox launch fails, inspect the host policy or use a compatible dedicated VM. The service does
not silently fall back to an unsandboxed browser. Development tests may disable the sandbox only
in their isolated test configuration. Keep the Playwright Python pin, installed browser version
and Docker image tag aligned when upgrading.

Some identity providers refuse automated Chromium. No configuration guarantees Google login.
You can use an explicitly installed supported browser channel (`browser_channel` in private config)
and manual account login, subject to the provider's policies. Do not expose CDP or reuse a personal
desktop browser profile. Headless mode is available but may affect provider login behavior.

## Health, failures and restarts

- `/healthz`: HTTP process liveness; no auth or secrets.
- `/readyz`: Telegram polling freshness (or dashboard-only mode). It does not verify AI quota,
  a logged-in Google account, CapCut access, browser render capability, or provider uptime.
- Dashboard Telegram status reports startup/polling errors. A startup token/webhook error requires
  reconfiguration/restart; transient polling network failures retry with a bounded delay.
- `doctor` checks local configuration/dependencies. `doctor --live` checks the bot and AI API,
  making one small AI request. It does not validate end-to-end video generation.
- Native deployment can adapt `deploy/cloudbrowser.service`. Create an unprivileged service user,
  install the venv under `/opt/Cloudbrowser`, and preconfigure `/var/lib/cloudbrowser` as that user.
  Adjust filesystem paths for your installation. Use one worker.

After a restart, review any interrupted browser task in the dashboard and the provider's history,
then `/resume` it with clear instructions. A prior click may already have spent credits or started
a render. Automated recovery preserves evidence and avoids replaying saved mutations.
