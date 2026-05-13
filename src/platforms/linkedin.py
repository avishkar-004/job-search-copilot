"""
LinkedIn — read-only scraper.

Logs in (if env creds + cookies allow), searches jobs, then opens each
job listing to scrape the full description, salary, applicants, and posted_at.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from .base import BasePlatform
from ..utils.browser import random_delay, jd_jitter
from ..types import Job

logger = logging.getLogger(__name__)

LINKEDIN_BASE = "https://www.linkedin.com"


class LinkedInPlatform(BasePlatform):
    name = "linkedin"

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    async def login(self, page) -> None:
        creds = self.config.get_platform_credentials("linkedin")
        email = creds["email"]
        password = creds["password"]
        if not password:
            raise ValueError("LINKEDIN_PASSWORD env var not set.")

        logger.info("Logging in to LinkedIn as %s", email)
        await page.goto(f"{LINKEDIN_BASE}/login", wait_until="domcontentloaded")
        await random_delay(800, 1500)

        await page.wait_for_selector("#username", timeout=15000)
        await page.fill("#username", email)
        await page.fill("#password", password)
        await random_delay(400, 800)
        await page.click('button[type="submit"]')
        await random_delay(3000, 5000)

        if "/checkpoint" in page.url or "/challenge" in page.url:
            logger.warning("LinkedIn 2FA checkpoint — complete it in the browser (waiting 120s).")
            try:
                await page.wait_for_url(
                    lambda url: "/feed" in url or "/jobs" in url or "/in/" in url,
                    timeout=120000,
                )
            except Exception:
                raise RuntimeError("LinkedIn 2FA not completed in time.")

        if not await self.is_logged_in(page):
            raise RuntimeError("LinkedIn login failed.")
        logger.info("LinkedIn login successful.")

    async def is_logged_in(self, page) -> bool:
        try:
            await page.wait_for_selector(
                'nav[aria-label="Primary"], .global-nav__me, [data-control-name="nav.homepage"]',
                timeout=5000,
            )
            return True
        except Exception:
            return "/login" not in page.url and "/checkpoint" not in page.url

    # ------------------------------------------------------------------
    # Collect
    # ------------------------------------------------------------------

    async def collect_jobs(self, page, filters: dict) -> list[Job]:
        keywords: list[str] = filters.get("keywords") or self.config.search.get("keywords", [])
        locations: list[str] = filters.get("locations") or self.config.search.get("locations", [])
        limit: int = filters.get("limit") or self.config.search.get("max_per_run", 20)
        since_hours: Optional[int] = filters.get("since_hours")

        cards: list[Job] = []
        seen_ids: set[str] = set()

        for keyword in keywords[:3]:
            for location in locations[:2]:
                found = await self._search_one_query(page, keyword, location, since_hours)
                for job in found:
                    if job.id in seen_ids:
                        continue
                    seen_ids.add(job.id)
                    cards.append(job)
                if len(cards) >= limit:
                    break
            if len(cards) >= limit:
                break

        cards = cards[:limit]
        logger.info("LinkedIn: %d listings, fetching full JDs", len(cards))

        # Visit each card for full JD
        enriched: list[Job] = []
        for job in cards:
            try:
                await self._fetch_full_jd(page, job)
            except Exception as exc:
                logger.debug("LinkedIn JD fetch failed for %s: %s", job, exc)
            enriched.append(job)
            await jd_jitter()
        return enriched

    # ------------------------------------------------------------------
    # Search helpers
    # ------------------------------------------------------------------

    async def _search_one_query(self, page, keyword: str, location: str, since_hours: Optional[int]) -> list[Job]:
        # f_TPR=r86400 = past 24h, r604800 = past 7 days
        tpr = ""
        if since_hours:
            tpr = f"&f_TPR=r{since_hours * 3600}"

        url = (
            f"{LINKEDIN_BASE}/jobs/search/?keywords={keyword.replace(' ', '%20')}"
            f"&location={location.replace(' ', '%20')}"
            f"&f_E=1%2C2%2C3&sortBy=DD{tpr}"
        )

        jobs: list[Job] = []
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await random_delay(2000, 3500)
        except Exception as exc:
            logger.error("LinkedIn search load failed: %s", exc)
            return jobs

        for _ in range(5):
            await page.evaluate("window.scrollBy(0, 700)")
            await random_delay(600, 1100)

        cards = await page.query_selector_all(
            ".job-card-container, .jobs-search-results__list-item"
        )
        for card in cards:
            try:
                job = await self._parse_job_card(card)
                if job:
                    jobs.append(job)
            except Exception as exc:
                logger.debug("LinkedIn card parse error: %s", exc)
        return jobs

    async def _parse_job_card(self, card) -> Optional[Job]:
        job_id = await card.get_attribute("data-job-id") or ""
        if not job_id:
            link = await card.query_selector("a[href*='/jobs/view/']")
            if link:
                href = await link.get_attribute("href") or ""
                m = re.search(r"/jobs/view/(\d+)", href)
                job_id = m.group(1) if m else ""
        if not job_id:
            return None

        title_el = await card.query_selector(
            ".job-card-list__title, .job-card-container__link, [class*='job-title']"
        )
        title = (await title_el.inner_text()).strip() if title_el else "Unknown"

        company_el = await card.query_selector(
            ".job-card-container__company-name, .job-card-list__company-name, [class*='company-name']"
        )
        company = (await company_el.inner_text()).strip() if company_el else "Unknown"

        location_el = await card.query_selector(
            ".job-card-container__metadata-item, [class*='location']"
        )
        location = (await location_el.inner_text()).strip() if location_el else ""

        return Job(
            id=f"linkedin_{job_id}",
            platform="linkedin",
            title=title,
            company=company,
            location=location,
            url=f"{LINKEDIN_BASE}/jobs/view/{job_id}/",
        )

    # ------------------------------------------------------------------
    # Full JD scrape
    # ------------------------------------------------------------------

    async def _fetch_full_jd(self, page, job: Job) -> None:
        await page.goto(job.url, wait_until="domcontentloaded", timeout=25000)
        await random_delay(1500, 2500)

        # Try clicking "See more" to expand
        try:
            see_more = await page.query_selector("button.jobs-description__footer-button, .show-more-less-html__button")
            if see_more:
                await see_more.click()
                await random_delay(400, 800)
        except Exception:
            pass

        desc_el = await page.query_selector(
            ".jobs-description-content__text, .jobs-description, [class*='description']"
        )
        if desc_el:
            job.jd_text = (await desc_el.inner_text()).strip()

        # Salary
        try:
            sal_el = await page.query_selector(
                ".job-details-jobs-unified-top-card__job-insight, [class*='salary']"
            )
            if sal_el:
                txt = (await sal_el.inner_text()) or ""
                if any(c in txt for c in ("$", "₹", "Lakh", "LPA")):
                    job.salary_text = txt.strip()
        except Exception:
            pass

        # Applicants
        try:
            apps_el = await page.query_selector(
                "[class*='applicant-count'], [class*='num-applicants']"
            )
            if apps_el:
                job.applicants_text = (await apps_el.inner_text()).strip()
        except Exception:
            pass

        # Posted at
        try:
            posted_el = await page.query_selector("time, [class*='posted']")
            if posted_el:
                dt = await posted_el.get_attribute("datetime")
                job.posted_at = dt or (await posted_el.inner_text()).strip()
        except Exception:
            pass
