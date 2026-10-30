from __future__ import annotations

import os

import pytest

from cloudbrowser.artifacts import Artifacts
from cloudbrowser.browser import Browser
from cloudbrowser.store import Store

pytestmark = [pytest.mark.browser, pytest.mark.skipif(os.environ.get("CLOUDBROWSER_TEST_BROWSER") != "1",
                                                    reason="Set CLOUDBROWSER_TEST_BROWSER=1 with installed Chromium")]


async def test_actual_chromium_observe_fill_click_screenshot_and_stale_guard(settings, tmp_path):
    store = Store(tmp_path)
    browser = Browser(settings, tmp_path, Artifacts(tmp_path, store))
    try:
        await browser.start()
        page = await browser.active_page()
        await page.set_content('<title>Creator test</title><input aria-label="Prompt"><button onclick="document.querySelector(\'output\').textContent=\'done\'">Create</button><output></output>')
        first = await browser.snapshot()
        input_id = next(e["id"] for e in first["elements"] if e["tag"] == "input")
        second = await browser.action("fill", {"snapshot_id": first["snapshot_id"], "element_id": input_id, "text": "Video prompt"})
        button_id = next(e["id"] for e in second["elements"] if e["tag"] == "button")
        with pytest.raises(ValueError, match="Stale"):
            await browser.action("click", {"snapshot_id": first["snapshot_id"], "element_id": button_id})
        third = await browser.action("click", {"snapshot_id": second["snapshot_id"], "element_id": button_id})
        assert await page.locator("output").inner_text() == "done"
        assert (await browser.screenshot()).startswith(b"\xff\xd8")
        await page.locator("button").evaluate("el => el.innerText = 'Purchase'")
        with pytest.raises(ValueError, match="Element changed"):
            await browser.action("click", {"snapshot_id": third["snapshot_id"], "element_id": button_id})
    finally:
        await browser.close()
        store.close()


async def test_password_is_excluded_from_observation_and_manual_entry_required(settings, tmp_path):
    store = Store(tmp_path)
    browser = Browser(settings, tmp_path, Artifacts(tmp_path, store))
    try:
        await browser.start()
        page = await browser.active_page()
        await page.set_content('<input type="password" aria-label="Password" value="private-password">')
        snapshot = await browser.snapshot()
        assert "private-password" not in str(snapshot)
        await page.locator("input").focus()
        with pytest.raises(ValueError, match="dashboard"):
            await browser.action("type", {"snapshot_id": snapshot["snapshot_id"], "text": "no"})
        # Focus does not guarantee an end-position caret across Chromium versions.
        await browser.action("press", {"key": "End"}, manual=True)
        await browser.action("type", {"text": "manual"}, manual=True)
        assert await page.locator("input").input_value() == "private-passwordmanual"
    finally:
        await browser.close()
        store.close()
