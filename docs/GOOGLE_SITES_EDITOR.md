# Google Sites → Cloudbrowser Studio (secure portal)

**Supported mode:** Google Sites is a navigation/landing page. The **MorphGLB 3D editor remains served from the authenticated Cloudbrowser origin** and is never made public or placed in a cross-origin iframe.

## Owner setup

1. Deploy Cloudbrowser behind an HTTPS reverse proxy with `CLOUDBROWSER_PUBLIC_ORIGIN=https://your-cloudbrowser-domain.example`. Keep container and Studio service ports private, and ensure `/readyz` reports healthy.
2. Open the owner-editable **Google Sites** page on a computer.
3. Use **Insert → Button**, label it **Buka Editor ARUSIA 3D**, and set its link to:

   ```text
   https://your-cloudbrowser-domain.example/?open=studio
   ```

4. Publish Google Sites and test the link in a new browser tab. If the dashboard has no active session, enter the Cloudbrowser dashboard password. After valid authentication, the app redirects to **`/studio#morphglb`**, where the owner can open the MorphGLB editor and upload GLB/PNG to the gated Studio pipeline.
5. If already logged in, the same link opens Studio directly. A bad/expired session still requires login; Google Sites never receives the editor session cookie, artifact data or token.

**Alternative:** Google Sites can also link directly to `https://your-cloudbrowser-domain.example/studio#morphglb`, but an expired session then produces HTTP 401. The `?open=studio` portal entry is intended to preserve the existing login workflow.

## Why not an iframe?

The Studio route sends `Content-Security-Policy: frame-ancestors 'none'`, its session cookie is HttpOnly and `SameSite=Strict`, and the raw MorphGLB editor is isolated in an opaque-origin sandbox. These restrictions prevent clickjacking and unauthorized browser-session exposure. Do **not** weaken CSP, add `SameSite=None`, publish `/studio/morphglb` under `/static`, or place credentials in Google Sites to force an iframe to work.

Google Sites itself supports embedded websites and full-page embeds, **only when the target website permits framing**. This deployment intentionally forbids framing of authenticated Cloudbrowser pages. For a brochure/site page, use the native Google Sites button.

## This integration does not grant edit rights to Google Sites

The New Google Sites product has **no supported general-purpose Sites content-write API** (the deprecated Sites Data API applies only to Classic Sites). If the user wants Cloudbrowser AI to edit a Google Sites page, that is a **separate Playwright browser workflow**: owner must log in, authorize specific changes, inspect the preview, and approve publishing. Do not infer website edit permission from this launcher. No unattended Google Sites publishing, OAuth integration or Google Drive asset sync is installed by this change.

## Acceptance checks

- `GET /` is public only as a login shell; no editor content or private artifacts are exposed.
- `GET /studio` and `GET /studio/morphglb` return 401 without a Cloudbrowser owner session.
- `GET /studio` succeeds with a valid session and still responds `frame-ancestors 'none'`.
- `/static/app.js` redirects to a **fixed same-origin** editor path only after successful session validation; it does not accept a caller-controlled redirect URL.
- HTTPS reverse proxy and a publicly reachable Cloudbrowser hostname are deployment prerequisites. This repository change does not itself update any externally hosted Google Sites page; the owner must insert and publish the button.

See [Google Sites Embed Help](https://support.google.com/sites/answer/90569), [Google Sites legacy API scope](https://developers.google.com/workspace/sites), and [Cloudbrowser deployment](DEPLOYMENT.md).
