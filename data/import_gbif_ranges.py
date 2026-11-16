"""
Import geographic ranges from a GBIF SQL download into geo_bounding_box.

The download (one row per GBIF species) holds the 0.5% and 99.5% percentiles of
the latitude and longitude of its wild records, so zoo and stray records don't
stretch a range. Submitted with E:/AnimalKingdomSystem/gbif_ranges/gbif_sql_download.py
on 2026-11-11 (DOI 10.15468/dl.5v8cu8, ~1 h on GBIF's side).

Rules (geo_range.py): at least 10 wild records; a longitude span over 340° crosses
the 180° line, so only latitude is kept. Extinct species and rows outside the tree
are skipped. A synonym's range goes to its accepted species unless that species has
its own row; of several synonyms the best recorded wins.

Existing ranges are replaced; the old geo_bounding_box and trait_sources are
appended to the backup file first. Writes go in short transactions of 1,000 rows,
so a running backend isn't blocked. Re-running skips rows that already hold the
new range. Seconds for the dry run; ~15 min for a full real run (172k rows,
2026-11-11), seconds for a re-run.

Usage:
    python data/import_gbif_ranges.py --dry-run
    python data/import_gbif_ranges.py [--csv FILE] [--min-records 10] [--backup FILE]
"""

import argparse
import csv
import json
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
from app import database, geo_range  # noqa: E402

DEFAULT_CSV = "E:/AnimalKingdomSystem/gbif_ranges/0001920-261110092616502.csv"
DEFAULT_BACKUP = "E:/AnimalKingdomSystem/gbif_ranges_backup.jsonl"
DEFAULT_DOI = "10.15468/dl.5v8cu8"
_EDGES = ("lat_min", "lat_max", "lon_min", "lon_max")


def read_ranges(csv_path: Path, min_records: int = geo_range.MIN_RECORDS) -> dict[str, dict]:
    """Species name -> range dict. Of two rows with the same name, the better recorded wins."""
    out: dict[str, dict] = {}
    with open(csv_path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            n = int(row["n"] or 0)
            name = (row["species"] or "").strip()
            if not name or n < min_records or any(not row[e] for e in _EDGES):
                continue
            if name in out and out[name]["records"] >= n:
                continue
            countries = int(row["countries"]) if row.get("countries") else None
            out[name] = geo_range.make_range(*(float(row[e]) for e in _EDGES), n, countries)
    return out


def _usable(row: sqlite3.Row | None) -> bool:
    return (row is not None and row["taxonomic_status"] == "ACCEPTED"
            and row["taxon_path"] is not None and row["extinct"] != 1)


def match_ranges(conn: sqlite3.Connection, ranges: dict[str, dict]) -> tuple[dict[str, dict], Counter]:
    """Target scientific_name -> range, and counts per kind of match. Only exact
    primary-key matches: a homonym row "Name [Parent]" never matches "Name"."""
    has_accepted = "accepted_name" in {r[1] for r in conn.execute("PRAGMA table_info(species)")}
    cols = "scientific_name, taxonomic_status, taxon_path, extinct" + (", accepted_name" if has_accepted else "")
    lookup = f"SELECT {cols} FROM species WHERE scientific_name = ?"
    counts: Counter = Counter()
    updates: dict[str, dict] = {}
    synonyms: list[tuple[str, dict]] = []
    for name, rng in ranges.items():
        row = conn.execute(lookup, (name,)).fetchone()
        if row is None:
            counts["no_match"] += 1
        elif row["taxonomic_status"] == "SYNONYM":
            synonyms.append((row["accepted_name"] if has_accepted else None, rng))
        elif row["taxon_path"] is None or row["taxonomic_status"] != "ACCEPTED":
            counts["outside_tree"] += 1
        elif row["extinct"] == 1:
            counts["extinct"] += 1
        else:
            updates[name] = rng
            counts["accepted"] += 1
    from_synonyms: dict[str, dict] = {}
    for target, rng in synonyms:
        if not target or not _usable(conn.execute(lookup, (target,)).fetchone()):
            counts["synonym_unusable"] += 1
            continue
        counts["synonym"] += 1
        if target in updates:
            continue          # the accepted species has its own range
        if target not in from_synonyms or from_synonyms[target]["records"] < rng["records"]:
            from_synonyms[target] = rng
    updates.update(from_synonyms)
    return updates, counts


def apply_ranges(updates: dict[str, dict], source: str, backup_path: Path, batch: int = 1000) -> int:
    """Write the ranges with provenance, in short transactions. Returns rows changed."""
    names = list(updates)
    changed = 0
    backup_path = Path(backup_path)
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    conn = database.get_connection()
    try:
        with open(backup_path, "a", encoding="utf-8") as backup:
            for i in range(0, len(names), batch):
                conn.execute("BEGIN IMMEDIATE")
                lines = []
                for name in names[i:i + batch]:
                    row = conn.execute("SELECT geo_bounding_box, trait_sources FROM species "
                                       "WHERE scientific_name = ?", (name,)).fetchone()
                    if row is None or database.parse_geo_bbox(row["geo_bounding_box"]) == updates[name]:
                        continue
                    lines.append(json.dumps({"scientific_name": name, "geo_bounding_box": row["geo_bounding_box"],
                                             "trait_sources": row["trait_sources"]}, ensure_ascii=False))
                    sources = database.parse_trait_sources(row["trait_sources"])
                    sources["geo_bounding_box"] = {"source": source, "estimated": False}
                    conn.execute("UPDATE species SET geo_bounding_box = ?, trait_sources = ? "
                                 "WHERE scientific_name = ?",
                                 (database.serialize_geo_bbox(updates[name]),
                                  database.serialize_trait_sources(sources), name))
                # The backup is written before the commit: a crash leaves a backup line
                # for an unchanged row, never a changed row without one.
                if lines:
                    backup.write("".join(line + "\n" for line in lines))
                    backup.flush()
                conn.commit()
                changed += len(lines)
    finally:
        conn.close()
    return changed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", default=DEFAULT_CSV)
    ap.add_argument("--min-records", type=int, default=geo_range.MIN_RECORDS)
    ap.add_argument("--doi", default=DEFAULT_DOI)
    ap.add_argument("--backup", default=DEFAULT_BACKUP)
    ap.add_argument("--dry-run", action="store_true", help="count only, write nothing")
    args = ap.parse_args(argv)

    t0 = time.monotonic()
    ranges = read_ranges(Path(args.csv), args.min_records)
    print(f"GBIF species with {args.min_records}+ wild records: {len(ranges):,}")
    conn = database.get_connection()
    try:
        updates, counts = match_ranges(conn, ranges)
    finally:
        conn.close()
    for key in ("accepted", "synonym", "synonym_unusable", "extinct", "outside_tree", "no_match"):
        print(f"  {key:<17} {counts[key]:>9,}")
    print(f"species to receive a range: {len(updates):,}")
    if not args.dry_run:
        source = f"GBIF occurrences (wild records, 0.5% edges, doi:{args.doi})"
        changed = apply_ranges(updates, source, Path(args.backup))
        print(f"rows changed: {changed:,} (old values in {args.backup})")
    print(f"done in {time.monotonic() - t0:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
