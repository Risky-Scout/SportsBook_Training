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
backup = target.with_suffix(target.suffix + ".bak_etfix_v2")
shutil.copy2(target, backup)

helper = """
def _et_game_date_from_commence(series):
    ts = pd.to_datetime(series, utc=True, errors="coerce")
    return ts.dt.tz_convert("America/New_York").dt.strftime("%Y-%m-%d")
""".strip()

if "_et_game_date_from_commence" not in src:
    m = re.search(r'^\s*import pandas as pd\s*$', src, re.M)
    if not m:
        sys.exit("Could not find 'import pandas as pd' line.")
    src = src[:m.end()] + "\n\n" + helper + "\n" + src[m.end():]

patterns = [
    re.compile(r'(?m)^(\s*)(\w+)\s*=\s*\2\[\s*\2\["commence"\]\.astype\(str\)\.str\[:10\]\s*==\s*(.+?)\s*\]\s*$'),
    re.compile(r'(?m)^(\s*)(\w+)\s*=\s*\2\[\s*\2\["commence"\]\.str\[:10\]\s*==\s*(.+?)\s*\]\s*$'),
    re.compile(r'(?m)^(\s*)(\w+)\s*=\s*\2\[\s*pd\.to_datetime\(\2\["commence"\][^\n]*?\.dt\.strftime\("%Y-%m-%d"\)\s*==\s*(.+?)\s*\]\s*$'),
]

replacements = 0

def repl(m):
    global replacements
    indent, var, date_expr = m.group(1), m.group(2), m.group(3)
    replacements += 1
    return (
        f'{indent}{var} = {var}.copy()\n'
        f'{indent}{var}["_commence_et_date"] = _et_game_date_from_commence({var}["commence"])\n'
        f'{indent}{var} = {var}[{var}["_commence_et_date"] == {date_expr}].copy()'
    )

new_src = src
for pat in patterns:
    new_src = pat.sub(repl, new_src)

if replacements == 0:
    print("No filter patterns replaced. Lines containing 'commence':")
    for i, line in enumerate(src.splitlines(), 1):
        if "commence" in line:
            print(f"{i}: {line}")
    sys.exit(f"Backup saved to: {backup}")

target.write_text(new_src)
print(f"Patched ET slate-date filtering in: {target}")
print(f"Backup saved to: {backup}")
print(f"Replaced {replacements} UTC-date filter line(s).")
