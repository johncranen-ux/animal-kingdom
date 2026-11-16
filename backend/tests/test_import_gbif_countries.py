"""data/import_gbif_countries.py: wild GBIF records per species per country."""

import sys
from pathlib import Path

import pytest

from app import database

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "data"))
import import_gbif_countries as imp  # noqa: E402

PATH = "Animalia|Chordata|Reptilia|Squamata|Natricidae|Natrix|"
HEADER = "specieskey\tspecies\tcountrycode\tn\n"


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


def _add(name, path=PATH, status="ACCEPTED", **fields):
    cols = {"scientific_name": name, "taxon_path": path, "taxon_rank": "species",
            "taxonomic_status": status, "common_names": "[]", **fields}
    c = database.get_connection()
    c.execute(f"INSERT INTO species ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
              list(cols.values()))
    c.commit()
    c.close()


def _csv(tmp_path, *lines):
    p = tmp_path / "countries.csv"
    p.write_text(HEADER + "".join(line + "\n" for line in lines), encoding="utf-8")
    return p


def test_read_counts_sums_rows_and_skips_bad_codes(tmp_path):
    csv = _csv(tmp_path, "1\tNatrix natrix\tNL\t500", "2\tNatrix natrix\tnl\t5",
                         "1\tNatrix natrix\tZZZ\t9", "1\tNatrix natrix\t\t9", "3\t\tNL\t4")
    assert imp.read_counts(csv) == {"Natrix natrix": {"NL": 505}}


def test_match_accepted_synonym_and_skips(conn):
    _add("Natrix natrix")
    _add("Coluber natrix", status="SYNONYM", accepted_name="Natrix natrix")
    _add("Natrix extincta", extinct=1)
    _add("Natrix nowhere", path=None)
    matched, kinds = imp.match_counts(conn, {
        "Natrix natrix": {"NL": 500}, "Coluber natrix": {"NL": 3, "BE": 2},
        "Natrix extincta": {"NL": 1}, "Natrix nowhere": {"NL": 1}, "Unknown sp": {"NL": 1}})
    assert matched == {"Natrix natrix": {"NL": 503, "BE": 2}}
    assert (kinds["accepted"], kinds["synonym"], kinds["extinct"], kinds["outside_tree"],
            kinds["no_match"]) == (1, 1, 1, 1, 1)


def test_synonym_of_an_unusable_species_is_skipped(conn):
    _add("Coluber natrix", status="SYNONYM", accepted_name="Missing sp")
    matched, kinds = imp.match_counts(conn, {"Coluber natrix": {"NL": 3}})
    assert matched == {} and kinds["synonym_unusable"] == 1


def test_write_table_replaces_old_rows(conn):
    conn.execute("INSERT INTO species_countries VALUES ('IE', 'Old sp', 9)")
    conn.commit()
    assert imp.write_table(conn, {"Natrix natrix": {"NL": 503, "BE": 2}}, batch=1) == 2
    rows = conn.execute("SELECT country, scientific_name, records FROM species_countries "
                        "ORDER BY country").fetchall()
    assert [tuple(r) for r in rows] == [("BE", "Natrix natrix", 2), ("NL", "Natrix natrix", 503)]
    assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'species_countries_new'").fetchone() is None


def test_main_dry_run_writes_nothing(tmp_path, capsys):
    _add("Natrix natrix")
    csv = _csv(tmp_path, "1\tNatrix natrix\tNL\t500")
    assert imp.main(["--csv", str(csv), "--dry-run"]) == 0
    c = database.get_connection()
    try:
        assert c.execute("SELECT COUNT(*) FROM species_countries").fetchone()[0] == 0
    finally:
        c.close()
    assert "tree species with country records: 1" in capsys.readouterr().out
