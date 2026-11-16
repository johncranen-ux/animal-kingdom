"""
Import wild GBIF records per species per country into species_countries.

The download (one row per GBIF species and country) counts the wild records
(human or machine observations, DETECTED, with coordinates and no geospatial
issues) of each animal species per countryCode. Submitted with
E:/AnimalKingdomSystem/gbif_countries/gbif_countries_download.py on 2026-11-12.

Names match as in import_gbif_ranges.py: exact primary keys only; a synonym's
counts go to its accepted species (added to that species' own counts). Extinct
species and rows outside the tree are skipped.

The table is rebuilt in species_countries_new in short transactions, then swapped
in one, so a running backend sees the old or the new table, never half of one.

Usage:
    python data/import_gbif_countries.py --dry-run
    python data/import_gbif_countries.py [--csv FILE]
"""

import argparse
import csv
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
from app import database  # noqa: E402

DEFAULT_CSV = "E:/AnimalKingdomSystem/gbif_countries/0003676-261110092616502.csv"


def read_counts(csv_path: Path) -> dict[str, dict[str, int]]:
    """GBIF species name -> {country code: records}."""
    out: dict[str, dict[str, int]] = defaultdict(dict)
    with open(csv_path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            name = (row["species"] or "").strip()
            code = (row["countrycode"] or "").strip().upper()
            n = int(row["n"] or 0)
            if not name or len(code) != 2 or n <= 0:
                continue
            out[name][code] = out[name].get(code, 0) + n
    return dict(out)


def _usable(row: sqlite3.Row | None) -> bool:
    return (row is not None and row["taxonomic_status"] == "ACCEPTED"
            and row["taxon_path"] is not None and row["extinct"] != 1)


def match_counts(conn: sqlite3.Connection, counts: dict[str, dict[str, int]]
                 ) -> tuple[dict[str, dict[str, int]], Counter]:
    """Tree species -> {country: records}, and counts per kind of match."""
    lookup = ("SELECT scientific_name, taxonomic_status, taxon_path, extinct, accepted_name "
              "FROM species WHERE scientific_name = ?")
    kinds: Counter = Counter()
    out: dict[str, dict[str, int]] = defaultdict(dict)
    for name, by_country in counts.items():
        row = conn.execute(lookup, (name,)).fetchone()
        if row is None:
            kinds["no_match"] += 1
            continue
        if row["taxonomic_status"] == "SYNONYM":
            target = row["accepted_name"]
            row = conn.execute(lookup, (target,)).fetchone() if target else None
            if not _usable(row):
                kinds["synonym_unusable"] += 1
                continue
            kinds["synonym"] += 1
        elif row["taxon_path"] is None or row["taxonomic_status"] != "ACCEPTED":
            kinds["outside_tree"] += 1
            continue
        elif row["extinct"] == 1:
            kinds["extinct"] += 1
            continue
        else:
            kinds["accepted"] += 1
        target = out[row["scientific_name"]]
        for code, n in by_country.items():
            target[code] = target.get(code, 0) + n
    return dict(out), kinds


def write_table(conn: sqlite3.Connection, matched: dict[str, dict[str, int]], batch: int = 20_000) -> int:
    """Rebuild species_countries from `matched`; returns the rows written."""
    conn.execute("DROP TABLE IF EXISTS species_countries_new")
    conn.execute(database._CREATE_SPECIES_COUNTRIES.replace(
        "IF NOT EXISTS species_countries", "species_countries_new"))
    conn.commit()
    rows = [(code, name, n) for name, by_country in matched.items() for code, n in by_country.items()]
    rows.sort()
    for i in range(0, len(rows), batch):
        conn.execute("BEGIN IMMEDIATE")
        conn.executemany("INSERT INTO species_countries_new VALUES (?, ?, ?)", rows[i:i + batch])
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    conn.execute("DROP TABLE IF EXISTS species_countries")
    conn.execute("ALTER TABLE species_countries_new RENAME TO species_countries")
    conn.commit()
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", default=DEFAULT_CSV)
    ap.add_argument("--dry-run", action="store_true", help="count only, write nothing")
    args = ap.parse_args(argv)

    t0 = time.monotonic()
    counts = read_counts(Path(args.csv))
    print(f"GBIF species: {len(counts):,}, species-country rows: {sum(map(len, counts.values())):,}")
    conn = database.get_connection()
    try:
        matched, kinds = match_counts(conn, counts)
        for key in ("accepted", "synonym", "synonym_unusable", "extinct", "outside_tree", "no_match"):
            print(f"  {key:<17} {kinds[key]:>9,}")
        print(f"tree species with country records: {len(matched):,}")
        if not args.dry_run:
            print(f"rows written: {write_table(conn, matched):,}")
    finally:
        conn.close()
    print(f"done in {time.monotonic() - t0:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
