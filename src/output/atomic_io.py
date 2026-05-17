"""
Atomic file-write helpers.

Writes go to <path>.tmp then `os.replace` to the final path so a Ctrl+C
mid-write can never leave a half-written CSV or markdown file on disk.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Union


def atomic_write_text(path: Union[str, Path], content: str, encoding: str = "utf-8") -> None:
    """Write text atomically: write to <path>.tmp then rename."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding=encoding, newline="") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)


def atomic_write_json(path: Union[str, Path], data: object, indent: int = 2) -> None:
    """Serialize and write JSON atomically."""
    atomic_write_text(path, json.dumps(data, indent=indent, ensure_ascii=False))
