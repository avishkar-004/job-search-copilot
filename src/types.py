"""
Shared dataclasses for the Job Search Copilot.

The Job dataclass is the canonical representation of a scraped job posting
that flows from a platform scraper -> dedup -> AI scorer -> report generator.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional


@dataclass
class Job:
    """A single scraped job posting from any platform."""

    id: str                          # platform-prefixed unique id, e.g. "linkedin_1234567"
    platform: str
    title: str
    company: str
    location: str
    url: str
    posted_at: Optional[str] = None      # ISO date or platform-supplied string
    salary_text: Optional[str] = None    # raw salary text as shown on page
    applicants_text: Optional[str] = None  # e.g. "Over 100 applicants"
    jd_text: str = ""                    # full job description
    scraped_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    # Optional structured fields populated by AI / dedup steps. Not required.
    required_years_exp: Optional[str] = None
    key_skills: list[str] = field(default_factory=list)

    # Cross-platform deduplication key (filled by dedup module).
    dedup_key: Optional[str] = None

    # ------------------------------------------------------------------
    # Hash / dedup helpers
    # ------------------------------------------------------------------

    def job_hash(self) -> str:
        """Stable hash for cross-run identity (used by tracker + AI cache)."""
        basis = f"{self.platform}|{self.company.strip().lower()}|{_normalize_title(self.title)}|{self.url}"
        return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    def is_blacklisted(self, config) -> bool:
        """Return True if company or title contains a blacklisted keyword."""
        blacklist_companies = (config.search.get("blacklist_companies") or []) if hasattr(config, "search") else []
        blacklist_keywords = (config.search.get("blacklist_keywords") or []) if hasattr(config, "search") else []

        title_lower = self.title.lower()
        company_lower = self.company.lower()

        for kw in blacklist_keywords:
            if str(kw).lower() in title_lower:
                return True
        for co in blacklist_companies:
            if str(co).lower() in company_lower:
                return True
        return False

    def to_dict(self) -> dict:
        return asdict(self)

    def __repr__(self) -> str:
        return f"Job({self.platform}|{self.company}|{self.title[:40]})"


def _normalize_title(title: str) -> str:
    """Lowercase + strip non-alphanumerics for stable hashing/dedup."""
    t = title.lower()
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return " ".join(t.split())
