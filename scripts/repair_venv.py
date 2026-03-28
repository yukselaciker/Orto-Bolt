#!/usr/bin/env python3
"""Repair a moved virtualenv after the project folder has been renamed."""

from __future__ import annotations

import re
import sys
from pathlib import Path


VENV_PATH_RE = re.compile(r"/[^\n\"']+?/.venv")
VENV_PYTHON_RE = re.compile(r"/[^\n\"']+?/.venv/bin/python")


def repair_file(path: Path, venv_path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return False

    updated = VENV_PYTHON_RE.sub(f"{venv_path}/bin/python", text)
    updated = VENV_PATH_RE.sub(str(venv_path), updated)

    if updated == text:
        return False

    path.write_text(updated, encoding="utf-8")
    return True


def main() -> int:
    venv_path = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(".venv").resolve()

    if not venv_path.exists():
        print(f"Virtualenv not found: {venv_path}", file=sys.stderr)
        return 1

    candidates = [venv_path / "pyvenv.cfg"]
    candidates.extend(sorted((venv_path / "bin").iterdir()))

    changed = 0
    for candidate in candidates:
        if repair_file(candidate, venv_path):
            changed += 1

    print(f"Repaired {changed} virtualenv launcher file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
