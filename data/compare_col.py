"""
Compare the animal species in species.db with Catalogue of Life trial databases
built by import_col.py. Read-only; writes results to a separate output folder.

Usage:
    python data/compare_col.py [--out E:/AnimalKingdomSystem/col/comparison]

The app's taxon_path skips empty levels, so "Animalia|Chordata|Cypriniformes|..." cannot
be read by position: GBIF's levels come from the backbone's Taxon.tsv instead. A level
counts as moved only if both sources name it and the names differ; a level GBIF left
blank and COL fills is a filled gap.
"""

import argparse
import json
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict, namedtuple
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from import_gbif import _build_taxon_path  # noqa: E402

LEVELS = ("phylum", "class", "order", "family")
ACCEPTED_STATUSES = {"accepted", "provisionally accepted"}
ANIMAL_MARK = "kingdom:Animalia"
DATA_FIELDS = ("iucn", "image", "abstract", "traits")
_EPITHET_ENDING = re.compile(r"(ii|ae|us|um|is|a|e|i)$")
_SUBGENUS = re.compile(r"\s+\([^)]*\)\s+")

SPECIES_DB = "E:/AnimalKingdomSystem/species_gbif_backup.db"  # the GBIF side; species.db is a COL build since the switch
TAXON_TSV = "E:/AnimalKingdomSystem/gbif/backbone/Taxon.tsv"
RELEASES = {"base": "E:/AnimalKingdomSystem/col/col_base.db", "xr": "E:/AnimalKingdomSystem/col/col_xr.db"}

GbifRow = namedtuple("GbifRow", "name status levels extinct iucn image abstract traits")


def match_name(name):
    """COL writes many species with their subgenus ("Danaus (Danaus) plexippus");
    GBIF's canonical names never do, so names are compared without it."""
    return _SUBGENUS.sub(" ", name) if "(" in name else name


def levels_from_lineage(lineage):
    found = dict.fromkeys(LEVELS, "")
    for step in (lineage or "").split("|"):
        rank, _, name = step.partition(":")
        if rank in found:
            found[rank] = name
    return found


def level_state(gbif, col):
    if gbif and col:
        return "same" if gbif == col else "different"
    if col:
        return "filled"
    return "emptied" if gbif else "both_blank"


def highest_move(gbif, col):
    """The highest level that both sources name differently, or None."""
    for level in LEVELS:
        if level_state(gbif[level], col[level]) == "different":
            return level
    return None


def _closest(rows, levels):
    """Among rows of one name, prefer the one agreeing with GBIF's placement."""
    if levels:
        for level in ("family", "order", "class"):
            mark = f"{level}:{levels[level]}|"
            for row in rows:
                if levels[level] and mark in row["lineage"] + "|":
                    return row
    return rows[0]


def classify(rows, levels):
    """Where one GBIF name ended up, given every COL row with that exact name."""
    animal = [r for r in rows if ANIMAL_MARK in r["lineage"]]
    accepted = [r for r in animal if r["status"] in ACCEPTED_STATUSES]
    if accepted:
        return "accepted", _closest(accepted, levels)
    if animal:
        return "synonym", _closest(animal, levels)
    if rows:
        return "not_animal", rows[0]
    return "absent", None


def spelling_stem(name):
    """Genus plus the epithet without its Latin ending: finds -us/-a and -i/-ii variants."""
    genus, _, epithet = name.partition(" ")
    return genus, _EPITHET_ENDING.sub("", epithet)


def compare_release(gbif_rows, conn):
    wanted = {row.name for row in gbif_rows}
    accepted_in_gbif = {row.name for row in gbif_rows if row.status == "ACCEPTED"}
    by_name = defaultdict(list)
    stems = {}
    out = {
        "col_animal_species": 0,
        "col_only": Counter(),
        "col_extinct": Counter(),
        "blank_col": Counter(),
        "blank_col_class_by_phylum": Counter(),
        "col_rank_counts": Counter(),
    }
    distinct_col = {level: set() for level in LEVELS}

    query = "SELECT scientific_name, status, rank, lineage, extinct, merged FROM name_usage"
    for raw_name, status, rank, lineage, extinct, merged in conn.execute(query):
        lineage = lineage or ""
        name = match_name(raw_name)
        if name in wanted:
            by_name[name].append({
                "scientific_name": name, "status": status, "lineage": lineage, "merged": merged, "extinct": extinct,
            })
        if ANIMAL_MARK not in lineage or status not in ACCEPTED_STATUSES:
            continue
        out["col_rank_counts"][rank] += 1
        if rank != "species":
            continue
        out["col_animal_species"] += 1
        out["col_extinct"][extinct] += 1
        stems[spelling_stem(name)] = name
        levels = levels_from_lineage(lineage)
        for level in LEVELS:
            if levels[level]:
                distinct_col[level].add(levels[level])
            else:
                out["blank_col"][level] += 1
        if not levels["class"]:
            out["blank_col_class_by_phylum"][levels["phylum"]] += 1
        if name not in accepted_in_gbif:
            out["col_only"]["gbif_synonym" if name in wanted else "not_in_gbif"] += 1
    out["distinct_col"] = {level: sorted(names) for level, names in distinct_col.items()}

    out.update(
        accepted_categories=Counter(), synonym_row_categories=Counter(),
        data_by_category=defaultdict(Counter), synonym_data_by_category=defaultdict(Counter),
        level_states={level: Counter() for level in LEVELS}, moves=Counter(), moved_rows=[],
        move_pairs={level: Counter() for level in LEVELS},
        filled_classes_by_order=defaultdict(Counter), filled_values={level: Counter() for level in LEVELS},
        unresolved_levels=0, absent_spelling_variants=0, absent_rows=[], accepted_via_merged=0,
        extinct_crosstab=Counter(), blank_gbif=Counter(), category_by_gbif_class=defaultdict(Counter),
        chordates_without_class=Counter(), absent_by_extinct=Counter(),
    )
    distinct_gbif = {level: set() for level in LEVELS}

    for row in gbif_rows:
        category, chosen = classify(by_name.get(row.name, []), row.levels)
        if row.status != "ACCEPTED":
            out["synonym_row_categories"][category] += 1
            data = out["synonym_data_by_category"][category]
        else:
            out["accepted_categories"][category] += 1
            data = out["data_by_category"][category]
            _record_accepted(out, distinct_gbif, row, category, chosen, stems)
        for field in DATA_FIELDS:
            data[field] += bool(getattr(row, field))
    out["distinct_gbif"] = {level: sorted(names) for level, names in distinct_gbif.items()}
    return out


def _record_accepted(out, distinct_gbif, row, category, chosen, stems):
    if row.levels is None:
        out["unresolved_levels"] += 1
        gbif_class = "?"
    else:
        gbif_class = row.levels["class"] or f"(no class: {row.levels['phylum'] or 'no phylum'})"
        for level in LEVELS:
            if row.levels[level]:
                distinct_gbif[level].add(row.levels[level])
            else:
                out["blank_gbif"][level] += 1
        if row.levels["phylum"] == "Chordata" and not row.levels["class"]:
            out["chordates_without_class"][category] += 1
    out["category_by_gbif_class"][category][gbif_class] += 1

    if category == "absent":
        out["absent_by_extinct"][row.extinct] += 1
        variant = stems.get(spelling_stem(row.name), "")
        out["absent_spelling_variants"] += bool(variant)
        out["absent_rows"].append((
            row.name, variant, gbif_class, row.extinct,
            row.iucn, row.image, row.abstract, row.traits,
        ))
        return
    if category != "accepted":
        return

    out["accepted_via_merged"] += bool(chosen["merged"])
    out["extinct_crosstab"][(row.extinct, chosen["extinct"])] += 1
    if row.levels is None:
        return
    col_levels = levels_from_lineage(chosen["lineage"])
    for level in LEVELS:
        state = level_state(row.levels[level], col_levels[level])
        out["level_states"][level][state] += 1
        if state == "filled":
            out["filled_values"][level][col_levels[level]] += 1
            if level == "class":
                out["filled_classes_by_order"][row.levels["order"]][col_levels["class"]] += 1
    moved = highest_move(row.levels, col_levels)
    if moved:
        out["moves"][moved] += 1
        out["move_pairs"][moved][(row.levels[moved], col_levels[moved])] += 1
        out["moved_rows"].append((row.name, moved, row.levels[moved], col_levels[moved]))


def load_gbif_rows(species_db=SPECIES_DB, taxon_tsv=TAXON_TSV):
    """Every animal species row of species.db, with levels read from the backbone."""
    # immutable: never touches the live database or its WAL files.
    conn = sqlite3.connect(f"file:{species_db}?mode=ro&immutable=1", uri=True)
    rows = conn.execute("""
        SELECT scientific_name, taxon_path, taxonomic_status, extinct, iucn_status IS NOT NULL,
               primary_image_url IS NOT NULL, wikipedia_abstract IS NOT NULL, trait_sources IS NOT NULL
        FROM species WHERE taxon_rank = 'species' AND taxon_path LIKE 'Animalia|%'
    """).fetchall()
    conn.close()
    print(f"  {len(rows):,} animal species rows in species.db", flush=True)

    paths = {row[1] for row in rows}
    levels_by_path = {}
    with open(taxon_tsv, encoding="utf-8", errors="replace", newline="\n") as f:
        header = f.readline().rstrip("\r\n").split("\t")
        for line in f:
            record = dict(zip(header, line.rstrip("\r\n").split("\t")))
            if record.get("kingdom") != "Animalia" or record.get("taxonRank") != "species":
                continue
            path = _build_taxon_path(record)
            if path in paths:
                levels_by_path[path] = {level: (record.get(level) or "").strip() for level in LEVELS}
    return [
        GbifRow(name, status, levels_by_path.get(path), extinct, iucn, image, abstract, traits)
        for name, path, status, extinct, iucn, image, abstract, traits in rows
    ]


def _write_tsv(path, header, rows):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(header) + "\n")
        for row in rows:
            f.write("\t".join("" if v is None else str(v) for v in row) + "\n")


def _jsonable(value):
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _summary(out, top=60):
    summary = {}
    for key, value in out.items():
        if key in ("absent_rows", "moved_rows"):
            continue
        if key == "move_pairs":
            value = {level: {f"{a} -> {b}": n for (a, b), n in pairs.most_common(top)} for level, pairs in value.items()}
        elif key == "filled_classes_by_order":
            value = {order: dict(c) for order, c in sorted(value.items(), key=lambda kv: -sum(kv[1].values()))}
        elif key in ("distinct_col", "distinct_gbif"):
            summary[f"{key}_counts"] = {level: len(names) for level, names in value.items()}
        elif isinstance(value, Counter):
            value = dict(value.most_common())
        summary[key] = value
    return _jsonable(summary)


def main():
    parser = argparse.ArgumentParser(description="Compare species.db with COL trial databases")
    parser.add_argument("--out", default="E:/AnimalKingdomSystem/col/comparison")
    args = parser.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.monotonic()
    print("Loading GBIF side", flush=True)
    gbif_rows = load_gbif_rows()
    print(f"  loaded in {time.monotonic() - t0:,.0f} s", flush=True)

    absent = {}
    for release, db in RELEASES.items():
        print(f"Comparing with {release}", flush=True)
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        out = compare_release(gbif_rows, conn)
        conn.close()
        absent[release] = {row[0] for row in out["absent_rows"]}
        _write_tsv(out_dir / f"gbif_only_{release}.tsv",
                   ("name", "possible_spelling_variant", "gbif_class", "extinct", "iucn", "image", "abstract", "traits"),
                   out["absent_rows"])
        _write_tsv(out_dir / f"moved_{release}.tsv", ("name", "level", "gbif", "col"), out["moved_rows"])
        (out_dir / f"summary_{release}.json").write_text(
            json.dumps(_summary(out), indent=1, ensure_ascii=False), encoding="utf-8",
        )
    (out_dir / "releases.json").write_text(json.dumps({
        "absent_from_both": len(absent["base"] & absent["xr"]),
        "absent_from_base_found_in_xr": len(absent["base"] - absent["xr"]),
        "absent_from_xr_found_in_base": len(absent["xr"] - absent["base"]),
    }, indent=1), encoding="utf-8")
    print(f"Finished in {time.monotonic() - t0:,.0f} s; results in {out_dir}")


if __name__ == "__main__":
    main()
