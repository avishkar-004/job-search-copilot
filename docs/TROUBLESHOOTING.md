# Troubleshooting

Common problems and how to fix them, ordered roughly by how often I see them.

## Install / setup

### `mediapipe` / `playwright` install fails

```
ERROR: Could not find a version that satisfies the requirement playwright
```

You're on Python 3.14+. Use 3.10–3.13:

```bash
brew install python@3.12         # macOS
sudo apt install python3.12      # Ubuntu
```

Then recreate the venv:

```bash
bash setup.sh --recreate
```

### `playwright install chromium` hangs

Chromium is ~400 MB. On a slow connection it takes a while. If it times out,
retry. If it consistently fails, try:

```bash
PLAYWRIGHT_BROWSERS_PATH=$HOME/.playwright playwright install chromium
```

### `GROQ_API_KEY env var not set`

```bash
export GROQ_API_KEY=gsk_...
# or put in .env and: source .env
```

Get a key (free tier) at https://console.groq.com.

## Login / sessions

### LinkedIn redirects to `/checkpoint/challenge`

That's 2FA. Run non-headless and complete the SMS / authenticator prompt
in the visible browser window. The bot waits up to 120s. Once you complete
it, the cookies save to `data/sessions/linkedin.json` and the next run
reuses them.

### Indeed shows a CAPTCHA

Same pattern — run non-headless once:

```bash
python main.py --platforms indeed --limit 1
```

Solve the CAPTCHA. Future runs reuse the cookies.

### "Session cookies expired" mid-run

Cookies last ~7–30 days depending on the platform. The bot will detect this,
fall back to `login()`, and prompt for 2FA if needed. If running headless on
a cron, this will fail — schedule a manual re-auth every couple of weeks.

## Search / scraping

### 0 jobs found on a platform that should have many

Three causes, in order of likelihood:

1. **The platform's DOM changed.** Open the search page in a normal browser,
   inspect the job-card element, compare to the selector in
   `src/platforms/<name>.py`. Update if needed.
2. **You're rate-limited.** Wait 30 minutes and retry.
3. **Your search filters are too narrow.** Try fewer
   `search.experience_levels`, more `search.keywords`, more
   `search.locations`.

### Job descriptions come back empty

Some platforms render JDs client-side via React. The scraper waits for
`networkidle` and a `main, article` selector before extracting text. If a
platform is still returning empty JDs, edit its module to bump the
`wait_for_selector` timeout or add a more specific selector.

### Bot freezes on the first job after login

This is usually a CAPTCHA appearing mid-session. Run non-headless to see
what's happening on screen.

## AI / scoring

### Groq returns 429 (rate limited)

The token bucket in `src/ai/engine.py` enforces 25 req/min — well under
Groq's free-tier limit of 30. If you're still seeing 429, you might have
another process hitting Groq. Wait 60 seconds; the bot retries with
exponential backoff.

### Scores look wrong (e.g. everything scores 50)

- Check the model name in `profile.yaml` matches Groq's catalog.
  `llama-3.3-70b-versatile` is the current default.
- Make sure `personal.summary`, `skills`, and `achievements` in
  `profile.yaml` are filled out. The LLM scores by matching JD against
  your profile — if your profile is sparse, scores compress.
- Delete `data/ai_cache/` to re-score against a refreshed prompt.

### Cover letter / bullets are generic

Tailoring quality scales with how specific your profile fields are.
"Built a distributed database in C++17 with MVCC + Raft" generates much
sharper output than "C++ developer".

## Output / reports

### `reports/` is empty after a run

Either no jobs cleared `min_fit_score` (lower it temporarily to debug), or
the run errored out before report generation (check `logs/`).

### Markdown looks broken in my editor

The reports use GitHub-flavoured markdown. Open in VS Code, GitHub, or
any GFM-compatible viewer.

## Tracker

### `python main.py mark-applied abc123` says "no row found"

The hash you pasted doesn't match any row in `data/jobs.csv`. Easiest fix:

```bash
head data/jobs.csv
```

Copy the first column of the right row.

### CSV got corrupted

Restore from git or backup. The atomic-write pattern means the only way to
corrupt the CSV is to edit it by hand mid-run.

## Performance

### A full run takes >30 minutes

That's expected with 9 platforms × 20–30 jobs each × 3-second polite delay
between each detail-page load. To speed it up:

- Drop platforms you don't need from `search.platforms`
- Lower `--limit` per platform
- Run `--dry-run` first to skip AI scoring while you tune filters

### Memory grows during long runs

The bot keeps every scraped Job in memory and writes everything at the end.
For runs >500 jobs total, that's still well under 100MB. If you're seeing
gigabytes, something's leaking — file an issue.

## Still stuck?

1. Re-read `docs/ARCHITECTURE.md` to make sure you understand what the bot
   is doing at each stage.
2. Check `logs/` for the most recent error trace.
3. Run `pytest -v` to confirm the local code base is healthy.
4. Try `python main.py --dry-run --platforms ycombinator --limit 3` — that
   exercises the smallest possible path (one no-login platform, no AI) and
   tells you whether the basic plumbing works.
