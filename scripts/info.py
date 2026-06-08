"""
Print a one-screen summary of repo state — useful when you forget where you
left off.

Usage:  python scripts/info.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    print("=" * 60)
    print(" JOB SEARCH COPILOT  -  repo info")
    print("=" * 60)

    py_files = sorted(ROOT.rglob("*.py"))
    py_files = [p for p in py_files if ".venv" not in p.parts and "__pycache__" not in p.parts]
    total_lines = sum(len(p.read_text().splitlines()) for p in py_files)
    print(f" Python files: {len(py_files)}  ({total_lines} lines)")

    plats = list((ROOT / "src" / "platforms").glob("*.py"))
    plats = [p for p in plats if p.name not in ("__init__.py", "base.py", "registry.py")]
    print(f" Platforms   : {len(plats)}  ({', '.join(sorted(p.stem for p in plats))})")

    data = ROOT / "data" / "jobs.csv"
    if data.exists():
        rows = max(0, len(data.read_text().splitlines()) - 1)
        print(f" Tracker     : {rows} jobs in data/jobs.csv")
    else:
        print(" Tracker     : (no data/jobs.csv yet — run the bot)")

    reports = sorted((ROOT / "reports").glob("*/README.md")) if (ROOT / "reports").exists() else []
    print(f" Reports     : {len(reports)} daily reports under reports/")

    git_head = ROOT / ".git" / "HEAD"
    if git_head.exists():
        print(f" Git HEAD    : {git_head.read_text().strip()}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
