"""Catalogue of Life switch: data/verify_col_levels.py checks GBIF's family or order for
groups COL leaves unplaced against independent sources."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "data"))
import compare_col as cc  # noqa: E402
import verify_col_levels as vl  # noqa: E402


def _result(source, path, ranks, match="Exact"):
    return {"dataSourceTitleShort": source, "matchType": match, "classificationPath": path, "classificationRanks": ranks}


WORMS = _result(
    "WoRMS",
    "Biota|Animalia|Arthropoda|Myriapoda|Diplopoda|Polydesmida|Dalodesmidae",
    "superdomain|kingdom|phylum|subphylum|class|order|family",
)
PLANT = _result("ITIS", "Plantae|Tracheophyta|Liliopsida|Poales|Poaceae", "kingdom|phylum|class|order|family")


def test_source_value_is_read_at_the_requested_rank():
    assert vl.source_value(WORMS, "order", "Arthropoda") == "Polydesmida"


def test_source_without_that_rank_gives_no_value():
    result = _result("WoRMS", "Animalia|Mollusca|Gastropoda|Eupulmonata|Camaenidae", "kingdom|phylum|class|superorder|family")
    assert vl.source_value(result, "order", "Mollusca") is None


def test_homonym_in_another_phylum_is_not_evidence():
    assert vl.source_value(PLANT, "order", "Arthropoda") is None


def test_unknown_col_phylum_still_requires_an_animal_path():
    assert vl.source_value(WORMS, "order", "") == "Polydesmida"
    assert vl.source_value(PLANT, "order", "") is None


def test_metazoa_counts_as_animal_for_ncbi_paths():
    result = _result("NCBI", "Eukaryota|Metazoa|Arthropoda|Diplopoda|Polydesmida", "domain|kingdom|phylum|class|order")
    assert vl.source_value(result, "order", "") == "Polydesmida"


def test_fuzzy_name_match_is_not_evidence():
    fuzzy = dict(WORMS, matchType="Fuzzy")
    assert vl.source_value(fuzzy, "order", "Arthropoda") is None


@pytest.mark.parametrize("values,want", [
    ({"WoRMS": "Polydesmida"}, "confirmed"),
    ({"WoRMS": "Polydesmida", "IRMNG": "Polydesmida", "NCBI": None}, "confirmed"),
    ({"WoRMS": "Polydesmida", "IRMNG": "Julida"}, "conflict"),
    ({"IRMNG": "Julida"}, "conflict"),
    ({"WoRMS": None}, "no_evidence"),
    ({}, "no_evidence"),
])
def test_verdict_needs_agreement_and_no_disagreement(values, want):
    assert vl.verdict("Polydesmida", values) == want


@pytest.mark.parametrize("values,want", [
    ({"IRMNG": "Stylommatophora", "NCBI": "Stylommatophora", "ITIS": "Helicida"}, "majority"),
    ({"NCBI": "Stylommatophora", "WoRMS": "Stylommatophora", "IRMNG": "Mollusca"}, "majority"),
    ({"WoRMS": "Stylommatophora", "IRMNG": "Mollusca"}, "conflict"),  # a tie is no majority
    ({"WoRMS": "Stylommatophora", "NCBI": "Stylommatophora", "ITIS": "Helicida", "IRMNG": "Mollusca"}, "conflict"),
    ({"WoRMS": "Stylommatophora", "NCBI": "Stylommatophora"}, "confirmed"),
])
def test_land_snail_order_goes_by_majority(values, want):
    assert vl.verdict("Stylommatophora", values) == want


def test_other_orders_do_not_go_by_majority():
    assert vl.verdict("Polydesmida", {"WoRMS": "Polydesmida", "NCBI": "Polydesmida", "IRMNG": "Julida"}) == "conflict"


def _gbif(name, family="", order="", phylum="Arthropoda", class_="Diplopoda"):
    return cc.GbifRow(name, "ACCEPTED", {"phylum": phylum, "class": class_, "order": order, "family": family}, None, 0, 0, 0, 0)


COL_NO_ORDER = "kingdom:Animalia|phylum:Arthropoda|class:Diplopoda|superorder:Merocheta|family:Dalodesmidae|genus:Dasystigma|species:Dasystigma margaretae"
COL_NO_FAMILY = "kingdom:Animalia|phylum:Mollusca|class:Gastropoda|infraorder:Helicoidei|genus:Acusta|species:Acusta ravida"
COL_NO_FAMILY_NO_ORDER_GENUS = "kingdom:Animalia|phylum:Arthropoda|class:Ostracoda|genus:Thlipsuropsis|species:Thlipsuropsis digitata"
COL_COMPLETE = "kingdom:Animalia|phylum:Chordata|class:Mammalia|order:Carnivora|family:Felidae|genus:Panthera|species:Panthera leo"


def _col(name, lineage):
    return {name: [{"scientific_name": name, "status": "accepted", "lineage": lineage, "merged": 0, "extinct": None}]}


def test_lost_order_is_checked_on_the_family_col_does_have():
    cands = vl.collect_candidates([_gbif("Dasystigma margaretae", order="Polydesmida")], _col("Dasystigma margaretae", COL_NO_ORDER))
    assert cands == {("order", "Dalodesmidae", "Polydesmida"): {"phylum": "Arthropoda", "species": 1}}


def test_lost_order_without_a_family_is_checked_on_the_genus():
    cands = vl.collect_candidates(
        [_gbif("Thlipsuropsis digitata", order="Platycopida", class_="Ostracoda")],
        _col("Thlipsuropsis digitata", COL_NO_FAMILY_NO_ORDER_GENUS),
    )
    assert cands == {("order", "Thlipsuropsis", "Platycopida"): {"phylum": "Arthropoda", "species": 1}}


def test_lost_family_is_checked_on_the_genus():
    cands = vl.collect_candidates(
        [_gbif("Acusta ravida", family="Camaenidae", phylum="Mollusca", class_="Gastropoda")],
        _col("Acusta ravida", COL_NO_FAMILY),
    )
    assert cands == {("family", "Acusta", "Camaenidae"): {"phylum": "Mollusca", "species": 1}}


def test_species_of_one_group_share_a_candidate():
    rows = [_gbif("Acusta ravida", family="Camaenidae"), _gbif("Acusta sieboldiana", family="Camaenidae")]
    col = {**_col("Acusta ravida", COL_NO_FAMILY), **_col("Acusta sieboldiana", COL_NO_FAMILY)}
    assert vl.collect_candidates(rows, col)[("family", "Acusta", "Camaenidae")]["species"] == 2


def test_level_col_already_has_is_not_a_candidate():
    rows = [_gbif("Panthera leo", family="Pantheridae", order="Felales", phylum="Chordata", class_="Mammalia")]
    assert vl.collect_candidates(rows, _col("Panthera leo", COL_COMPLETE)) == {}


def test_gbif_placeholder_values_are_not_candidates():
    # GBIF uses "Paleo" as a family for some trilobites: not a taxon anyone can confirm.
    rows = [_gbif("Acusta ravida", family="Paleo")]
    assert vl.collect_candidates(rows, _col("Acusta ravida", COL_NO_FAMILY)) == {}


def test_names_not_in_col_or_only_synonyms_are_not_candidates():
    assert vl.collect_candidates([_gbif("Lostus perditus", family="Lostidae")], {}) == {}
    syn = {"Acusta ravida": [{"scientific_name": "Acusta ravida", "status": "synonym", "lineage": COL_NO_FAMILY, "merged": 0, "extinct": None}]}
    assert vl.collect_candidates([_gbif("Acusta ravida", family="Camaenidae")], syn) == {}
