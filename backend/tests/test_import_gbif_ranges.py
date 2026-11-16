"""data/import_gbif_ranges.py: GBIF SQL-download ranges into geo_bounding_box."""

import json
import sys
from pathlib import Path

import pytest

from app import database

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "data"))
import import_gbif_ranges as imp  # noqa: E402

PATH = "Animalia|Chordata|Aves|Sphenisciformes|Spheniscidae|Spheniscus|"
HEADER = "specieskey\tspecies\tn\tcountries\tlat_min\tlat_max\tlon_min\tlon_max\n"
R = {"lat_min": -1.3, "lat_max": 0.1, "lon_min": -91.6, "lon_max": -90.0, "records": 9706, "countries": 1}


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    conn = database.get_connection()
    conn.commit()
    conn.close()


@pytest.fixture
def conn():
    c = database.get_connection()
    yield c
    c.close()


def _add(name, path, status="ACCEPTED", **fields):
    cols = {"scientific_name": name, "taxon_path": path, "taxon_rank": "species",
            "taxonomic_status": status, "common_names": "[]", **fields}
    c = database.get_connection()
    c.execute(f"INSERT INTO species ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
              list(cols.values()))
    c.commit()
    c.close()


def _row(name):
    c = database.get_connection()
    try:
        return dict(c.execute("SELECT * FROM species WHERE scientific_name = ?", (name,)).fetchone())
    finally:
        c.close()


def _csv(tmp_path, *lines):
    p = tmp_path / "ranges.csv"
    p.write_text(HEADER + "".join(line + "\n" for line in lines), encoding="utf-8")
    return p


def _rng(n, lat_max=1.0):
    return {"lat_min": 0.0, "lat_max": lat_max, "lon_min": 0.0, "lon_max": 1.0, "records": n}


# ── read_ranges ───────────────────────────────────────────────────────────────

def test_read_ranges_applies_minimum_and_skips_empty_edges(tmp_path):
    csv = _csv(tmp_path, "1\tA a\t10\t1\t0\t1\t0\t1",
                         "2\tB b\t9\t1\t0\t1\t0\t1",
                         "3\tC c\t50\t2\t0\t1\t0\t")
    assert list(imp.read_ranges(csv)) == ["A a"]
    assert imp.read_ranges(csv)["A a"] == {"lat_min": 0, "lat_max": 1, "lon_min": 0, "lon_max": 1,
                                           "records": 10, "countries": 1}


def test_read_ranges_keeps_the_better_recorded_duplicate(tmp_path):
    csv = _csv(tmp_path, "1\tA a\t12\t1\t0\t1\t0\t1", "2\tA a\t40\t1\t0\t2\t0\t1")
    assert imp.read_ranges(csv)["A a"]["lat_max"] == 2


def test_read_ranges_drops_longitude_across_the_180_line(tmp_path):
    csv = _csv(tmp_path, "1\tUrsus maritimus\t4892\t5\t51.6\t83.0\t-179.7\t179.4")
    assert imp.read_ranges(csv)["Ursus maritimus"] == {"lat_min": 51.6, "lat_max": 83.0,
                                                       "records": 4892, "countries": 5}


# ── match_ranges ──────────────────────────────────────────────────────────────

def test_match_accepted_species_in_tree(conn):
    _add("Spheniscus mendiculus", PATH + "Spheniscus mendiculus")
    updates, counts = imp.match_ranges(conn, {"Spheniscus mendiculus": R})
    assert updates == {"Spheniscus mendiculus": R} and counts["accepted"] == 1


def test_match_skips_extinct_and_outside_tree_and_homonym_keys(conn):
    _add("Fossilis x", PATH + "Fossilis x", extinct=1)
    _add("Orphan y", None, status="GBIF_ONLY")
    _add("Homonym z [Aves]", PATH + "Homonym z [Aves]")
    updates, counts = imp.match_ranges(conn, {"Fossilis x": R, "Orphan y": R, "Homonym z": R})
    assert updates == {}
    assert (counts["extinct"], counts["outside_tree"], counts["no_match"]) == (1, 1, 1)


def test_synonym_range_goes_to_accepted_unless_it_has_its_own(conn):
    _add("Old name", None, status="SYNONYM", accepted_name="New name")
    _add("New name", PATH + "New name")
    updates, counts = imp.match_ranges(conn, {"Old name": _rng(20)})
    assert updates == {"New name": _rng(20)} and counts["synonym"] == 1
    updates, _ = imp.match_ranges(conn, {"Old name": _rng(20), "New name": _rng(15, 5.0)})
    assert updates == {"New name": _rng(15, 5.0)}


def test_of_two_synonyms_the_better_recorded_wins(conn):
    _add("Old a", None, status="SYNONYM", accepted_name="New name")
    _add("Old b", None, status="SYNONYM", accepted_name="New name")
    _add("New name", PATH + "New name")
    updates, _ = imp.match_ranges(conn, {"Old a": _rng(20, 1.0), "Old b": _rng(90, 2.0)})
    assert updates == {"New name": _rng(90, 2.0)}


def test_synonym_to_extinct_or_missing_species_is_unusable(conn):
    _add("Old a", None, status="SYNONYM", accepted_name="Gone")
    _add("Old b", None, status="SYNONYM", accepted_name="Fossil")
    _add("Fossil", PATH + "Fossil", extinct=1)
    updates, counts = imp.match_ranges(conn, {"Old a": R, "Old b": R})
    assert updates == {} and counts["synonym_unusable"] == 2


# ── apply_ranges ──────────────────────────────────────────────────────────────

def test_apply_replaces_range_writes_provenance_and_backs_up(tmp_path):
    _add("A a", PATH + "A a", geo_bounding_box='{"lat_min": 1, "lat_max": 60}',
         trait_sources='{"habitat_type": {"source": "GBIF", "estimated": false}}')
    backup = tmp_path / "b.jsonl"
    assert imp.apply_ranges({"A a": R}, "SRC", backup) == 1
    row = _row("A a")
    assert json.loads(row["geo_bounding_box"]) == R
    src = json.loads(row["trait_sources"])
    assert src["geo_bounding_box"] == {"source": "SRC", "estimated": False} and "habitat_type" in src
    saved = json.loads(backup.read_text(encoding="utf-8").splitlines()[0])
    assert saved == {"scientific_name": "A a", "geo_bounding_box": '{"lat_min": 1, "lat_max": 60}',
                     "trait_sources": '{"habitat_type": {"source": "GBIF", "estimated": false}}'}


def test_apply_rerun_skips_rows_already_holding_the_range(tmp_path):
    _add("A a", PATH + "A a")
    backup = tmp_path / "b.jsonl"
    assert imp.apply_ranges({"A a": R}, "SRC", backup) == 1
    assert imp.apply_ranges({"A a": R}, "SRC", backup) == 0
    assert len(backup.read_text(encoding="utf-8").splitlines()) == 1


def test_apply_works_in_batches(tmp_path):
    for i in range(5):
        _add(f"A a{i}", PATH + f"A a{i}")
    assert imp.apply_ranges({f"A a{i}": R for i in range(5)}, "SRC", tmp_path / "b.jsonl", batch=2) == 5
    assert all(json.loads(_row(f"A a{i}")["geo_bounding_box"]) == R for i in range(5))


# ── main ──────────────────────────────────────────────────────────────────────

def test_dry_run_writes_nothing(tmp_path, capsys):
    _add("A a", PATH + "A a")
    csv = _csv(tmp_path, "1\tA a\t10\t1\t0\t1\t0\t1")
    backup = tmp_path / "b.jsonl"
    assert imp.main(["--csv", str(csv), "--backup", str(backup), "--dry-run"]) == 0
    assert _row("A a")["geo_bounding_box"] is None and not backup.exists()
    assert "accepted" in capsys.readouterr().out


def test_real_run_writes_with_doi_source(tmp_path):
    _add("A a", PATH + "A a")
    csv = _csv(tmp_path, "1\tA a\t10\t1\t0\t1\t0\t1")
    assert imp.main(["--csv", str(csv), "--backup", str(tmp_path / "b.jsonl")]) == 0
    src = json.loads(_row("A a")["trait_sources"])["geo_bounding_box"]["source"]
    assert src == "GBIF occurrences (wild records, 0.5% edges, doi:10.15468/dl.5v8cu8)"
