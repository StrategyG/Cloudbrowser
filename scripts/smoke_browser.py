"""Verify that the deployment host actually supports sandboxed Chromium."""
import asyncio

from playwright.async_api import async_playwright


async def main():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, chromium_sandbox=True)
        try:
            page = await browser.new_page()
            await page.set_content("<title>Cloudbrowser</title><h1>Ready</h1>")
            assert await page.title() == "Cloudbrowser"
            assert await page.locator("h1").inner_text() == "Ready"
            assert (await page.screenshot()).startswith(b"\x89PNG")
            print("Sandboxed Chromium: PASS")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
