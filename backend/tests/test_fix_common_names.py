"""data/fix_common_names.py: wrong common names on top-rank taxa."""

import json
import sys
from pathlib import Path

import pytest

from app import database

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "data"))
import fix_common_names as fx  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))


def _insert(name, rank, names):
    conn = database.get_connection()
    conn.execute(
        "INSERT INTO species (scientific_name, taxon_path, taxon_rank, taxonomic_status, common_names) "
        "VALUES (?, ?, ?, 'ACCEPTED', ?)",
        (name, f"Animalia|{name}", rank, json.dumps(names)),
    )
    conn.commit()
    conn.close()


def _names(name):
    conn = database.get_connection()
    try:
        row = conn.execute("SELECT common_names FROM species WHERE scientific_name = ?", (name,)).fetchone()
        return json.loads(row["common_names"])
    finally:
        conn.close()


FIX = {"Myxini": fx.Fix("class", "Hagfish", drop=("fish", "fishes"))}


def test_right_name_goes_first_and_wrong_names_go(tmp_path):
    _insert("Myxini", "class", ["fish", "fishes", "slime eels"])
    fx.apply_fixes(FIX, tmp_path / "backup.jsonl")
    assert _names("Myxini") == ["Hagfish", "slime eels"]


def test_right_name_already_listed_is_moved_not_repeated(tmp_path):
    _insert("Myxini", "class", ["fish", "slime eels", "hagfish"])
    fx.apply_fixes(FIX, tmp_path / "backup.jsonl")
    assert _names("Myxini") == ["Hagfish", "slime eels"]


def test_old_names_can_be_restored_from_the_backup(tmp_path):
    _insert("Myxini", "class", ["fish", "fishes"])
    backup = tmp_path / "backup.jsonl"
    fx.apply_fixes(FIX, backup)
    saved = [json.loads(line) for line in backup.read_text(encoding="utf-8").splitlines()]
    assert saved == [{"scientific_name": "Myxini", "common_names": json.dumps(["fish", "fishes"])}]


def test_a_second_run_changes_nothing_and_keeps_the_first_backup(tmp_path):
    _insert("Myxini", "class", ["fish", "fishes"])
    backup = tmp_path / "backup.jsonl"
    fx.apply_fixes(FIX, backup)
    first = backup.read_text(encoding="utf-8")
    assert fx.apply_fixes(FIX, backup).changed == []
    assert backup.read_text(encoding="utf-8") == first


def test_dry_run_reports_but_writes_nothing(tmp_path):
    _insert("Myxini", "class", ["fish"])
    backup = tmp_path / "backup.jsonl"
    result = fx.apply_fixes(FIX, backup, dry_run=True)
    assert [c[0] for c in result.changed] == ["Myxini"]
    assert _names("Myxini") == ["fish"]
    assert not backup.exists()


def test_row_of_another_rank_is_left_alone(tmp_path):
    """Names are shared across ranks: a genus called Myxini must not get the class's label."""
    _insert("Myxini", "genus", ["fish"])
    result = fx.apply_fixes(FIX, tmp_path / "backup.jsonl")
    assert _names("Myxini") == ["fish"]
    assert result.skipped == ["Myxini"]


def test_missing_row_is_reported(tmp_path):
    database.get_connection().close()
    assert fx.apply_fixes(FIX, tmp_path / "backup.jsonl").skipped == ["Myxini"]


def test_correction_list_is_well_formed():
    assert fx.CORRECTIONS
    for name, fix in fx.CORRECTIONS.items():
        assert name[0].isupper() and " " not in name, name
        assert fix.rank in {"kingdom", "phylum", "class", "order"}, name
        assert fix.name.strip(), name
        assert fix.name.lower() not in {d.lower() for d in fix.drop}, name
