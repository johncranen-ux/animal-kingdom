"""Catalogue of Life trial: data/compare_col.py compares a release with the GBIF-based names."""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "data"))
import compare_col as cc  # noqa: E402
import import_col  # noqa: E402

BARBUS = (
    "domain:Eukaryota|kingdom:Animalia|phylum:Chordata|gigaclass:Actinopterygii"
    "|class:Teleostei|order:Cypriniformes|family:Cyprinidae|genus:Barbus|species:Barbus barbus"
)
LEO = "kingdom:Animalia|phylum:Chordata|class:Mammalia|order:Carnivora|family:Felidae|genus:Panthera|species:Panthera leo"
PLANT = "kingdom:Plantae|phylum:Tracheophyta|class:Liliopsida|order:Poales|family:Poaceae|genus:Zea|species:Zea mays"


def _levels(phylum="Chordata", class_="Mammalia", order="Carnivora", family="Felidae"):
    return {"phylum": phylum, "class": class_, "order": order, "family": family}


def test_levels_ignore_ranks_outside_the_compared_four():
    assert cc.levels_from_lineage(BARBUS) == {
        "phylum": "Chordata", "class": "Teleostei", "order": "Cypriniformes", "family": "Cyprinidae",
    }


def test_levels_leave_a_missing_rank_blank():
    assert cc.levels_from_lineage("kingdom:Animalia|phylum:Porifera|genus:Foo")["class"] == ""


@pytest.mark.parametrize("gbif,col,want", [
    ("Mammalia", "Mammalia", "same"),
    ("", "Teleostei", "filled"),
    ("Mammalia", "", "emptied"),
    ("Reptilia", "Testudines", "different"),
    ("", "", "both_blank"),
])
def test_level_state(gbif, col, want):
    assert cc.level_state(gbif, col) == want


def test_move_reports_the_highest_level_that_really_differs():
    gbif = _levels(class_="Reptilia", family="Testudinidae")
    col = _levels(class_="Testudines", family="Geoemydidae")
    assert cc.highest_move(gbif, col) == "class"


def test_filling_a_blank_level_is_not_a_move():
    assert cc.highest_move(_levels(class_=""), _levels(class_="Teleostei")) is None


def _col_row(status, lineage, name="Panthera leo"):
    return {"scientific_name": name, "status": status, "lineage": lineage, "merged": 0, "extinct": None}


def test_accepted_animal_outranks_a_synonym_of_the_same_name():
    syn = _col_row("synonym", "kingdom:Animalia|phylum:Arthropoda|family:Geometridae|genus:Pantherodes")
    acc = _col_row("accepted", LEO)
    category, chosen = cc.classify([syn, acc], _levels())
    assert category == "accepted"
    assert chosen is acc


def test_homonym_closest_to_the_gbif_family_is_chosen():
    other = _col_row("accepted", "kingdom:Animalia|phylum:Arthropoda|family:Geometridae|genus:Panthera|species:Panthera leo")
    right = _col_row("provisionally accepted", LEO)
    _, chosen = cc.classify([other, right], _levels())
    assert chosen is right


def test_name_kept_only_as_an_animal_synonym():
    syn = _col_row("synonym", LEO, name="Felis leo")
    assert cc.classify([syn], _levels()) == ("synonym", syn)


def test_name_found_only_outside_animals():
    plant = _col_row("accepted", PLANT)
    assert cc.classify([plant], _levels()) == ("not_animal", plant)


def test_name_not_in_the_release():
    assert cc.classify([], _levels()) == ("absent", None)


@pytest.mark.parametrize("a,b,same", [
    ("Barbus albus", "Barbus alba", True),
    ("Barbus smithii", "Barbus smithi", True),
    ("Barbus albus", "Puntius alba", False),
    ("Barbus albus", "Barbus niger", False),
])
def test_spelling_stem_only_matches_the_same_genus_and_stem(a, b, same):
    assert (cc.spelling_stem(a) == cc.spelling_stem(b)) is same


@pytest.mark.parametrize("col_name,want", [
    ("Danaus (Danaus) plexippus", "Danaus plexippus"),
    ("Agonum (Europhilus) gratiosum", "Agonum gratiosum"),
    ("Panthera leo", "Panthera leo"),
    ("Tipula (Microtipula) infida minor", "Tipula infida minor"),
])
def test_match_name_drops_the_subgenus_col_writes_inside_names(col_name, want):
    assert cc.match_name(col_name) == want


def test_species_written_with_a_subgenus_matches_the_plain_gbif_name(tmp_path):
    conn = sqlite3.connect(tmp_path / "sub.db")
    conn.executescript(import_col.SCHEMA)
    lineage = "kingdom:Animalia|phylum:Arthropoda|class:Insecta|family:Nymphalidae|genus:Danaus|species:Danaus (Danaus) plexippus"
    conn.execute(
        "INSERT INTO name_usage (id, status, rank, scientific_name, lineage) VALUES ('D', 'accepted', 'species', ?, ?)",
        ("Danaus (Danaus) plexippus", lineage),
    )
    conn.commit()
    butterfly = _levels(phylum="Arthropoda", class_="Insecta", order="Lepidoptera", family="Nymphalidae")
    out = cc.compare_release([_gbif("Danaus plexippus", levels=butterfly)], conn)
    conn.close()
    assert out["accepted_categories"] == {"accepted": 1}
    assert out["col_only"] == {}


def _gbif(name, status="ACCEPTED", levels=None, extinct=None, iucn=0, image=0, abstract=0, traits=0):
    return cc.GbifRow(name, status, levels or _levels(), extinct, iucn, image, abstract, traits)


@pytest.fixture
def col_db(tmp_path):
    conn = sqlite3.connect(tmp_path / "col.db")
    conn.executescript(import_col.SCHEMA)
    rows = [
        # id, status, rank, name, lineage, extinct, merged
        ("1", "accepted", "species", "Panthera leo", LEO, 0, 0),
        ("2", "accepted", "species", "Barbus barbus", BARBUS, None, 1),
        ("3", "synonym", "species", "Felis leo", LEO, None, 0),
        ("4", "accepted", "species", "Zea mays", PLANT, None, 0),
        ("5", "accepted", "species", "Barbus novus",
         "kingdom:Animalia|phylum:Chordata|class:Teleostei|genus:Barbus|species:Barbus novus", None, 0),
        ("6", "accepted", "species", "Barbus alba",
         "kingdom:Animalia|phylum:Chordata|class:Teleostei|genus:Barbus|species:Barbus alba", None, 0),
        ("7", "accepted", "species", "Vombatus ursinus",
         "kingdom:Animalia|phylum:Chordata|class:Mammalia|genus:Vombatus|species:Vombatus ursinus", None, 0),
        ("8", "accepted", "genus", "Barbus", "kingdom:Animalia|phylum:Chordata|genus:Barbus", None, 0),
    ]
    conn.executemany(
        "INSERT INTO name_usage (id, status, rank, scientific_name, lineage, extinct, merged) VALUES (?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def result(col_db):
    fish = _levels(class_="", order="Cypriniformes", family="Cyprinidae")
    return cc.compare_release([
        _gbif("Panthera leo", iucn=1),
        _gbif("Barbus barbus", levels=fish, extinct=1),
        _gbif("Felis leo", image=1),
        _gbif("Zea mays"),
        _gbif("Lostus perditus", abstract=1, traits=1),
        _gbif("Barbus albus", levels=fish),
        _gbif("Vombatus ursinus", status="SYNONYM"),
    ], col_db)


def test_every_accepted_gbif_species_lands_in_one_category(result):
    assert result["accepted_categories"] == {"accepted": 2, "synonym": 1, "not_animal": 1, "absent": 2}


def test_data_on_names_that_do_not_match_as_accepted_is_counted(result):
    assert result["data_by_category"]["synonym"]["image"] == 1
    assert result["data_by_category"]["absent"]["abstract"] == 1
    assert result["data_by_category"]["absent"]["traits"] == 1
    assert result["data_by_category"]["accepted"]["iucn"] == 1


def test_gbif_synonym_rows_are_tracked_apart_from_accepted_ones(result):
    assert result["synonym_row_categories"] == {"accepted": 1}


def test_filled_class_is_counted_with_its_new_value(result):
    assert result["level_states"]["class"]["filled"] == 1
    assert result["level_states"]["class"]["same"] == 1
    assert result["filled_classes_by_order"]["Cypriniformes"]["Teleostei"] == 1


def test_only_real_differences_count_as_moves(result):
    assert result["moves"] == {}


def test_a_real_move_is_listed(col_db):
    moved = _gbif("Panthera leo", levels=_levels(family="Pantheridae"))
    out = cc.compare_release([moved], col_db)
    assert out["moves"] == {"family": 1}
    assert out["moved_rows"] == [("Panthera leo", "family", "Pantheridae", "Felidae")]


def test_missing_gbif_levels_are_counted_and_not_compared(col_db):
    out = cc.compare_release([cc.GbifRow("Panthera leo", "ACCEPTED", None, None, 0, 0, 0, 0)], col_db)
    assert out["unresolved_levels"] == 1
    assert out["moves"] == {}
    assert out["accepted_categories"] == {"accepted": 1}


def test_possible_spelling_variants_of_absent_names_are_flagged(result):
    assert result["absent_spelling_variants"] == 1
    assert [r[0] for r in result["absent_rows"]] == ["Lostus perditus", "Barbus albus"]
    assert [r[1] for r in result["absent_rows"]] == ["", "Barbus alba"]


def test_col_only_species_split_by_whether_gbif_has_the_name_at_all(result):
    # Vombatus ursinus is a GBIF synonym; Barbus novus and Barbus alba are not in GBIF.
    assert result["col_only"] == {"gbif_synonym": 1, "not_in_gbif": 2}


def test_merged_rows_are_counted_for_matches(result):
    assert result["accepted_via_merged"] == 1


def test_extinct_flags_are_crosstabulated_for_matches(result):
    assert result["extinct_crosstab"][(1, None)] == 1
    assert result["extinct_crosstab"][(None, 0)] == 1


def test_blank_levels_are_counted_for_each_side(result):
    # Accepted animal species: GBIF rows with no class vs COL species with no class.
    assert result["blank_gbif"]["class"] == 2
    assert result["blank_col"]["class"] == 0
    assert result["blank_col"]["family"] == 3


def test_non_species_col_rows_do_not_count_as_col_species(result):
    assert result["col_animal_species"] == 5
