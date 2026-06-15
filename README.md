# Job Search Copilot

![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)
![Playwright](https://img.shields.io/badge/Playwright-1.44-green?logo=playwright)
![Groq](https://img.shields.io/badge/AI-Groq-orange)

A **read-only** job search copilot. It logs in to LinkedIn / Naukri / Indeed /
Wellfound / Y Combinator / Cutshort, runs your saved searches, scrapes the
full job description for every match, scores fit with Groq's free-tier
llama-3.3-70b, generates tailored resume bullets + a cover letter for each
strong match, and emits a ranked daily markdown report — for **you** to apply
manually.

**The bot never clicks Apply.** Auto-applying invites LinkedIn / Indeed
account bans, so this tool is designed to save you the dull "open 40 tabs,
read JDs" part of the day and leave the actual submission to a human.

---

## Features

- **9 platforms in one run**: LinkedIn, Naukri, Indeed, Wellfound, Glassdoor,
  Internshala, Unstop, Y Combinator (no login), Cutshort (no login).
- **Full-JD scraping**: each match is opened in-page; we capture the full
  description, salary text, applicant count, and posted timestamp.
- **Cross-platform deduplication**: same role on LinkedIn + Indeed +
  company page collapses to one entry; the richest JD wins.
- **AI fit scoring (0-100)** with `matched_skills`, `missing_skills`,
  `red_flags`, and a one-line summary. Disk-cached so re-runs are free.
- **Tailored materials per high-fit job**: 5 resume bullets + 3-paragraph
  cover letter referencing your 3 main projects (MiniDB, StreamFlow,
  VectorFlow), saved alongside the JD.
- **Daily markdown report**: `reports/YYYY-MM-DD/README.md` with a sorted
  table of matches, a "Top 10 to apply today" section, and a collapsed
  "Skipped (low fit)" appendix.
- **Master CSV** at `data/jobs.csv` tracks every job across runs with a
  stable hash. You update statuses (applied / rejected_by_user) via CLI.
- **Polite scraping**: 2-4 s jitter between JD page loads, plain Playwright
  (no stealth tricks), Groq token-bucket rate limiter (25 req/min, under
  free-tier limit of 30).
- **Atomic file writes**: CSV + reports go through `<path>.tmp -> rename`,
  so Ctrl+C never corrupts on-disk state.

---

## Setup

**Requirements**: Python 3.11+, pip

```bash
cd job-apply-bot

# 1. Install (deps + Playwright Chromium)
bash setup.sh

# 2. Edit your profile + verify the search keywords / locations
nano config/profile.yaml

# 3. Set credentials for the platforms you want to scrape
export LINKEDIN_EMAIL="you@email.com"
export LINKEDIN_PASSWORD="..."
export NAUKRI_EMAIL="you@email.com"
export NAUKRI_PASSWORD="..."
export WELLFOUND_EMAIL="you@email.com"
export WELLFOUND_PASSWORD="..."
export INDEED_EMAIL="you@email.com"
export INDEED_PASSWORD="..."
# YCombinator + Cutshort are public — no credentials needed.

# 4. Dry-run (search only, no AI scoring, no report)
python main.py --dry-run

# 5. Full run
python main.py
```

> First time per platform: log in by hand in the visible browser window so
> session cookies get saved to `logs/session_<platform>.json`. Subsequent
> runs reuse them.

---

## CLI

```
python main.py                              # full run on all configured platforms
python main.py --platforms linkedin wellfound
python main.py --dry-run                    # search only, no AI / no markdown
python main.py --limit 20                   # cap jobs per platform
python main.py --since 24h                  # only fresh postings (24h or 7d, etc.)
python main.py --headless                   # no browser window (CI / server)
python main.py --config /path/to/other.yaml # alternate profile

# Tracker (user-driven status transitions)
python main.py mark-applied <job_hash>
python main.py mark-rejected <job_hash>

# Regenerate today's markdown from the CSV without re-scraping
python main.py report

# Existing live dashboard
python main.py --dashboard
```

The `<job_hash>` is shown in each per-job markdown file under "Job hash" and
in `data/jobs.csv`.

---

## Output Layout

```
data/
  jobs.csv                              # master cross-run tracker
logs/
  session_<platform>.json               # saved cookies per platform
  ai_cache.json                         # AI score cache (job_hash -> result)
reports/
  2026-05-18/
    README.md                           # daily ranked index
    jobs/
      acme-corp--backend-engineer.md    # JD + tailored bullets + cover letter
      ...
```

---

## Configuration

`config/profile.yaml` keys (the loader fails fast if any required key is
missing):

| Section         | Required keys                                                   |
|-----------------|-----------------------------------------------------------------|
| `personal`      | full_name, email, phone, location, city, country                |
| `links`         | linkedin, github, portfolio                                     |
| `education`     | degree, major, university, graduation_year, cgpa                |
| `experience`    | years, current_role, expected_ctc_lpa, work_authorization       |
| `skills`        | primary, summary                                                |
| `resume.text`   | full resume as plain text — fed into AI prompts                 |
| `ai`            | provider (groq), api_key, model                                 |
| `search`        | platforms, keywords, locations, experience_levels, min_fit_score, preferred_min_ctc_lpa, max_per_run |

Free Groq API key: https://console.groq.com  — generous free tier; the token
bucket caps us at 25 req/min just under the 30 req/min limit.

---

## How a Run Works

```
1. For each enabled platform:
   - Load saved cookies; log in if missing
   - Run keyword x location searches
   - For every listing card, visit the URL and scrape full JD
2. Merge all jobs -> dedup by (normalized_company, normalized_title, 3-day bucket)
3. AI-score each survivor (Groq, llama-3.3-70b). Cached by job hash.
4. For each job with fit_score >= min_fit_score:
   - AI-generate 5 tailored resume bullets
   - AI-generate 3-paragraph cover letter
   - Write reports/today/jobs/<safe-slug>.md with JD + materials
5. Upsert into data/jobs.csv (status='new' for unseen rows)
6. Write reports/today/README.md sorted by fit score
7. Done — open the report, click links, apply manually.
```

---

## File Structure

```
job-apply-bot/
  main.py                       # CLI entry
  config/profile.yaml           # your profile
  data/jobs.csv                 # master tracker (auto-created)
  reports/YYYY-MM-DD/           # daily output
  src/
    types.py                    # Job dataclass
    config.py                   # YAML loader + validation
    browser.py                  # plain Playwright bootstrap + cookie save/load
    atomic_io.py                # atomic writes
    ai_engine.py                # Groq calls + token bucket + disk cache
    dedup.py                    # cross-platform dedup
    tracker.py                  # master CSV upsert + status transitions
    report.py                   # daily markdown generator
    platforms/
      base.py                   # abstract BasePlatform (collect_jobs only)
      linkedin.py
      naukri.py
      indeed.py
      wellfound.py
      glassdoor.py
      internshala.py
      unstop.py
      ycombinator.py            # NEW: public scrape, no login
      cutshort.py               # NEW: public scrape, no login
      registry.py
  dashboard/app.py              # existing Flask dashboard (kept)
  logs/
  requirements.txt
  setup.sh
```

---

## Troubleshooting

| Symptom                                  | Fix                                                                              |
|------------------------------------------|----------------------------------------------------------------------------------|
| `Field 'search.locations' must be set`   | Add a non-empty `search.locations` list in profile.yaml                          |
| LinkedIn redirects to `/checkpoint`      | Complete 2FA in the browser — the bot waits up to 120 s                          |
| Indeed shows a CAPTCHA                   | Run without `--headless` once so you can clear it; cookies will persist          |
| Groq returns 429                         | The built-in token bucket should prevent this; if you see it, lower max_per_run  |
| Empty `jd_text` for a job                | Selectors changed on that site; check the per-job markdown — the URL still works |
| Wrong `job_hash` for `mark-applied`      | Look up the hash in `data/jobs.csv` or in the per-job markdown header            |

---

## Disclaimer / Responsible Use

This tool is read-only. It does **not** submit applications. Please:

- Respect each platform's Terms of Service and rate limits.
- Use the report to apply only to roles you'd genuinely take.
- The Groq free tier is generous but finite — the token bucket is there to
  keep you within it; do not bypass it.

The maintainer accepts no responsibility for account bans or any other
consequence of running this software.
