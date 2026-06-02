# Job Search Copilot (formerly Job Apply Bot)

Read-only job search assistant. Now strictly:

1. Logs into each platform
2. Searches by keyword + location
3. Scrapes the full JD for every match
4. Scores fit with Groq (llama-3.3-70b)
5. Writes a daily ranked markdown report

It NEVER submits an application. That's your job.

## Modules removed in this refactor
- `anti_detection.py` (Bezier mouse, stealth — unneeded read-only)
- `ai_form_filler.py` (LLM form filler for auto-apply)
- `monitor.py` (health monitor)
- `notifications.py` (Slack/Discord on apply)
- `resume_parser.py` (PDF → profile.yaml, out of scope)

See CHANGELOG.md for the rationale.
