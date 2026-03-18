#!/usr/bin/env python3
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

target = Path("/Users/josephshackelford/Desktop/SportsBook Training/mmodel_turnkey_complete/extract_schedule_from_workbook_two_tabs.py")
if not target.exists():
    sys.exit(f"Target file not found: {target}")

src = target.read_text()

backup = target.with_suffix(target.suffix + ".bak_etnormalize")
shutil.copy2(target, backup)

new_func = '''def normalize_date(x):
    if x is None or x == "":
        return ""
    s = str(x).strip()
    if not s:
        return ""

    # Primary path: treat commence timestamps as UTC and convert to ET slate date
    try:
        ts = pd.to_datetime(s, utc=True, errors="raise")
        if pd.isna(ts):
            return ""
        return ts.tz_convert("America/New_York").strftime("%Y-%m-%d")
    except Exception:
        pass

    # Fallback for plain date / non-timezone values
    try:
        ts = pd.to_datetime(s, errors="raise")
        if pd.isna(ts):
            return ""
        return ts.strftime("%Y-%m-%d")
    except Exception:
        return s[:10]
'''

pattern = re.compile(r'(?ms)^def normalize_date\([^\)]*\):\n.*?(?=^def |\Z)')
m = pattern.search(src)
if not m:
    print("Could not find def normalize_date(...).")
    print(f"Backup saved to: {backup}")
    sys.exit(1)

patched = src[:m.start()] + new_func + "\n\n" + src[m.end():]
target.write_text(patched)

print(f"Patched normalize_date() to use ET in: {target}")
print(f"Backup saved to: {backup}")
