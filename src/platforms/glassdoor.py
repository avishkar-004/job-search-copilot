"""
Glassdoor — read-only scraper.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from .base import BasePlatform
from ..utils.browser import random_delay, jd_jitter
from ..types import Job

logger = logging.getLogger(__name__)

GD_BASE = "https://www.glassdoor.com"
GD_IN_BASE = "https://www.glassdoor.co.in"


class GlassdoorPlatform(BasePlatform):
    name = "glassdoor"

    def _base_url(self) -> str:
        try:
            country = (self.config.personal.country or "").lower()
        except Exception:
            country = ""
        return GD_IN_BASE if "india" in country else GD_BASE

    async def login(self, page) -> None:
        creds = self.config.get_platform_credentials("glassdoor")
        if not creds.get("password"):
            creds = self.config.get_platform_credentials("indeed")
        email = creds["email"]
        password = creds["password"]
        if not password:
            raise ValueError("GLASSDOOR_PASSWORD (or INDEED_PASSWORD) env var not set.")

        base = self._base_url()
        logger.info("Logging in to Glassdoor as %s", email)
        await page.goto(f"{base}/profile/login_input.htm", wait_until="domcontentloaded")
        await random_delay(1500, 2500)

        try:
            await page.wait_for_selector(
                'input[type="email"], input#inlineUserEmail, input[name="username"]', timeout=15000,
            )
        except Exception:
            logger.warning("Glassdoor login slow to render.")
            return

        await page.fill(
            'input[type="email"], input#inlineUserEmail, input[name="username"]', email,
        )
        await random_delay(500, 1000)
        cont = await page.query_selector('button[type="submit"], button[data-test="email-form-button"]')
        if cont:
            await cont.click()
            await random_delay(1800, 3000)

        pass_el = await page.query_selector(
            'input[type="password"], input#inlineUserPassword, input[name="password"]'
        )
        if pass_el:
            await pass_el.fill(password)
            await random_delay(500, 1000)
            submit = await page.query_selector('button[type="submit"]')
            if submit:
                await submit.click()
        else:
            logger.warning("Glassdoor sent verification — finish in browser (120s).")

        try:
            await page.wait_for_url(
                lambda url: "login_input" not in url and "/profile/login" not in url,
                timeout=120000,
            )
        except Exception:
            pass

        if not await self.is_logged_in(page):
            logger.warning("Glassdoor login state unclear — continuing as guest.")

    async def is_logged_in(self, page) -> bool:
        # Glassdoor often allows anonymous browsing.
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
        logger.info("Glassdoor: %d listings, fetching full JDs", len(cards))
        for job in cards:
            try:
                await self._fetch_full_jd(page, job)
            except Exception as exc:
                logger.debug("Glassdoor JD fetch failed for %s: %s", job, exc)
            await jd_jitter()
        return cards

    async def _search_one_query(self, page, keyword: str, location: str) -> list[Job]:
        jobs: list[Job] = []
        base = self._base_url()
        url = (
            f"{base}/Job/jobs.htm"
            f"?sc.keyword={keyword.replace(' ', '+')}"
            f"&locT=C&locKeyword={location.replace(' ', '+')}"
        )

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await random_delay(2000, 3500)
        except Exception as exc:
            logger.error("Glassdoor search failed: %s", exc)
            return jobs

        try:
            close_btn = await page.query_selector(
                'button[aria-label*="Close"], button[data-test="close-modal"], .modal_closeIcon'
            )
            if close_btn:
                await close_btn.click()
                await random_delay(400, 800)
        except Exception:
            pass

        for _ in range(4):
            await page.evaluate("window.scrollBy(0, 700)")
            await random_delay(500, 900)

        cards = await page.query_selector_all(
            '[data-test="job-listing"], li.react-job-listing, .JobsList_jobListItem__JBBUV, '
            'div[data-brandviews*="JOB_SEARCH"]'
        )
        for card in cards:
            try:
                job = await self._parse_card(card, base)
                if job:
                    jobs.append(job)
            except Exception as exc:
                logger.debug("Glassdoor card parse error: %s", exc)
        return jobs

    async def _parse_card(self, card, base: str) -> Optional[Job]:
        title_el = await card.query_selector(
            'a[data-test="job-link"], a.jobLink, .JobCard_seoLink__WdqHZ'
        )
        if not title_el:
            return None
        title = (await title_el.inner_text()).strip()
        href = await title_el.get_attribute("href") or ""
        if href.startswith("/"):
            href = f"{base}{href}"

        jl = await card.get_attribute("data-id") or ""
        if not jl:
            m = re.search(r"jobListingId=(\d+)", href)
            jl = m.group(1) if m else re.sub(r"[^a-z0-9]", "", title.lower())[:24]

        company_el = await card.query_selector(
            '[data-test="employer-name"], .EmployerProfile_compactEmployerName__9MGcV'
        )
        company = (await company_el.inner_text()).strip() if company_el else "Unknown"

        location_el = await card.query_selector(
            '[data-test="emp-location"], .JobCard_location__N_iYE'
        )
        location = (await location_el.inner_text()).strip() if location_el else ""

        salary_el = await card.query_selector(
            '[data-test="detailSalary"], [class*="salary"], .JobCard_salaryEstimate__QpbTW'
        )
        salary = (await salary_el.inner_text()).strip() if salary_el else None

        return Job(
            id=f"glassdoor_{jl}",
            platform="glassdoor",
            title=title,
            company=company,
            location=location,
            url=href,
            salary_text=salary,
        )

    async def _fetch_full_jd(self, page, job: Job) -> None:
        await page.goto(job.url, wait_until="domcontentloaded", timeout=25000)
        await random_delay(1800, 2800)
        desc_el = await page.query_selector(
            '.JobDetails_jobDescription__uW_fK, [data-test="jobDescription"], .jobDescriptionContent'
        )
        if desc_el:
            job.jd_text = (await desc_el.inner_text()).strip()
