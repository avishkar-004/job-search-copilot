"""
Abstract base class for all platform scrapers.

The Job Search Copilot is READ-ONLY: each platform implementation must
log in, run a search, optionally open each result for richer JD extraction,
and return a list of Job objects. There is NO apply path.
"""

from abc import ABC, abstractmethod
from typing import Optional

from ..types import Job


class BasePlatform(ABC):
    """
    Abstract base for all platform scrapers.

    Each platform must implement:
      - login(page)        — interactive or cookie-based session bootstrap
      - is_logged_in(page) — True if the current session is authenticated
      - collect_jobs(page, filters) -> list[Job]  — search + scrape JDs
    """

    name: str = "base"

    def __init__(self, config):
        self.config = config

    # ------------------------------------------------------------------
    # Auth lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    async def login(self, page) -> None:
        """Navigate to and complete the login flow. May no-op for public sites."""
        ...

    @abstractmethod
    async def is_logged_in(self, page) -> bool:
        """Return True if the browser session is already authenticated.
        For public-scrape platforms, return True unconditionally."""
        ...

    # ------------------------------------------------------------------
    # Core read-only operation
    # ------------------------------------------------------------------

    @abstractmethod
    async def collect_jobs(self, page, filters: dict) -> list[Job]:
        """
        Search and return a list of Job objects.

        Args:
            page: Playwright page handle
            filters: dict with keys: keywords, locations, limit, since_hours,
                     experience_levels, etc.  Implementations may read whatever
                     keys are relevant; missing keys should fall back to config.

        Implementations should:
          1. Run search(es) using filters["keywords"] x filters["locations"]
          2. Visit each job URL
          3. Scrape full JD text + salary / applicants / posted_at if available
          4. Wait 2-4 s with jitter between jobs (politeness)
          5. Respect filters["limit"] as a per-platform cap
        """
        ...
