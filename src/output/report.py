"""
Daily markdown report generator.

For each run, writes:
  reports/YYYY-MM-DD/README.md          — index page
  reports/YYYY-MM-DD/jobs/<slug>.md     — one file per high-fit job with JD,
                                          tailored bullets, and cover letter
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from .atomic_io import atomic_write_text
from ..types import Job

logger = logging.getLogger(__name__)

REPORTS_DIR = Path("reports")


def _safe_slug(text: str, max_len: int = 60) -> str:
    s = (text or "").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:max_len] or "untitled"


def per_job_path(run_dir: Path, job: Job) -> Path:
    company = _safe_slug(job.company, 40)
    title = _safe_slug(job.title, 60)
    return run_dir / "jobs" / f"{company}--{title}.md"


def write_per_job_file(
    job: Job,
    score: dict,
    bullets: list[str],
    cover_letter: str,
    run_dir: Path,
) -> Path:
    """Write the per-job markdown with JD + AI score + tailored bullets + cover letter."""
    path = per_job_path(run_dir, job)
    parts: list[str] = []
    parts.append(f"# {job.title} — {job.company}")
    parts.append("")
    parts.append(f"- **Platform**: {job.platform}")
    parts.append(f"- **Location**: {job.location or 'N/A'}")
    parts.append(f"- **Posted**: {job.posted_at or 'N/A'}")
    parts.append(f"- **Salary**: {job.salary_text or 'N/A'}")
    parts.append(f"- **Applicants**: {job.applicants_text or 'N/A'}")
    parts.append(f"- **URL**: {job.url}")
    parts.append(f"- **Job hash**: `{job.job_hash()}`")
    parts.append("")

    parts.append(f"## Fit Score: {score.get('fit_score', 0)}/100")
    parts.append("")
    parts.append(f"> {score.get('one_line_summary', '')}")
    parts.append("")

    if score.get("matched_skills"):
        parts.append("**Matched skills**: " + ", ".join(score["matched_skills"]))
    if score.get("missing_skills"):
        parts.append("**Missing skills**: " + ", ".join(score["missing_skills"]))
    if score.get("red_flags"):
        parts.append("**Red flags**:")
        for flag in score["red_flags"]:
            parts.append(f"- {flag}")
    parts.append("")

    if bullets:
        parts.append("## Tailored Resume Bullets")
        for b in bullets:
            parts.append(f"- {b}")
        parts.append("")

    if cover_letter:
        parts.append("## Cover Letter")
        parts.append("")
        parts.append(cover_letter)
        parts.append("")

    parts.append("## Full Job Description")
    parts.append("")
    parts.append("```")
    parts.append(job.jd_text or "(no description scraped)")
    parts.append("```")
    parts.append("")

    atomic_write_text(path, "\n".join(parts))
    return path


def write_index(
    run_dir: Path,
    today: date,
    all_jobs: list[Job],
    scores: dict[str, dict],
    min_fit_score: int,
    new_count: int,
) -> Path:
    """Write the daily README.md index for the run."""
    index_path = run_dir / "README.md"
    total = len(all_jobs)
    above = [j for j in all_jobs if scores.get(j.job_hash(), {}).get("fit_score", 0) >= min_fit_score]
    below = [j for j in all_jobs if scores.get(j.job_hash(), {}).get("fit_score", 0) < min_fit_score]

    above_sorted = sorted(above,
                          key=lambda j: scores.get(j.job_hash(), {}).get("fit_score", 0),
                          reverse=True)

    parts: list[str] = []
    parts.append(f"# Job Search Copilot — {today.isoformat()}")
    parts.append("")
    parts.append(f"- Jobs scanned: **{total}**")
    parts.append(f"- Above threshold (>= {min_fit_score}): **{len(above)}**")
    parts.append(f"- Below threshold: **{len(below)}**")
    parts.append(f"- New since yesterday: **{new_count}**")
    parts.append("")

    if above_sorted:
        parts.append("## Matches (ranked by fit score)")
        parts.append("")
        parts.append("| # | Company | Role | Location | Salary | Fit | Details | Apply |")
        parts.append("|---|---------|------|----------|--------|-----|---------|-------|")
        for i, j in enumerate(above_sorted, 1):
            sc = scores.get(j.job_hash(), {})
            details_rel = f"jobs/{per_job_path(run_dir, j).name}"
            parts.append(
                f"| {i} "
                f"| {j.company} "
                f"| {j.title} "
                f"| {j.location or '-'} "
                f"| {j.salary_text or '-'} "
                f"| **{sc.get('fit_score', 0)}** "
                f"| [open]({details_rel}) "
                f"| [Apply]({j.url}) |"
            )
        parts.append("")

        parts.append("## Top 10 to apply today")
        parts.append("")
        for j in above_sorted[:10]:
            sc = scores.get(j.job_hash(), {})
            parts.append(f"### {j.title} — {j.company} (fit {sc.get('fit_score', 0)})")
            parts.append(f"{sc.get('one_line_summary', '')}")
            parts.append(f"[JD + materials](jobs/{per_job_path(run_dir, j).name}) · [{j.platform} listing]({j.url})")
            parts.append("")

    if below:
        parts.append("<details>")
        parts.append(f"<summary>Skipped (low fit) — {len(below)} jobs</summary>")
        parts.append("")
        below_sorted = sorted(below,
                              key=lambda j: scores.get(j.job_hash(), {}).get("fit_score", 0),
                              reverse=True)
        for j in below_sorted:
            sc = scores.get(j.job_hash(), {})
            parts.append(f"- **{j.company}** — {j.title} ({j.location or '-'}) "
                         f"— fit **{sc.get('fit_score', 0)}**. "
                         f"{sc.get('one_line_summary', '')} "
                         f"[{j.platform}]({j.url})")
        parts.append("")
        parts.append("</details>")

    atomic_write_text(index_path, "\n".join(parts))
    return index_path


def run_dir_for(today: Optional[date] = None) -> Path:
    today = today or date.today()
    return REPORTS_DIR / today.isoformat()
