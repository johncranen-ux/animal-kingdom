"""
Build the app's `species` table from the Catalogue of Life Extended trial database,
carrying across what the current species.db has collected. Writes a new file; refuses a
target that exists, so species.db is never touched.

Usage:
    python data/build_col_db.py [--target <data dir>/col/species_col.db] [--col-db P]
                                [--old-db P|none] [--verdicts P|none]

The earlier species database and the verification verdicts are optional. Without the
first, nothing is carried over and there are no GBIF_ONLY rows; without the second, no
fixes are applied. Each defaults to its usual file in the data folder when that exists.

Levels: kingdom, phylum, class, order, family, genus, species and below. Where one of
those is missing, the lowest level COL has in that gap stands in for it, under its real
rank. Other intermediate levels stay as rows with no place in the tree (taxon_path NULL).

Names COL lacks are kept outside the tree (status GBIF_ONLY, taxon_path NULL, old path in
gbif_taxon_path) if they are accepted animal species or hold data.

Fixes come from data/verify_col_levels.py: a family for a genus, or an order for a family
or genus, only where independent sources confirmed it, and never where it would change a
level COL does state. Applied fixes are listed in the taxon_fixes table.
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict, namedtuple
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from compare_col import match_name  # noqa: E402
from import_gbif import row_score  # noqa: E402  (also puts backend/ on sys.path)
from app.paths import data_path  # noqa: E402
from app import database  # noqa: E402

COL_DB = str(data_path("col", "col_xr.db"))
OLD_DB = str(data_path("species_gbif_backup.db"))  # species.db is itself a COL build since the switch
TARGET = str(data_path("col", "species_col.db"))
VERDICTS = str(data_path("col", "verification", "verdicts.tsv"))

Fixes = namedtuple("Fixes", "family order")

_MAIN = {"kingdom": 0, "phylum": 1, "class": 2, "order": 3, "family": 4, "genus": 5, "species": 6}
_INFRASPECIFIC = {"subspecies", "variety", "form", "infraspecies", "forma", "aberration", "morph", "natio"}
_ACCEPTED = {"accepted", "provisionally accepted"}
_DNA_CLUSTER = re.compile(r"^(BOLD:|SH\d)")
_HAS_DATA = ("iucn_status", "population_trend", "wikipedia_abstract", "body_mass", "body_length", "max_lifespan",
             "metabolic_rate", "reproduction_strategy", "geo_bounding_box", "habitat_type", "elevation_limits",
             "trophic_level", "activity_period", "extinct")
_CARRIED = (*_HAS_DATA, "primary_image_url", "image_attribution", "trait_sources", "rejected_images")
_FILLED_FROM_SYNONYM = tuple(f for f in _HAS_DATA if f != "extinct") + ("primary_image_url",)
_NO_IMAGE = "__none__"
_DOMAINS_WITHOUT_ROWS = {"Bacteria", "Archaea"}  # main.py adds these two tree nodes itself

_COLUMNS = ("scientific_name", "taxon_path", "taxon_rank", "common_names", "taxonomic_status", "body_mass", "body_length",
            "max_lifespan", "metabolic_rate", "reproduction_strategy", "geo_bounding_box", "habitat_type",
            "elevation_limits", "trophic_level", "activity_period", "iucn_status", "population_trend",
            "primary_image_url", "image_attribution", "wikipedia_abstract", "taxon_depth", "trait_sources", "extinct",
            "gbif_taxon_path", "col_id", "accepted_name", "rejected_images")


def step_name(rank, name):
    return match_name(name) if rank == "species" or rank in _INFRASPECIFIC else name


def map_status(status):
    return "ACCEPTED" if status in _ACCEPTED else "SYNONYM"


def genus_lineage(lineage):
    head, sep, tail = lineage.partition("|genus:")
    return head + sep + tail.split("|", 1)[0] if sep else None


def is_dna_cluster(name, rank):
    return rank == "unranked" and bool(_DNA_CLUSTER.match(name))


def _steps(lineage):
    return [tuple(step.split(":", 1)) for step in lineage.split("|")]


def _find(steps, rank):
    return next((name for r, name in steps if r == rank), None)


def _lineage_fits(steps, lineage):
    """Would moving this group under that COL lineage keep every level COL states for it?"""
    theirs = _steps(lineage)
    return all(_find(theirs, rank) == own for rank in ("phylum", "class", "order") if (own := _find(steps, rank)))


def _attach(steps, below, level, value, known):
    """Put a confirmed family or order above the `below` step. A group COL knows brings its
    own lineage, so it stays in one place in the tree; if that lineage contradicts what COL
    states here, COL stands and nothing changes."""
    lineages = known.get(value)
    index = next(i for i, (rank, _) in enumerate(steps) if rank == below)
    if not lineages:
        return [*steps[:index], (level, value), *steps[index:]]
    for lineage in lineages:
        if _lineage_fits(steps, lineage):
            return [s for s in _steps(lineage) if s != ("domain", "Eukaryota")] + steps[index:]
    return steps


def _apply_fixes(steps, fixes, known):
    genus = _find(steps, "genus")
    if genus and not _find(steps, "family") and (genus, _find(steps, "phylum") or "") in fixes.family:
        family, _ = fixes.family[(genus, _find(steps, "phylum") or "")]
        steps = _attach(steps, "genus", "family", family, known)
    if not _find(steps, "order"):
        family = _find(steps, "family")
        group, below = (family, "family") if family else (genus, "genus")
        key = (group, _find(steps, "phylum") or "")
        if group and key in fixes.order:
            steps = _attach(steps, below, "order", fixes.order[key][0], known)
    return steps


def tree_path(lineage, fixes=None, known=None):
    """The app's taxon_path for one COL lineage (see the module docstring)."""
    steps = [s for s in _steps(lineage) if s != ("domain", "Eukaryota")]
    if not steps:
        return None
    if fixes:
        steps = _apply_fixes(steps, fixes, known or {})

    kept, run, previous = [], [], None
    last = len(steps) - 1
    for i, (rank, name) in enumerate(steps):
        if i == 0 and rank in ("domain", "unranked"):
            kept.append(name)
            previous = -1
            continue
        index = _MAIN.get(rank, 6 if rank in _INFRASPECIFIC else None)
        if index is None and i != last:
            run.append(name)
            continue
        if index is not None and run and previous is not None and index - previous > 1:
            kept.append(run[-1])
        run = []
        kept.append(step_name(rank, name))
        if index is not None:
            previous = index
    return "|".join(kept)


def synonym_path(accepted_path, name):
    parent, _, _ = accepted_path.rpartition("|")
    return f"{parent}|{name}" if parent else name


def same_taxon(new_path, new_rank, old):
    """Is this old row about the same organism? One row per name makes homonyms compete,
    and an image or status must not jump from an old snail genus to a horse synonym."""
    if (old.get("taxon_rank") or "").lower() != (new_rank or "").lower():
        return False
    old_segments = (old.get("taxon_path") or "").split("|")
    new_segments = (new_path or "").split("|")
    if old_segments[0] != new_segments[0]:
        return False
    old_middle, new_middle = set(old_segments[1:-1]), set(new_segments[1:-1])
    return not old_middle or not new_middle or bool(old_middle & new_middle)


def extinct_update(col_extinct, old):
    """extinct column (and trait_sources if changed) from COL's flag and the old row."""
    current = old.get("extinct")
    sources = database.parse_trait_sources(old.get("trait_sources"))
    entry = sources.get("extinct")
    derived = isinstance(entry, dict) and str(entry.get("source", "")).startswith("Derived:")
    if derived:
        del sources["extinct"]
        current = None
    assessed_living = old.get("iucn_status") not in (None, "", "EX")
    if col_extinct is not None and col_extinct != current and not (col_extinct == 1 and assessed_living):
        sources["extinct"] = {"source": "Catalogue of Life", "estimated": False}
        return {"extinct": col_extinct, "trait_sources": database.serialize_trait_sources(sources)}
    updates = {"extinct": current}
    if derived:
        updates["trait_sources"] = database.serialize_trait_sources(sources)
    return updates


def apply_iucn_extinct(values):
    """IUCN status EX means extinct, whatever else the row says, so the tree and
    "Hide extinct" know it without the species panel being opened."""
    if values.get("iucn_status") != "EX" or values.get("extinct") == 1:
        return
    sources = database.parse_trait_sources(values.get("trait_sources"))
    sources["extinct"] = {"source": "IUCN Red List", "estimated": False}
    values["extinct"] = 1
    values["trait_sources"] = database.serialize_trait_sources(sources)


def merge_common_names(old_names, col_names):
    """Old names first: the first name is the tree label, and those were reviewed."""
    merged, seen = [], set()
    for name in [*old_names, *col_names]:
        key = name.casefold()
        if key not in seen:
            seen.add(key)
            merged.append(name)
    return merged


def optional_input(given, default, label):
    """Path of an optional input file, or None to build without it.

    given: the command-line value (None when not given; "none" turns the input off).
    A missing default is skipped with a note; a missing file named on the command
    line stops the build, since that is most likely a typo.
    """
    if given is not None:
        if given.lower() == "none":
            return None
        if not os.path.exists(given):
            sys.exit(f"ERROR: {label} not found: {given}")
        return given
    if os.path.exists(default):
        return default
    print(f"  No {label} at {default}; building without it.")
    return None


def load_fixes(verdicts_path):
    fixes = Fixes({}, {})
    if verdicts_path is None:
        return fixes
    with open(verdicts_path, encoding="utf-8", newline="\n") as f:
        next(f)
        for line in f:
            level, group, value, phylum, _, verdict, agree, _ = line.rstrip("\n").split("\t")
            if verdict in ("confirmed", "majority"):
                getattr(fixes, level)[(group, phylum)] = (value, agree)
    return fixes


def _has_data(old):
    return any(old.get(field) not in (None, "") for field in _HAS_DATA) or old.get("primary_image_url") not in (None, "", _NO_IMAGE)


def _load_old(old_db):
    conn = sqlite3.connect(f"file:{old_db}?mode=ro&immutable=1", uri=True)
    conn.row_factory = sqlite3.Row
    old = {}
    for row in conn.execute("SELECT * FROM species"):
        old[row["scientific_name"]] = {k: row[k] for k in row.keys() if row[k] is not None and k != "scientific_name"}
    conn.close()
    return old


def _read_col(conn, fixes, known, extinct_genera, summary):
    """{name: winning row}, plus accepted rows that lost their name to a homonym."""
    best, losers = {}, []
    query = "SELECT id, status, rank, scientific_name, lineage, extinct FROM name_usage"
    for col_id, status, rank, raw_name, lineage, extinct in conn.execute(query):
        if rank == "domain":
            continue
        if is_dna_cluster(raw_name, rank):
            summary["dna_clusters_skipped"] += 1
            continue
        name = step_name(rank, raw_name)
        app_status = map_status(status)
        path = tree_path(lineage, fixes, known)
        accepted_name = None
        if extinct is None and app_status == "ACCEPTED" and (rank == "species" or rank in _INFRASPECIFIC)                 and genus_lineage(lineage) in extinct_genera:
            extinct = 1
            summary["extinct_from_genus"] += 1
        if app_status == "SYNONYM":
            accepted_name = step_name("species", _steps(lineage)[-1][1])
            path = synonym_path(path or name, name)
        candidate = {
            "name": name, "col_id": col_id, "rank": rank, "status": app_status, "path": path, "extinct": extinct,
            "accepted_name": accepted_name, "unique_target": status == "synonym",
        }
        score = row_score(app_status, path, rank) * 2 + (status == "accepted")
        current = best.get(name)
        if current is None or score > current["score"]:
            if current is not None and current["status"] == "ACCEPTED":
                losers.append(current)
            candidate["score"] = score
            best[name] = candidate
        elif app_status == "ACCEPTED":
            losers.append(candidate)
    return best, losers


def _prefixes(path):
    segments = path.split("|")
    return ("|".join(segments[:i]) for i in range(1, len(segments)))


def _old_row_fields(old):
    return {field: old[field] for field in _CARRIED if field in old}


def _fill_from_synonym(values, old):
    """Fill blanks on an accepted species from its synonym's row. Returns True if any changed."""
    changed = False
    sources = database.parse_trait_sources(values.get("trait_sources"))
    old_sources = database.parse_trait_sources(old.get("trait_sources"))
    for field in _FILLED_FROM_SYNONYM:
        if values.get(field) not in (None, "", _NO_IMAGE) or old.get(field) in (None, "", _NO_IMAGE):
            continue
        values[field] = old[field]
        changed = True
        if field == "primary_image_url":
            values["image_attribution"] = old.get("image_attribution")
        if field in old_sources:
            sources[field] = old_sources[field]
    if changed and sources:
        values["trait_sources"] = database.serialize_trait_sources(sources)
    return changed


def _row_values(row, old, english, used_paths, summary):
    values = {}
    carried = old is not None
    if carried:
        values.update(_old_row_fields(old))
    names = database.parse_common_names((old or {}).get("common_names"))
    values["common_names"] = database.serialize_common_names(merge_common_names(names, english.get(row["col_id"], [])))
    values.update(extinct_update(row["extinct"], old or {}))
    path = row["path"]
    if row["rank"] not in _MAIN and row["rank"] not in _INFRASPECIFIC and row["status"] == "ACCEPTED" and path not in used_paths:
        path = None
    values.update(
        scientific_name=row.get("key", row["name"]), taxon_path=path, taxon_rank=row["rank"], taxonomic_status=row["status"],
        taxon_depth=path.count("|") if path else None, col_id=row["col_id"], accepted_name=row["accepted_name"],
    )
    return values


def _insert(conn, batch):
    placeholders = ",".join("?" * len(_COLUMNS))
    conn.executemany(
        f"INSERT INTO species ({','.join(_COLUMNS)}) VALUES ({placeholders})",
        [[values.get(column) for column in _COLUMNS] for values in batch],
    )
    batch.clear()


def _flush_if_full(conn, batch):
    if len(batch) >= 50_000:
        _insert(conn, batch)


def unique_key(name, path, taken):
    """A primary key for this row: its name if free, else qualified by parent, then by
    whole path. Reserves the key in `taken`. The tree label comes from the path."""
    parent = path.rsplit("|", 2)[-2] if "|" in path else "?"
    for key in (name, f"{name} [{parent}]", f"{name} [{path}]"):
        if key not in taken:
            taken.add(key)
            return key
    raise ValueError(f"no free key for {path}")


def _disambiguate(losers, taken, summary):
    """Accepted homonyms keep a row of their own, or their whole branch would vanish
    from the tree: nodes come from rows."""
    kept, seen_paths = [], set()
    for row in losers:
        path = row["path"] or ""
        if path in seen_paths:
            summary["duplicate_accepted_skipped"] += 1
            continue
        seen_paths.add(path)
        row["key"] = unique_key(row["name"], path or row["name"], taken)
        kept.append(row)
    summary["homonym_rows"] += len(kept)
    return kept


def _write_fixes(conn, fixes, node_paths, summary):
    conn.execute("CREATE TABLE taxon_fixes (level TEXT, grp TEXT, phylum TEXT, value TEXT, sources TEXT, applied INTEGER)")
    for level, table in (("family", fixes.family), ("order", fixes.order)):
        for (group, phylum), (value, sources) in table.items():
            applied = any(value in path.split("|") for path in node_paths.get(group, []))
            summary["fixes_applied"] += applied
            summary["fixes_refused"] += not applied
            conn.execute("INSERT INTO taxon_fixes VALUES (?,?,?,?,?,?)", (level, group, phylum, value, sources, int(applied)))


def build(col_db, old_db, target, fixes, progress=lambda *_: None):
    if os.path.exists(target):
        raise FileExistsError(f"{target} already exists; refusing to overwrite it")
    partial = f"{target}.partial"
    if os.path.exists(partial):
        os.remove(partial)

    summary = Counter(paths_missing_a_node=0, filled_from_synonym=0, gbif_only_kept=0, dna_clusters_skipped=0,
                      fixes_applied=0, fixes_refused=0, nodes_added_by_fixes=0, homonym_rows=0)
    col = sqlite3.connect(f"file:{col_db}?mode=ro", uri=True)
    known = defaultdict(list)
    extinct_genera = set()
    for name, rank, lineage, extinct in col.execute(
        "SELECT scientific_name, rank, lineage, extinct FROM name_usage "
        "WHERE rank IN ('family', 'order', 'genus') AND status IN ('accepted', 'provisionally accepted')"
    ):
        if rank == "genus":
            if extinct == 1:
                extinct_genera.add(lineage)
        else:
            known[name].append(lineage)

    progress("reading the COL names")
    best, losers = _read_col(col, fixes, known, extinct_genera, summary)
    taken = set(best)
    losers = _disambiguate(losers, taken, summary)

    progress("reading English names")
    english = defaultdict(list)
    for taxon_id, name in col.execute("SELECT taxon_id, name FROM vernacular WHERE language = 'eng'"):
        english[taxon_id].append(name)
    col.close()

    # Without the old database the tree is COL's alone: nothing carried over, no GBIF_ONLY rows.
    old_rows = {}
    if old_db is not None:
        progress("reading the old database")
        old_rows = _load_old(old_db)

    accepted = [r for r in best.values() if r["status"] == "ACCEPTED"] + losers
    used_paths = {prefix for row in accepted if row["path"] for prefix in _prefixes(row["path"])}
    node_paths = defaultdict(list)
    for row in accepted:
        if row["path"]:
            node_paths[row["name"]].append(row["path"])

    # Data on a synonym also belongs to its accepted species. Skipped for ambiguous
    # synonyms, which point at more than one taxon.
    fill_from = defaultdict(list)
    for row in best.values():
        old = old_rows.get(row["name"])
        if row["status"] == "SYNONYM" and row["unique_target"] and old and same_taxon(row["path"], row["rank"], old) and _has_data(old):
            fill_from[row["accepted_name"]].append(old)

    conn = sqlite3.connect(partial)
    try:
        conn.execute("PRAGMA journal_mode=OFF")
        conn.execute("PRAGMA synchronous=OFF")
        conn.execute(database._CREATE_SPECIES_TABLE)
        for column in ("trait_sources TEXT", "gbif_taxon_path TEXT", "col_id TEXT", "accepted_name TEXT",
                       "rejected_images TEXT"):
            conn.execute(f"ALTER TABLE species ADD COLUMN {column}")

        progress("writing rows")
        batch, used_old, written_paths = [], set(), set()
        for row in [*best.values(), *losers]:
            old = old_rows.get(row["name"])
            matches = old is not None and "key" not in row and same_taxon(row["path"], row["rank"], old)
            if old is not None and "key" not in row:
                if matches:
                    used_old.add(row["name"])
                elif _has_data(old):
                    summary["homonym_data_left_in_backup"] += 1
            values = _row_values(row, old if matches else None, english, used_paths, summary)
            if row["status"] == "ACCEPTED":
                filled = [_fill_from_synonym(values, source) for source in fill_from.get(row["name"], [])]
                summary["filled_from_synonym"] += any(filled)
                if values["taxon_path"]:
                    written_paths.add(values["taxon_path"])
            apply_iucn_extinct(values)
            batch.append(values)
            _flush_if_full(conn, batch)

        # Groups that only a confirmed fix brought into the tree need a row of their own.
        fix_ranks = {value: level for level, table in (("family", fixes.family), ("order", fixes.order)) for value, _ in table.values()}
        for path in sorted(used_paths - written_paths - _DOMAINS_WITHOUT_ROWS):
            name = path.rsplit("|", 1)[-1]
            if name not in fix_ranks:
                summary["paths_missing_a_node"] += 1
                continue
            key = unique_key(name, path, taken)
            written_paths.add(path)
            batch.append({
                "scientific_name": key, "taxon_path": path, "taxon_rank": fix_ranks[name], "taxonomic_status": "ACCEPTED",
                "taxon_depth": path.count("|"), "common_names": "[]",
            })
            summary["nodes_added_by_fixes"] += 1
            _flush_if_full(conn, batch)

        progress("keeping names COL lacks")
        for name, old in old_rows.items():
            if name in used_old or name in taken:
                continue
            is_accepted_animal = (old.get("taxonomic_status") == "ACCEPTED" and old.get("taxon_rank") == "species"
                                  and (old.get("taxon_path") or "").startswith("Animalia|"))
            if not is_accepted_animal and not _has_data(old):
                continue
            values = _old_row_fields(old)
            values.update(extinct_update(None, old))
            values.update(
                scientific_name=name, taxon_path=None, taxon_rank=old.get("taxon_rank"), taxonomic_status="GBIF_ONLY",
                common_names=old.get("common_names") or "[]", gbif_taxon_path=old.get("taxon_path"),
            )
            apply_iucn_extinct(values)
            batch.append(values)
            summary["gbif_only_kept"] += 1
            _flush_if_full(conn, batch)
        _insert(conn, batch)

        _write_fixes(conn, fixes, node_paths, summary)
        summary["rows_in_col"] = len(best)
        conn.commit()
    except BaseException:
        conn.close()
        os.remove(partial)
        raise
    conn.close()
    os.rename(partial, target)

    # Indexes and triggers come from the app's own schema code, on the final file.
    saved = database.DB_PATH
    database.DB_PATH = target
    try:
        progress("creating indexes")
        database.get_connection().close()
    finally:
        database.DB_PATH = saved
    return dict(summary)


def main():
    parser = argparse.ArgumentParser(description="Build species table from COL Extended")
    parser.add_argument("--target", default=TARGET)
    parser.add_argument("--col-db", default=COL_DB, help="COL database made by import_col.py")
    parser.add_argument("--old-db", help=f"earlier species database to carry data from (default {OLD_DB} "
                                         "if it exists; 'none' to build without)")
    parser.add_argument("--verdicts", help=f"verify_col_levels.py verdicts (default {VERDICTS} "
                                           "if it exists; 'none' to build without)")
    args = parser.parse_args()
    t0 = time.monotonic()

    def progress(text):
        print(f"  [{time.monotonic() - t0:6.0f} s] {text}", flush=True)

    if not os.path.exists(args.col_db):
        sys.exit(f"ERROR: COL database not found: {args.col_db} (make it with data/import_col.py)")
    old_db = optional_input(args.old_db, OLD_DB, "earlier species database")
    verdicts = optional_input(args.verdicts, VERDICTS, "verification verdicts")
    try:
        summary = build(args.col_db, old_db, args.target, load_fixes(verdicts), progress)
    except FileExistsError as exc:
        sys.exit(f"ERROR: {exc}")
    print(f"Finished in {time.monotonic() - t0:,.0f} s")
    for key, value in sorted(summary.items()):
        print(f"  {key}: {value:,}")


if __name__ == "__main__":
    main()
