# Usage

Step-by-step from a fresh clone to your first daily report.

For the TL;DR, see the [root README](../README.md).

## 0. Prerequisites

| What             | Why                                                          |
| ---------------- | ------------------------------------------------------------ |
| Python 3.10–3.13 | Playwright's greenlet dep doesn't ship 3.14 wheels yet       |
| ~1 GB free disk  | Playwright Chromium is ~400 MB                               |
| Groq API key     | Free at https://console.groq.com                             |
| A working webcam | (not actually — just making sure you're awake)               |

## 1. Setup

```bash
git clone <your-fork-url>
cd job-apply-bot
bash setup.sh
```

`setup.sh` will:
- Pick a compatible Python (3.10–3.13)
- Create `.venv/` and install dependencies
- Install Playwright's Chromium binary
- Create `data/`, `reports/`, `logs/` directories

## 2. Configure your profile

Open `config/profile.yaml`. Critical sections:

```yaml
personal:
  full_name: "Your Name"
  email: "you@example.com"
  phone: "+91-..."
  location: "Bangalore, India"

links:
  linkedin: "https://linkedin.com/in/yourhandle"
  github: "https://github.com/yourhandle"
  portfolio: "https://yourhandle.github.io"   # the canonical URL, no extra path

skills:
  primary: "Python, C++, ..."

search:
  keywords:
    - "Software Engineer"
    - "Backend Engineer"
  locations:
    - "Bangalore, India"
    - "Remote, India"
  experience_levels:
    - "Entry level"
    - "Internship"
  min_fit_score: 65
  preferred_min_ctc_lpa: 18
  blacklist_companies:
    - "(companies you do not want to work for)"
  blacklist_keywords:
    - "Senior"            # if you're entry-level
```

The bot fails loud if `search.keywords`, `search.locations`, or
`search.min_fit_score` are missing.

## 3. Credentials

Copy the env template and fill in what you need:

```bash
cp .env.example .env
nano .env
```

You'll set:
- `GROQ_API_KEY` (required — the bot fails without this)
- `LINKEDIN_EMAIL`, `LINKEDIN_PASSWORD` (only if you'll use LinkedIn)
- Similar pairs for `NAUKRI_*`, `INDEED_*`, `WELLFOUND_*`, etc.
- `INTERNSHALA_*`, `UNSTOP_*`, `GLASSDOOR_*` — only the platforms you'll use.

Then in every new terminal session:

```bash
source .venv/bin/activate
source .env                # exports the variables
```

(Or use direnv / a shell rc file if you don't want to keep sourcing it.)

## 4. First-time login per platform

Sessions are saved as cookies under `data/sessions/<platform>.json`. The
first run on each platform needs to be non-headless so you can complete any
login / 2FA / CAPTCHA flow manually.

```bash
python main.py --platforms linkedin --limit 3
```

Watch the browser. Log in. If 2FA pops up, complete it. The bot waits up to
120s before timing out. Once you're logged in, the cookies get saved and
subsequent runs reuse them.

Repeat once per platform you intend to use.

## 5. Daily workflow

```bash
# Standard run — search all configured platforms, score everything,
# write the daily report
python main.py

# Only show postings from the last 24 hours
python main.py --since 24h

# Limit each platform to its first 20 results
python main.py --limit 20

# Search a subset of platforms
python main.py --platforms linkedin wellfound ycombinator

# Dry-run — search and dedup only, no AI scoring, no markdown
python main.py --dry-run
```

When the run finishes, open today's report:

```bash
open reports/$(date +%Y-%m-%d)/README.md
```

You'll see a ranked table of jobs. Click into each `jobs/<company>--<role>.md`
for the full JD, your matched/missing skills, tailored resume bullets, and
draft cover letter.

## 6. Tracking application status

After you actually apply to a job (manually, on the platform's website):

```bash
python main.py mark-applied <job_hash>
```

The job_hash is shown in each report row. To withdraw a job from
consideration:

```bash
python main.py mark-rejected <job_hash>
```

This updates `data/jobs.csv` so future reports stop suggesting it.

## 7. Regenerating today's report without re-scraping

If you only want to refresh the markdown view of `data/jobs.csv`:

```bash
python main.py report
```

Useful after `mark-applied` calls.

## 8. Optional dashboard

For real-time monitoring during a long run:

```bash
python main.py --dashboard
```

Opens a Flask + Socket.IO dashboard at http://localhost:7000.

## 9. Common pitfalls

| Symptom                                       | Cause / Fix                                                  |
| --------------------------------------------- | ------------------------------------------------------------ |
| `GROQ_API_KEY env var not set`                | Set it in `.env`, then `source .env`                         |
| LinkedIn / Naukri logs in then asks 2FA       | Run non-headless first time; complete by hand                |
| Indeed shows a CAPTCHA                        | Same — run non-headless once                                 |
| Bot finds 0 jobs on LinkedIn                  | LinkedIn restructured the search page; selectors need a tweak — file an issue or check `src/platforms/linkedin.py` |
| AI scores look weird                          | Check the model name in `profile.yaml` matches Groq's catalog |
| `reports/` empty after run                    | Check `logs/` for errors; common cause: 0 jobs above `min_fit_score` |
| Re-running gives the same scores              | That's the cache (`data/ai_cache/`) doing its job. Delete it to re-score. |

## 10. Putting it on a schedule

The bot is stateless across runs. Schedule it via cron:

```cron
# Run every weekday at 8 AM
0 8 * * 1-5 cd /path/to/job-apply-bot && source .venv/bin/activate && source .env && python main.py --since 24h >> logs/cron.log 2>&1
```

Or launchd on macOS, or systemd-timer on Linux. The atomic writes mean
overlapping runs won't corrupt the CSV, but they will waste API tokens, so
don't double-schedule.
