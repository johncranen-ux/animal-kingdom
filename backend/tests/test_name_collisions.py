"""Name collisions: data/fix_name_collisions.py and the import's row preference."""

import json
import sys
from pathlib import Path

import pytest

from app import database

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "data"))
import fix_name_collisions as fx  # noqa: E402
import import_gbif  # noqa: E402

CATS = "Animalia|Chordata|Mammalia|Carnivora|Felidae|Panthera"
MOTH = "Animalia|Arthropoda|Insecta|Lepidoptera|Geometridae|Pantherodes"


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))


def _insert(name, path, rank="genus", status="SYNONYM", **extra):
    cols = {"scientific_name": name, "taxon_path": path, "taxon_rank": rank,
            "taxonomic_status": status, **extra}
    conn = database.get_connection()
    conn.execute(f"INSERT INTO species ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                 list(cols.values()))
    conn.commit()
    conn.close()


def _row(name):
    conn = database.get_connection()
    try:
        return dict(conn.execute("SELECT * FROM species WHERE scientific_name = ?", (name,)).fetchone())
    finally:
        conn.close()


def _tsv(tid, canonical, rank, status, kingdom="Animalia", lineage=("", "", "", "", "")):
    cols = [""] * 23
    cols[0], cols[7], cols[11], cols[14], cols[17] = tid, canonical, rank, status, kingdom
    cols[18:23] = lineage
    return "\t".join(cols) + "\n"


# ── Backbone parsing ──────────────────────────────────────────────────────────

def test_accepted_animals_skips_synonyms_and_other_kingdoms():
    lines = [
        _tsv("1", "Panthera", "genus", "synonym", lineage=("Arthropoda", "Insecta", "Lepidoptera", "Geometridae", "Pantherodes")),
        _tsv("2", "Panthera", "genus", "accepted", lineage=("Chordata", "Mammalia", "Carnivora", "Felidae", "Panthera")),
        _tsv("3", "Oenanthe", "genus", "accepted", kingdom="Plantae"),
    ]
    assert fx.accepted_animals(lines) == {"Panthera": [("2", CATS, "genus")]}


def test_english_names_filters_ids_and_language():
    rows = [
        {"taxonID": "2", "vernacularName": "Big cats", "language": "en"},
        {"taxonID": "2", "vernacularName": "Großkatzen", "language": "de"},
        {"taxonID": "9", "vernacularName": "Other", "language": "en"},
        {"taxonID": "2", "vernacularName": "big cats", "language": "eng"},   # repeat
    ]
    assert fx.english_names(rows, {"2"}) == {"2": ["Big cats"]}


# ── plan_fix ──────────────────────────────────────────────────────────────────

def test_plan_replaces_a_synonym_shadowing_an_accepted_animal():
    row = {"taxon_path": MOTH, "taxonomic_status": "SYNONYM"}
    assert fx.plan_fix(row, [("2", CATS, "genus")]) == ("replace", ("2", CATS, "genus"))


def test_plan_relabels_when_the_lineage_already_matches():
    row = {"taxon_path": CATS, "taxonomic_status": "SYNONYM"}
    assert fx.plan_fix(row, [("2", CATS, "genus")])[0] == "relabel"


def test_plan_replaces_an_accepted_row_of_another_kingdom():
    row = {"taxon_path": "Plantae|Orbella", "taxonomic_status": "ACCEPTED"}
    assert fx.plan_fix(row, [("5", "Animalia|Arthropoda|Orbella", "genus")])[0] == "replace"


def test_plan_never_touches_an_accepted_animal():
    row = {"taxon_path": CATS, "taxonomic_status": "ACCEPTED"}
    assert fx.plan_fix(row, [("7", "Animalia|Mollusca|Panthera", "genus")]) == ("already_ok", None)


def test_plan_without_accepted_animal_does_nothing():
    row = {"taxon_path": MOTH, "taxonomic_status": "SYNONYM"}
    assert fx.plan_fix(row, None) == ("no_accepted_animal", None)


def test_plan_homonyms_highest_rank_wins():
    row = {"taxon_path": "Animalia|Nematoda|Proboscidea", "taxonomic_status": "SYNONYM"}
    cands = [("9462777", "Animalia|Annelida|Polychaeta|Phyllodocida|Glyceridae|Proboscidea", "genus"),
             ("799", "Animalia|Chordata|Mammalia|Proboscidea", "order"),
             ("9430421", "Animalia|Chordata|Mammalia|Proboscidea", "family")]
    assert fx.plan_fix(row, cands) == ("replace", cands[1])


def test_plan_homonyms_of_equal_rank_are_left_alone():
    row = {"taxon_path": MOTH, "taxonomic_status": "SYNONYM"}
    cands = [("2", CATS, "genus"), ("7", "Animalia|Mollusca|Panthera", "genus")]
    assert fx.plan_fix(row, cands) == ("ambiguous", None)


# ── DB writes ─────────────────────────────────────────────────────────────────

def test_apply_replace_swaps_lineage_and_clears_organism_data():
    _insert("Panthera", MOTH, extinct=1, primary_image_url="moth.jpg", wikipedia_abstract="A moth.",
            trait_sources=json.dumps({"extinct": {"source": "x", "estimated": False}}), body_mass=0.001)
    conn = database.get_connection()
    fx.apply_fixes(conn, [("replace", "Panthera", ("2", CATS, "genus"), ["Big cats"])])
    conn.close()
    row = _row("Panthera")
    assert (row["taxon_path"], row["taxon_rank"], row["taxonomic_status"]) == (CATS, "genus", "ACCEPTED")
    assert database.parse_common_names(row["common_names"]) == ["Big cats"]
    for col in ("extinct", "primary_image_url", "wikipedia_abstract", "trait_sources", "body_mass"):
        assert row[col] is None, col
    assert row["taxon_depth"] == 5   # trigger recomputed it from the new path


def test_apply_relabel_keeps_data_and_existing_common_names():
    _insert("Leo", CATS + "|Leo", rank="species", body_mass=190.0, common_names='["Lion"]')
    _insert("Tigris", CATS + "|Tigris", rank="species", common_names="[]")
    conn = database.get_connection()
    fx.apply_fixes(conn, [("relabel", "Leo", ("3", CATS + "|Leo", "species"), ["Other"]),
                          ("relabel", "Tigris", ("4", CATS + "|Tigris", "species"), ["Tiger"])])
    conn.close()
    leo, tigris = _row("Leo"), _row("Tigris")
    assert leo["taxonomic_status"] == "ACCEPTED" and leo["body_mass"] == 190.0
    assert database.parse_common_names(leo["common_names"]) == ["Lion"]
    assert database.parse_common_names(tigris["common_names"]) == ["Tiger"]


def test_backup_rows_writes_full_rows_as_jsonl(tmp_path):
    _insert("Panthera", MOTH, primary_image_url="moth.jpg")
    out = tmp_path / "backup.jsonl"
    conn = database.get_connection()
    assert fx.backup_rows(conn, ["Panthera", "Missing"], out) == 1
    conn.close()
    saved = json.loads(out.read_text(encoding="utf-8").strip())
    assert saved["taxon_path"] == MOTH and saved["primary_image_url"] == "moth.jpg"


# ── import_gbif keeps the best row per name ───────────────────────────────────

def test_row_score_order():
    s = import_gbif.row_score
    assert s("ACCEPTED", CATS, "genus") > s("ACCEPTED", "Plantae|Panthera", "genus") > s("SYNONYM", MOTH, "genus")
    assert s("ACCEPTED", "Animalia|Chordata|Mammalia|Proboscidea", "order") > s(
        "ACCEPTED", "Animalia|Annelida|Proboscidea", "genus")


def test_import_upsert_prefers_accepted_animal_regardless_of_file_order():
    conn = database.get_connection()
    conn.create_function("row_score", 3, import_gbif.row_score, deterministic=True)
    conn.executemany(import_gbif.UPSERT_SQL, [
        ("Panthera", MOTH, "genus", "[]", "SYNONYM"),                     # first in the file
        ("Panthera", CATS, "genus", '["Big cats"]', "ACCEPTED"),          # better: replaces
        ("Panthera", "Animalia|Mollusca|Panthera", "genus", "[]", "SYNONYM"),  # worse: ignored
    ])
    conn.commit()
    conn.close()
    row = _row("Panthera")
    assert (row["taxon_path"], row["taxonomic_status"]) == (CATS, "ACCEPTED")
