#!/usr/bin/env python3
from pathlib import Path
import csv
import sys

BASE = Path("/Users/josephshackelford/Desktop/SportsBook Training/mmodel_turnkey_complete")

ALIASES = {
    # Today’s slate / common Odds API display names
    "Miami (OH) RedHawks": "Miami OH",
    "GW Revolutionaries": "George Washington",
    "Saint Joseph's Hawks": "Saint Joseph's",
    "Kent State Golden Flashes": "Kent St.",
    "Prairie View Panthers": "Prairie View A&M",

    # Useful common display-name cleanups
    "Wake Forest Demon Deacons": "Wake Forest",
    "Navy Midshipmen": "Navy",
    "Bradley Braves": "Bradley",
    "Dayton Flyers": "Dayton",
    "California Golden Bears": "California",
    "Colorado St. Rams": "Colorado St.",
    "Illinois St. Redbirds": "Illinois St.",
    "Lehigh Mountain Hawks": "Lehigh",
    "Murray St. Racers": "Murray St.",
    "Nevada Wolf Pack": "Nevada",
    "New Mexico Lobos": "New Mexico",
    "Sam Houston St. Bearkats": "Sam Houston St.",
    "SMU Mustangs": "SMU",
    "Utah Valley Wolverines": "Utah Valley",
    "Prairie View A&M Panthers": "Prairie View A&M",
    "St. Thomas (MN) Tommies": "St. Thomas",
}

FILES = [
    BASE / "Schedule.csv",
    BASE / "cbb_cache" / "GameInputs.csv",
]

BLENDED = BASE / "cbb_cache" / "BlendedRatings.csv"


def load_canonical_names():
    names = set()
    with BLENDED.open(newline="") as f:
        r = csv.reader(f)
        header = next(r, None)
        for row in r:
            if row and row[0]:
                names.add(row[0].strip())
    return names


def rewrite_csv(path: Path, canonical_names: set[str]) -> None:
    with path.open(newline="") as f:
        r = csv.DictReader(f)
        rows = list(r)
        fields = r.fieldnames

    for row in rows:
        for col in ("Home Team", "Away Team"):
            t = (row.get(col) or "").strip()
            if t in ALIASES:
                row[col] = ALIASES[t]

    unresolved = set()
    for row in rows:
        for col in ("Home Team", "Away Team"):
            t = (row.get(col) or "").strip()
            if t and t not in canonical_names:
                unresolved.add(t)

    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    if unresolved:
        print(f"UNRESOLVED in {path}:")
        for t in sorted(unresolved):
            print(f"  - {t}")
        raise SystemExit(1)

    print(f"Canonicalized names in {path}")


def main():
    canonical_names = load_canonical_names()
    for p in FILES:
        rewrite_csv(p, canonical_names)
    print("Name canonicalization passed.")


if __name__ == "__main__":
    main()
