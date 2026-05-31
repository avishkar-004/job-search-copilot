# Changelog

## [Unreleased] — pivot to read-only

### Changed
- **Removed all auto-apply behaviour.** No `apply_to_job()` anywhere.
  Platform modules only search + scrape now.
- Renamed project from "Job Apply Bot" to "Job Search Copilot".
- Each platform's `collect_jobs()` now opens every match URL and scrapes
  the full job description, salary, and applicants text.

### Removed
- `src/anti_detection.py` (Bezier mouse, stealth flags) — unnecessary for
  read-only scraping.
- `src/ai_form_filler.py` (LLM-driven form filler for auto-apply).
- `src/monitor.py` (health monitor / smart pause).
- `src/notifications.py` (Slack/Discord webhooks).
- `src/resume_parser.py` (PDF → profile.yaml; out of scope).

### Added
- `data/ai_cache/` — disk-cached AI responses keyed by `job_hash`.

### Rationale
LinkedIn's automation policy makes auto-submit a permanent-ban risk for
a candidate in active job search. The cost of a ban (recruiter
invisibility for 6-12 months) dwarfs the time saved by automating
clicks. A copilot that drafts materials and leaves submission to the
user is the only safe operating mode.
