"""Tests for atomic_io — writes must never leave a half-written file behind."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.output.atomic_io import atomic_write_text, atomic_write_json


def test_atomic_write_text_creates_file(tmp_path: Path):
    target = tmp_path / "out.txt"
    atomic_write_text(target, "hello world")
    assert target.read_text() == "hello world"


def test_atomic_write_text_creates_parent_dirs(tmp_path: Path):
    target = tmp_path / "deeply" / "nested" / "out.txt"
    atomic_write_text(target, "ok")
    assert target.read_text() == "ok"


def test_atomic_write_text_overwrites_existing(tmp_path: Path):
    target = tmp_path / "out.txt"
    target.write_text("old")
    atomic_write_text(target, "new")
    assert target.read_text() == "new"


def test_atomic_write_text_no_temp_left_behind(tmp_path: Path):
    target = tmp_path / "out.txt"
    atomic_write_text(target, "ok")
    # After a successful write there should be no `.tmp` siblings
    leftovers = list(tmp_path.glob("*.tmp"))
    assert leftovers == []


def test_atomic_write_json_creates_valid_json(tmp_path: Path):
    target = tmp_path / "data.json"
    payload = {"name": "Avishkar", "skills": ["C++", "Java", "Python"], "n": 42}
    atomic_write_json(target, payload)
    assert json.loads(target.read_text()) == payload


def test_atomic_write_json_handles_unicode(tmp_path: Path):
    target = tmp_path / "data.json"
    payload = {"city": "Pūne", "emoji": "🚀"}
    atomic_write_json(target, payload)
    assert json.loads(target.read_text()) == payload
