"""
Naukri — read-only scraper.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from .base import BasePlatform
from ..utils.browser import random_delay, jd_jitter
from ..types import Job

logger = logging.getLogger(__name__)

NAUKRI_BASE = "https://www.naukri.com"


class NaukriPlatform(BasePlatform):
    name = "naukri"

    async def login(self, page) -> None:
        creds = self.config.get_platform_credentials("naukri")
        email = creds["email"]
        password = creds["password"]
        if not password:
            raise ValueError("NAUKRI_PASSWORD env var not set.")

        logger.info("Logging in to Naukri as %s", email)
        await page.goto(f"{NAUKRI_BASE}/nlogin/login", wait_until="domcontentloaded")
        await random_delay(1500, 2500)

        await page.wait_for_selector('input[placeholder*="Email"], input[name="email"]', timeout=15000)
        await page.fill('input[placeholder*="Email"], input[name="email"]', email)
        await page.fill('input[type="password"]', password)
        await random_delay(500, 1000)
        await page.click('button[type="submit"], .loginButton')
        await random_delay(3000, 5000)

        if not await self.is_logged_in(page):
            raise RuntimeError("Naukri login failed.")
        logger.info("Naukri login successful.")

    async def is_logged_in(self, page) -> bool:
        try:
            await page.wait_for_selector(
                '.nI-gNb-log-reg, [class*="naukri-header-user"], .nI-gNb-drawer',
                timeout=5000,
            )
            return True
        except Exception:
            return "nlogin" not in page.url

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
        logger.info("Naukri: %d listings, fetching full JDs", len(cards))
        for job in cards:
            try:
                await self._fetch_full_jd(page, job)
            except Exception as exc:
                logger.debug("Naukri JD fetch failed for %s: %s", job, exc)
            await jd_jitter()
        return cards

    async def _search_one_query(self, page, keyword: str, location: str) -> list[Job]:
        jobs: list[Job] = []
        keyword_slug = keyword.lower().replace(" ", "-")
        location_slug = (location.split(",")[0] if "," in location else location).strip().lower().replace(" ", "-")
        url = f"{NAUKRI_BASE}/{keyword_slug}-jobs-in-{location_slug}?experience=0-2"

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await random_delay(1500, 2500)
        except Exception as exc:
            logger.error("Naukri search failed: %s", exc)
            return jobs

        for _ in range(4):
            await page.evaluate("window.scrollBy(0, 800)")
            await random_delay(500, 900)

        cards = await page.query_selector_all(".jobTuple, .cust-job-tuple, article.jobTuple")
        for card in cards:
            try:
                job = await self._parse_card(card)
                if job:
                    jobs.append(job)
            except Exception as exc:
                logger.debug("Naukri card parse error: %s", exc)
        return jobs

    async def _parse_card(self, card) -> Optional[Job]:
        title_el = await card.query_selector("a.title, .desig, [class*='title']")
        title = (await title_el.inner_text()).strip() if title_el else ""
        if not title:
            return None
        href = await title_el.get_attribute("href") if title_el else ""

        company_el = await card.query_selector(".comp-name, [class*='comp-name'], a.subTitle")
        company = (await company_el.inner_text()).strip() if company_el else "Unknown"

        location_el = await card.query_selector(".locWdth, [class*='loc'], .location")
        location = (await location_el.inner_text()).strip() if location_el else ""

        salary_el = await card.query_selector(".salary, [class*='salary']")
        salary = (await salary_el.inner_text()).strip() if salary_el else None

        m = re.search(r"-(\d+)\.htm", href or "")
        jid = m.group(1) if m else re.sub(r"[^a-z0-9]", "", title.lower())[:24]

        return Job(
            id=f"naukri_{jid}",
            platform="naukri",
            title=title,
            company=company,
            location=location,
            url=href or f"{NAUKRI_BASE}/job-listings-{title.replace(' ', '-').lower()}",
            salary_text=salary,
        )

    async def _fetch_full_jd(self, page, job: Job) -> None:
        await page.goto(job.url, wait_until="domcontentloaded", timeout=25000)
        await random_delay(1500, 2500)

        desc_el = await page.query_selector(".jd-desc, [class*='job-desc'], .dang-inner-html")
        if desc_el:
            job.jd_text = (await desc_el.inner_text()).strip()

        try:
            sal_el = await page.query_selector("[class*='salary']")
            if sal_el and not job.salary_text:
                job.salary_text = (await sal_el.inner_text()).strip()
        except Exception:
            pass

        try:
            posted_el = await page.query_selector("[class*='posted'], [class*='post-date']")
            if posted_el:
                job.posted_at = (await posted_el.inner_text()).strip()
        except Exception:
            pass
