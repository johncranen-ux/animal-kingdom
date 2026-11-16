"""Increment 13 — extinct flags: data/backfill_extinct.py and the tree API field."""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import database
from app.main import app

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "data"))
import backfill_extinct as bf  # noqa: E402

client = TestClient(app)
PBDB, COL = bf.PBDB_DATASET_ID, "7ddf754f-d193-4cc9-b351-99906754a03b"
TAPIR = "Animalia|Chordata|Mammalia|Perissodactyla|Tapiridae"


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))


def _insert(name, path, rank="species", extinct=None, iucn=None, status="ACCEPTED", trait_sources=None):
    conn = database.get_connection()
    conn.execute(
        "INSERT INTO species (scientific_name, taxon_path, taxon_rank, taxonomic_status, "
        "extinct, iucn_status, trait_sources) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (name, path, rank, status, extinct, iucn, trait_sources),
    )
    conn.commit()
    conn.close()


def _row(name):
    conn = database.get_connection()
    try:
        return dict(conn.execute("SELECT * FROM species WHERE scientific_name = ?", (name,)).fetchone())
    finally:
        conn.close()


def _tsv_line(dataset, canonical, rank="species", status="accepted", kingdom="Animalia",
              family="Tapiridae", genus="Tapirus"):
    cols = [""] * 23
    cols[1], cols[7], cols[11], cols[14] = dataset, canonical, rank, status
    cols[17:23] = [kingdom, "Chordata", "Mammalia", "Perissodactyla", family, genus]
    return "\t".join(cols) + "\n"


# ── Pure helpers ──────────────────────────────────────────────────────────────

def test_taxon_path_matches_import_gbif():
    cols = _tsv_line(PBDB, "Tapirus merriami").rstrip("\n").split("\t")
    assert bf.taxon_path(cols) == f"{TAPIR}|Tapirus|Tapirus merriami"


def test_pbdb_species_keeps_only_accepted_pbdb_animal_species():
    lines = [
        _tsv_line(PBDB, "Tapirus merriami"),
        _tsv_line(COL,  "Tapirus terrestris"),                     # other source
        _tsv_line(PBDB, "Tapirus oldname", status="synonym"),      # not accepted
        _tsv_line(PBDB, "Ficus fossilis", kingdom="Plantae"),      # not an animal
        _tsv_line(PBDB, "Sirenia", rank="order"),                  # higher rank: roll-up only
        "short\tline\n",
    ]
    assert [n for n, _ in bf.pbdb_species(lines)] == ["Tapirus merriami"]


def test_plan_update_rules():
    path = f"{TAPIR}|Tapirus|Tapirus merriami"
    row = {"taxon_path": path, "extinct": None, "iucn_status": None, "trait_sources": None}
    outcome, ts = bf.plan_update(row, bf.PBDB_SOURCE, path)
    assert outcome == "flagged"
    assert database.parse_trait_sources(ts)["extinct"] == {"source": bf.PBDB_SOURCE, "estimated": False}
    assert bf.plan_update({**row, "taxon_path": "Animalia|X"}, "s", path)[0] == "path_mismatch"
    assert bf.plan_update({**row, "extinct": 0}, "s", path)[0] == "already_set"
    assert bf.plan_update({**row, "iucn_status": "LC"}, "s", path)[0] == "assessed_living"
    assert bf.plan_update({**row, "iucn_status": "EX"}, "s", path)[0] == "flagged"


def test_plan_update_keeps_existing_provenance():
    row = {"taxon_path": "P", "extinct": None, "iucn_status": None,
           "trait_sources": '{"body_mass": {"source": "AnAge", "estimated": false}}'}
    sources = database.parse_trait_sources(bf.plan_update(row, "src", "P")[1])
    assert set(sources) == {"body_mass", "extinct"}


def test_extinct_groups_need_every_species_extinct():
    species = [
        ("A|F1|G1|G1 a", 1), ("A|F1|G1|G1 b", 1),     # G1 all extinct
        ("A|F1|G2|G2 a", 1), ("A|F1|G2|G2 b", None),  # G2 has an unknown
        ("A|F2|G3|G3 a", 0),
    ]
    groups = bf.extinct_groups(bf.species_counts(species))
    assert groups == {"A|F1|G1": 2}


# ── DB passes ─────────────────────────────────────────────────────────────────

def test_species_pass_writes_flags_and_provenance(tmp_path):
    _insert("Tapirus merriami", f"{TAPIR}|Tapirus|Tapirus merriami")
    _insert("Tapirus terrestris", f"{TAPIR}|Tapirus|Tapirus terrestris")
    _insert("Tapirus homonym", "Animalia|Mollusca|X|Y|Z|Tapirus|Tapirus homonym")
    tsv = tmp_path / "Taxon.tsv"
    tsv.write_text("header\n" + _tsv_line(PBDB, "Tapirus merriami") + _tsv_line(COL, "Tapirus terrestris")
                   + _tsv_line(PBDB, "Tapirus homonym") + _tsv_line(PBDB, "Tapirus absent"), encoding="utf-8")

    conn = database.get_connection()
    try:
        stats = bf.species_pass(conn, tsv, dry_run=False)
    finally:
        conn.close()

    assert stats["flagged"] == 1 and stats["path_mismatch"] == 1 and stats["not_in_db"] == 1
    assert _row("Tapirus merriami")["extinct"] == 1
    assert _row("Tapirus terrestris")["extinct"] is None
    assert _row("Tapirus homonym")["extinct"] is None
    assert database.parse_trait_sources(_row("Tapirus merriami")["trait_sources"])["extinct"]["source"] \
        == bf.PBDB_SOURCE


def test_species_pass_dry_run_writes_nothing(tmp_path):
    _insert("Tapirus merriami", f"{TAPIR}|Tapirus|Tapirus merriami")
    tsv = tmp_path / "Taxon.tsv"
    tsv.write_text("header\n" + _tsv_line(PBDB, "Tapirus merriami"), encoding="utf-8")
    conn = database.get_connection()
    try:
        assert bf.species_pass(conn, tsv, dry_run=True)["flagged"] == 1
    finally:
        conn.close()
    assert _row("Tapirus merriami")["extinct"] is None


def test_rollup_flags_only_all_extinct_groups():
    _insert("Tapiridae", TAPIR, rank="family")
    _insert("Tapirus", f"{TAPIR}|Tapirus", rank="genus")
    _insert("Protapirus", f"{TAPIR}|Protapirus", rank="genus")
    _insert("Tapirus merriami", f"{TAPIR}|Tapirus|Tapirus merriami", extinct=1)
    _insert("Tapirus terrestris", f"{TAPIR}|Tapirus|Tapirus terrestris", extinct=0)
    _insert("Protapirus priscus", f"{TAPIR}|Protapirus|Protapirus priscus", extinct=1)
    _insert("Protapirus simplex", f"{TAPIR}|Protapirus|Protapirus simplex", extinct=1)

    conn = database.get_connection()
    try:
        stats, ranks = bf.rollup_pass(conn, dry_run=False)
    finally:
        conn.close()

    assert ranks == {"genus": 1}
    assert _row("Protapirus")["extinct"] == 1
    assert database.parse_trait_sources(_row("Protapirus")["trait_sources"])["extinct"]["source"] \
        == bf.rollup_source(2)
    assert _row("Tapirus")["extinct"] is None
    assert _row("Tapiridae")["extinct"] is None


def test_rollup_dry_run_counts_pending_species():
    _insert("Protapirus", f"{TAPIR}|Protapirus", rank="genus")
    _insert("Protapirus priscus", f"{TAPIR}|Protapirus|Protapirus priscus")
    conn = database.get_connection()
    try:
        _, ranks = bf.rollup_pass(conn, dry_run=True, pass1_flagged={"Protapirus priscus"})
    finally:
        conn.close()
    assert ranks == {"genus": 1}
    assert _row("Protapirus")["extinct"] is None


# ── Tree API ──────────────────────────────────────────────────────────────────

def test_zoom_nodes_carry_extinct_flag():
    _insert("Tapirus", f"{TAPIR}|Tapirus", rank="genus")
    _insert("Tapirus merriami", f"{TAPIR}|Tapirus|Tapirus merriami", extinct=1)
    _insert("Tapirus terrestris", f"{TAPIR}|Tapirus|Tapirus terrestris", extinct=0)
    _insert("Tapirus webbi", f"{TAPIR}|Tapirus|Tapirus webbi")

    resp = client.get("/api/taxonomy/zoom", params={"node_id": f"{TAPIR}|Tapirus"})
    assert resp.status_code == 200
    flags = {n["name"]: n["extinct"] for n in resp.json()}
    assert flags == {"Tapirus merriami": True, "Tapirus terrestris": False, "Tapirus webbi": None}


def test_node_endpoint_carries_extinct_flag():
    _insert("Protapirus", f"{TAPIR}|Protapirus", rank="genus", extinct=1)
    resp = client.get("/api/taxonomy/node", params={"node_id": f"{TAPIR}|Protapirus"})
    assert resp.json()["extinct"] is True


# ── Live roll-up when the sourced stage learns a flag ─────────────────────────

GIRAFFIDAE = "Animalia|Chordata|Mammalia|Artiodactyla|Giraffidae"


def _flag(name):
    from app.trait_utils import TraitValue
    return database.update_species_traits(name, {"extinct": TraitValue(1, "GBIF")}, "sourced", False)


def _giraffids():
    _insert("Giraffidae", GIRAFFIDAE, rank="family")
    _insert("Samotherium", f"{GIRAFFIDAE}|Samotherium", rank="genus")
    _insert("Samotherium boissieri", f"{GIRAFFIDAE}|Samotherium|Samotherium boissieri", extinct=1)
    _insert("Samotherium major", f"{GIRAFFIDAE}|Samotherium|Samotherium major")
    _insert("Okapia", f"{GIRAFFIDAE}|Okapia", rank="genus")
    _insert("Okapia johnstoni", f"{GIRAFFIDAE}|Okapia|Okapia johnstoni", iucn="EN")


def test_learning_the_last_species_flags_its_genus():
    _giraffids()
    assert _row("Samotherium")["extinct"] is None
    assert _flag("Samotherium major")
    assert _row("Samotherium")["extinct"] == 1
    assert database.parse_trait_sources(_row("Samotherium")["trait_sources"])["extinct"]["source"] \
        == database.extinct_rollup_source(2)
    assert _row("Giraffidae")["extinct"] is None          # okapi is alive


def test_genus_with_a_species_still_unknown_stays_unflagged():
    _giraffids()
    _insert("Samotherium sinense", f"{GIRAFFIDAE}|Samotherium|Samotherium sinense")
    _flag("Samotherium major")
    assert _row("Samotherium")["extinct"] is None


def test_rollup_climbs_while_groups_are_all_extinct_but_never_flags_the_kingdom():
    _insert("Animalia", "Animalia", rank="kingdom")
    _insert("Fossilia", "Animalia|Fossilia", rank="phylum")
    _insert("Fossilus", "Animalia|Fossilia|Fossilus", rank="genus")
    _insert("Fossilus primus", "Animalia|Fossilia|Fossilus|Fossilus primus")
    _flag("Fossilus primus")
    assert _row("Fossilus")["extinct"] == 1
    assert _row("Fossilia")["extinct"] == 1
    assert _row("Animalia")["extinct"] is None


# ── data/batch_extinct_gbif.py ────────────────────────────────────────────────

import batch_extinct_gbif as batch  # noqa: E402


def test_batch_candidates_are_unknown_species_in_genera_with_a_fossil():
    _giraffids()                                   # Samotherium: boissieri extinct, major unknown
    _insert("Okapia erikssoni", f"{GIRAFFIDAE}|Okapia|Okapia erikssoni")   # genus without a fossil
    conn = database.get_connection()
    try:
        assert batch.candidate_names(conn) == {
            "Samotherium major": f"{GIRAFFIDAE}|Samotherium|Samotherium major"}
    finally:
        conn.close()


def test_batch_gbif_keys_match_name_and_path(tmp_path):
    def line(tid, name, family="Giraffidae", genus="Samotherium"):
        cols = _tsv_line(COL, name, family=family, genus=genus).rstrip("\n").split("\t")
        cols[0], cols[19], cols[20] = str(tid), "Mammalia", "Artiodactyla"
        return "\t".join(cols) + "\n"
    tsv = tmp_path / "Taxon.tsv"
    tsv.write_text("header\n" + line(111, "Samotherium major", family="Otheridae")
                   + line(222, "Samotherium major"), encoding="utf-8")
    wanted = {"Samotherium major": f"{GIRAFFIDAE}|Samotherium|Samotherium major"}
    assert batch.gbif_keys(wanted, tsv) == [("Samotherium major", 222)]


def test_batch_lookup_uses_the_shared_profile_rule(monkeypatch):
    from app import trait_utils
    monkeypatch.setattr(trait_utils, "_get_json", lambda url: {"results": [
        {"extinct": True, "source": "The Paleobiology Database"}]})
    tv = batch.lookup(123)
    assert (tv.value, tv.source) == (1, "GBIF (The Paleobiology Database)")


def test_trait_write_still_finds_a_differently_cased_name():
    _insert("Tapirus merriami", f"{TAPIR}|Tapirus|Tapirus merriami")
    assert _flag("tapirus MERRIAMI")
    assert _row("Tapirus merriami")["extinct"] == 1
