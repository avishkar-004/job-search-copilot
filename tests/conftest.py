"""Make `import src.*` work from tests without installing the package."""
from __future__ import annotations

import sys
from pathlib import Path

# Repo root is one level up from tests/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
