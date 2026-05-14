"""
Lightweight Playwright browser bootstrap for the read-only copilot.

We no longer need stealth flags / bezier mouse: we are not submitting forms.
This module just spins up Chromium with a normal user-agent, optional saved
cookies, and a polite delay helper.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from pathlib import Path

logger = logging.getLogger(__name__)

SESSIONS_DIR = Path("logs")

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_VIEWPORT = {"width": 1440, "height": 900}


async def random_delay(min_ms: int = 3000, max_ms: int = 6000) -> None:
    """Async sleep for a uniformly random duration in milliseconds."""
    duration = random.randint(min_ms, max_ms) / 1000.0
    await asyncio.sleep(duration)


async def jd_jitter() -> None:
    """Polite 2-4 second pause between JD page loads."""
    await asyncio.sleep(random.uniform(2.0, 4.0))


async def setup_browser(playwright, platform: str = "", headless: bool = False):
    """
    Launch a plain Chromium browser (no stealth flags) and load any saved cookies
    for the given platform.

    Returns:
        (browser, context, page) tuple.
    """
    browser = await playwright.chromium.launch(headless=headless)

    context = await browser.new_context(
        viewport=_VIEWPORT,
        user_agent=_USER_AGENT,
        locale="en-US",
        timezone_id="Asia/Kolkata",
    )

    if platform:
        session_file = SESSIONS_DIR / f"session_{platform}.json"
        if session_file.exists():
            try:
                with open(session_file, "r", encoding="utf-8") as f:
                    cookies = json.load(f)
                await context.add_cookies(cookies)
                logger.info("Loaded saved session cookies for %s", platform)
            except Exception as exc:
                logger.warning("Could not load session cookies for %s: %s", platform, exc)

    page = await context.new_page()
    return browser, context, page


async def save_session(context, platform: str) -> None:
    """Persist browser cookies so subsequent runs can skip login."""
    try:
        SESSIONS_DIR.mkdir(exist_ok=True)
        cookies = await context.cookies()
        session_file = SESSIONS_DIR / f"session_{platform}.json"
        tmp = session_file.with_suffix(session_file.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cookies, f, indent=2)
        tmp.replace(session_file)
        logger.info("Session cookies saved for %s", platform)
    except Exception as exc:
        logger.warning("Could not save session for %s: %s", platform, exc)
