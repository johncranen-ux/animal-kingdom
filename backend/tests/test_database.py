"""Tests for database.py — schema, JSON helpers, and query functions."""

import sqlite3
import pytest
from app import database


EXPECTED_COLUMNS = {
    "scientific_name",
    "gbif_taxon_path", "col_id", "accepted_name",   # Catalogue of Life build (Increment 30: in the app schema)
    "extinct",
    "taxon_path",
    "taxon_rank",
    "common_names",
    "taxonomic_status",
    "body_mass",
    "body_length",
    "max_lifespan",
    "metabolic_rate",
    "reproduction_strategy",
    "geo_bounding_box",
    "habitat_type",
    "elevation_limits",
    "trophic_level",
    "activity_period",
    "iucn_status",
    "population_trend",
    "primary_image_url",
    "image_attribution",
    "wikipedia_abstract",
    "taxon_depth",
    "trait_sources",
    "rejected_images",   # Increment 32: pictures the user replaced
}


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Point every test at a fresh temp database."""
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))


def _insert(conn: sqlite3.Connection, scientific_name: str, taxon_path: str,
            taxon_rank: str = "species", common_names: str = "[]",
            taxonomic_status: str = "ACCEPTED") -> None:
    conn.execute(
        """
        INSERT INTO species (scientific_name, taxon_path, taxon_rank,
                             common_names, taxonomic_status)
        VALUES (?, ?, ?, ?, ?)
        """,
        (scientific_name, taxon_path, taxon_rank, common_names, taxonomic_status),
    )
    conn.commit()


# --- Schema ---

def test_schema_has_all_columns():
    conn = database.get_connection()
    info = conn.execute("PRAGMA table_info(species)").fetchall()
    conn.close()
    col_names = {row["name"] for row in info}
    assert col_names == EXPECTED_COLUMNS


def test_schema_has_27_columns():
    conn = database.get_connection()
    info = conn.execute("PRAGMA table_info(species)").fetchall()
    conn.close()
    assert len(info) == 27


def test_indexes_exist():
    conn = database.get_connection()
    indexes = {
        row[1]
        for row in conn.execute(
            "SELECT * FROM sqlite_master WHERE type='index' AND tbl_name='species'"
        ).fetchall()
    }
    conn.close()
    assert "idx_taxon_rank" in indexes
    assert "idx_taxonomic_status" in indexes
    assert "idx_iucn_status" in indexes
    assert "idx_taxon_path" in indexes


# --- JSON helpers ---

def test_common_names_roundtrip():
    names = ["Lion", "African lion"]
    assert database.parse_common_names(database.serialize_common_names(names)) == names


def test_common_names_empty_string():
    assert database.parse_common_names("") == []


def test_common_names_none():
    assert database.parse_common_names(None) == []


def test_common_names_unicode():
    names = ["Löwe", "狮子"]
    assert database.parse_common_names(database.serialize_common_names(names)) == names


def test_geo_bbox_roundtrip():
    bbox = {"lat_min": -10.0, "lat_max": 20.5, "lon_min": 30.0, "lon_max": 50.25}
    assert database.parse_geo_bbox(database.serialize_geo_bbox(bbox)) == bbox


def test_geo_bbox_empty_string():
    assert database.parse_geo_bbox("") == {}


def test_geo_bbox_none():
    assert database.parse_geo_bbox(None) == {}


# --- get_children ---

@pytest.fixture
def taxonomy_seed():
    """Insert a small 3-level taxonomy tree."""
    conn = database.get_connection()
    _insert(conn, "Animalia", "Animalia", taxon_rank="kingdom")
    _insert(conn, "Chordata", "Animalia|Chordata", taxon_rank="phylum")
    _insert(conn, "Arthropoda", "Animalia|Arthropoda", taxon_rank="phylum")
    _insert(conn, "Mammalia", "Animalia|Chordata|Mammalia", taxon_rank="class")
    conn.close()


def test_get_children_root_returns_kingdoms(taxonomy_seed):
    results = database.get_children("", depth=1)
    paths = {r["taxon_path"] for r in results}
    assert paths == {"Animalia"}


def test_get_children_depth1_returns_direct_children(taxonomy_seed):
    results = database.get_children("Animalia", depth=1)
    paths = {r["taxon_path"] for r in results}
    assert paths == {"Animalia|Chordata", "Animalia|Arthropoda"}


def test_get_children_depth1_excludes_grandchildren(taxonomy_seed):
    results = database.get_children("Animalia", depth=1)
    paths = {r["taxon_path"] for r in results}
    assert "Animalia|Chordata|Mammalia" not in paths


def test_get_children_depth2_includes_grandchildren(taxonomy_seed):
    results = database.get_children("Animalia", depth=2)
    paths = {r["taxon_path"] for r in results}
    assert "Animalia|Chordata|Mammalia" in paths
    assert len(paths) == 3


def test_get_children_leaf_returns_empty(taxonomy_seed):
    results = database.get_children("Animalia|Chordata|Mammalia", depth=1)
    assert results == []


# --- get_species ---

def test_get_species_returns_record():
    conn = database.get_connection()
    _insert(conn, "Panthera leo", "Animalia|Chordata|Mammalia|Carnivora|Felidae|Panthera|Panthera leo",
            taxon_rank="species",
            common_names=database.serialize_common_names(["Lion", "African lion"]))
    conn.close()

    result = database.get_species("Panthera leo")
    assert result is not None
    assert result["scientific_name"] == "Panthera leo"
    assert result["taxon_rank"] == "species"


def test_get_species_returns_none_for_unknown():
    assert database.get_species("Nonexistent species") is None


def test_get_species_case_insensitive(isolated_db):
    conn = database.get_connection()
    _insert(conn, "Felis maxima", "Animalia|Felis maxima", taxon_rank="species")
    conn.commit()
    conn.close()
    assert database.get_species("felis maxima") is not None
    assert database.get_species("FELIS MAXIMA") is not None
    assert database.get_species("Felis maxima") is not None


# --- search_species ---

def test_search_by_scientific_name():
    conn = database.get_connection()
    _insert(conn, "Panthera leo", "Animalia|...|Panthera leo")
    _insert(conn, "Panthera tigris", "Animalia|...|Panthera tigris")
    _insert(conn, "Canis lupus", "Animalia|...|Canis lupus")
    conn.close()

    results = database.search_species("Panthera")
    names = {r["scientific_name"] for r in results}
    assert names == {"Panthera leo", "Panthera tigris"}


def test_search_by_common_name():
    conn = database.get_connection()
    _insert(conn, "Panthera leo", "Animalia|...|Panthera leo",
            common_names=database.serialize_common_names(["Lion"]))
    _insert(conn, "Canis lupus", "Animalia|...|Canis lupus",
            common_names=database.serialize_common_names(["Wolf"]))
    conn.close()

    results = database.search_species("Lion")
    names = {r["scientific_name"] for r in results}
    assert "Panthera leo" in names
    assert "Canis lupus" not in names


def test_search_respects_limit():
    conn = database.get_connection()
    for i in range(10):
        _insert(conn, f"Species {i}", f"Animalia|Species {i}")
    conn.close()

    results = database.search_species("Species", limit=3)
    assert len(results) == 3


def test_search_exact_match_ranks_first_despite_limit():
    # Subspecies inserted first would fill the limit under storage order
    conn = database.get_connection()
    for i in range(5):
        _insert(conn, f"Apis cerana sub{i}", f"Animalia|Apis cerana sub{i}",
                taxon_rank="subspecies", taxonomic_status="SYNONYM")
    _insert(conn, "Apis cerana", "Animalia|Apis cerana")
    conn.close()

    results = database.search_species("apis cerana", limit=3)
    assert results[0]["scientific_name"] == "Apis cerana"


def test_search_exact_common_name_ranks_before_substring():
    conn = database.get_connection()
    _insert(conn, "Lionotus", "Animalia|Lionotus", taxon_rank="genus")
    _insert(conn, "Panthera leo", "Animalia|Panthera leo",
            common_names=database.serialize_common_names(["Lion", "African lion"]))
    conn.close()

    results = database.search_species("lion")
    assert [r["scientific_name"] for r in results] == ["Panthera leo", "Lionotus"]


def test_search_prefers_accepted_then_shorter_names():
    conn = database.get_connection()
    _insert(conn, "Felis catus domesticus", "Animalia|Felis catus domesticus")
    _insert(conn, "Felis catusa", "Animalia|Felis catusa", taxonomic_status="SYNONYM")
    _insert(conn, "Felis catus x", "Animalia|Felis catus x")
    conn.close()

    results = database.search_species("Felis catu")
    assert [r["scientific_name"] for r in results] == [
        "Felis catus x", "Felis catus domesticus", "Felis catusa",
    ]


# --- get_children_letter_counts ---

def test_get_children_letter_counts_groups_by_first_letter():
    conn = database.get_connection()
    _insert(conn, "Fabaceae", "Fabaceae",          taxon_rank="family")
    _insert(conn, "Acacia",   "Fabaceae|Acacia",   taxon_rank="genus")
    _insert(conn, "Albizia",  "Fabaceae|Albizia",  taxon_rank="genus")
    _insert(conn, "Bauhinia", "Fabaceae|Bauhinia", taxon_rank="genus")
    conn.close()

    counts = database.get_children_letter_counts("Fabaceae")
    assert counts == {"A": 2, "B": 1}


def test_get_children_letter_counts_excludes_synonyms():
    conn = database.get_connection()
    _insert(conn, "Fabaceae", "Fabaceae",         taxon_rank="family")
    _insert(conn, "Acacia",   "Fabaceae|Acacia",  taxon_rank="genus")
    _insert(conn, "Albizia",  "Fabaceae|Albizia", taxon_rank="genus", taxonomic_status="SYNONYM")
    conn.close()

    counts = database.get_children_letter_counts("Fabaceae")
    assert counts == {"A": 1}   # Albizia excluded as SYNONYM


def test_get_children_letter_counts_groups_non_alpha_under_hash():
    conn = database.get_connection()
    _insert(conn, "Fabaceae",  "Fabaceae",          taxon_rank="family")
    _insert(conn, "Acacia",    "Fabaceae|Acacia",   taxon_rank="genus")
    _insert(conn, "123Virus",  "Fabaceae|123Virus", taxon_rank="genus")
    conn.close()

    counts = database.get_children_letter_counts("Fabaceae")
    assert counts == {"#": 1, "A": 1}


# --- get_children_by_letter ---

def test_get_children_by_letter_returns_matching_children():
    conn = database.get_connection()
    _insert(conn, "Fabaceae", "Fabaceae",          taxon_rank="family")
    _insert(conn, "Acacia",   "Fabaceae|Acacia",   taxon_rank="genus")
    _insert(conn, "Albizia",  "Fabaceae|Albizia",  taxon_rank="genus")
    _insert(conn, "Bauhinia", "Fabaceae|Bauhinia", taxon_rank="genus")
    conn.close()

    rows = database.get_children_by_letter("Fabaceae", "A")
    names = {r["scientific_name"] for r in rows}
    assert names == {"Acacia", "Albizia"}

    rows = database.get_children_by_letter("Fabaceae", "B")
    assert {r["scientific_name"] for r in rows} == {"Bauhinia"}

    rows = database.get_children_by_letter("Fabaceae", "Z")
    assert rows == []


# --- get_orphan_letter_counts ---

def test_get_orphan_letter_counts():
    # Viruses is a kingdom; expected child rank = "phylum"
    # Insert "family"-ranked children which are orphans
    conn = database.get_connection()
    _insert(conn, "Viruses",       "Viruses",              taxon_rank="kingdom")
    _insert(conn, "Adenoviridae",  "Viruses|Adenoviridae", taxon_rank="family")
    _insert(conn, "Astroviridae",  "Viruses|Astroviridae", taxon_rank="family")
    _insert(conn, "Bunyaviridae",  "Viruses|Bunyaviridae", taxon_rank="family")
    conn.commit()
    conn.close()

    expected = frozenset({"phylum"})
    counts = database.get_orphan_letter_counts("Viruses", expected)
    assert counts == {"A": 2, "B": 1}


# --- get_orphan_children_by_letter ---

def test_get_orphan_children_by_letter():
    conn = database.get_connection()
    _insert(conn, "Viruses",       "Viruses",              taxon_rank="kingdom")
    _insert(conn, "Adenoviridae",  "Viruses|Adenoviridae", taxon_rank="family")
    _insert(conn, "Bunyaviridae",  "Viruses|Bunyaviridae", taxon_rank="family")
    conn.commit()
    conn.close()

    expected = frozenset({"phylum"})
    rows = database.get_orphan_children_by_letter("Viruses", expected, "A")
    assert {r["scientific_name"] for r in rows} == {"Adenoviridae"}

    rows = database.get_orphan_children_by_letter("Viruses", expected, "B")
    assert {r["scientific_name"] for r in rows} == {"Bunyaviridae"}


# --- update_species_image ---

def test_update_species_image_writes_url_and_attribution(isolated_db):
    conn = database.get_connection()
    conn.execute(
        "INSERT INTO species (scientific_name, taxon_path, taxon_rank, taxonomic_status) "
        "VALUES ('Apis mellifera', 'Animalia|Apis mellifera', 'species', 'ACCEPTED')"
    )
    conn.commit()
    conn.close()

    database.update_species_image(
        'Apis mellifera',
        'https://example.com/bee.jpg',
        '© Some Photographer (CC BY 4.0)',
    )

    row = database.get_species('Apis mellifera')
    assert row['primary_image_url'] == 'https://example.com/bee.jpg'
    assert row['image_attribution'] == '© Some Photographer (CC BY 4.0)'


def test_update_species_image_overwrites_existing_url(isolated_db):
    conn = database.get_connection()
    conn.execute(
        "INSERT INTO species (scientific_name, taxon_path, taxon_rank, taxonomic_status, "
        "primary_image_url, image_attribution) "
        "VALUES ('Apis mellifera', 'Animalia|Apis mellifera', 'species', 'ACCEPTED', "
        "'https://old.com/img.jpg', 'old attribution')"
    )
    conn.commit()
    conn.close()

    database.update_species_image('Apis mellifera', 'https://new.com/img.jpg', 'new attribution')

    row = database.get_species('Apis mellifera')
    assert row['primary_image_url'] == 'https://new.com/img.jpg'
    assert row['image_attribution'] == 'new attribution'


# --- trait storage (Increment 12) ---

from app.database import TraitValue


def _row(name):
    conn = database.get_connection()
    try:
        return dict(conn.execute("SELECT * FROM species WHERE scientific_name = ?", (name,)).fetchone())
    finally:
        conn.close()


def _seed(name="Panthera leo", **cols):
    conn = database.get_connection()
    _insert(conn, name, f"Animalia|{name}")
    for k, v in cols.items():
        conn.execute(f"UPDATE species SET {k} = ? WHERE scientific_name = ?", (v, name))
    conn.commit()
    conn.close()


def test_schema_has_trait_sources_column():
    conn = database.get_connection()
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(species)")}
    conn.close()
    assert "trait_sources" in cols


def test_update_traits_fills_null_and_records_source():
    _seed()
    database.update_species_traits(
        "Panthera leo", {"habitat_type": TraitValue("Grassland", "IUCN Red List")}, "sourced", True)
    row = _row("Panthera leo")
    assert row["habitat_type"] == "Grassland"
    src = database.parse_trait_sources(row["trait_sources"])
    assert src["habitat_type"] == {"source": "IUCN Red List", "estimated": False}
    assert "_sourced" in src


def test_update_traits_never_overwrites_sourced():
    _seed(body_mass=3.9)
    database.update_species_traits(
        "Panthera leo", {"body_mass": TraitValue(5.0, "Wikidata")}, "sourced", True)
    assert _row("Panthera leo")["body_mass"] == 3.9


def test_estimate_never_overwrites_sourced_value():
    _seed()
    database.update_species_traits(
        "Panthera leo", {"habitat_type": TraitValue("Grassland", "IUCN Red List")}, "sourced", True)
    database.update_species_traits(
        "Panthera leo",
        {"habitat_type": TraitValue("Forest", "Estimated from Wikipedia description", True)},
        "estimated", True)
    row = _row("Panthera leo")
    assert row["habitat_type"] == "Grassland"
    assert database.parse_trait_sources(row["trait_sources"])["habitat_type"]["estimated"] is False


def test_sourced_replaces_estimated_value():
    _seed()
    database.update_species_traits(
        "Panthera leo",
        {"activity_period": TraitValue("nocturnal", "Estimated from Wikipedia description", True)},
        "estimated", True)
    database.update_species_traits(
        "Panthera leo", {"activity_period": TraitValue("diurnal", "Wikidata")}, "sourced", True)
    row = _row("Panthera leo")
    assert row["activity_period"] == "diurnal"
    assert database.parse_trait_sources(row["trait_sources"])["activity_period"] == {
        "source": "Wikidata", "estimated": False}


def test_incomplete_stage_sets_no_marker():
    _seed()
    database.update_species_traits(
        "Panthera leo", {"habitat_type": TraitValue("Grassland", "IUCN Red List")}, "sourced", False)
    row = _row("Panthera leo")
    assert row["habitat_type"] == "Grassland"
    assert "_sourced" not in database.parse_trait_sources(row["trait_sources"])


def test_provenance_defaults_for_imported_values():
    _seed(body_mass=3.9, iucn_status="VU")
    prov = database.trait_provenance(_row("Panthera leo"))
    assert prov["body_mass"] == {"source": "AnAge", "estimated": False}
    assert prov["iucn_status"] == {"source": "IUCN Red List", "estimated": False}
    assert "habitat_type" not in prov


def test_update_traits_serializes_bbox():
    _seed()
    bbox = {"lat_min": -10.0, "lat_max": 5.0, "lon_min": 20.0, "lon_max": 40.0}
    database.update_species_traits(
        "Panthera leo", {"geo_bounding_box": TraitValue(bbox, "GBIF occurrences")}, "sourced", True)
    assert database.parse_geo_bbox(_row("Panthera leo")["geo_bounding_box"]) == bbox


def test_concurrent_trait_updates_keep_all_provenance():
    import threading
    _seed()
    fields = ["habitat_type", "elevation_limits", "trophic_level", "activity_period",
              "reproduction_strategy", "population_trend", "iucn_status", "wikipedia_abstract"]
    threads = [threading.Thread(target=database.update_species_traits,
                                args=("Panthera leo", {f: TraitValue(f"v-{f}", "Wikidata")}, "sourced", False))
               for f in fields]
    for t in threads: t.start()
    for t in threads: t.join()
    row = _row("Panthera leo")
    src = database.parse_trait_sources(row["trait_sources"])
    assert all(row[f] == f"v-{f}" for f in fields)
    assert all(f in src for f in fields)


def test_init_schema_idempotent():
    database.get_connection().close()
    conn = database.get_connection()
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(species)")]
    conn.close()
    assert cols.count("trait_sources") == 1


def test_parse_trait_sources_tolerates_garbage():
    assert database.parse_trait_sources("{not json") == {}
    assert database.parse_trait_sources("[1,2]") == {}
    assert database.parse_trait_sources(None) == {}
    _seed(body_mass=3.9, trait_sources="{not json")
    assert database.trait_provenance(_row("Panthera leo"))["body_mass"]["source"] == "AnAge"


def test_update_traits_gives_up_when_db_locked(monkeypatch):
    import time
    _seed()
    monkeypatch.setattr(database, "TRAIT_WRITE_TIMEOUT_S", 0.2)
    holder = database.get_connection()
    holder.execute("BEGIN IMMEDIATE")  # a bulk script mid-transaction
    try:
        start = time.monotonic()
        ok = database.update_species_traits(
            "Panthera leo", {"habitat_type": TraitValue("Grassland", "IUCN Red List")}, "sourced", True)
        assert ok is False and time.monotonic() - start < 2
    finally:
        holder.rollback()
        holder.close()
    assert _row("Panthera leo")["habitat_type"] is None
    assert database.update_species_traits(
        "Panthera leo", {"habitat_type": TraitValue("Grassland", "IUCN Red List")}, "sourced", True) is True


def test_merge_trait_values_is_pure_and_matches_write_rules():
    row = {"scientific_name": "X", "habitat_type": None, "body_mass": 3.9, "trait_sources": None}
    updates = database.merge_trait_values(row, {"habitat_type": TraitValue("Grassland", "IUCN Red List"),
                                                "body_mass": TraitValue(5.0, "Wikidata")}, "sourced", False)
    assert updates["habitat_type"] == "Grassland" and "body_mass" not in updates
    assert database.parse_trait_sources(updates["trait_sources"]) == {
        "habitat_type": {"source": "IUCN Red List", "estimated": False}}
    assert row["habitat_type"] is None


def test_search_exact_common_name_of_accepted_beats_exact_synonym_genus():
    # "Zebra" is also an outdated snail genus name; typing it should open the zebra
    conn = database.get_connection()
    _insert(conn, "Zebra", "Animalia|Mollusca|Orthalicidae|Orthalicus",
            taxon_rank="genus", taxonomic_status="SYNONYM")
    _insert(conn, "Equus zebra", "Animalia|Chordata|Equidae|Equus|Equus zebra",
            common_names=database.serialize_common_names(["Mountain zebra", "Zebra"]))
    conn.close()

    results = database.search_species("Zebra")
    assert [r["scientific_name"] for r in results] == ["Equus zebra", "Zebra"]


def test_search_exact_accepted_scientific_name_still_ranks_first():
    conn = database.get_connection()
    _insert(conn, "Bombus terrestris", "Animalia|Bombus terrestris",
            common_names=database.serialize_common_names(["Panthera"]))
    _insert(conn, "Panthera", "Animalia|Felidae|Panthera", taxon_rank="genus")
    conn.close()

    results = database.search_species("Panthera")
    assert results[0]["scientific_name"] == "Panthera"


def _names(query):
    return [r["scientific_name"] for r in database.search_species(query)]


@pytest.mark.parametrize("signal", [
    {"wikipedia_abstract": "The common ostrich is a large bird."},
    {"iucn_status": "LC"},
    {"primary_image_url": "https://example.org/ostrich.jpg"},
])
def test_search_well_known_taxon_beats_shorter_equal_match(signal):
    # "ostrich" listed the genus above the species people are looking for
    ostrich = database.serialize_common_names(["ostrich"])
    _seed("Struthio", common_names=ostrich)
    _seed("Struthio camelus", common_names=ostrich, **signal)

    assert _names("ostrich") == ["Struthio camelus", "Struthio"]


def test_search_more_signals_beat_fewer_among_equal_matches():
    name = database.serialize_common_names(["ostrich"])
    _seed("Aaa aaa", common_names=name, iucn_status="LC")
    _seed("Bbbbbb bbbbbb", common_names=name, iucn_status="LC",
          primary_image_url="https://example.org/b.jpg")

    assert _names("ostrich") == ["Bbbbbb bbbbbb", "Aaa aaa"]


def test_search_well_known_taxon_stays_below_stronger_match_type():
    # A genus starting with the query stays above a famous name only containing it
    _seed("Bostrichus famous", iucn_status="LC",
          wikipedia_abstract="Text.", primary_image_url="https://example.org/b.jpg")
    _seed("Ostrichia")

    assert _names("ostrich") == ["Ostrichia", "Bostrichus famous"]


def test_search_well_known_synonym_stays_below_accepted_equal_match():
    # Old data on a synonym must not bring back the "Panther" butterfly
    panther = database.serialize_common_names(["Panther"])
    _seed("Neurosigma siva", common_names=panther, taxonomic_status="SYNONYM",
          primary_image_url="https://example.org/butterfly.jpg")
    _seed("Puma concolor var", common_names=panther)

    assert _names("panther") == ["Puma concolor var", "Neurosigma siva"]


def test_init_schema_adds_extinct_column_to_existing_db():
    conn = database.get_connection()
    conn.execute("ALTER TABLE species DROP COLUMN extinct")
    database._init_schema(conn)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(species)")}
    conn.close()
    assert "extinct" in cols


def test_update_traits_stores_extinct_flag_with_provenance():
    _seed()
    database.update_species_traits(
        "Panthera leo", {"extinct": database.TraitValue(1, "GBIF (Paleobiology Database)")},
        "sourced", completed=True)
    row = database.get_species("Panthera leo")
    assert row["extinct"] == 1
    assert database.trait_provenance(row)["extinct"] == {
        "source": "GBIF (Paleobiology Database)", "estimated": False}


# --- Increment 30: search ranking and old names ---

def test_search_common_name_word_beats_scientific_prefix():
    # "wombat": Vombatus ursinus ("Common wombat") above the genus synonym Wombatus
    # and the fossil Wombatus fossor, which only match by their scientific names
    conn = database.get_connection()
    _insert(conn, "Wombatus fossor", "Animalia|Wombatus fossor")
    _insert(conn, "Wombatus", "Animalia|Wombatus", taxon_rank="genus", taxonomic_status="SYNONYM")
    _insert(conn, "Lasiorhinus", "Animalia|Lasiorhinus", taxon_rank="genus",
            common_names=database.serialize_common_names(["Hairy-nosed Wombats"]))
    _insert(conn, "Vombatus ursinus", "Animalia|Vombatus ursinus",
            common_names=database.serialize_common_names(["Common wombat", "Forest Wombat"]))
    _insert(conn, "Wombatula", "Animalia|Wombatula", taxon_rank="genus")
    conn.close()

    names = [r["scientific_name"] for r in database.search_species("wombat")]
    assert set(names[:2]) == {"Vombatus ursinus", "Lasiorhinus"}
    assert names.index("Lasiorhinus") < names.index("Wombatus fossor")


def test_search_common_name_inside_a_word_is_no_word_match():
    # "lion" inside "Dandelion" is no better than a scientific-name prefix
    conn = database.get_connection()
    _insert(conn, "Taraxacum officinale", "Plantae|Taraxacum officinale",
            common_names=database.serialize_common_names(["Common dandelion"]))
    _insert(conn, "Lionotus", "Animalia|Lionotus", taxon_rank="genus")
    conn.close()

    names = [r["scientific_name"] for r in database.search_species("lion")]
    assert names == ["Lionotus", "Taraxacum officinale"]


def _link_seed():
    conn = database.get_connection()
    _insert(conn, "Acrocodia indica", "Animalia|Acrocodia|Acrocodia indica",
            common_names=database.serialize_common_names(["Malayan tapir"]))
    _insert(conn, "Tapirus indicus", "Animalia|Acrocodia|Tapirus indicus", taxonomic_status="SYNONYM")
    _insert(conn, "Tapirus indicus indicus", "Animalia|Acrocodia|Tapirus indicus indicus",
            taxon_rank="subspecies", taxonomic_status="SYNONYM")
    _insert(conn, "Tapirus malayanus", "Animalia|Tapirus|Tapirus malayanus")
    conn.execute("UPDATE species SET accepted_name = 'Acrocodia indica' "
                 "WHERE scientific_name IN ('Tapirus indicus', 'Tapirus indicus indicus')")
    conn.commit()
    conn.close()


def test_current_name_of_a_col_synonym():
    _link_seed()
    link = database.current_name(_row("Tapirus indicus"))
    assert link == {"scientific_name": "Acrocodia indica", "common_name": "Malayan tapir",
                    "taxon_path": "Animalia|Acrocodia|Acrocodia indica", "taxon_rank": "species",
                    "source": "Catalogue of Life"}


def test_current_name_follows_a_wikidata_link_through_a_synonym():
    _link_seed()
    database.update_species_traits(
        "Tapirus malayanus", {"accepted_name": TraitValue("Tapirus indicus indicus", "Wikidata")},
        "sourced", True)
    row = _row("Tapirus malayanus")
    assert row["accepted_name"] == "Tapirus indicus indicus"
    assert row["taxonomic_status"] == "ACCEPTED"          # the Catalogue of Life's status stays
    link = database.current_name(row)
    assert link["scientific_name"] == "Acrocodia indica" and link["source"] == "Wikidata"


def test_current_name_none_for_accepted_or_missing_target():
    _link_seed()
    assert database.current_name(_row("Acrocodia indica")) is None
    conn = database.get_connection()
    conn.execute("UPDATE species SET accepted_name = 'Nowhere found' WHERE scientific_name = 'Tapirus indicus'")
    conn.commit()
    conn.close()
    assert database.current_name(_row("Tapirus indicus")) is None


def test_current_name_stops_on_a_loop():
    conn = database.get_connection()
    _insert(conn, "A a", "Animalia|A a", taxonomic_status="SYNONYM")
    _insert(conn, "B b", "Animalia|B b", taxonomic_status="SYNONYM")
    conn.execute("UPDATE species SET accepted_name = 'B b' WHERE scientific_name = 'A a'")
    conn.execute("UPDATE species SET accepted_name = 'A a' WHERE scientific_name = 'B b'")
    conn.commit()
    conn.close()
    assert database.current_name(_row("A a")) is None


def test_a_complete_sourced_stage_counts_as_the_name_check():
    # The sourced stage asks Wikidata for "taxon synonym of" too, so rows looked up
    # from Increment 30 on need no separate name check
    _seed()
    database.update_species_traits("Panthera leo", {}, "sourced", True)
    markers = database.parse_trait_sources(_row("Panthera leo")["trait_sources"])
    assert "_sourced" in markers and "_names" in markers
    _seed("Felis catus")
    database.update_species_traits("Felis catus", {}, "sourced", False)
    assert "_names" not in database.parse_trait_sources(_row("Felis catus")["trait_sources"])


# --- Increment 32: chosen pictures and rejected ones ---

def _image_row(name, url=None):
    conn = database.get_connection()
    conn.execute("INSERT INTO species (scientific_name, taxon_path, taxon_rank, primary_image_url) "
                 "VALUES (?, ?, 'species', ?)", (name, f"Animalia|{name}", url))
    conn.commit()
    conn.close()


def test_parse_rejected_images():
    assert database.parse_rejected_images(None) == []
    assert database.parse_rejected_images("not json") == []
    assert database.parse_rejected_images('["https://a/1.jpg"]') == ["https://a/1.jpg"]


def test_choose_species_image_remembers_the_replaced_picture():
    _image_row("Oreamnos americanus", "https://w/snake.jpg")
    database.choose_species_image("Oreamnos americanus", "https://i/goat.jpg", "(c) a")
    row = database.get_species("Oreamnos americanus")
    assert (row["primary_image_url"], row["image_attribution"]) == ("https://i/goat.jpg", "(c) a")
    assert database.parse_rejected_images(row["rejected_images"]) == ["https://w/snake.jpg"]
    database.choose_species_image("Oreamnos americanus", "https://i/goat2.jpg", "(c) b")
    row = database.get_species("Oreamnos americanus")
    assert database.parse_rejected_images(row["rejected_images"]) == ["https://w/snake.jpg", "https://i/goat.jpg"]


def test_choose_same_picture_rejects_nothing():
    _image_row("Oreamnos americanus", "https://i/goat.jpg")
    database.choose_species_image("Oreamnos americanus", "https://i/goat.jpg", "(c) a")
    assert database.parse_rejected_images(database.get_species("Oreamnos americanus")["rejected_images"]) == []


def test_choose_after_no_picture_rejects_nothing():
    _image_row("Neomonas", "__none__")
    database.choose_species_image("Neomonas", "https://g/1.jpg", "© X via GBIF")
    assert database.parse_rejected_images(database.get_species("Neomonas")["rejected_images"]) == []
