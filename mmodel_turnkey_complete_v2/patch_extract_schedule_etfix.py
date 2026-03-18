#!/usr/bin/env python3
from __future__ import annotations

import re
import shutil
from pathlib import Path


def main() -> None:
    target = Path(
        "/Users/josephshackelford/Desktop/SportsBook Training/mmodel_turnkey_complete/extract_schedule_from_workbook_two_tabs.py"
    )
    if not target.exists():
        raise SystemExit(f"Target file not found: {target}")

    src = target.read_text()

    backup = target.with_suffix(target.suffix + ".bak_etfix")
    shutil.copy2(target, backup)

    new = src

    helper = 