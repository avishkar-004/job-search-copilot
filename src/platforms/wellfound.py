"""
Wellfound (AngelList) — read-only scraper.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from .base import BasePlatform
from ..utils.browser import random_delay, jd_jitter
from ..types import Job

logger = logging.getLogger(__name__)

WELLFOUND_BASE = "https://wellfound.com"


class WellfoundPlatform(BasePlatform):
    name = "wellfound"

    async def login(self, page) -> None:
        creds = self.config.get_platform_credentials("wellfound")
        email = creds["email"]
        password = creds["password"]
        if not password:
            raise ValueError("WELLFOUND_PASSWORD env var not set.")

        logger.info("Logging in to Wellfound as %s", email)
        await page.goto(f"{WELLFOUND_BASE}/login", wait_until="domcontentloaded")
        await random_delay(1500, 2500)
        await page.wait_for_selector('input[name="email"], input[type="email"]', timeout=15000)
        await page.fill('input[name="email"], input[type="email"]', email)
        await page.fill('input[type="password"]', password)
        await random_delay(500, 1000)
        await page.click('button[type="submit"], input[type="submit"]')
        await random_delay(3000, 5000)

        if "challenge" in page.url or "verify" in page.url:
            logger.warning("Wellfound CAPTCHA — complete in browser (waiting 60s).")
            try:
                await page.wait_for_url(
                    lambda url: "/jobs" in url or "/talent" in url or "/u/" in url, timeout=60000,
                )
            except Exception:
                raise RuntimeError("Wellfound CAPTCHA not resolved in time.")

        if not await self.is_logged_in(page):
            raise RuntimeError("Wellfound login failed.")
        logger.info("Wellfound login successful.")

    async def is_logged_in(self, page) -> bool:
        try:
            await page.wait_for_selector(
                '[data-test="UserMenu"], .user-avatar, [class*="NavUser"], a[href*="/u/"]',
                timeout=5000,
            )
            return True
        except Exception:
            return "login" not in page.url

    async def collect_jobs(self, page, filters: dict) -> list[Job]:
        keywords: list[str] = filters.get("keywords") or self.config.search.get("keywords", [])
        locations: list[str] = filters.get("locations") or self.config.search.get("locations", [])
        limit: int = filters.get("limit") or self.config.search.get("max_per_run", 20)

        cards: list[Job] = []
        seen: set[str] = set()
        for keyword in keywords[:3]:
            for location in locations[:2]:
                found = await self._search_one_query(page, keyword, location)
                for job in found:
                    if job.id in seen:
                        continue
                    seen.add(job.id)
                    cards.append(job)
                if len(cards) >= limit:
                    break
            if len(cards) >= limit:
                break

        cards = cards[:limit]
        logger.info("Wellfound: %d listings, fetching full JDs", len(cards))
        for job in cards:
            try:
                await self._fetch_full_jd(page, job)
            except Exception as exc:
                logger.debug("Wellfound JD fetch failed for %s: %s", job, exc)
            await jd_jitter()
        return cards

    async def _search_one_query(self, page, keyword: str, location: str) -> list[Job]:
        jobs: list[Job] = []
        kw_slug = keyword.lower().replace(" ", "-")
        loc_slug = (location.split(",")[0] if "," in location else location).strip().lower().replace(" ", "-")
        if loc_slug in ("remote", "remote india"):
            url = f"{WELLFOUND_BASE}/role/{kw_slug}?remote=true"
        else:
            url = f"{WELLFOUND_BASE}/role/{kw_slug}?location={loc_slug}"

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await random_delay(2500, 4000)
        except Exception as exc:
            logger.error("Wellfound search failed: %s", exc)
            return jobs

        for _ in range(5):
            await page.evaluate("window.scrollBy(0, 800)")
            await random_delay(600, 1000)

        cards = await page.query_selector_all(
            "[class*='JobListingCard'], [data-test*='JobListing'], .styles_component__job"
        )
        if not cards:
            cards = await page.query_selector_all("div[class*='job'] a[href*='/jobs/']")

        for card in cards:
            try:
                job = await self._parse_card(card)
                if job:
                    jobs.append(job)
            except Exception as exc:
                logger.debug("Wellfound card parse error: %s", exc)
        return jobs

    async def _parse_card(self, card) -> Optional[Job]:
        title_el = await card.query_selector(
            "h2, h3, [class*='title']:not([class*='company']), [data-test='JobTitle']"
        )
        title = (await title_el.inner_text()).strip() if title_el else ""
        if not title:
            return None

        company_el = await card.query_selector(
            "[class*='startup-name'], [class*='company'], [data-test='StartupName']"
        )
        company = (await company_el.inner_text()).strip() if company_el else "Unknown"

        location_el = await card.query_selector("[class*='location'], [data-test='Location']")
        location = (await location_el.inner_text()).strip() if location_el else ""

        link_el = await card.query_selector("a[href*='/jobs/']") or await card.query_selector("a")
        href = await link_el.get_attribute("href") if link_el else ""
        full_url = f"{WELLFOUND_BASE}{href}" if href and not href.startswith("http") else href

        salary_el = await card.query_selector("[class*='salary'], [class*='compensation']")
        salary = (await salary_el.inner_text()).strip() if salary_el else None

        m = re.search(r"/jobs/(\d+)", full_url or "")
        jid = m.group(1) if m else re.sub(r"[^a-z0-9]", "", f"{company}{title}".lower())[:24]

        return Job(
            id=f"wellfound_{jid}",
            platform="wellfound",
            title=title,
            company=company,
            location=location,
            url=full_url or f"{WELLFOUND_BASE}/jobs",
            salary_text=salary,
        )

    async def _fetch_full_jd(self, page, job: Job) -> None:
        await page.goto(job.url, wait_until="domcontentloaded", timeout=25000)
        await random_delay(1500, 2500)
        desc_el = await page.query_selector(
            "[class*='description'], [class*='JobDescription'], .styles_description"
        )
        if desc_el:
            job.jd_text = (await desc_el.inner_text()).strip()
