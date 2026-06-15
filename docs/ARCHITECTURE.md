# Architecture

This document explains how the Job Search Copilot is wired internally, so you
can extend it without breaking the rest.

## One sentence

A daily cron-able CLI that runs a fan-out of platform scrapers, dedups the
results across platforms, asks an LLM to score each match against your
profile, and writes a ranked markdown brief you can review before applying
manually.

## Pipeline

```
        ┌────────────────────────────────────────────────────────────┐
        │                       main.py (CLI)                         │
        └────────────────────────────────────────────────────────────┘
                    │
                    ▼
        ┌────────────────────────────┐    config/profile.yaml
        │ Config.from_yaml()         │ ◄────────────────────────────
        │ — search keywords          │
        │ — locations, exp levels    │
        │ — min_fit_score (default 65)│
        │ — blacklist co + keywords  │
        └────────────┬───────────────┘
                     │
                     ▼
        ┌─────────────────────────────┐
        │ src/platforms/<name>.py     │  one per job board
        │ — login (session reuse)     │
        │ — search by keyword+loc     │
        │ — open every match URL      │
        │ — scrape full JD            │
        │ → returns list[Job]         │
        └────────────┬────────────────┘
                     │  list[Job] from all platforms
                     ▼
        ┌─────────────────────────────┐
        │ src/search/dedup.py         │
        │ — collapse same-role        │
        │   duplicates across boards  │
        │ — keep entry with richest JD│
        └────────────┬────────────────┘
                     ▼
        ┌─────────────────────────────┐    GROQ_API_KEY
        │ src/ai/engine.py            │ ◄──────────────
        │ — Groq llama-3.3-70b        │
        │ — disk cache by job_hash    │
        │ — token bucket (25/min)     │
        │ — returns {fit_score, ...}  │
        └────────────┬────────────────┘
                     ▼
        ┌─────────────────────────────┐
        │ src/output/tracker.py       │  data/jobs.csv
        │ — atomic CSV upserts        │
        │ — status field for user     │
        └────────────┬────────────────┘
                     ▼
        ┌─────────────────────────────┐
        │ src/output/report.py        │  reports/YYYY-MM-DD/
        │ — ranked daily README.md    │
        │ — per-job .md briefs        │
        │   with tailored bullets +   │
        │   draft cover letter        │
        └─────────────────────────────┘
```

## Module map

| Where               | What it owns                                                         |
| ------------------- | -------------------------------------------------------------------- |
| `main.py`           | CLI parsing, top-level orchestration, terminal colours               |
| `src/types.py`      | `Job` dataclass — the canonical record format                        |
| `src/config.py`     | YAML loader + validation; fails loud on missing keys                 |
| `src/ai/engine.py`  | Groq client, scoring, tailoring, rate limit, disk cache              |
| `src/search/dedup.py` | Cross-platform deduplication (company + title + 3-day window)      |
| `src/output/tracker.py` | Master `data/jobs.csv` with statuses                             |
| `src/output/report.py` | Generates daily markdown bundle                                   |
| `src/output/atomic_io.py` | `tmp → rename` writes so Ctrl+C never corrupts state           |
| `src/utils/browser.py` | Playwright bootstrap + session cookie save/load                   |
| `src/platforms/`    | One module per job board — each implements `collect_jobs()`          |
| `dashboard/app.py`  | Optional Flask + Socket.IO dashboard at `localhost:7000`             |

## Data flow at runtime

1. `main.py` parses CLI flags → loads `config/profile.yaml` into `Config`.
2. For each platform in `config.search.platforms`:
    - Get the class from `platforms.registry.PLATFORM_REGISTRY`
    - Launch Playwright (`utils.browser.setup_browser`), restoring session
      cookies from `data/sessions/<platform>.json` if they exist
    - Call `platform.collect_jobs(page, filters)`
    - Append jobs to the global list
3. `search.dedup.deduplicate()` collapses cross-platform duplicates.
4. For every survivor:
    - Compute `job_hash` for stable cross-run identity
    - If cached in `data/ai_cache/`, skip the API call
    - Otherwise call `ai.engine.score_job()` and cache the response
5. `output.tracker.upsert()` writes/updates rows in `data/jobs.csv`.
6. `output.report.write_index()` regenerates today's markdown.
7. `output.report.write_per_job_file()` writes a brief per match.

## Why this layout

- **`src/types.py` and `src/config.py` are kernels.** Almost every module
  uses them. Putting them at the top of `src/` avoids 4-deep imports like
  `from src.kernel.types import Job`.
- **Subpackages map to pipeline stages, not file types.** `ai/`, `search/`,
  `output/`, `utils/`, `platforms/`. Easier to reason about than a flat
  src dir with 20 files.
- **`data/`, `reports/`, `logs/` are gitignored.** They're outputs, not
  source. Regenerating them from scratch is one CLI invocation.
- **No `apply_to_job()` anywhere.** Search is the only verb. By design.

## Adding a new platform

1. Create `src/platforms/<name>.py`. Subclass `BasePlatform`.
2. Implement `async def collect_jobs(self, page, filters) -> list[Job]`.
3. Register in `src/platforms/registry.py`.
4. Add login credentials to `.env.example` (if the platform requires login).
5. The rest (dedup, scoring, reporting) wires up automatically.

## Adding a new AI provider

`src/ai/engine.py` has a thin httpx client targeting Groq's OpenAI-compatible
endpoint. To swap to Gemini or OpenAI, change `BASE_URL` and the auth header
in `_call_llm()`. The rate limiter, cache, and JSON-extraction logic are
provider-agnostic.

## Failure modes and recovery

| Symptom                              | Recovery                                                          |
| ------------------------------------ | ----------------------------------------------------------------- |
| Platform login redirects to 2FA      | Run non-headless; complete by hand once; cookies save             |
| CAPTCHA appears                      | Run non-headless once; clear it; session reused                   |
| Groq 429 rate limit                  | Token bucket already enforces 25/min; on 429 we back off + retry  |
| Selectors broke after DOM change     | Platform module's `collect_jobs()` raises; bot logs + skips that platform; other platforms continue |
| Ctrl+C mid-run                       | Atomic writes guarantee no half-files; next run picks up where left off |

## Not in this repo

- Auto-apply (intentionally — see the README disclaimer)
- CAPTCHA solving
- Account creation / sign-up automation
- Email/SMS-based 2FA bypass
