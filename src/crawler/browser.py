"""Playwright browser context manager."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

logger = logging.getLogger(__name__)

# Reasonable desktop user-agent to avoid bot detection
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


@asynccontextmanager
async def managed_browser() -> AsyncGenerator[BrowserContext, None]:
    async with async_playwright() as p:
        browser: Browser = await p.chromium.launch(headless=True)
        context: BrowserContext = await browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 900},
            java_script_enabled=True,
        )
        try:
            yield context
        finally:
            await context.close()
            await browser.close()


async def fetch_page(context: BrowserContext, url: str) -> Page:
    """Navigate to URL and wait for JS to render. Returns the Page object."""
    page = await context.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        # Wait for network to settle (JS apps finish their initial data fetches)
        try:
            await page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            pass  # Timeout is acceptable — proceed with whatever rendered

        # Try to expand any collapsed TOC nodes to expose child links
        try:
            collapsed = page.locator("[aria-expanded='false']")
            count = await collapsed.count()
            for i in range(min(count, 20)):
                try:
                    await collapsed.nth(i).click(timeout=2_000)
                    await page.wait_for_timeout(300)
                except Exception:
                    pass
        except Exception:
            pass

        return page
    except Exception:
        await page.close()
        raise
