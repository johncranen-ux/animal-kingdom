"""
Flag fossil taxa as extinct from the local GBIF Backbone (no network).

Pass 1 — species. The backbone records, per taxon, which checklist it was taken
from. Species whose source is the Paleobiology Database (PBDB) are fossil-only:
living species come from the Catalogue of Life and other extant checklists.
Checked on Tapiridae (all 55 PBDB-sourced species are fossils) and against every
IUCN-assessed animal row (no PBDB-sourced animal species is assessed as living).
The signal is one-way: PBDB-sourced -> extinct = 1. Any other source stays NULL
(unknown); the on-demand GBIF species-profile lookup fills those later.

Higher ranks are NOT taken from PBDB: the backbone uses PBDB as the source of
some groups with living members (the order Sirenia — manatees and dugongs).

Pass 2 — higher ranks. A genus / family / order / ... is flagged only when it
has accepted species and every one of them is extinct = 1 (from pass 1 or from
GBIF species profiles). Correct by construction; re-run after more flags arrive.

Rules for both passes:
  * kingdom Animalia only
  * pass 1 matches the DB row on name AND full taxon_path (rules out homonyms)
  * never overwrite an existing extinct value (GBIF profiles win)
  * skip rows with an IUCN status other than EX (assessed as living)
  * provenance goes to trait_sources["extinct"]

Idempotent; re-running only fills what is still NULL.

Usage:
    python data/backfill_extinct.py                       # default backbone path
    python data/backfill_extinct.py <data dir>/gbif/backbone --dry-run
"""

import argparse
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Iterable, Iterator

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
from app.paths import data_path  # noqa: E402
from app import database

PBDB_DATASET_ID  = "c33ce2f2-c3cc-43a5-a380-fe4526d63650"
PBDB_SOURCE      = "GBIF backbone (Paleobiology Database)"
DEFAULT_BACKBONE = str(data_path("gbif", "backbone"))
BATCH = 900   # stays under SQLite's 999 host-parameter limit

# Taxon.tsv column positions (see meta.xml)
_DATASET, _CANONICAL, _RANK, _STATUS = 1, 7, 11, 14
_KINGDOM, _GENUS = 17, 22
_SPECIES_RANKS = {"species", "subspecies", "variety", "form", "infraspecies"}


rollup_source = database.extinct_rollup_source   # same label as the live roll-up


def taxon_path(cols: list[str]) -> str:
    """Same lineage path data/import_gbif.py builds for a backbone row."""
    parts = [v.strip() for v in cols[_KINGDOM:_GENUS + 1] if v.strip()]
    canonical = cols[_CANONICAL].strip()
    if cols[_RANK].strip().lower() in _SPECIES_RANKS and canonical and (not parts or parts[-1] != canonical):
        parts.append(canonical)
    return "|".join(parts)


def pbdb_species(lines: Iterable[str]) -> Iterator[tuple[str, str]]:
    """Yield (canonical name, taxon_path) for accepted PBDB-sourced animal species
    and infraspecific taxa (higher ranks are left to the roll-up)."""
    for line in lines:
        cols = line.rstrip("\r\n").split("\t")
        if len(cols) <= _GENUS:
            continue
        if (cols[_DATASET] == PBDB_DATASET_ID and cols[_KINGDOM] == "Animalia"
                and cols[_STATUS] == "accepted" and cols[_CANONICAL].strip()
                and cols[_RANK].strip().lower() in _SPECIES_RANKS):
            yield cols[_CANONICAL].strip(), taxon_path(cols)


def plan_update(row: dict, source: str, expected_path: str | None = None) -> tuple[str, str | None]:
    """(outcome, new trait_sources JSON or None) for one DB row."""
    if expected_path is not None and (row.get("taxon_path") or "") != expected_path:
        return "path_mismatch", None
    if row.get("extinct") is not None:
        return "already_set", None
    if row.get("iucn_status") not in (None, "", "EX"):
        return "assessed_living", None
    sources = database.parse_trait_sources(row.get("trait_sources"))
    sources["extinct"] = {"source": source, "estimated": False}
    return "flagged", database.serialize_trait_sources(sources)


def species_counts(species: Iterable[tuple[str, int | None]]) -> dict[str, list[int]]:
    """{ancestor taxon_path: [accepted species, extinct species]} from
    (taxon_path, extinct) pairs of accepted species."""
    counts: dict[str, list[int]] = {}
    for path, extinct in species:
        segs = path.split("|")
        for i in range(1, len(segs)):
            c = counts.setdefault("|".join(segs[:i]), [0, 0])
            c[0] += 1
            c[1] += extinct == 1
    return counts


def extinct_groups(counts: dict[str, list[int]]) -> dict[str, int]:
    """{taxon_path: species count} for groups whose species are all extinct."""
    return {p: n for p, (n, x) in counts.items() if n and n == x}


# ── DB passes ─────────────────────────────────────────────────────────────────

_COLS = "scientific_name, taxon_path, taxon_rank, extinct, iucn_status, trait_sources"


def _write(conn, updates: list[tuple[str, str]], dry_run: bool) -> None:
    if updates and not dry_run:
        conn.executemany(
            "UPDATE species SET extinct = 1, trait_sources = ? WHERE scientific_name = ?", updates
        )
        conn.commit()


def _species_batch(conn, batch: dict[str, str], stats: Counter, dry_run: bool) -> None:
    ph = ",".join("?" * len(batch))
    rows = conn.execute(
        f"SELECT {_COLS} FROM species WHERE scientific_name IN ({ph})", list(batch)
    ).fetchall()
    stats["not_in_db"] += len(batch) - len(rows)
    updates = []
    for row in map(dict, rows):
        outcome, ts = plan_update(row, PBDB_SOURCE, batch[row["scientific_name"]])
        stats[outcome] += 1
        if ts:
            updates.append((ts, row["scientific_name"]))
    _write(conn, updates, dry_run)


def species_pass(conn, tsv: Path, dry_run: bool) -> Counter:
    stats: Counter = Counter()
    batch: dict[str, str] = {}
    with open(tsv, encoding="utf-8", errors="replace", newline="") as f:
        next(f)  # header
        for name, path in pbdb_species(f):
            stats["pbdb_species"] += 1
            batch[name] = path
            if len(batch) >= BATCH:
                _species_batch(conn, batch, stats, dry_run)
                batch.clear()
    if batch:
        _species_batch(conn, batch, stats, dry_run)
    return stats


def rollup_pass(conn, dry_run: bool, pass1_flagged: set[str] = frozenset()) -> tuple[Counter, Counter]:
    """Flag higher-rank rows whose accepted species are all extinct. In a dry run
    `pass1_flagged` (species names pass 1 would flag) stands in for the writes."""
    species = (
        (path, 1 if name in pass1_flagged else extinct)
        for name, path, extinct in conn.execute(
            "SELECT scientific_name, taxon_path, extinct FROM species "
            "WHERE taxon_rank = 'species' AND taxonomic_status = 'ACCEPTED' "
            "AND taxon_path LIKE 'Animalia|%'"
        )
    )
    groups = extinct_groups(species_counts(species))
    stats, ranks = Counter(groups=len(groups)), Counter()
    paths = list(groups)
    for i in range(0, len(paths), BATCH):
        chunk = paths[i:i + BATCH]
        rows = conn.execute(
            f"SELECT {_COLS} FROM species WHERE taxon_path IN ({','.join('?' * len(chunk))}) "
            f"AND taxon_rank NOT IN ({','.join('?' * len(_SPECIES_RANKS))})",
            [*chunk, *_SPECIES_RANKS],
        ).fetchall()
        updates = []
        for row in map(dict, rows):
            outcome, ts = plan_update(row, rollup_source(groups[row["taxon_path"]]))
            stats[outcome] += 1
            if ts:
                ranks[row.get("taxon_rank") or "?"] += 1
                updates.append((ts, row["scientific_name"]))
        _write(conn, updates, dry_run)
    return stats, ranks


def _pass1_names(tsv: Path, conn) -> set[str]:
    """Names pass 1 would flag (dry run only)."""
    want = dict(pbdb_species(open(tsv, encoding="utf-8", errors="replace", newline="")))
    names, keys = set(), list(want)
    for i in range(0, len(keys), BATCH):
        chunk = keys[i:i + BATCH]
        for row in conn.execute(
            f"SELECT {_COLS} FROM species WHERE scientific_name IN ({','.join('?' * len(chunk))})", chunk
        ):
            row = dict(row)
            if plan_update(row, PBDB_SOURCE, want[row["scientific_name"]])[0] == "flagged":
                names.add(row["scientific_name"])
    return names


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("backbone", nargs="?", default=DEFAULT_BACKBONE,
                        help="directory containing Taxon.tsv")
    parser.add_argument("--dry-run", action="store_true", help="report counts, write nothing")
    parser.add_argument("--rollup-only", action="store_true",
                        help="skip the GBIF species pass (no backbone needed); use after a COL build")
    args = parser.parse_args()

    tsv = Path(args.backbone) / "Taxon.tsv"
    if not args.rollup_only and not tsv.exists():
        sys.exit(f"ERROR: {tsv} not found (the GBIF backbone was deleted 2026-11-10; use --rollup-only)")

    t0 = time.monotonic()
    conn = database.get_connection()
    try:
        s1 = None if args.rollup_only else species_pass(conn, tsv, args.dry_run)
        pending = _pass1_names(tsv, conn) if args.dry_run and s1 is not None else frozenset()
        s2, ranks = rollup_pass(conn, args.dry_run, pending)
    finally:
        conn.close()

    print(f"{'DRY RUN - ' if args.dry_run else ''}finished in {time.monotonic() - t0:.0f}s")
    if s1 is not None:
        print("Pass 1 (PBDB species):")
        for key in ("pbdb_species", "flagged", "already_set", "assessed_living", "path_mismatch", "not_in_db"):
            print(f"  {key:16} {s1[key]:>9,}")
    print("Pass 2 (all-extinct groups):")
    for key in ("groups", "flagged", "already_set", "assessed_living"):
        print(f"  {key:16} {s2[key]:>9,}")
    print("  flagged by rank: " + ", ".join(f"{r} {n:,}" for r, n in ranks.most_common()))


if __name__ == "__main__":
    main()
