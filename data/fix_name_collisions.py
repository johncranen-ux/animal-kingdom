"""
Repair rows where a name collision left the wrong taxon in species.db.

The table has one row per name (scientific_name is the primary key), and the
original import kept the FIRST backbone row of each name (INSERT OR IGNORE). When
an outdated synonym came first, it shadowed the accepted animal of the same name:
"Panthera" was stored as a moth synonym of Pantherodes, not the big-cat genus.

For every DB row that is NOT an accepted animal, this script looks for accepted
Animalia backbone rows with the same canonical name:
  * exactly one, same lineage -> "relabel": only status (and missing common
                    names) change; traits are kept, it is the same organism
  * exactly one, other lineage -> "replace": the row is replaced by it: lineage, rank, status and English
                    common names from the backbone; traits, image, abstract and
                    extinct flag are cleared (they were fetched for the other
                    organism) and the name is dropped from the vector store
  * two or more  -> the highest rank wins ("Proboscidea" is the elephant order,
                    not the polychaete genus); a tie is left alone and reported
Rows that already are an accepted animal are never touched.

Idempotent: a second run finds nothing to do.

Usage:
    python data/fix_name_collisions.py --dry-run
    python data/fix_name_collisions.py [backbone_dir] [--backup FILE] [--list-ambiguous]
"""

import argparse
import csv
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
from app.paths import data_path  # noqa: E402
from app import database

DEFAULT_BACKBONE = str(data_path("gbif", "backbone"))
DEFAULT_BACKUP   = str(data_path("name_collisions_backup.jsonl"))
BATCH = 900
csv.field_size_limit(2_147_483_647)   # VernacularName.tsv has very long fields

# Taxon.tsv column positions (see meta.xml)
_ID, _CANONICAL, _RANK, _STATUS, _KINGDOM, _GENUS = 0, 7, 11, 14, 17, 22
_SPECIES_RANKS = {"species", "subspecies", "variety", "form", "infraspecies"}

# Columns describing the organism itself, cleared when the row changes organism.
_CLEARED = (
    "body_mass", "body_length", "max_lifespan", "metabolic_rate", "reproduction_strategy",
    "geo_bounding_box", "habitat_type", "elevation_limits", "trophic_level",
    "activity_period", "iucn_status", "population_trend", "primary_image_url",
    "image_attribution", "wikipedia_abstract", "trait_sources", "extinct",
)


def taxon_path(cols: list[str]) -> str:
    """Same lineage path data/import_gbif.py builds for a backbone row."""
    parts = [v.strip() for v in cols[_KINGDOM:_GENUS + 1] if v.strip()]
    canonical = cols[_CANONICAL].strip()
    if cols[_RANK].strip().lower() in _SPECIES_RANKS and canonical and (not parts or parts[-1] != canonical):
        parts.append(canonical)
    return "|".join(parts)


def accepted_animals(lines: Iterable[str]) -> dict[str, list[tuple[str, str, str]]]:
    """{canonical name: [(taxonID, taxon_path, rank), ...]} for accepted Animalia rows."""
    out: dict[str, list[tuple[str, str, str]]] = {}
    for line in lines:
        cols = line.rstrip("\r\n").split("\t")
        if len(cols) <= _GENUS:
            continue
        name = cols[_CANONICAL].strip()
        if name and cols[_KINGDOM] == "Animalia" and cols[_STATUS] == "accepted":
            out.setdefault(name, []).append((cols[_ID], taxon_path(cols), cols[_RANK].strip()))
    return out


_RANK_ORDER = ("kingdom", "phylum", "class", "order", "family", "genus",
               "species", "subspecies", "variety", "form")


def _rank_order(rank: str) -> int:
    """Lower = higher rank; unknown ranks sort last."""
    r = (rank or "").lower()
    return _RANK_ORDER.index(r) if r in _RANK_ORDER else len(_RANK_ORDER)


def is_accepted_animal(row: dict) -> bool:
    path = row.get("taxon_path") or ""
    return row.get("taxonomic_status") == "ACCEPTED" and (path == "Animalia" or path.startswith("Animalia|"))


def plan_fix(row: dict, candidates: list[tuple[str, str, str]] | None) -> tuple[str, tuple | None]:
    """(outcome, chosen (taxonID, path, rank) or None) for one DB row."""
    if is_accepted_animal(row):
        return "already_ok", None
    if not candidates:
        return "no_accepted_animal", None
    if len(candidates) > 1:
        ranked = sorted(candidates, key=lambda c: _rank_order(c[2]))
        if _rank_order(ranked[0][2]) == _rank_order(ranked[1][2]):
            return "ambiguous", None
        candidates = ranked[:1]
    if (row.get("taxon_path") or "") == candidates[0][1]:
        return "relabel", candidates[0]   # same organism, only the status was wrong
    return "replace", candidates[0]


def english_names(lines: Iterable[dict], wanted: set[str]) -> dict[str, list[str]]:
    """{taxonID: [English vernacular names]} for the wanted IDs (same filter as import_gbif)."""
    names: dict[str, list[str]] = {}
    for row in lines:
        tid = (row.get("taxonID") or "").strip()
        if tid not in wanted:
            continue
        if (row.get("language") or "").lower().strip() not in ("", "eng", "en"):
            continue
        name = (row.get("vernacularName") or "").strip()
        got = names.setdefault(tid, [])
        if name and name.lower() not in (n.lower() for n in got):   # GBIF repeats names
            got.append(name)
    return {t: v for t, v in names.items() if v}


def apply_fixes(conn, fixes: list[tuple[str, str, tuple, list[str]]]) -> None:
    """fixes: [(outcome, scientific_name, (taxonID, path, rank), common names)].
    "replace" swaps the organism and clears its data; "relabel" keeps the data,
    sets the status and fills common names only where there were none."""
    cleared = ", ".join(f"{c} = NULL" for c in _CLEARED)
    conn.executemany(
        f"UPDATE species SET taxon_path = ?, taxon_rank = ?, taxonomic_status = 'ACCEPTED', "
        f"common_names = ?, {cleared} WHERE scientific_name = ?",
        [(path, rank, database.serialize_common_names(common), name)
         for kind, name, (_tid, path, rank), common in fixes if kind == "replace"],
    )
    conn.executemany(
        "UPDATE species SET taxon_rank = ?, taxonomic_status = 'ACCEPTED', "
        "common_names = CASE WHEN common_names IS NULL OR common_names IN ('', '[]') "
        "THEN ? ELSE common_names END WHERE scientific_name = ?",
        [(rank, database.serialize_common_names(common), name)
         for kind, name, (_tid, _path, rank), common in fixes if kind == "relabel"],
    )
    conn.commit()


def backup_rows(conn, names: list[str], path: Path) -> int:
    """Append the full current rows to a JSONL file before they are changed."""
    n = 0
    with open(path, "a", encoding="utf-8") as f:
        for i in range(0, len(names), BATCH):
            chunk = names[i:i + BATCH]
            for row in conn.execute(
                f"SELECT * FROM species WHERE scientific_name IN ({','.join('?' * len(chunk))})", chunk
            ):
                f.write(json.dumps(dict(row), ensure_ascii=False) + "\n")
                n += 1
    return n


def _drop_embeddings(names: list[str]) -> int:
    """Remove stale abstracts of replaced rows from the vector store."""
    if not names:
        return 0
    from app import vector_db
    col = vector_db.get_collection()
    present = col.get(ids=names).get("ids") or []
    if present:
        col.delete(ids=present)
    return len(present)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("backbone", nargs="?", default=DEFAULT_BACKBONE,
                        help="directory containing Taxon.tsv and VernacularName.tsv")
    parser.add_argument("--dry-run", action="store_true", help="report counts, write nothing")
    parser.add_argument("--backup", default=DEFAULT_BACKUP,
                        help="JSONL file the original rows are appended to before writing")
    parser.add_argument("--list-ambiguous", action="store_true", help="print the skipped homonyms")
    args = parser.parse_args()

    root = Path(args.backbone)
    tsv = root / "Taxon.tsv"
    if not tsv.exists():
        sys.exit(f"ERROR: {tsv} not found")

    t0 = time.monotonic()
    with open(tsv, encoding="utf-8", errors="replace", newline="") as f:
        next(f)  # header
        animals = accepted_animals(f)
    print(f"{len(animals):,} accepted animal names in the backbone ({time.monotonic() - t0:.0f}s)")

    conn = database.get_connection()
    stats, ranks = Counter(), Counter()
    fixes: list[tuple[str, str, tuple, list[str]]] = []
    ambiguous: list[str] = []
    try:
        names = list(animals)
        for i in range(0, len(names), BATCH):
            chunk = names[i:i + BATCH]
            rows = conn.execute(
                "SELECT scientific_name, taxon_path, taxonomic_status, taxon_rank FROM species "
                f"WHERE scientific_name IN ({','.join('?' * len(chunk))})", chunk,
            ).fetchall()
            for row in map(dict, rows):
                outcome, chosen = plan_fix(row, animals[row["scientific_name"]])
                stats[outcome] += 1
                if outcome in ("replace", "relabel"):
                    if outcome == "replace":
                        stats["was_synonym" if row["taxonomic_status"] == "SYNONYM" else "was_other_kingdom"] += 1
                        ranks[chosen[2]] += 1
                    fixes.append((outcome, row["scientific_name"], chosen, []))
                elif outcome == "ambiguous":
                    ambiguous.append(row["scientific_name"])

        if fixes:
            vern = root / "VernacularName.tsv"
            common = {}
            if vern.exists():
                with open(vern, encoding="utf-8", errors="replace", newline="") as f:
                    common = english_names(csv.DictReader(f, delimiter="\t"), {c[0] for _, _, c, _ in fixes})
            fixes = [(k, n, c, common.get(c[0], [])) for k, n, c, _ in fixes]

        dropped = 0
        if not args.dry_run:
            saved = backup_rows(conn, [n for _, n, _, _ in fixes], Path(args.backup))
            print(f"  {saved:,} original rows saved to {args.backup}")
            for i in range(0, len(fixes), BATCH):
                apply_fixes(conn, fixes[i:i + BATCH])
            dropped = _drop_embeddings([n for k, n, _, _ in fixes if k == "replace"])
    finally:
        conn.close()

    print(f"{'DRY RUN - ' if args.dry_run else ''}finished in {time.monotonic() - t0:.0f}s")
    for key in ("replace", "was_synonym", "was_other_kingdom", "relabel", "ambiguous", "already_ok"):
        print(f"  {key:18} {stats[key]:>9,}")
    print("  replaced by rank: " + ", ".join(f"{r} {n:,}" for r, n in ranks.most_common()))
    if not args.dry_run:
        print(f"  vector-store entries dropped: {dropped:,}")
    sample = [f"{n}: {c[1]}" for k, n, c, _ in fixes if k == "replace"][:8]
    if sample:
        print("  e.g. " + "\n       ".join(sample))
    if args.list_ambiguous:
        print("Ambiguous (left alone):\n  " + "\n  ".join(sorted(ambiguous)))


if __name__ == "__main__":
    main()
