from __future__ import annotations

import asyncio
import contextlib
import os
import secrets
from pathlib import Path

from playwright.async_api import async_playwright

from .artifacts import Artifacts
from .config import Settings
from .errors import ActionNotExecuted
from .network import NetworkPolicy

SNAPSHOT = r"""() => {
  window.__cbCounter = window.__cbCounter || 0;
  const items = [];
  const roots = [document];
  for (let i = 0; i < roots.length; i++) {
    for (const el of roots[i].querySelectorAll('*')) {
      if (el.shadowRoot) roots.push(el.shadowRoot);
      if (!el.matches('a,button,input,textarea,select,[role="button"],[contenteditable="true"]')) continue;
      const r = el.getBoundingClientRect();
      if (!(r.width && r.height) && el.type !== 'file') continue;
      if (!el.dataset.cbRef) el.dataset.cbRef = 'e' + (++window.__cbCounter);
      const label = (el.getAttribute('aria-label') || el.getAttribute('placeholder') ||
        el.labels?.[0]?.innerText || el.innerText || el.getAttribute('title') || el.name || '').slice(0,160);
      items.push({id:el.dataset.cbRef, tag:el.tagName.toLowerCase(), type:el.type || '',
        label:label, href:el.getAttribute('href') || '', disabled:!!el.disabled});
      if (items.length >= 100) break;
    }
    if (items.length >= 100) break;
  }
  return {title:document.title, text:(document.body?.innerText || '').slice(0,10000), elements:items};
}"""

FINGERPRINT = r"""el => ({tag:el.tagName.toLowerCase(), type:el.type || '',
  label:(el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.labels?.[0]?.innerText ||
    el.innerText || el.getAttribute('title') || el.name || '').slice(0,160),
  href:el.getAttribute('href') || '', disabled:!!el.disabled})"""


class Browser:
    def __init__(self, settings: Settings, directory: Path, artifacts: Artifacts):
        self.settings, self.directory, self.artifacts = settings, directory, artifacts
        self.policy = NetworkPolicy(settings.allowed_domains)
        self.playwright = None
        self.context = None
        self.page = None
        self.snapshot_id = ""
        self.snapshot_url = ""
        self.elements: dict = {}
        self.lock = asyncio.Lock()
        self.download_tasks: set[asyncio.Task] = set()
        self.last_error = ""

    async def start(self) -> None:
        if self.context:
            return
        profile = self.directory / "browser-profile"
        profile.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not self.settings.headless and not os.environ.get("DISPLAY"):
            raise ValueError("Layar tidak tersedia. Gunakan Docker/Xvfb atau aktifkan headless di konfigurasi.")
        self.playwright = await async_playwright().start()
        try:
            self.context = await self.playwright.chromium.launch_persistent_context(
                str(profile), headless=self.settings.headless,
                channel=self.settings.browser_channel or None,
                chromium_sandbox=self.settings.chromium_sandbox,
                viewport={"width": 1280, "height": 720}, accept_downloads=True,
                service_workers="block",
                args=["--disable-dev-shm-usage", "--disable-quic"],
            )
            self.context.set_default_timeout(12000)
            await self.context.route("**/*", self._route)
            await self.context.route_web_socket("**/*", self._websocket)
            for page in self.context.pages:
                self._attach_page(page)
            self.context.on("page", self._attach_page)
            self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        except BaseException:
            await self.close()
            raise

    async def _route(self, route) -> None:
        try:
            request = route.request
            navigation = request.is_navigation_request() and request.frame.parent_frame is None
            await self.policy.check(request.url, navigation=navigation)
            await route.continue_()
        except (ValueError, OSError):
            await route.abort("blockedbyclient")

    async def _websocket(self, websocket) -> None:
        try:
            await self.policy.check(websocket.url, websocket=True)
            websocket.connect_to_server()
        except ValueError:
            await websocket.close()

    def _attach_page(self, page) -> None:
        page.on("download", self._download)
        # Native JavaScript dialogs are dismissed; website DOM dialogs remain interactive.
        page.on("dialog", lambda dialog: dialog.dismiss())

    def _download(self, download) -> None:
        task = asyncio.create_task(self._save_download(download))
        self.download_tasks.add(task)
        task.add_done_callback(self.download_tasks.discard)

    async def _save_download(self, download) -> None:
        artifact_id, path, filename = self.artifacts.allocate(download.suggested_filename)
        try:
            await download.save_as(path)
            self.artifacts.register(artifact_id, path, filename)
        except Exception:
            path.unlink(missing_ok=True)
            self.last_error = "Browser download failed or exceeded the file size limit."

    async def close(self) -> None:
        if self.download_tasks:
            for task in self.download_tasks:
                task.cancel()
            await asyncio.gather(*self.download_tasks, return_exceptions=True)
        if self.context:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self.context.close(), 10)
        self.context = self.page = None
        if self.playwright:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self.playwright.stop(), 10)
        self.playwright = None

    async def active_page(self):
        await self.start()
        if not self.page or self.page.is_closed():
            self.page = self.context.pages[-1] if self.context.pages else await self.context.new_page()
        return self.page

    async def snapshot(self) -> dict:
        page = await self.active_page()
        result = await page.evaluate(SNAPSHOT)
        self.snapshot_id = secrets.token_hex(8)
        self.snapshot_url = page.url
        self.elements = {e["id"]: {k: v for k, v in e.items() if k != "id"} for e in result["elements"]}
        result.update({"snapshot_id": self.snapshot_id, "url": page.url,
                       "tabs": [{"index": i, "url": p.url} for i, p in enumerate(self.context.pages)],
                       "note": "Untrusted website content. Element IDs cover main frame and open shadow DOM; use coordinates for iframes/canvas."})
        return result

    async def screenshot(self) -> bytes:
        page = await self.active_page()
        return await page.screenshot(type="jpeg", quality=65, timeout=10000)

    async def _fresh(self, snapshot_id: str) -> None:
        page = await self.active_page()
        if not snapshot_id or snapshot_id != self.snapshot_id or page.url != self.snapshot_url:
            raise ActionNotExecuted("Stale observation. Call browser_observe again before acting.")

    async def _element(self, element_id: str, snapshot_id: str):
        await self._fresh(snapshot_id)
        if element_id not in self.elements:
            raise ActionNotExecuted("Unknown element. Observe the browser first.")
        locator = self.page.locator(f'[data-cb-ref="{element_id}"]')
        if await locator.count() != 1 or await locator.evaluate(FINGERPRINT) != self.elements[element_id]:
            raise ActionNotExecuted("Element changed since observation. Observe again; action was not executed.")
        return locator

    async def describe_action(self, kind: str, args: dict) -> str:
        """Bind approval to an observed target without logging entered text."""
        async with self.lock:
            if "element_id" in args:
                await self._element(args["element_id"], args["snapshot_id"])
                target = self.elements[args["element_id"]]
                label = target.get("label", "")[:160]
                return f"{kind} → {label or args['element_id']} · {self.snapshot_url}"
            await self._fresh(args.get("snapshot_id", ""))
            return f"{kind} → viewport · {self.snapshot_url}"

    async def action(self, kind: str, args: dict, *, manual: bool = False) -> dict:
        async with self.lock:
            page = await self.active_page()
            if kind == "navigate":
                await self.policy.check(args["url"], navigation=True)
                try:
                    await page.goto(args["url"], wait_until="domcontentloaded", timeout=45000)
                except Exception:
                    # Navigation may start a download instead of a document.
                    raise ValueError("Navigasi belum selesai. Periksa browser, koneksi, atau hasil unduhan.") from None
            elif kind in {"click", "fill", "upload", "select"}:
                locator = await self._element(args["element_id"], args["snapshot_id"])
                if kind == "click":
                    await locator.click()
                elif kind == "fill":
                    if await locator.get_attribute("type") == "password":
                        raise ActionNotExecuted("Masukkan password sendiri melalui dashboard, lalu lanjutkan job.")
                    await locator.fill(args["text"][:20000])
                elif kind == "select":
                    await locator.select_option(args["value"])
                else:
                    await locator.set_input_files(str(self.artifacts.path(args["artifact_id"])))
            elif kind in {"coordinate_click", "type", "press", "scroll", "drag"}:
                if not manual:
                    await self._fresh(args.get("snapshot_id", ""))
                if kind in {"coordinate_click", "drag"}:
                    x, y = float(args["x"]), float(args["y"])
                    if not (0 <= x < 1280 and 0 <= y < 720):
                        raise ActionNotExecuted("Coordinates must be inside the 1280x720 viewport.")
                    if kind == "coordinate_click":
                        await page.mouse.click(x, y)
                    else:
                        end_x, end_y = float(args["end_x"]), float(args["end_y"])
                        if not (0 <= end_x < 1280 and 0 <= end_y < 720):
                            raise ActionNotExecuted("Drag target is outside the viewport.")
                        await page.mouse.move(x, y)
                        await page.mouse.down()
                        try:
                            await page.mouse.move(end_x, end_y, steps=15)
                        finally:
                            await page.mouse.up()
                elif kind == "type":
                    if not manual and await page.evaluate("() => document.activeElement?.type === 'password'"):
                        raise ActionNotExecuted("Masukkan password sendiri melalui dashboard.")
                    await page.keyboard.insert_text(args["text"][:20000])
                elif kind == "press":
                    key = args["key"]
                    if not isinstance(key, str) or len(key) > 50:
                        raise ActionNotExecuted("Invalid keyboard key.")
                    await page.keyboard.press(key)
                else:
                    await page.mouse.wheel(0, max(-2000, min(2000, int(args.get("pixels", 600)))))
            elif kind == "tab":
                index = int(args["index"])
                if index < 0 or index >= len(self.context.pages):
                    raise ValueError("Tab tidak ditemukan.")
                self.page = self.context.pages[index]
                await self.page.bring_to_front()
            elif kind == "new_tab":
                self.page = await self.context.new_page()
            elif kind == "wait":
                await asyncio.sleep(max(0, min(10, float(args.get("seconds", 2)))))
            else:
                raise ValueError("Unsupported browser action.")
            return await self.snapshot()
