# Platforms

What each supported platform looks like, what creds it needs, and quirks
that have bitten me before.

## Currently supported

| Platform      | Login needed | India-focused | Anti-bot         | Notes                                  |
| ------------- | ------------ | ------------- | ---------------- | -------------------------------------- |
| LinkedIn      | yes (2FA)    | global        | aggressive       | Use sparingly; bans are permanent      |
| Naukri        | yes          | ✅            | medium           | Reliable; preferred for Indian roles   |
| Indeed        | yes          | global        | aggressive (CAPTCHA) | First-time run will hit a CAPTCHA  |
| Glassdoor     | yes          | global        | medium           | Slow; consider deprioritising          |
| Wellfound     | yes          | startup-heavy | low              | (formerly AngelList) — good signal     |
| Internshala   | yes          | ✅            | low              | Best for internships + entry-level     |
| Unstop        | yes          | ✅            | low              | Competitions + jobs mixed              |
| YCombinator   | **no**       | global        | low              | Public; Work at a Startup feed          |
| Cutshort      | **no**       | ✅            | low              | Public listings; Indian unicorns       |

## How a platform module is structured

Each `src/platforms/<name>.py` subclasses `BasePlatform` and implements:

```python
async def collect_jobs(self, page, filters: dict) -> list[Job]:
    # 1. ensure_logged_in(page)
    # 2. for each keyword × location: open search URL, paginate
    # 3. extract job_id, title, company, location, posted_at, url
    # 4. open each match URL in same context (cookies preserved)
    # 5. scrape full JD, salary text, applicants text
    # 6. return list[Job]
```

`BasePlatform` provides:
- `name` — short id used in registry and CSV
- `session_path` — where to save cookies
- `ensure_logged_in(page)` — checks for the "you are logged in" sentinel,
  else runs `login(page)` and saves a fresh session

## Per-platform login flow

### LinkedIn
- First-time run: a manual 2FA SMS / authenticator app step is unavoidable.
- Session cookies persist for ~30 days then need re-auth.
- LinkedIn aggressively detects automation. Stick to read-only scraping
  with reasonable delays (`random_delay()` between actions = 3–6s).

### Naukri
- Email + password works; rarely 2FA.
- Daily job-alert page is a goldmine — consider scraping that too.

### Indeed
- First search WILL trigger a CAPTCHA. Run non-headless once.
- After clearing, cookies are good for ~7 days.

### Wellfound (AngelList)
- Profile must be filled out on Wellfound first; without it, recruiters can't
  message you back even if you apply. (We don't apply, but bear in mind.)

### YCombinator
- Public, no login. We scrape `https://www.ycombinator.com/jobs`.
- They sometimes lazy-load with React; if 0 jobs returned, the React mount
  hadn't completed before we read the DOM. The default `wait_for_selector`
  with a 5s timeout fixes 95% of these.

### Cutshort
- Public listings page. India-focused, lots of unicorn jobs.

## Disabling a platform

Just remove it from `config/profile.yaml`:

```yaml
search:
  platforms:
    - linkedin
    - naukri
    - ycombinator
    # don't include the ones you skip
```

If `search.platforms` is not set, the bot runs all registered platforms.

## Rate limits and politeness

Each platform module uses `random_delay(3, 6)` between actions and
`jd_jitter()` (2–4s) between opening each job's detail page. This is the
single most effective anti-ban behaviour in this codebase. Don't lower it.

## When platforms inevitably break

Job sites refactor their DOM every few months. Symptoms:
- 0 jobs returned but no error
- "selector did not match" errors in logs
- bot freezes on the search page

Fix:
1. Open the platform in a normal browser
2. DevTools → inspect the job-card element
3. Update the selector at the top of the platform module
4. Re-run

The two new public scrapers (`ycombinator.py`, `cutshort.py`) deliberately
fall back to `main, article` for JD text — so even if the title/company
selectors shift, you still get usable text from each match.
