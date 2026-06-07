"""
Y Combinator Work at a Startup — public scraper (no login).

We hit https://www.ycombinator.com/jobs and filter client-side by
keyword + location.  The page is server-rendered enough that we can
parse cards with Playwright directly.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from .base import BasePlatform
from ..utils.browser import random_delay, jd_jitter
from ..types import Job

logger = logging.getLogger(__name__)

YC_BASE = "https://www.ycombinator.com"


class YCombinatorPlatform(BasePlatform):
    name = "ycombinator"

    async def login(self, page) -> None:
        # Public site — no login required.
        return None

    async def is_logged_in(self, page) -> bool:
        return True

    async def collect_jobs(self, page, filters: dict) -> list[Job]:
        keywords: list[str] = filters.get("keywords") or self.config.search.get("keywords", [])
        locations: list[str] = filters.get("locations") or self.config.search.get("locations", [])
        limit: int = filters.get("limit") or self.config.search.get("max_per_run", 20)

        # YC's /jobs page is a single listing index; we filter client-side.
        url = f"{YC_BASE}/jobs"
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await random_delay(2000, 3500)
        except Exception as exc:
            logger.error("YC search load failed: %s", exc)
            return []

        # Lazy-load: scroll a bunch
        for _ in range(8):
            await page.evaluate("window.scrollBy(0, 900)")
            await random_delay(400, 800)

        cards = await page.query_selector_all("a[href*='/jobs/'], div[class*='JobListing'], li[class*='job']")

        wanted_kws = {kw.lower() for kw in keywords}
        wanted_locs = {loc.lower().split(",")[0].strip() for loc in locations} if locations else set()

        results: list[Job] = []
        seen_urls: set[str] = set()

        for card in cards:
            try:
                job = await self._parse_card(card)
                if not job:
                    continue
                if job.url in seen_urls:
                    continue
                seen_urls.add(job.url)

                title_lc = job.title.lower()
                loc_lc = (job.location or "").lower()

                if wanted_kws and not any(kw in title_lc for kw in wanted_kws):
                    continue
                if wanted_locs:
                    # Allow remote / any India match
                    if not (
                        "remote" in loc_lc
                        or any(loc in loc_lc for loc in wanted_locs)
                        or "india" in loc_lc
                    ):
                        continue
                results.append(job)
                if len(results) >= limit:
                    break
            except Exception as exc:
                logger.debug("YC card parse error: %s", exc)

        logger.info("YC: %d listings after filter, fetching full JDs", len(results))
        for job in results:
            try:
                await self._fetch_full_jd(page, job)
            except Exception as exc:
                logger.debug("YC JD fetch failed for %s: %s", job, exc)
            await jd_jitter()
        return results

    async def _parse_card(self, card) -> Optional[Job]:
        try:
            href = await card.get_attribute("href")
            if not href:
                link = await card.query_selector("a[href*='/jobs/']")
                href = await link.get_attribute("href") if link else None
            if not href or "/jobs/" not in href:
                return None
            full_url = href if href.startswith("http") else f"{YC_BASE}{href}"

            title_el = await card.query_selector("h3, h2, [class*='title']")
            title = (await title_el.inner_text()).strip() if title_el else ""
            if not title:
                title = (await card.inner_text()).strip().split("\n")[0]

            company_el = await card.query_selector("[class*='company'], [class*='startup']")
            company = (await company_el.inner_text()).strip() if company_el else "Unknown"

            location_el = await card.query_selector("[class*='location']")
            location = (await location_el.inner_text()).strip() if location_el else ""

            m = re.search(r"/jobs/(\d+)", full_url)
            jid = m.group(1) if m else re.sub(r"[^a-z0-9]", "", full_url.lower())[-20:]

            return Job(
                id=f"yc_{jid}",
                platform="ycombinator",
                title=title,
                company=company,
                location=location,
                url=full_url,
            )
        except Exception as exc:
            logger.debug("YC parse error: %s", exc)
            return None

    async def _fetch_full_jd(self, page, job: Job) -> None:
        await page.goto(job.url, wait_until="domcontentloaded", timeout=25000)
        await random_delay(1500, 2500)
        desc_el = await page.query_selector(
            "main, article, [class*='description'], [class*='Description']"
        )
        if desc_el:
            job.jd_text = (await desc_el.inner_text()).strip()
