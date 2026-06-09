"""
Cross-platform deduplication.

The same role often appears on LinkedIn + Indeed + the company's careers page.
We collapse such duplicates using a hash of (normalized_company, normalized_title,
posted_within_3_days_bucket) and keep the entry with the richest JD text.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Iterable, Optional

from ..types import Job

logger = logging.getLogger(__name__)

_DEDUP_WINDOW_DAYS = 3


def _normalize_company(name: str) -> str:
    n = (name or "").lower().strip()
    # Strip common suffixes
    n = re.sub(r"\b(pvt|private|ltd|limited|inc|incorporated|llp|llc|corp|corporation|gmbh)\b\.?", "", n)
    n = re.sub(r"[^a-z0-9]+", " ", n)
    return " ".join(n.split())


def _normalize_title(title: str) -> str:
    t = (title or "").lower()
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return " ".join(t.split())


def _parse_posted_at(posted_at: Optional[str]) -> Optional[datetime]:
    if not posted_at:
        return None
    try:
        # Try ISO first
        return datetime.fromisoformat(posted_at.replace("Z", "+00:00"))
    except Exception:
        return None


def _posted_bucket(posted_at: Optional[str]) -> str:
    """Bucket the posted-at into 3-day windows so 'today' and 'yesterday' collapse."""
    dt = _parse_posted_at(posted_at)
    if dt is None:
        return "unknown"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    epoch_days = int(dt.timestamp() // 86400)
    bucket = epoch_days // _DEDUP_WINDOW_DAYS
    return str(bucket)


def dedup_key(job: Job) -> str:
    """Stable cross-platform dedup key."""
    basis = "|".join([
        _normalize_company(job.company),
        _normalize_title(job.title),
        _posted_bucket(job.posted_at),
    ])
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def deduplicate(jobs: Iterable[Job]) -> list[Job]:
    """
    Collapse duplicates by dedup_key. When multiple jobs share a key, keep the
    one with the longest JD text (richest signal). Preserves insertion order
    of the surviving jobs.
    """
    by_key: dict[str, Job] = {}
    order: list[str] = []

    for job in jobs:
        key = dedup_key(job)
        job.dedup_key = key
        if key not in by_key:
            by_key[key] = job
            order.append(key)
            continue

        incumbent = by_key[key]
        if len(job.jd_text or "") > len(incumbent.jd_text or ""):
            logger.debug(
                "dedup: replacing %s (%d chars JD) with %s (%d chars JD)",
                incumbent, len(incumbent.jd_text or ""), job, len(job.jd_text or ""),
            )
            by_key[key] = job

    survivors = [by_key[k] for k in order]
    removed = sum(1 for _ in jobs) - len(survivors) if isinstance(jobs, list) else None
    if removed:
        logger.info("Deduplicated %d -> %d jobs (%d duplicates collapsed)",
                    sum(1 for _ in jobs), len(survivors), removed)
    return survivors
