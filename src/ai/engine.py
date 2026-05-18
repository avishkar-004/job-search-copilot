"""
AI engine for the Job Search Copilot.

Responsibilities:
  - Score each Job against the candidate profile (Groq llama-3.3-70b by default)
  - Surface matched_skills, missing_skills, red_flags, one_line_summary
  - Generate tailored resume bullets + cover letter for high-fit jobs
  - Cache results by job_hash so re-runs do not re-spend tokens
  - Enforce a token-bucket rate limit (Groq free tier: 30 req/min)
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Optional

import httpx

from ..output.atomic_io import atomic_write_json
from ..types import Job

logger = logging.getLogger(__name__)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

_MAX_RETRIES = 4
_RETRY_BASE_DELAY = 2.0

# AI score cache lives on disk so repeat runs are free.
_CACHE_PATH = Path("logs/ai_cache.json")


# ---------------------------------------------------------------------------
# Token bucket rate limiter — never trip Groq's 30 req/min free tier
# ---------------------------------------------------------------------------

class _TokenBucket:
    """Simple async token-bucket. Default = 25 req/min (under Groq's 30)."""

    def __init__(self, rate_per_min: int = 25):
        self.capacity = rate_per_min
        self.tokens = float(rate_per_min)
        self.refill_per_sec = rate_per_min / 60.0
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.last_refill) * self.refill_per_sec)
                self.last_refill = now
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return
                wait = (1.0 - self.tokens) / self.refill_per_sec
                logger.debug("rate limiter: sleeping %.2fs", wait)
                await asyncio.sleep(wait)


_RATE_LIMITER = _TokenBucket(rate_per_min=25)


# ---------------------------------------------------------------------------
# Disk cache helpers
# ---------------------------------------------------------------------------

def _load_cache() -> dict:
    if not _CACHE_PATH.exists():
        return {}
    try:
        with open(_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("AI cache unreadable, starting fresh: %s", exc)
        return {}


def _save_cache(cache: dict) -> None:
    try:
        atomic_write_json(_CACHE_PATH, cache)
    except Exception as exc:
        logger.warning("Failed to persist AI cache: %s", exc)


# ---------------------------------------------------------------------------
# Core HTTP — Groq / Gemini
# ---------------------------------------------------------------------------

async def call_ai(prompt: str, config, *, max_tokens: int = 1024, temperature: float = 0.3) -> str:
    """Send a prompt to the configured AI provider. Retries on 429s."""
    provider = config.ai.provider.lower()
    api_key = config.ai.api_key
    model = config.ai.model

    for attempt in range(_MAX_RETRIES):
        await _RATE_LIMITER.acquire()
        try:
            if provider == "groq":
                return await _call_groq(prompt, model, api_key, max_tokens, temperature)
            if provider == "gemini":
                return await _call_gemini(prompt, model, api_key, max_tokens, temperature)
            raise ValueError(f"Unknown AI provider: {provider!r}. Use 'groq' or 'gemini'.")

        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                wait = _RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning("AI provider %s rate-limited (429). Retry %d/%d in %.1fs",
                               provider, attempt + 1, _MAX_RETRIES, wait)
                await asyncio.sleep(wait)
            else:
                logger.error("AI API error %d: %s", exc.response.status_code, exc.response.text[:300])
                raise
        except httpx.RequestError as exc:
            wait = _RETRY_BASE_DELAY * (2 ** attempt)
            logger.warning("Network error calling %s: %s — retrying in %.1fs", provider, exc, wait)
            await asyncio.sleep(wait)

    raise RuntimeError(f"AI call failed after {_MAX_RETRIES} retries.")


async def _call_groq(prompt: str, model: str, api_key: str, max_tokens: int, temperature: float) -> str:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(GROQ_API_URL, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


async def _call_gemini(prompt: str, model: str, api_key: str, max_tokens: int, temperature: float) -> str:
    url = GEMINI_API_URL.format(model=model)
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
    }
    headers = {"X-goog-api-key": api_key, "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


# ---------------------------------------------------------------------------
# JSON extraction — AI sometimes wraps JSON in markdown
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> Any:
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        try:
            return json.loads(fence.group(1).strip())
        except json.JSONDecodeError:
            pass

    for pat in (r"\{[\s\S]*\}", r"\[[\s\S]*\]"):
        m = re.search(pat, text)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass

    raise ValueError(f"Could not extract JSON from AI response:\n{text[:500]}")


# ---------------------------------------------------------------------------
# Public AI functions
# ---------------------------------------------------------------------------

async def score_job(job: Job, profile, config) -> dict:
    """
    Score a Job against the profile. Returns:

        {
            "fit_score": int 0-100,
            "matched_skills": [...],
            "missing_skills": [...],
            "red_flags": [...],
            "one_line_summary": "...",
        }

    Cached by job_hash on disk; re-runs are free.
    """
    cache = _load_cache()
    key = job.job_hash()
    cached = cache.get(key)
    if cached and "fit_score" in cached:
        logger.debug("ai_engine: cache hit for %s", job)
        return cached

    salary_floor = (config.search.get("preferred_min_ctc_lpa") if hasattr(config, "search") else None) or 0

    prompt = f"""You are a senior tech recruiter screening a candidate.

CANDIDATE PROFILE:
Name: {profile.personal.full_name}
Education: {profile.education.degree} in {profile.education.major}, {profile.education.university} (graduating {profile.education.graduation_year}, CGPA {profile.education.cgpa}/10)
Current role: {profile.experience.current_role} at {profile.experience.current_company} ({profile.experience.years} year)
Skills: {profile.skills.primary}
Summary: {profile.skills.summary}
Resume excerpt:
{str(profile.resume.text)[:1200]}
Preferred minimum CTC (LPA): {salary_floor}
Work authorization: {profile.experience.work_authorization}; needs sponsorship: {profile.experience.require_sponsorship}

JOB POSTING:
Platform: {job.platform}
Title: {job.title}
Company: {job.company}
Location: {job.location}
Salary text: {job.salary_text or "N/A"}
Applicants: {job.applicants_text or "N/A"}
Posted at: {job.posted_at or "N/A"}
Full JD:
{job.jd_text[:3500]}

TASK: Score the fit and surface red flags.
Respond ONLY with valid JSON (no markdown fence, no prose) in EXACTLY this shape:
{{
  "fit_score": <integer 0-100>,
  "matched_skills": ["<skill>", ...],
  "missing_skills": ["<skill>", ...],
  "red_flags": ["<flag>", ...],
  "one_line_summary": "<<=20 word elevator pitch of the role + fit verdict>"
}}

Score guide:
- 85-100: Excellent — most requirements met, role + seniority aligned
- 65-84: Good — core skills match, minor gaps
- 40-64: Partial — relevant but notable gaps
- 0-39: Poor — significant mismatch

Red-flag examples (only list if literally true): "8+ years exp required", "requires US work auth", "internship not allowed", "below user's salary floor of {salary_floor} LPA", "senior/staff role"
"""

    try:
        raw = await call_ai(prompt, config, max_tokens=900)
        result = _extract_json(raw)
        result["fit_score"] = max(0, min(100, int(result.get("fit_score", 0))))
        result.setdefault("matched_skills", [])
        result.setdefault("missing_skills", [])
        result.setdefault("red_flags", [])
        result.setdefault("one_line_summary", "")
    except Exception as exc:
        logger.error("score_job failed for %s: %s", job, exc)
        result = {
            "fit_score": 0,
            "matched_skills": [],
            "missing_skills": [],
            "red_flags": [f"AI error: {exc}"],
            "one_line_summary": "Could not score (AI error).",
        }

    # Persist
    cache[key] = result
    _save_cache(cache)
    return result


async def tailor_resume_bullets(job: Job, profile, config) -> list[str]:
    """Generate 5 resume bullets tailored to this JD, anchored on the user's projects."""
    prompt = f"""You are a resume coach. Write 5 resume bullets tailored to the job below.

STRICT RULES:
- Use only true facts from the candidate's resume — never fabricate metrics, projects, or technologies.
- Anchor on the candidate's 3 main projects (MiniDB, StreamFlow, VectorFlow) when relevant.
- Each bullet starts with a strong action verb; <= 120 characters.
- Emphasize skills/keywords from the JD that the candidate actually has.

JOB:
Title: {job.title} @ {job.company}
JD: {job.jd_text[:1800]}

CANDIDATE RESUME:
{str(profile.resume.text)[:1500]}

Return ONLY a JSON array of 5 strings, e.g. ["bullet 1", "bullet 2", ...]"""
    try:
        raw = await call_ai(prompt, config, max_tokens=700)
        result = _extract_json(raw)
        if isinstance(result, list):
            return [str(b).strip("- ").strip() for b in result[:5]]
        if isinstance(result, dict):
            for k in ("bullets", "items", "result"):
                if k in result and isinstance(result[k], list):
                    return [str(b).strip("- ").strip() for b in result[k][:5]]
        return []
    except Exception as exc:
        logger.error("tailor_resume_bullets failed for %s: %s", job, exc)
        return []


async def generate_cover_letter(job: Job, profile, config) -> str:
    """3-paragraph customised cover letter."""
    prompt = f"""Write a 3-paragraph cover letter for this job. No "I am writing to apply" filler.

STRUCTURE:
- Paragraph 1: Hook + the candidate's single strongest match to {job.company} and the {job.title} role.
- Paragraph 2: One specific project/achievement (use MiniDB, StreamFlow, or VectorFlow — whichever is most relevant)
  with concrete numbers, that addresses what the JD asks for.
- Paragraph 3: Why {job.company} specifically + clear call to action.

CANDIDATE:
{profile.personal.full_name} | {profile.education.degree} {profile.education.major},
{profile.education.university} (graduating {profile.education.graduation_year}).
Skills: {profile.skills.primary}
Resume excerpt: {str(profile.resume.text)[:1200]}

JOB:
Title: {job.title}
Company: {job.company}
JD excerpt: {job.jd_text[:1500]}

Return only the cover letter text, no preamble."""
    try:
        raw = await call_ai(prompt, config, max_tokens=700)
        return raw.strip().strip('"').strip("```").strip()
    except Exception as exc:
        logger.error("generate_cover_letter failed for %s: %s", job, exc)
        return (
            f"Dear {job.company} team,\n\n"
            f"I am a final-year {profile.education.major} student with strong systems projects "
            f"(MiniDB, StreamFlow, VectorFlow) and am excited about the {job.title} role. "
            f"I would welcome the chance to discuss how I can contribute."
        )
