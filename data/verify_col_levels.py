"""
Check the family or order GBIF gives for groups COL leaves unplaced, against taxonomic
databases other than COL and GBIF (through Global Names Verifier). Read-only for the
databases; results go to E:/AnimalKingdomSystem/col/verification/. Resumable.

A family is checked on the genus, an order on the family (or on the genus if COL has no
family either), because that link belongs to the group, not to one species. A value is
confirmed when at least one source agrees and none names a different one; a source
that has no such rank says nothing. Land snails alone go by majority (at least two sources,
more agreeing than not). Anything else is left as it is in COL.

Usage:
    python data/verify_col_levels.py
"""

import json
import sqlite3
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import compare_col as cc  # noqa: E402

VERIFIER_URL = "https://verifier.globalnames.org/api/v1/verifications"
BATCH_SIZE = 500
OUT_DIR = Path("E:/AnimalKingdomSystem/col/verification")
COL_DB = "E:/AnimalKingdomSystem/col/col_xr.db"

# Excluded on purpose: COL itself; GBIF, EOL and Open Tree of Life, which are built from
# GBIF's or COL's data, so agreeing with GBIF would prove nothing.
SOURCES = {
    9: "WoRMS", 181: "IRMNG", 3: "ITIS", 4: "NCBI", 180: "iNaturalist",
    172: "PaleoBioDB", 193: "Myriatrix", 2: "Wikispecies",
}
_ANIMAL_MARKS = {"Animalia", "Metazoa"}
_PLACEHOLDERS = {"paleo", "incertae sedis", "unknown", "unassigned", "not assigned"}
# Decided by the user 2026-11-06. Land snails: ITIS alone says Helicida, and IRMNG sometimes
# gives "Mollusca" or "Gastropoda" as the order, so the strict rule left them all blank.
_ORDERS_BY_MAJORITY = {"Stylommatophora"}


def source_value(result, level, phylum):
    """The family or order one source record gives, or None if it gives no usable answer."""
    if result.get("matchType") != "Exact":
        return None
    path = (result.get("classificationPath") or "").split("|")
    ranks = (result.get("classificationRanks") or "").split("|")
    if len(path) != len(ranks) or not _ANIMAL_MARKS & set(path) or (phylum and phylum not in path):
        return None
    for name, rank in zip(path, ranks):
        if rank.lower() == level:
            return name
    return None


def verdict(value, source_values):
    answers = {v for v in source_values.values() if v}
    if not answers:
        return "no_evidence"
    if answers == {value}:
        return "confirmed"
    if value in _ORDERS_BY_MAJORITY:
        given = [v for v in source_values.values() if v]
        agree = given.count(value)
        if agree >= 2 and agree > len(given) - agree:
            return "majority"
    return "conflict"


def collect_candidates(gbif_rows, col_rows):
    """{(level, group name, GBIF's value): {"phylum", "species"}} for every accepted GBIF
    species whose order or family is blank in COL."""
    candidates = {}

    def add(level, group, value, phylum):
        if not group or value.casefold() in _PLACEHOLDERS:
            return
        entry = candidates.setdefault((level, group, value), {"phylum": phylum, "species": 0})
        entry["species"] += 1

    for row in gbif_rows:
        if row.status != "ACCEPTED" or not row.levels:
            continue
        category, chosen = cc.classify(col_rows.get(row.name, []), row.levels)
        if category != "accepted":
            continue
        col = cc.levels_from_lineage(chosen["lineage"])
        genus = next((s.split(":", 1)[1] for s in chosen["lineage"].split("|") if s.startswith("genus:")), row.name.split(" ")[0])
        if row.levels["family"] and not col["family"]:
            add("family", genus, row.levels["family"], col["phylum"])
        if row.levels["order"] and not col["order"]:
            add("order", col["family"] or genus, row.levels["order"], col["phylum"])
    return candidates


def _load_col_rows(names):
    conn = sqlite3.connect(f"file:{COL_DB}?mode=ro", uri=True)
    rows = defaultdict(list)
    query = "SELECT scientific_name, status, lineage, merged, extinct FROM name_usage WHERE instr(lineage, 'kingdom:Animalia')"
    for raw, status, lineage, merged, extinct in conn.execute(query):
        name = cc.match_name(raw)
        if name in names:
            rows[name].append({"scientific_name": raw, "status": status, "lineage": lineage, "merged": merged, "extinct": extinct})
    conn.close()
    return rows


def _ask_verifier(names):
    body = json.dumps({"nameStrings": names, "dataSources": list(SOURCES), "withAllMatches": True}).encode()
    request = urllib.request.Request(VERIFIER_URL, data=body, headers={"Content-Type": "application/json"})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                return json.load(response)["names"]
        except OSError as exc:
            if attempt == 5:
                raise
            print(f"  retry after {exc}", flush=True)
            time.sleep(15 * (attempt + 1))


def _fetch_all(groups, cache_path):
    """{group name: [results]}, keeping every answer on disk so a rerun only asks for the rest."""
    answers = {}
    if cache_path.exists():
        with open(cache_path, encoding="utf-8") as f:
            for line in f:
                entry = json.loads(line)
                answers[entry["name"]] = entry["results"]
    missing = [g for g in groups if g not in answers]
    print(f"  {len(groups):,} groups, {len(missing):,} still to ask", flush=True)
    with open(cache_path, "a", encoding="utf-8") as cache:
        for i in range(0, len(missing), BATCH_SIZE):
            batch = missing[i:i + BATCH_SIZE]
            for name, entry in zip(batch, _ask_verifier(batch)):
                answers[name] = entry.get("results") or []
                cache.write(json.dumps({"name": name, "results": answers[name]}, ensure_ascii=False) + "\n")
            cache.flush()
            print(f"  {min(i + BATCH_SIZE, len(missing)):,} / {len(missing):,}", flush=True)
    return answers


def _source_values(results, level, phylum, value):
    """{source: its answer}. A source with several records counts as agreeing if any does."""
    found = defaultdict(set)
    for result in results:
        answer = source_value(result, level, phylum)
        if answer:
            found[result.get("dataSourceTitleShort")].add(answer)
    return {source: value if value in values else sorted(values)[0] for source, values in found.items()}


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("Loading GBIF side", flush=True)
    gbif_rows = cc.load_gbif_rows()
    wanted = {r.name for r in gbif_rows if r.status == "ACCEPTED"}
    print("Loading COL side", flush=True)
    candidates = collect_candidates(gbif_rows, _load_col_rows(wanted))
    print(f"  {len(candidates):,} candidate links", flush=True)
    answers = _fetch_all(sorted({group for _, group, _ in candidates}), OUT_DIR / "verifier_answers.jsonl")

    stats = {"order": Counter(), "family": Counter()}
    confirmers = Counter()
    with open(OUT_DIR / "verdicts.tsv", "w", encoding="utf-8", newline="\n") as out:
        out.write("level\tgroup\tgbif_value\tphylum\tspecies\tverdict\tagree\tdisagree\n")
        for (level, group, value), info in sorted(candidates.items()):
            values = _source_values(answers.get(group, []), level, info["phylum"], value)
            result = verdict(value, values)
            agree = sorted(s for s, v in values.items() if v == value)
            disagree = sorted(f"{s}={v}" for s, v in values.items() if v != value)
            stats[level][result] += 1
            stats[level][f"{result}_species"] += info["species"]
            if result == "confirmed":
                stats[level]["confirmed_by_2plus_species"] += info["species"] if len(agree) > 1 else 0
                confirmers[",".join(agree)] += info["species"]
            out.write("\t".join((level, group, value, info["phylum"], str(info["species"]), result, ",".join(agree), ";".join(disagree))) + "\n")
    print(json.dumps(stats, indent=1))
    print("Confirmed species by source set:", confirmers.most_common(25))


if __name__ == "__main__":
    main()
