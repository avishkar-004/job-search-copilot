"""
Cutshort — public scraping path (no login).

Cutshort is an Indian-focused startup hiring site. Public job listings can be
read without an account at https://cutshort.io/jobs.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from .base import BasePlatform
from ..utils.browser import random_delay, jd_jitter
from ..types import Job

logger = logging.getLogger(__name__)

CUTSHORT_BASE = "https://cutshort.io"


class CutshortPlatform(BasePlatform):
    name = "cutshort"

    async def login(self, page) -> None:
        # Public scrape — no login.
        return None

    async def is_logged_in(self, page) -> bool:
        return True

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
        logger.info("Cutshort: %d listings, fetching full JDs", len(cards))
        for job in cards:
            try:
                await self._fetch_full_jd(page, job)
            except Exception as exc:
                logger.debug("Cutshort JD fetch failed for %s: %s", job, exc)
            await jd_jitter()
        return cards

    async def _search_one_query(self, page, keyword: str, location: str) -> list[Job]:
        jobs: list[Job] = []
        kw = keyword.replace(" ", "%20")
        loc = (location.split(",")[0] if "," in location else location).strip()
        loc_param = f"&location={loc.replace(' ', '%20')}" if loc and loc.lower() != "india" else ""
        url = f"{CUTSHORT_BASE}/jobs?query={kw}{loc_param}"

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await random_delay(2000, 3500)
        except Exception as exc:
            logger.error("Cutshort search failed: %s", exc)
            return jobs

        for _ in range(5):
            await page.evaluate("window.scrollBy(0, 800)")
            await random_delay(400, 800)

        cards = await page.query_selector_all(
            "a[href*='/jobs/'], div[class*='job-card'], li[class*='job']"
        )
        for card in cards:
            try:
                job = await self._parse_card(card)
                if job:
                    jobs.append(job)
            except Exception as exc:
                logger.debug("Cutshort card parse error: %s", exc)
        return jobs

    async def _parse_card(self, card) -> Optional[Job]:
        try:
            href = await card.get_attribute("href")
            if not href:
                link = await card.query_selector("a[href*='/jobs/']")
                href = await link.get_attribute("href") if link else None
            if not href:
                return None
            full_url = href if href.startswith("http") else f"{CUTSHORT_BASE}{href}"
            if "/jobs/" not in full_url:
                return None

            title_el = await card.query_selector("h2, h3, [class*='title']")
            title = (await title_el.inner_text()).strip() if title_el else ""
            if not title:
                return None

            company_el = await card.query_selector("[class*='company'], [class*='employer']")
            company = (await company_el.inner_text()).strip() if company_el else "Unknown"

            location_el = await card.query_selector("[class*='location']")
            location = (await location_el.inner_text()).strip() if location_el else ""

            salary_el = await card.query_selector("[class*='salary'], [class*='ctc']")
            salary = (await salary_el.inner_text()).strip() if salary_el else None

            m = re.search(r"/jobs/([a-z0-9\-]+)", full_url)
            jid = m.group(1) if m else re.sub(r"[^a-z0-9]", "", full_url.lower())[-24:]

            return Job(
                id=f"cutshort_{jid}",
                platform="cutshort",
                title=title,
                company=company,
                location=location,
                url=full_url,
                salary_text=salary,
            )
        except Exception as exc:
            logger.debug("Cutshort parse error: %s", exc)
            return None

    async def _fetch_full_jd(self, page, job: Job) -> None:
        await page.goto(job.url, wait_until="domcontentloaded", timeout=25000)
        await random_delay(1500, 2500)
        desc_el = await page.query_selector(
            "main, article, [class*='description'], [class*='job-detail']"
        )
        if desc_el:
            job.jd_text = (await desc_el.inner_text()).strip()
