"""Tests for the Job dataclass — hashing, blacklist filtering, serialisation."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.types import Job, _normalize_title


def _make_job(**overrides) -> Job:
    defaults = dict(
        id="linkedin_42",
        platform="linkedin",
        title="Software Engineer",
        company="Acme Corp",
        location="Bangalore, India",
        url="https://linkedin.com/jobs/42",
    )
    defaults.update(overrides)
    return Job(**defaults)


# ---------------------------------------------------------------------------
# _normalize_title
# ---------------------------------------------------------------------------

def test_normalize_title_lowercases_and_collapses_whitespace():
    assert _normalize_title("Software   ENGINEER") == "software engineer"


def test_normalize_title_strips_punctuation():
    assert _normalize_title("SDE-1 / Backend (Bangalore)") == "sde 1 backend bangalore"


def test_normalize_title_handles_empty():
    assert _normalize_title("") == ""


# ---------------------------------------------------------------------------
# Job.job_hash
# ---------------------------------------------------------------------------

def test_job_hash_is_stable_across_calls():
    j = _make_job()
    assert j.job_hash() == j.job_hash()


def test_job_hash_is_deterministic_for_equal_inputs():
    a = _make_job()
    b = _make_job()
    assert a.job_hash() == b.job_hash()


def test_job_hash_changes_when_url_differs():
    a = _make_job(url="https://linkedin.com/jobs/42")
    b = _make_job(url="https://linkedin.com/jobs/99")
    assert a.job_hash() != b.job_hash()


def test_job_hash_is_case_insensitive_on_company():
    a = _make_job(company="Acme Corp")
    b = _make_job(company="ACME CORP")
    assert a.job_hash() == b.job_hash()


def test_job_hash_treats_title_punctuation_as_noise():
    a = _make_job(title="Software Engineer")
    b = _make_job(title="Software-Engineer!")
    assert a.job_hash() == b.job_hash()


def test_job_hash_changes_when_platform_differs():
    a = _make_job(platform="linkedin")
    b = _make_job(platform="naukri")
    assert a.job_hash() != b.job_hash()


def test_job_hash_is_short_hex():
    h = _make_job().job_hash()
    assert len(h) == 16
    int(h, 16)  # raises if not hex


# ---------------------------------------------------------------------------
# Job.is_blacklisted
# ---------------------------------------------------------------------------

def _config(blacklist_companies=None, blacklist_keywords=None):
    return SimpleNamespace(
        search={
            "blacklist_companies": blacklist_companies or [],
            "blacklist_keywords": blacklist_keywords or [],
        }
    )


def test_is_blacklisted_matches_company_substring():
    job = _make_job(company="Tata Consultancy Services")
    assert job.is_blacklisted(_config(blacklist_companies=["Tata"]))


def test_is_blacklisted_matches_company_case_insensitive():
    job = _make_job(company="Infosys")
    assert job.is_blacklisted(_config(blacklist_companies=["infosys"]))


def test_is_blacklisted_matches_keyword_in_title():
    job = _make_job(title="Senior Software Engineer")
    assert job.is_blacklisted(_config(blacklist_keywords=["Senior"]))


def test_not_blacklisted_when_no_match():
    job = _make_job(title="Software Engineer", company="Stripe")
    assert not job.is_blacklisted(_config(blacklist_companies=["Tata"], blacklist_keywords=["Senior"]))


def test_blacklist_handles_empty_lists():
    assert not _make_job().is_blacklisted(_config())


def test_blacklist_handles_missing_search_attribute():
    """If the caller hands us something without a `search` attr, default to False."""
    cfg = SimpleNamespace()
    assert not _make_job().is_blacklisted(cfg)


# ---------------------------------------------------------------------------
# to_dict / __repr__ sanity
# ---------------------------------------------------------------------------

def test_to_dict_round_trips():
    j = _make_job(salary_text="18-25 LPA", applicants_text="120 applicants")
    d = j.to_dict()
    assert d["title"] == "Software Engineer"
    assert d["salary_text"] == "18-25 LPA"
    assert d["applicants_text"] == "120 applicants"


def test_repr_is_compact_and_readable():
    r = repr(_make_job())
    assert "linkedin" in r and "Acme Corp" in r and "Software Engineer" in r
