"""
Job Search Copilot — main entry point.

READ-ONLY: this tool searches job platforms, scores fit with AI, and writes
a daily markdown report. It NEVER submits applications. The user opens the
ranked report and applies manually.

Usage:
  python main.py                              # full run on configured platforms
  python main.py --platforms linkedin wellfound
  python main.py --dry-run                    # search only, no AI scoring, no markdown
  python main.py --limit 20                   # cap jobs per platform
  python main.py --since 24h                  # only fresh postings
  python main.py mark-applied <job_hash>      # update tracker
  python main.py mark-rejected <job_hash>     # update tracker
  python main.py report                       # regenerate latest markdown from CSV
  python main.py --dashboard                  # start the Flask dashboard
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# Logging setup before any src imports
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, stream=sys.stdout)
logger = logging.getLogger("main")
for noisy in ("httpx", "httpcore", "playwright", "asyncio"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import Config
from src.ai import engine as ai_engine
from src.output import tracker, report
from src.search import dedup
from src.utils.browser import setup_browser, save_session, random_delay
from src.platforms.registry import get_platform, PLATFORM_REGISTRY
from src.types import Job


# ---------------------------------------------------------------------------
# Terminal colours
# ---------------------------------------------------------------------------
_RESET = "\033[0m"
_BOLD = "\033[1m"
_GREEN = "\033[92m"
_YELLOW = "\033[93m"
_RED = "\033[91m"
_CYAN = "\033[96m"
_DIM = "\033[2m"


def _c(text: object, *codes: str) -> str:
    if sys.stdout.isatty():
        return "".join(codes) + str(text) + _RESET
    return str(text)


def print_header() -> None:
    print()
    print(_c("==================================================", _BOLD, _CYAN))
    print(_c("        JOB SEARCH COPILOT  -  read-only          ", _BOLD, _CYAN))
    print(_c("==================================================", _BOLD, _CYAN))
    print()


# ---------------------------------------------------------------------------
# Profile proxy (lightweight access object for AI prompts)
# ---------------------------------------------------------------------------

def _build_profile_proxy(config: Config):
    class _Proxy:
        pass

    p = _Proxy()
    for section in ("personal", "links", "education", "experience", "skills", "resume"):
        setattr(p, section, getattr(config, section))
    return p


# ---------------------------------------------------------------------------
# Single-platform scrape
# ---------------------------------------------------------------------------

async def run_platform(
    platform_name: str,
    config: Config,
    headless: bool,
    filters: dict,
) -> list[Job]:
    """Log in (if needed), scrape jobs, return Job list (no AI scoring yet)."""
    from playwright.async_api import async_playwright

    platform = get_platform(platform_name, config)
    logger.info("Starting platform: %s", platform_name.upper())

    jobs: list[Job] = []
    async with async_playwright() as pw:
        browser, context, page = await setup_browser(pw, platform=platform_name, headless=headless)
        try:
            if not await platform.is_logged_in(page):
                try:
                    await platform.login(page)
                    await save_session(context, platform_name)
                except Exception as exc:
                    logger.warning("%s: login skipped/failed (%s) — continuing as guest where possible",
                                   platform_name, exc)
            else:
                logger.info("%s: using existing session.", platform_name)

            jobs = await platform.collect_jobs(page, filters)
            print(_c(f"\n  [{platform_name.upper()}]", _BOLD, _CYAN)
                  + f" Collected {_c(len(jobs), _BOLD)} jobs")

        except Exception as exc:
            logger.error("Platform %s crashed: %s", platform_name, exc)
        finally:
            await context.close()
            await browser.close()
    return jobs


# ---------------------------------------------------------------------------
# Scoring + report writing
# ---------------------------------------------------------------------------

async def score_all(jobs: list[Job], config: Config) -> dict[str, dict]:
    """Score every job with AI. Returns dict job_hash -> score result."""
    profile = _build_profile_proxy(config)
    scores: dict[str, dict] = {}
    for i, job in enumerate(jobs, 1):
        logger.info("Scoring %d/%d: %s", i, len(jobs), job)
        result = await ai_engine.score_job(job, profile, config)
        scores[job.job_hash()] = result
        print(
            f"  [{i:>3}/{len(jobs)}] "
            f"{job.company[:24]:<26} "
            f"{job.title[:34]:<36} "
            f"fit: {_c(result['fit_score'], _GREEN if result['fit_score'] >= 75 else _YELLOW if result['fit_score'] >= 65 else _RED)}/100"
        )
    return scores


async def write_high_fit_materials(
    jobs: list[Job],
    scores: dict[str, dict],
    config: Config,
    min_fit_score: int,
    run_dir: Path,
) -> None:
    """For each above-threshold job: AI-generate tailored bullets + cover letter,
    write a per-job markdown file."""
    profile = _build_profile_proxy(config)
    for job in jobs:
        score = scores.get(job.job_hash(), {})
        if score.get("fit_score", 0) < min_fit_score:
            # Still write a stub file so the user can read the JD if curious.
            report.write_per_job_file(job, score, [], "", run_dir)
            continue
        logger.info("Tailoring materials: %s", job)
        bullets = await ai_engine.tailor_resume_bullets(job, profile, config)
        cover = await ai_engine.generate_cover_letter(job, profile, config)
        report.write_per_job_file(job, score, bullets, cover, run_dir)


# ---------------------------------------------------------------------------
# `since` parser
# ---------------------------------------------------------------------------

def _parse_since(since: str | None) -> int | None:
    if not since:
        return None
    m = re.match(r"^(\d+)\s*([hd])$", since.strip().lower())
    if not m:
        raise ValueError(f"Invalid --since value {since!r}. Use e.g. '24h' or '7d'.")
    n = int(m.group(1))
    return n if m.group(2) == "h" else n * 24


# ---------------------------------------------------------------------------
# CLI handlers
# ---------------------------------------------------------------------------

async def cmd_run(args, config: Config) -> None:
    """The default 'scrape -> dedup -> score -> report' pipeline."""
    enabled = args.platforms or config.search.get("platforms", list(PLATFORM_REGISTRY.keys()))
    limit_per_platform = args.limit or int(config.search.get("max_per_run", 20))
    since_hours = _parse_since(args.since)
    min_fit = int(config.search.get("min_fit_score", 65))

    filters = {
        "keywords": list(config.search.get("keywords", [])),
        "locations": list(config.search.get("locations", [])),
        "experience_levels": list(config.search.get("experience_levels", [])),
        "limit": limit_per_platform,
        "since_hours": since_hours,
    }

    run_start = time.time()
    all_jobs: list[Job] = []
    for platform_name in enabled:
        try:
            jobs = await run_platform(platform_name, config, headless=args.headless, filters=filters)
        except Exception as exc:
            logger.error("Platform %s failed: %s", platform_name, exc)
            continue
        # Pre-filter blacklisted
        jobs = [j for j in jobs if not j.is_blacklisted(config)]
        all_jobs.extend(jobs)

    logger.info("Total raw jobs across platforms: %d", len(all_jobs))
    deduped = dedup.deduplicate(all_jobs)
    logger.info("After dedup: %d jobs", len(deduped))

    if args.dry_run:
        print(_c(f"\n[DRY-RUN] {len(deduped)} jobs collected. No AI scoring, no report.", _YELLOW, _BOLD))
        for j in deduped[:30]:
            print(f"  {_c('>', _DIM)} {j.platform:<11} {j.company[:22]:<24} {j.title[:50]}")
        return

    print(_c(f"\nScoring {len(deduped)} jobs with AI ...", _BOLD))
    scores = await score_all(deduped, config)

    today = date.today()
    run_dir = report.run_dir_for(today)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "jobs").mkdir(exist_ok=True)

    print(_c("\nWriting per-job materials ...", _BOLD))
    await write_high_fit_materials(deduped, scores, config, min_fit, run_dir)

    # Tracker upsert + new-count calculation
    yesterday_iso = (today - timedelta(days=1)).isoformat()
    new_rows_yday = len(tracker.new_since(today.isoformat()))  # before this run's upsert
    added, updated = tracker.upsert_jobs(deduped, scores)
    # After upsert, "new since yesterday" = rows whose first_seen == today
    new_today = len([r for r in tracker.all_rows() if r.get("first_seen") == today.isoformat()])

    print(_c("\nWriting daily report ...", _BOLD))
    index_path = report.write_index(run_dir, today, deduped, scores, min_fit, new_count=new_today)

    duration = round(time.time() - run_start, 1)
    print()
    print(_c("=== Run Summary ===", _BOLD))
    print(f"  Jobs scanned : {len(deduped)}")
    print(f"  Above {min_fit:<3}    : {sum(1 for j in deduped if scores.get(j.job_hash(), {}).get('fit_score', 0) >= min_fit)}")
    print(f"  Tracker      : {added} new, {updated} updated")
    print(f"  Report       : {_c(index_path, _BOLD, _GREEN)}")
    print(f"  Duration     : {duration}s")
    print()


def cmd_mark(args, status: str) -> None:
    ok = tracker.set_status(args.job_hash, status)
    if not ok:
        print(_c(f"No job found with hash={args.job_hash}", _RED, _BOLD))
        sys.exit(1)
    print(_c(f"Marked {args.job_hash} as {status}.", _GREEN, _BOLD))


def cmd_report(args, config: Config) -> None:
    """Regenerate today's report from the master CSV (no scraping, no AI)."""
    today = date.today()
    run_dir = report.run_dir_for(today)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "jobs").mkdir(exist_ok=True)

    rows = tracker.all_rows()
    # Build pseudo-Job + score from CSV rows (we don't have JD text here)
    pseudo_jobs: list[Job] = []
    pseudo_scores: dict[str, dict] = {}
    for r in rows:
        j = Job(
            id=f"{r.get('platform','?')}_{r.get('job_hash','?')}",
            platform=r.get("platform", "?"),
            title=r.get("title", ""),
            company=r.get("company", ""),
            location=r.get("location", ""),
            url=r.get("url", ""),
        )
        # We rely on the job_hash matching what tracker stored.
        pseudo_jobs.append(j)
        try:
            score = int(r.get("fit_score") or 0)
        except ValueError:
            score = 0
        pseudo_scores[j.job_hash()] = {
            "fit_score": score,
            "one_line_summary": f"status={r.get('status','?')}, last_seen={r.get('last_seen','?')}",
            "matched_skills": [], "missing_skills": [], "red_flags": [],
        }
    min_fit = int(config.search.get("min_fit_score", 65))
    new_today = len([r for r in rows if r.get("first_seen") == today.isoformat()])
    index_path = report.write_index(run_dir, today, pseudo_jobs, pseudo_scores, min_fit, new_count=new_today)
    print(_c(f"Regenerated {index_path}", _GREEN, _BOLD))


def cmd_dashboard() -> None:
    from dashboard.app import start_dashboard
    start_dashboard()


# ---------------------------------------------------------------------------
# Argparse
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="job-search-copilot",
        description="Read-only job search copilot. Searches, scores, reports. Never applies.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--platforms", nargs="+",
        choices=list(PLATFORM_REGISTRY.keys()),
        help="Subset of platforms to run (default: all in config.search.platforms)",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Search only — no AI scoring, no markdown, no tracker writes")
    parser.add_argument("--headless", action="store_true",
                        help="Run browser headless (no visible window)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Cap jobs per platform per run (overrides config)")
    parser.add_argument("--since", default=None,
                        help="Only postings within this window, e.g. '24h' or '7d'")
    parser.add_argument("--config", default="config/profile.yaml",
                        help="Path to profile config YAML")
    parser.add_argument("--dashboard", action="store_true",
                        help="Start the Flask dashboard (existing) and exit")

    sub = parser.add_subparsers(dest="cmd")

    p_mark_applied = sub.add_parser("mark-applied", help="Mark a tracked job as applied")
    p_mark_applied.add_argument("job_hash")

    p_mark_rejected = sub.add_parser("mark-rejected", help="Mark a tracked job as rejected_by_user")
    p_mark_rejected.add_argument("job_hash")

    sub.add_parser("report", help="Regenerate today's markdown report from the master CSV")

    return parser


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main_async(args: argparse.Namespace) -> None:
    print_header()

    if args.dashboard:
        cmd_dashboard()
        return

    config_path = Path(args.config)
    try:
        config = Config.from_yaml(config_path)
    except (FileNotFoundError, ValueError) as exc:
        print(_c(f"\n[ERROR] {exc}", _RED, _BOLD))
        sys.exit(1)

    print(f"  Config loaded: {_c(config.personal.full_name, _BOLD)} | {config.personal.email}")
    print(f"  AI provider  : {_c(config.ai.provider.upper(), _BOLD)} ({config.ai.model})")
    print()

    if args.cmd == "mark-applied":
        cmd_mark(args, "applied")
        return
    if args.cmd == "mark-rejected":
        cmd_mark(args, "rejected_by_user")
        return
    if args.cmd == "report":
        cmd_report(args, config)
        return

    await cmd_run(args, config)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print(_c("\n\nInterrupted. Goodbye.", _YELLOW))
        sys.exit(0)


if __name__ == "__main__":
    main()
