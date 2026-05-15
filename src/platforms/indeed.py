"""
Indeed — read-only scraper.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from .base import BasePlatform
from ..utils.browser import random_delay, jd_jitter
from ..types import Job

logger = logging.getLogger(__name__)

INDEED_BASE = "https://www.indeed.com"
INDEED_IN_BASE = "https://in.indeed.com"


class IndeedPlatform(BasePlatform):
    name = "indeed"

    def _base_url(self) -> str:
        try:
            country = (self.config.personal.country or "").lower()
        except Exception:
            country = ""
        return INDEED_IN_BASE if "india" in country else INDEED_BASE

    async def login(self, page) -> None:
        creds = self.config.get_platform_credentials("indeed")
        email = creds["email"]
        password = creds["password"]
        if not password:
            raise ValueError("INDEED_PASSWORD env var not set.")

        base = self._base_url()
        logger.info("Logging in to Indeed as %s", email)
        await page.goto(f"{base}/account/login", wait_until="domcontentloaded")
        await random_delay(1500, 2500)

        try:
            await page.wait_for_selector(
                'input[type="email"], input[name="__email"], input#login-email-input',
                timeout=15000,
            )
        except Exception:
            logger.warning("Indeed login page slow to render — skipping login.")
            return

        await page.fill(
            'input[type="email"], input[name="__email"], input#login-email-input', email
        )
        await random_delay(500, 1000)
        cont = await page.query_selector('button[type="submit"]')
        if cont:
            await cont.click()
        await random_delay(2000, 3500)

        pass_el = await page.query_selector(
            'input[type="password"], input[name="__password"], input#login-password-input'
        )
        if pass_el:
            await pass_el.fill(password)
            await random_delay(500, 1000)
            submit = await page.query_selector('button[type="submit"]')
            if submit:
                await submit.click()
        else:
            logger.warning("Indeed sent magic-link — finish in browser within 120s.")

        try:
            await page.wait_for_url(
                lambda url: "/account/login" not in url and "/auth" not in url,
                timeout=120000,
            )
        except Exception:
            pass

        if not await self.is_logged_in(page):
            logger.warning("Indeed login state unclear — continuing as guest.")

    async def is_logged_in(self, page) -> bool:
        # Indeed permits anonymous scraping; treat un-logged-in as fine.
        return True

    async def collect_jobs(self, page, filters: dict) -> list[Job]:
        keywords: list[str] = filters.get("keywords") or self.config.search.get("keywords", [])
        locations: list[str] = filters.get("locations") or self.config.search.get("locations", [])
        limit: int = filters.get("limit") or self.config.search.get("max_per_run", 20)
        since_hours: Optional[int] = filters.get("since_hours")

        cards: list[Job] = []
        seen: set[str] = set()

        for keyword in keywords[:3]:
            for location in locations[:2]:
                found = await self._search_one_query(page, keyword, location, since_hours)
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
        logger.info("Indeed: %d listings, fetching full JDs", len(cards))
        for job in cards:
            try:
                await self._fetch_full_jd(page, job)
            except Exception as exc:
                logger.debug("Indeed JD fetch failed for %s: %s", job, exc)
            await jd_jitter()
        return cards

    async def _search_one_query(self, page, keyword: str, location: str, since_hours: Optional[int]) -> list[Job]:
        jobs: list[Job] = []
        base = self._base_url()
        fromage = ""
        if since_hours:
            # Indeed uses fromage=1/3/7/14
            days = max(1, since_hours // 24)
            fromage = f"&fromage={days}"
        url = (
            f"{base}/jobs?q={keyword.replace(' ', '+')}"
            f"&l={location.replace(' ', '+')}"
            f"&sort=date{fromage}"
        )

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await random_delay(2000, 3500)
        except Exception as exc:
            logger.error("Indeed search load failed: %s", exc)
            return jobs

        if "challenges/" in page.url or "captcha" in page.url.lower():
            logger.warning("Indeed served a captcha — skipping query.")
            return jobs

        for _ in range(4):
            await page.evaluate("window.scrollBy(0, 700)")
            await random_delay(500, 900)

        cards = await page.query_selector_all(
            '[data-testid="job-card"], .job_seen_beacon, .resultContent, .tapItem'
        )
        for card in cards:
            try:
                job = await self._parse_card(card, base)
                if job:
                    jobs.append(job)
            except Exception as exc:
                logger.debug("Indeed card parse error: %s", exc)
        return jobs

    async def _parse_card(self, card, base: str) -> Optional[Job]:
        title_el = await card.query_selector(
            'h2.jobTitle a, a.jcs-JobTitle, [data-testid="job-title"] a, h2 a'
        )
        if not title_el:
            return None
        title = (await title_el.inner_text()).strip()
        href = await title_el.get_attribute("href") or ""
        if href.startswith("/"):
            href = f"{base}{href}"

        jk = await title_el.get_attribute("data-jk") or ""
        if not jk:
            m = re.search(r"jk=([a-z0-9]+)", href)
            jk = m.group(1) if m else re.sub(r"[^a-z0-9]", "", title.lower())[:24]

        company_el = await card.query_selector(
            '[data-testid="company-name"], .companyName, span.companyName'
        )
        company = (await company_el.inner_text()).strip() if company_el else "Unknown"

        location_el = await card.query_selector(
            '[data-testid="text-location"], .companyLocation, .location'
        )
        location = (await location_el.inner_text()).strip() if location_el else ""

        salary_el = await card.query_selector(
            '[data-testid*="salary"], .salary-snippet, [class*="salary"]'
        )
        salary = (await salary_el.inner_text()).strip() if salary_el else None

        return Job(
            id=f"indeed_{jk}",
            platform="indeed",
            title=title,
            company=company,
            location=location,
            url=href,
            salary_text=salary,
        )

    async def _fetch_full_jd(self, page, job: Job) -> None:
        await page.goto(job.url, wait_until="domcontentloaded", timeout=25000)
        await random_delay(1500, 2500)

        desc_el = await page.query_selector(
            "#jobDescriptionText, .jobsearch-jobDescriptionText, [data-testid*='jobDescription']"
        )
        if desc_el:
            job.jd_text = (await desc_el.inner_text()).strip()

        try:
            sal_el = await page.query_selector("[id*='salaryInfo'], [class*='salary']")
            if sal_el and not job.salary_text:
                job.salary_text = (await sal_el.inner_text()).strip()
        except Exception:
            pass

        try:
            posted_el = await page.query_selector("[class*='jobsearch-JobMetadataFooter'], [class*='posted']")
            if posted_el:
                job.posted_at = (await posted_el.inner_text()).strip()
        except Exception:
            pass
