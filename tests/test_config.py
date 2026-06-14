"""Tests for the YAML config loader."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from src.config import Config


def _write_config(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "profile.yaml"
    p.write_text(textwrap.dedent(body))
    return p


_MINIMAL_VALID = """
personal:
  full_name: "Test User"
  email: "test@example.com"
  phone: "+91-0000000000"

links:
  linkedin: "https://linkedin.com/in/test"
  github: "https://github.com/test"
  portfolio: "https://test.example"

ai:
  provider: "groq"
  api_key: "test-key"
  model: "llama-3.3-70b-versatile"

search:
  keywords:
    - "Software Engineer"
  locations:
    - "Bangalore, India"
  min_fit_score: 65
  preferred_min_ctc_lpa: 18
  experience_levels:
    - "Entry level"
"""


def test_config_loads_valid_yaml(tmp_path: Path):
    p = _write_config(tmp_path, _MINIMAL_VALID)
    cfg = Config.from_yaml(str(p))
    assert cfg.personal["full_name"] == "Test User"
    assert cfg.links["portfolio"] == "https://test.example"


def test_config_search_keywords_loaded(tmp_path: Path):
    p = _write_config(tmp_path, _MINIMAL_VALID)
    cfg = Config.from_yaml(str(p))
    assert "Software Engineer" in cfg.search["keywords"]


def test_config_min_fit_score_loaded(tmp_path: Path):
    p = _write_config(tmp_path, _MINIMAL_VALID)
    cfg = Config.from_yaml(str(p))
    assert cfg.search["min_fit_score"] == 65


def test_config_fails_loud_on_missing_file(tmp_path: Path):
    nonexistent = tmp_path / "missing.yaml"
    with pytest.raises((FileNotFoundError, Exception)):
        Config.from_yaml(str(nonexistent))


def test_config_real_profile_is_valid():
    """Sanity: the actually-committed profile.yaml loads cleanly."""
    real = Path(__file__).resolve().parents[1] / "config" / "profile.yaml"
    if not real.exists():
        pytest.skip("config/profile.yaml not present in this checkout")
    cfg = Config.from_yaml(str(real))
    # Portfolio URL fix from the refactor should be present
    portfolio = cfg.links.get("portfolio", "")
    assert "github.io" in portfolio
    # And it should be the canonical (not the old /avishkar-004/ path)
    assert not portfolio.endswith("/avishkar-004/"), \
        "Portfolio still has the stale /avishkar-004/ path"
