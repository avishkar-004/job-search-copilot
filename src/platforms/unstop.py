"""
Unstop — read-only scraper.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from .base import BasePlatform
from ..utils.browser import random_delay, jd_jitter
from ..types import Job

logger = logging.getLogger(__name__)

UNSTOP_BASE = "https://unstop.com"


class UnstopPlatform(BasePlatform):
    name = "unstop"

    async def login(self, page) -> None:
        creds = self.config.get_platform_credentials("unstop")
        email = creds["email"]
        password = creds["password"]
        if not password:
            raise ValueError("UNSTOP_PASSWORD env var not set.")

        logger.info("Logging in to Unstop as %s", email)
        await page.goto(f"{UNSTOP_BASE}/login", wait_until="domcontentloaded")
        await random_delay(1500, 2500)
        await page.wait_for_selector('input[type="email"], input[placeholder*="email" i]', timeout=15000)
        await page.fill('input[type="email"], input[placeholder*="email" i]', email)
        await page.fill('input[type="password"]', password)
        await random_delay(500, 1000)
        await page.click('button[type="submit"], .login-btn')
        await random_delay(3000, 5000)
        if not await self.is_logged_in(page):
            raise RuntimeError("Unstop login failed.")
        logger.info("Unstop login successful.")

    async def is_logged_in(self, page) -> bool:
        try:
            await page.wait_for_selector(
                ".user-avatar, .profile-photo, [class*='user-profile'], nav .user-name",
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
        for keyword in keywords[:2]:
            found = await self._search_one_query(page, keyword, locations)
            for job in found:
                if job.id in seen:
                    continue
                seen.add(job.id)
                cards.append(job)
            if len(cards) >= limit:
                break

        cards = cards[:limit]
        logger.info("Unstop: %d listings, fetching full JDs", len(cards))
        for job in cards:
            try:
                await self._fetch_full_jd(page, job)
            except Exception as exc:
                logger.debug("Unstop JD fetch failed for %s: %s", job, exc)
            await jd_jitter()
        return cards

    async def _search_one_query(self, page, keyword: str, locations: list[str]) -> list[Job]:
        jobs: list[Job] = []
        location_param = locations[0].lower() if locations else ""
        url = f"{UNSTOP_BASE}/jobs?search={keyword.replace(' ', '%20')}"
        if location_param and "remote" not in location_param:
            url += f"&location={location_param.replace(' ', '%20')}"
        url += "&level=entry-level"

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await random_delay(2000, 3500)
        except Exception as exc:
            logger.error("Unstop search failed: %s", exc)
            return jobs

        for _ in range(5):
            await page.evaluate("window.scrollBy(0, 800)")
            await random_delay(500, 900)

        cards = await page.query_selector_all(
            ".opportunity-card, .job-card, [class*='opportunityItem'], app-opportunity-card"
        )
        for card in cards:
            try:
                job = await self._parse_card(card)
                if job:
                    jobs.append(job)
            except Exception as exc:
                logger.debug("Unstop card parse error: %s", exc)
        return jobs

    async def _parse_card(self, card) -> Optional[Job]:
        title_el = await card.query_selector(
            ".opportunity-title, h3, [class*='title']:not([class*='company'])"
        )
        title = (await title_el.inner_text()).strip() if title_el else ""
        if not title:
            return None

        company_el = await card.query_selector(".company-name, [class*='org-name'], [class*='company']")
        company = (await company_el.inner_text()).strip() if company_el else "Unknown"

        location_el = await card.query_selector("[class*='location'], .loc")
        location = (await location_el.inner_text()).strip() if location_el else ""

        link_el = await card.query_selector("a")
        href = await link_el.get_attribute("href") if link_el else ""
        full_url = f"{UNSTOP_BASE}{href}" if href and not href.startswith("http") else href

        m = re.search(r"/(\d+)/?", full_url or "")
        jid = m.group(1) if m else re.sub(r"[^a-z0-9]", "", title.lower())[:24]

        return Job(
            id=f"unstop_{jid}",
            platform="unstop",
            title=title,
            company=company,
            location=location,
            url=full_url or f"{UNSTOP_BASE}/jobs",
        )

    async def _fetch_full_jd(self, page, job: Job) -> None:
        await page.goto(job.url, wait_until="domcontentloaded", timeout=25000)
        await random_delay(1500, 2500)
        desc_el = await page.query_selector(".about-section, [class*='description'], .job-description")
        if desc_el:
            job.jd_text = (await desc_el.inner_text()).strip()
