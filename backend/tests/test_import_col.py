"""Catalogue of Life trial: data/import_col.py loads a ColDP zip into its own database."""

import sqlite3
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "data"))
import import_col  # noqa: E402

USAGE_HEADER = (
    "col:ID", "col:parentID", "col:status", "col:scientificName", "col:authorship", "col:rank",
    "col:code", "col:extinct", "col:environment", "col:link", "clb:merged", "clb:taxGroup",
)
VERNACULAR_HEADER = ("col:taxonID", "col:name", "col:language", "col:preferred", "col:country", "clb:merged")


def _usage(id, parent, status, name, rank, author="", extinct=""):
    return (id, parent, status, name, author, rank, "zoological", extinct, "", "", "false", "")


# Eukaryota > Animalia > Chordata > Actinopterygii (gigaclass) > Teleostei > Barbus > Barbus barbus
TREE = [
    _usage("E", "", "accepted", "Eukaryota", "domain"),
    _usage("A", "E", "accepted", "Animalia", "kingdom"),
    _usage("C", "A", "accepted", "Chordata", "phylum"),
    _usage("G", "C", "accepted", "Actinopterygii", "gigaclass"),
    _usage("T", "G", "accepted", "Teleostei", "class"),
    _usage("B", "T", "accepted", "Barbus", "genus"),
    _usage("S", "B", "accepted", "Barbus barbus", "species", "(Linnaeus, 1758)"),
]
BARBUS_LINEAGE = (
    "domain:Eukaryota|kingdom:Animalia|phylum:Chordata|gigaclass:Actinopterygii"
    "|class:Teleostei|genus:Barbus|species:Barbus barbus"
)


def _make_zip(path, usages, vernacular=None, metadata="alias: COL26.10\nversion: 2026-10-14\n"):
    with zipfile.ZipFile(path, "w") as z:
        lines = ["\t".join(USAGE_HEADER)] + ["\t".join(row) for row in usages]
        z.writestr("NameUsage.tsv", "\n".join(lines) + "\n")
        if vernacular is not None:
            lines = ["\t".join(VERNACULAR_HEADER)] + ["\t".join(row) for row in vernacular]
            z.writestr("VernacularName.tsv", "\n".join(lines) + "\n")
        z.writestr("metadata.yaml", metadata)
    return str(path)


def _import(tmp_path, usages, vernacular=None):
    db = tmp_path / "col.db"
    summary = import_col.import_release(_make_zip(tmp_path / "col.zip", usages, vernacular), str(db))
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    return conn, summary


def test_species_lineage_keeps_every_level_of_the_source(tmp_path):
    conn, _ = _import(tmp_path, TREE)
    row = conn.execute("SELECT * FROM name_usage WHERE id = 'S'").fetchone()
    assert row["lineage"] == BARBUS_LINEAGE
    assert (row["rank"], row["status"], row["authorship"]) == ("species", "accepted", "(Linnaeus, 1758)")


def test_homonyms_each_keep_their_own_row(tmp_path):
    # One row per name is what let a moth synonym shadow the big cats in the GBIF import.
    conn, _ = _import(tmp_path, TREE + [
        _usage("MOTH", "A", "accepted", "Panthera", "genus"),
        _usage("CAT", "C", "accepted", "Panthera", "genus"),
    ])
    rows = conn.execute("SELECT lineage FROM name_usage WHERE scientific_name = 'Panthera' ORDER BY id").fetchall()
    assert [r["lineage"] for r in rows] == [
        "domain:Eukaryota|kingdom:Animalia|phylum:Chordata|genus:Panthera",
        "domain:Eukaryota|kingdom:Animalia|genus:Panthera",
    ]


@pytest.mark.parametrize("status", ["synonym", "ambiguous synonym", "misapplied"])
def test_non_accepted_name_sits_at_its_accepted_taxon(tmp_path, status):
    conn, _ = _import(tmp_path, TREE + [_usage("OLD", "S", status, "Cyprinus barbus", "species")])
    row = conn.execute("SELECT * FROM name_usage WHERE id = 'OLD'").fetchone()
    assert row["lineage"] == BARBUS_LINEAGE
    assert row["status"] == status
    assert row["parent_id"] == "S"


def test_child_of_a_provisionally_accepted_taxon_inherits_its_lineage(tmp_path):
    conn, _ = _import(tmp_path, TREE + [
        _usage("P", "B", "provisionally accepted", "Barbus novus", "species"),
        _usage("SUB", "P", "accepted", "Barbus novus minor", "subspecies"),
    ])
    lineage = conn.execute("SELECT lineage FROM name_usage WHERE id = 'SUB'").fetchone()[0]
    assert lineage.endswith("|genus:Barbus|species:Barbus novus|subspecies:Barbus novus minor")


@pytest.mark.parametrize("raw,stored", [("true", 1), ("false", 0), ("", None)])
def test_extinct_flag_distinguishes_living_from_unknown(tmp_path, raw, stored):
    conn, _ = _import(tmp_path, TREE + [_usage("X", "B", "accepted", "Barbus fossilis", "species", extinct=raw)])
    assert conn.execute("SELECT extinct FROM name_usage WHERE id = 'X'").fetchone()[0] == stored


def test_stray_quote_does_not_swallow_following_rows(tmp_path):
    conn, summary = _import(tmp_path, TREE + [
        _usage("Q", "B", "accepted", "Barbus quotus", "species", author='"Smith, 1900'),
        _usage("R", "B", "accepted", "Barbus rectus", "species", author="Jones"),
    ])
    assert summary["usages"] == 9
    assert conn.execute("SELECT authorship FROM name_usage WHERE id = 'Q'").fetchone()[0] == '"Smith, 1900'
    assert conn.execute("SELECT authorship FROM name_usage WHERE id = 'R'").fetchone()[0] == "Jones"


def test_missing_parent_is_counted_and_keeps_the_known_part_of_the_lineage(tmp_path):
    conn, summary = _import(tmp_path, TREE + [
        _usage("LOST", "NOPE", "accepted", "Lostus", "genus"),
        _usage("KID", "LOST", "accepted", "Lostus minor", "species"),
    ])
    assert conn.execute("SELECT lineage FROM name_usage WHERE id = 'KID'").fetchone()[0] == (
        "genus:Lostus|species:Lostus minor"
    )
    assert summary["broken_lineages"] == 2


def test_parent_cycle_stops_and_is_counted(tmp_path):
    conn, summary = _import(tmp_path, [
        _usage("L1", "L2", "accepted", "Loopa", "genus"),
        _usage("L2", "L1", "accepted", "Loopb", "family"),
    ])
    assert conn.execute("SELECT lineage FROM name_usage WHERE id = 'L1'").fetchone()[0] == (
        "family:Loopb|genus:Loopa"
    )
    assert summary["broken_lineages"] == 2


def test_row_with_wrong_field_count_is_counted(tmp_path):
    # An embedded tab or newline would shift columns: it has to show up in the summary.
    conn, summary = _import(tmp_path, TREE + [("SHORT", "B", "accepted", "Barbus brevis")])
    assert summary["malformed_rows"] == 1
    assert summary["usages"] == 8
    assert conn.execute("SELECT lineage FROM name_usage WHERE id = 'SHORT'").fetchone()[0] is None


def test_vernacular_names_load_in_every_language(tmp_path):
    conn, summary = _import(tmp_path, TREE, vernacular=[
        ("S", "barbel", "eng", "", "", "false"),
        ("S", "barbeel", "nld", "", "NL", "true"),
    ])
    rows = conn.execute(
        "SELECT name, language, country, merged FROM vernacular WHERE taxon_id = 'S' ORDER BY language"
    ).fetchall()
    assert [tuple(r) for r in rows] == [("barbel", "eng", "", 0), ("barbeel", "nld", "NL", 1)]
    assert summary["vernacular"] == 2


def test_release_without_vernacular_file_still_imports(tmp_path):
    conn, summary = _import(tmp_path, TREE)
    assert summary["vernacular"] == 0
    assert conn.execute("SELECT COUNT(*) FROM vernacular").fetchone()[0] == 0


def test_merged_flag_separates_extended_content_from_base(tmp_path):
    merged = list(TREE[-1])
    merged[0], merged[3], merged[10] = "M", "Barbus mergus", "true"
    conn, _ = _import(tmp_path, TREE + [tuple(merged)])
    assert conn.execute("SELECT merged FROM name_usage WHERE id = 'M'").fetchone()[0] == 1
    assert conn.execute("SELECT merged FROM name_usage WHERE id = 'S'").fetchone()[0] == 0


def test_release_version_is_recorded_for_provenance(tmp_path):
    conn, _ = _import(tmp_path, TREE)
    meta = dict(conn.execute("SELECT key, value FROM import_meta").fetchall())
    assert meta["alias"] == "COL26.10"
    assert meta["version"] == "2026-10-14"
    assert meta["source_file"] == "col.zip"


def test_existing_database_is_never_overwritten(tmp_path):
    target = tmp_path / "species.db"
    target.write_bytes(b"precious")
    source = _make_zip(tmp_path / "col.zip", TREE)
    with pytest.raises(FileExistsError):
        import_col.import_release(source, str(target))
    assert target.read_bytes() == b"precious"


def test_failed_import_leaves_no_database_behind(tmp_path):
    source = tmp_path / "broken.zip"
    with zipfile.ZipFile(source, "w") as z:
        z.writestr("metadata.yaml", "alias: x\n")
    target = tmp_path / "col.db"
    with pytest.raises(KeyError):
        import_col.import_release(str(source), str(target))
    assert list(tmp_path.glob("col.db*")) == []
