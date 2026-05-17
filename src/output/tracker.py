"""
Cross-run job tracker.

Master CSV: data/jobs.csv

Schema (one row per known job hash):
  job_hash, first_seen, last_seen, platform, title, company, location, url,
  fit_score, status, applied_at

Status values:
  new            — first time we have seen this job
  reviewed       — user has eyeballed it
  applied        — user actually submitted an application
  rejected_by_user — user looked + said "no thanks"
  expired        — listing has aged out

The bot only ever writes (job_hash, first_seen, last_seen, fit_score, scrape fields).
Status transitions are user-driven via the `mark-*` CLI subcommands.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from .atomic_io import atomic_write_text
from ..types import Job

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
CSV_PATH = DATA_DIR / "jobs.csv"

CSV_COLUMNS = [
    "job_hash",
    "first_seen",
    "last_seen",
    "platform",
    "title",
    "company",
    "location",
    "url",
    "fit_score",
    "status",
    "applied_at",
]

VALID_STATUSES = {"new", "reviewed", "applied", "rejected_by_user", "expired"}


# ---------------------------------------------------------------------------
# CSV I/O — atomic
# ---------------------------------------------------------------------------

def _ensure_csv() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not CSV_PATH.exists():
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        atomic_write_text(CSV_PATH, buf.getvalue())


def _read_all() -> list[dict]:
    _ensure_csv()
    with open(CSV_PATH, "r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write_all(rows: Iterable[dict]) -> None:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    for row in rows:
        clean = {col: row.get(col, "") for col in CSV_COLUMNS}
        writer.writerow(clean)
    atomic_write_text(CSV_PATH, buf.getvalue())


def _today_iso() -> str:
    return date.today().isoformat()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def upsert_jobs(jobs: Iterable[Job], scores: dict[str, dict]) -> tuple[int, int]:
    """
    Upsert scraped jobs into the master CSV.
    - Inserts brand-new rows with status='new'.
    - Updates last_seen and fit_score on existing rows.
    Never touches user-set statuses (applied/rejected_by_user/etc).

    Args:
        jobs: scraped Job objects.
        scores: mapping job_hash -> AI score dict (must contain 'fit_score').

    Returns:
        (added, updated) counts.
    """
    rows = _read_all()
    by_hash = {r["job_hash"]: r for r in rows}
    added = 0
    updated = 0
    today = _today_iso()

    for job in jobs:
        h = job.job_hash()
        score = scores.get(h, {}).get("fit_score", "")
        existing = by_hash.get(h)
        if existing:
            existing["last_seen"] = today
            if score != "":
                existing["fit_score"] = str(score)
            existing["title"] = job.title
            existing["company"] = job.company
            existing["location"] = job.location
            existing["url"] = job.url
            updated += 1
        else:
            new_row = {
                "job_hash": h,
                "first_seen": today,
                "last_seen": today,
                "platform": job.platform,
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "url": job.url,
                "fit_score": str(score) if score != "" else "",
                "status": "new",
                "applied_at": "",
            }
            by_hash[h] = new_row
            rows.append(new_row)
            added += 1

    _write_all(rows)
    logger.info("Tracker upsert: %d new, %d updated (total %d).", added, updated, len(rows))
    return added, updated


def get_row(job_hash: str) -> Optional[dict]:
    for row in _read_all():
        if row.get("job_hash") == job_hash:
            return row
    return None


def all_rows() -> list[dict]:
    return _read_all()


def new_since(date_iso: str) -> list[dict]:
    """Rows whose first_seen >= date_iso (inclusive)."""
    return [r for r in _read_all() if r.get("first_seen", "") >= date_iso]


def set_status(job_hash: str, status: str) -> bool:
    """Manually set the status for a job hash. Returns True on success."""
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status {status!r}. Must be one of {sorted(VALID_STATUSES)}")
    rows = _read_all()
    found = False
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for row in rows:
        if row.get("job_hash") == job_hash:
            row["status"] = status
            if status == "applied":
                row["applied_at"] = now
            found = True
            break
    if found:
        _write_all(rows)
        logger.info("Tracker: set %s -> %s", job_hash, status)
    else:
        logger.warning("Tracker: no row found for job_hash=%s", job_hash)
    return found


# ---------------------------------------------------------------------------
# Stats helpers (used by report regeneration + simple summaries)
# ---------------------------------------------------------------------------

def stats() -> dict:
    rows = _read_all()
    by_status: dict[str, int] = {}
    by_platform: dict[str, int] = {}
    for r in rows:
        by_status[r.get("status", "?")] = by_status.get(r.get("status", "?"), 0) + 1
        by_platform[r.get("platform", "?")] = by_platform.get(r.get("platform", "?"), 0) + 1
    return {
        "total": len(rows),
        "by_status": by_status,
        "by_platform": by_platform,
    }


# ---------------------------------------------------------------------------
# Dashboard compatibility shims (the existing Flask dashboard uses these
# names). They map to the read-only tracker semantics — we never log an
# "application" event, so log_application is a no-op kept for import safety.
# ---------------------------------------------------------------------------

def get_stats() -> dict:
    """Dashboard-compatible summary (subset of stats())."""
    s = stats()
    return {
        "total": s["total"],
        "today": sum(1 for r in _read_all() if r.get("first_seen") == _today_iso()),
        "by_platform": s["by_platform"],
        "by_status": s["by_status"],
        "success_rate": 0.0,  # not meaningful in read-only mode
    }


def get_recent(n: int = 20) -> list[dict]:
    """Dashboard-compatible recent rows (most-recently last_seen first)."""
    rows = sorted(_read_all(), key=lambda r: r.get("last_seen", ""), reverse=True)
    out: list[dict] = []
    for r in rows[:n]:
        out.append({
            "date": r.get("last_seen", ""),
            "platform": r.get("platform", ""),
            "company": r.get("company", ""),
            "job_title": r.get("title", ""),
            "fit_score": r.get("fit_score", ""),
            "status": r.get("status", ""),
        })
    return out


def log_application(app: dict) -> None:  # noqa: D401  (compat shim)
    """No-op in read-only mode. Kept so existing dashboard imports do not fail."""
    logger.debug("tracker.log_application called (no-op in read-only mode): %s", app.get("job_id"))
