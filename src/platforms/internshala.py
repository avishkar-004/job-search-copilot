"""
Internshala — read-only scraper.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from .base import BasePlatform
from ..utils.browser import random_delay, jd_jitter
from ..types import Job

logger = logging.getLogger(__name__)

INTERNSHALA_BASE = "https://internshala.com"


class IntershalaPlatform(BasePlatform):
    name = "internshala"

    async def login(self, page) -> None:
        creds = self.config.get_platform_credentials("internshala")
        email = creds["email"]
        password = creds["password"]
        if not password:
            raise ValueError("INTERNSHALA_PASSWORD env var not set.")

        logger.info("Logging in to Internshala as %s", email)
        await page.goto(f"{INTERNSHALA_BASE}/login", wait_until="domcontentloaded")
        await random_delay(1500, 2500)

        await page.wait_for_selector("#modal_email, input[name='email']", timeout=15000)
        await page.fill("#modal_email, input[name='email']", email)
        await page.fill("#modal_password, input[name='password']", password)
        await random_delay(500, 1000)
        await page.click("#modal_login_submit, button[type='submit']")
        await random_delay(3000, 5000)

        if not await self.is_logged_in(page):
            raise RuntimeError("Internshala login failed.")
        logger.info("Internshala login successful.")

    async def is_logged_in(self, page) -> bool:
        try:
            await page.wait_for_selector(
                ".profile-container, #profile, [class*='student-name']", timeout=5000,
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
        logger.info("Internshala: %d listings, fetching full JDs", len(cards))
        for job in cards:
            try:
                await self._fetch_full_jd(page, job)
            except Exception as exc:
                logger.debug("Internshala JD fetch failed for %s: %s", job, exc)
            await jd_jitter()
        return cards

    async def _search_one_query(self, page, keyword: str, location: str) -> list[Job]:
        jobs: list[Job] = []
        kw_slug = keyword.lower().replace(" ", "-")
        loc_slug = (location.split(",")[0] if "," in location else location).strip().lower().replace(" ", "-")
        url = f"{INTERNSHALA_BASE}/jobs/keyword-{kw_slug}/location-{loc_slug}"

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await random_delay(1500, 2500)
        except Exception as exc:
            logger.error("Internshala search failed: %s", exc)
            return jobs

        for _ in range(4):
            await page.evaluate("window.scrollBy(0, 700)")
            await random_delay(500, 900)

        cards = await page.query_selector_all(".job-internship-card, .individual_internship")
        for card in cards:
            try:
                job = await self._parse_card(card)
                if job:
                    jobs.append(job)
            except Exception as exc:
                logger.debug("Internshala card parse error: %s", exc)
        return jobs

    async def _parse_card(self, card) -> Optional[Job]:
        title_el = await card.query_selector(".job-title, .profile, h3")
        title = (await title_el.inner_text()).strip() if title_el else ""
        if not title:
            return None
        link_el = await card.query_selector("a.job-title-href, a.profile, a")
        href = await link_el.get_attribute("href") if link_el else ""
        full_url = f"{INTERNSHALA_BASE}{href}" if href and not href.startswith("http") else href

        company_el = await card.query_selector(".company-name, .company")
        company = (await company_el.inner_text()).strip() if company_el else "Unknown"

        location_el = await card.query_selector(".location-names, .location_link")
        location = (await location_el.inner_text()).strip() if location_el else ""

        salary_el = await card.query_selector(".stipend, [class*='salary'], [class*='ctc']")
        salary = (await salary_el.inner_text()).strip() if salary_el else None

        m = re.search(r"/(\d+)/?$", full_url or "")
        jid = m.group(1) if m else re.sub(r"[^a-z0-9]", "", title.lower())[:24]

        return Job(
            id=f"internshala_{jid}",
            platform="internshala",
            title=title,
            company=company,
            location=location,
            url=full_url or f"{INTERNSHALA_BASE}/jobs",
            salary_text=salary,
        )

    async def _fetch_full_jd(self, page, job: Job) -> None:
        await page.goto(job.url, wait_until="domcontentloaded", timeout=25000)
        await random_delay(1500, 2500)
        desc_el = await page.query_selector(".about-job, [class*='description'], #about_job_section")
        if desc_el:
            job.jd_text = (await desc_el.inner_text()).strip()
