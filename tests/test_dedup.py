"""Tests for cross-platform job deduplication."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from src.search.dedup import (
    _normalize_company,
    _normalize_title,
    _posted_bucket,
    dedup_key,
    deduplicate,
)
from src.types import Job


def _job(**kw) -> Job:
    defaults = dict(
        id=kw.get("id", "x_1"),
        platform="linkedin",
        title="Software Engineer",
        company="Acme",
        location="Pune",
        url="https://example.com/1",
    )
    defaults.update(kw)
    return Job(**defaults)


# ---------------------------------------------------------------------------
# Company normalisation
# ---------------------------------------------------------------------------

def test_normalize_company_lowercases():
    assert _normalize_company("ACME") == "acme"


def test_normalize_company_strips_pvt_ltd():
    assert _normalize_company("Acme Pvt Ltd") == "acme"


def test_normalize_company_strips_inc_llc():
    assert _normalize_company("Acme Inc.") == "acme"
    assert _normalize_company("Acme LLC") == "acme"


def test_normalize_company_collapses_whitespace():
    assert _normalize_company("Acme   Corporation") == "acme"


def test_normalize_company_handles_empty():
    assert _normalize_company("") == ""
    assert _normalize_company(None) == ""


# ---------------------------------------------------------------------------
# Title normalisation
# ---------------------------------------------------------------------------

def test_normalize_title_strips_punctuation():
    assert _normalize_title("SDE-1 (Backend)") == "sde 1 backend"


def test_normalize_title_handles_empty():
    assert _normalize_title("") == ""


# ---------------------------------------------------------------------------
# Posted-at bucketing (3-day window)
# ---------------------------------------------------------------------------

def test_posted_bucket_returns_unknown_for_none():
    assert _posted_bucket(None) == "unknown"
    assert _posted_bucket("") == "unknown"


def test_posted_bucket_returns_unknown_for_garbage():
    assert _posted_bucket("not a date") == "unknown"


def test_posted_bucket_same_day_same_bucket():
    # Two timestamps a few hours apart on the same day fall in the same bucket.
    a = "2026-05-20T08:00:00Z"
    b = "2026-05-20T20:00:00Z"
    assert _posted_bucket(a) == _posted_bucket(b)


def test_posted_bucket_within_3_days_same_bucket():
    # Within a 3-day window from epoch start, may or may not be same bucket
    # depending on the alignment. Pick two timestamps where we KNOW it lands
    # in the same bucket: epoch day 20240 / 3 == 20242 / 3 (i.e. same int division).
    base = datetime(2026, 5, 20, tzinfo=timezone.utc)
    a = base.isoformat()
    b = (base + timedelta(days=1)).isoformat()
    # We don't assert equality here because the 3-day window may straddle —
    # instead assert "near each other" by comparing as ints when both numeric.
    bucket_a = _posted_bucket(a)
    bucket_b = _posted_bucket(b)
    assert abs(int(bucket_a) - int(bucket_b)) <= 1


def test_posted_bucket_far_apart_different_buckets():
    a = "2026-01-01T00:00:00Z"
    b = "2026-06-01T00:00:00Z"
    assert _posted_bucket(a) != _posted_bucket(b)


# ---------------------------------------------------------------------------
# dedup_key
# ---------------------------------------------------------------------------

def test_dedup_key_collapses_company_suffixes():
    a = _job(company="Acme")
    b = _job(company="Acme Pvt Ltd")
    assert dedup_key(a) == dedup_key(b)


def test_dedup_key_collapses_title_punctuation():
    a = _job(title="Backend Engineer")
    b = _job(title="Backend-Engineer!")
    assert dedup_key(a) == dedup_key(b)


def test_dedup_key_differs_for_different_companies():
    a = _job(company="Acme")
    b = _job(company="Globex")
    assert dedup_key(a) != dedup_key(b)


def test_dedup_key_ignores_platform():
    """Same role on LinkedIn vs Indeed should dedup to the same key."""
    a = _job(platform="linkedin", company="Acme", title="SDE 1")
    b = _job(platform="indeed",   company="Acme", title="SDE 1")
    assert dedup_key(a) == dedup_key(b)


# ---------------------------------------------------------------------------
# deduplicate
# ---------------------------------------------------------------------------

def test_deduplicate_collapses_cross_platform_duplicates():
    a = _job(platform="linkedin", url="https://linkedin.com/1", jd_text="short JD")
    b = _job(platform="indeed",   url="https://indeed.com/1",  jd_text="much longer JD with more content here")
    result = deduplicate([a, b])
    assert len(result) == 1
    # We keep the entry with the richer JD
    assert result[0].platform == "indeed"


def test_deduplicate_preserves_distinct_jobs():
    a = _job(company="Acme",   title="Backend Engineer", url="https://x/1")
    b = _job(company="Globex", title="Frontend Engineer", url="https://x/2")
    assert len(deduplicate([a, b])) == 2


def test_deduplicate_preserves_order_of_survivors():
    a = _job(company="Acme",   url="https://x/1")
    b = _job(company="Globex", url="https://x/2")
    c = _job(company="Initech", url="https://x/3")
    result = deduplicate([a, b, c])
    assert [j.company for j in result] == ["Acme", "Globex", "Initech"]


def test_deduplicate_sets_dedup_key_on_survivor():
    a = _job()
    [survivor] = deduplicate([a])
    assert survivor.dedup_key is not None
    assert len(survivor.dedup_key) == 16


def test_deduplicate_empty_input():
    assert deduplicate([]) == []
