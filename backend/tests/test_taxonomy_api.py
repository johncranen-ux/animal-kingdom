"""Tests for Taxonomy API routes — /api/taxonomy/root, /zoom, /species, /search."""

import sqlite3
import pytest
from fastapi.testclient import TestClient

from app import database
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Redirect every test to a fresh temp database."""
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))


def _insert(scientific_name: str, taxon_path: str, taxon_rank: str = "species",
            common_names: str = "[]", taxonomic_status: str = "ACCEPTED",
            iucn_status: str | None = None,
            primary_image_url: str | None = None,
            wikipedia_abstract: str | None = None,
            trait_sources: str | None = None) -> None:
    conn = database.get_connection()
    conn.execute(
        """
        INSERT INTO species
          (scientific_name, taxon_path, taxon_rank, common_names, taxonomic_status,
           iucn_status, primary_image_url, wikipedia_abstract, trait_sources)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (scientific_name, taxon_path, taxon_rank, common_names, taxonomic_status,
         iucn_status, primary_image_url, wikipedia_abstract, trait_sources),
    )
    conn.commit()
    conn.close()


@pytest.fixture
def taxonomy_seed():
    """Small 3-level taxonomy tree spanning two kingdoms."""
    _insert("Animalia",          "Animalia",                                        taxon_rank="kingdom")
    _insert("Plantae",           "Plantae",                                         taxon_rank="kingdom")
    _insert("Chordata",          "Animalia|Chordata",                               taxon_rank="phylum")
    _insert("Arthropoda",        "Animalia|Arthropoda",                             taxon_rank="phylum")
    _insert("Mammalia",          "Animalia|Chordata|Mammalia",                      taxon_rank="class")
    _insert("Panthera leo",      "Animalia|Chordata|Mammalia|Carnivora|Felidae|Panthera|Panthera leo",
            common_names=database.serialize_common_names(["Lion", "African lion"]),
            iucn_status="VU")
    _insert("Canis lupus",       "Animalia|Chordata|Mammalia|Carnivora|Canidae|Canis|Canis lupus",
            common_names=database.serialize_common_names(["Wolf", "Grey wolf"]))
    _insert("Rosa canina",       "Plantae|Tracheophyta|Magnoliopsida|Rosales|Rosaceae|Rosa|Rosa canina",
            taxon_rank="species")


# --- /health ---

def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# --- GET /api/taxonomy/root ---

def _eukarya(root: list[dict]) -> dict:
    return next(n for n in root if n["node_id"] == "Eukarya")


def test_root_returns_kingdoms(taxonomy_seed):
    resp = client.get("/api/taxonomy/root")
    assert resp.status_code == 200
    node_ids = {n["node_id"] for n in _eukarya(resp.json())["children"]}
    assert node_ids == {"Animalia", "Plantae"}


def test_root_excludes_lower_ranks(taxonomy_seed):
    resp = client.get("/api/taxonomy/root")
    node_ids = {n["node_id"] for n in resp.json()}
    assert "Animalia|Chordata" not in node_ids


def test_root_node_shape(taxonomy_seed):
    resp = client.get("/api/taxonomy/root")
    node = next(n for n in _eukarya(resp.json())["children"] if n["node_id"] == "Animalia")
    assert node["name"] == "Animalia"
    assert node["rank"] == "kingdom"
    assert isinstance(node["children"], list)


def test_root_empty_db_returns_empty_list():
    resp = client.get("/api/taxonomy/root")
    assert resp.status_code == 200
    assert resp.json() == []


# --- Domains (display layer; no row or stored path changes) ---

STICK_INSECT_GENUS = "Animalia|Arthropoda|Insecta|Phasmida|Diapheromeridae|Bacteria"


@pytest.fixture
def domain_seed():
    """The real data's shape: Bacteria and Archaea have paths but no row of their own."""
    for kingdom in ("Animalia", "Plantae", "Fungi", "Chromista", "Protozoa", "Viruses"):
        _insert(kingdom, kingdom, taxon_rank="kingdom")
    _insert("Aquificota", "Bacteria|Aquificota", taxon_rank="phylum")
    _insert("Bacterium", "Bacteria|Bacterium", taxon_rank="genus")
    # A synonym family stored at the bare path "Bacteria", as in the real database
    _insert("Nitrobacteraceae", "Bacteria", taxon_rank="family", taxonomic_status="SYNONYM")
    _insert("Thermoproteota", "Archaea|Thermoproteota", taxon_rank="phylum")
    # The only row actually named Bacteria is a stick insect genus
    _insert("Bacteria", STICK_INSECT_GENUS, taxon_rank="genus")


def test_root_lists_domains_then_viruses(domain_seed):
    root = client.get("/api/taxonomy/root").json()
    assert [n["node_id"] for n in root] == ["Bacteria", "Archaea", "Eukarya", "Viruses"]
    assert [n["rank"] for n in root] == ["domain", "domain", "domain", "kingdom"]


def test_eukarya_holds_the_five_kingdoms(domain_seed):
    kingdoms = _eukarya(client.get("/api/taxonomy/root").json())["children"]
    assert {n["node_id"] for n in kingdoms} == {"Animalia", "Plantae", "Fungi", "Chromista", "Protozoa"}


def test_root_omits_domain_without_rows(taxonomy_seed):
    root = client.get("/api/taxonomy/root").json()
    assert [n["node_id"] for n in root] == ["Eukarya"]


def test_zoom_bacteria_lists_phyla_not_the_synonym_rows_rank(domain_seed):
    nodes = client.get("/api/taxonomy/zoom", params={"node_id": "Bacteria"}).json()
    assert [n["node_id"] for n in nodes] == ["Bacteria|Aquificota", "__unclassified__Bacteria"]


def test_unclassified_bacteria_holds_non_phylum_children(domain_seed):
    nodes = client.get("/api/taxonomy/unclassified", params={"node_id": "Bacteria"}).json()
    assert [n["node_id"] for n in nodes] == ["Bacteria|Bacterium"]


def test_zoom_archaea_lists_phyla(domain_seed):
    nodes = client.get("/api/taxonomy/zoom", params={"node_id": "Archaea"}).json()
    assert [n["node_id"] for n in nodes] == ["Archaea|Thermoproteota"]


def test_search_finds_domain_and_namesake_genus(domain_seed):
    hits = client.get("/api/search", params={"q": "Bacteria"}).json()
    assert hits[0]["taxon_path"] == "Bacteria"
    assert hits[0]["taxon_rank"] == "domain"
    assert STICK_INSECT_GENUS in [h["taxon_path"] for h in hits]


def test_search_matches_domain_by_prefix(domain_seed):
    hits = client.get("/api/search", params={"q": "euk"}).json()
    assert hits[0]["taxon_path"] == "Eukarya"


def test_search_ignores_short_or_inner_domain_matches(domain_seed):
    for q in ("ar", "karya"):
        hits = client.get("/api/search", params={"q": q}).json()
        assert all(h["taxon_rank"] != "domain" for h in hits), q


def test_search_limit_counts_domain_hits(domain_seed):
    hits = client.get("/api/search", params={"q": "Bacteria", "limit": 1}).json()
    assert [h["taxon_path"] for h in hits] == ["Bacteria"]


# --- GET /api/taxonomy/zoom ---

def test_zoom_depth1_returns_direct_children(taxonomy_seed):
    resp = client.get("/api/taxonomy/zoom", params={"node_id": "Animalia", "depth": 1})
    assert resp.status_code == 200
    node_ids = {n["node_id"] for n in resp.json()}
    assert node_ids == {"Animalia|Chordata", "Animalia|Arthropoda"}


def test_zoom_depth1_excludes_grandchildren(taxonomy_seed):
    resp = client.get("/api/taxonomy/zoom", params={"node_id": "Animalia", "depth": 1})
    node_ids = {n["node_id"] for n in resp.json()}
    assert "Animalia|Chordata|Mammalia" not in node_ids


def test_zoom_depth2_nests_grandchildren(taxonomy_seed):
    resp = client.get("/api/taxonomy/zoom", params={"node_id": "Animalia", "depth": 2})
    assert resp.status_code == 200
    chordata = next(n for n in resp.json() if n["node_id"] == "Animalia|Chordata")
    child_ids = {c["node_id"] for c in chordata["children"]}
    assert "Animalia|Chordata|Mammalia" in child_ids


def test_zoom_leaf_returns_empty(taxonomy_seed):
    resp = client.get("/api/taxonomy/zoom",
                      params={"node_id": "Animalia|Chordata|Mammalia", "depth": 1})
    assert resp.status_code == 200
    assert resp.json() == []


def test_zoom_depth_out_of_range(taxonomy_seed):
    resp = client.get("/api/taxonomy/zoom", params={"node_id": "Animalia", "depth": 5})
    assert resp.status_code == 422


def test_zoom_missing_node_id():
    resp = client.get("/api/taxonomy/zoom")
    assert resp.status_code == 422


def test_zoom_common_names_returned(taxonomy_seed):
    _insert("Felis catus", "Animalia|Chordata|Mammalia|Carnivora|Felidae|Felis|Felis catus",
            common_names=database.serialize_common_names(["Domestic cat"]))
    resp = client.get("/api/taxonomy/zoom",
                      params={"node_id": "Animalia|Chordata|Mammalia|Carnivora|Felidae|Felis", "depth": 1})
    assert resp.status_code == 200
    nodes = resp.json()
    assert len(nodes) == 1
    assert "Domestic cat" in nodes[0]["common_names"]


# --- GET /api/species/{scientific_name} ---

def test_species_found(taxonomy_seed):
    resp = client.get("/api/species/Panthera leo")
    assert resp.status_code == 200
    data = resp.json()
    assert data["scientific_name"] == "Panthera leo"
    assert data["taxon_rank"] == "species"
    assert "Lion" in data["common_names"]
    assert data["iucn_status"] == "VU"


def test_species_not_found():
    resp = client.get("/api/species/Fakus nonexistus")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_species_all_fields_present(taxonomy_seed):
    resp = client.get("/api/species/Panthera leo")
    data = resp.json()
    expected_keys = {
        "scientific_name", "taxon_path", "taxon_rank", "common_names",
        "taxonomic_status", "body_mass", "body_length", "max_lifespan",
        "metabolic_rate", "reproduction_strategy", "geo_bounding_box",
        "habitat_type", "elevation_limits", "trophic_level", "activity_period",
        "iucn_status", "population_trend", "primary_image_url",
        "image_attribution", "wikipedia_abstract",
    }
    assert expected_keys <= set(data.keys())


# --- GET /api/search ---

def test_search_by_scientific_name(taxonomy_seed):
    resp = client.get("/api/search", params={"q": "Panthera"})
    assert resp.status_code == 200
    names = {r["scientific_name"] for r in resp.json()}
    assert "Panthera leo" in names
    assert "Canis lupus" not in names


def test_search_by_common_name(taxonomy_seed):
    resp = client.get("/api/search", params={"q": "Wolf"})
    names = {r["scientific_name"] for r in resp.json()}
    assert "Canis lupus" in names


def test_search_result_shape(taxonomy_seed):
    resp = client.get("/api/search", params={"q": "Panthera"})
    result = resp.json()[0]
    assert "scientific_name" in result
    assert "common_names" in result
    assert "taxon_rank" in result
    assert "taxon_path" in result


def test_search_limit(taxonomy_seed):
    for i in range(10):
        _insert(f"Canis species{i}", f"Animalia|...|Canis|Canis species{i}")
    resp = client.get("/api/search", params={"q": "Canis", "limit": 3})
    assert len(resp.json()) <= 3


def test_search_limit_too_large():
    resp = client.get("/api/search", params={"q": "x", "limit": 999})
    assert resp.status_code == 422


def test_search_empty_query():
    resp = client.get("/api/search", params={"q": ""})
    assert resp.status_code == 422


def test_search_no_results(taxonomy_seed):
    resp = client.get("/api/search", params={"q": "zzznomatch"})
    assert resp.status_code == 200
    assert resp.json() == []


# --- GET /api/taxonomy/node ---

def test_taxonomy_node_found(taxonomy_seed):
    resp = client.get("/api/taxonomy/node", params={"node_id": "Animalia|Chordata"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["node_id"] == "Animalia|Chordata"
    assert data["name"] == "Chordata"
    assert data["rank"] == "phylum"


def test_taxonomy_node_not_found(taxonomy_seed):
    resp = client.get("/api/taxonomy/node", params={"node_id": "Animalia|Fakephylum"})
    assert resp.status_code == 404


def test_taxonomy_node_missing_param():
    resp = client.get("/api/taxonomy/node")
    assert resp.status_code == 422


def test_taxonomy_node_species(taxonomy_seed):
    resp = client.get(
        "/api/taxonomy/node",
        params={"node_id": "Animalia|Chordata|Mammalia|Carnivora|Felidae|Panthera|Panthera leo"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Panthera leo"
    assert data["rank"] == "species"


# --- Structural SYNONYM genus fix ---

def test_zoom_shows_synonym_genus_with_accepted_descendants():
    """A genus row whose taxonomic_status is SYNONYM must still appear in the tree
    when it has ACCEPTED species underneath — it is a structural path waypoint."""
    # Mimics the Apis honey bee situation: the genus row is a SYNONYM but its
    # species (Apis cerana etc.) are ACCEPTED.
    _insert("Apidae",       "K|P|C|O|Apidae",             taxon_rank="family")
    _insert("Apiarus",      "K|P|C|O|Apidae|Apis",        taxon_rank="genus",  taxonomic_status="SYNONYM")
    _insert("Apis cerana",  "K|P|C|O|Apidae|Apis|Apis cerana",  taxon_rank="species")

    resp = client.get("/api/taxonomy/zoom", params={"node_id": "K|P|C|O|Apidae", "depth": 1})
    assert resp.status_code == 200
    node_ids = {n["node_id"] for n in resp.json()}
    assert "K|P|C|O|Apidae|Apis" in node_ids, "Structural genus must be visible even when its row is SYNONYM"


def test_zoom_hides_synonym_genus_without_accepted_descendants():
    """A SYNONYM genus with no ACCEPTED species underneath should be excluded."""
    _insert("Apidae",    "K|P|C|O|Apidae",          taxon_rank="family")
    _insert("Apiarus",   "K|P|C|O|Apidae|Apis",     taxon_rank="genus",  taxonomic_status="SYNONYM")
    # No ACCEPTED species under Apis

    resp = client.get("/api/taxonomy/zoom", params={"node_id": "K|P|C|O|Apidae", "depth": 1})
    assert resp.status_code == 200
    node_ids = {n["node_id"] for n in resp.json()}
    assert "K|P|C|O|Apidae|Apis" not in node_ids, "Pure SYNONYM genus with no accepted children must stay hidden"


# --- Alpha grouping ---

def _insert_many_genera(parent_path, count, taxon_rank_parent="family"):
    """Insert a parent node + `count` genus children under it."""
    parent_name = parent_path.rsplit("|", 1)[-1] if "|" in parent_path else parent_path
    _insert(parent_name, parent_path, taxon_rank=taxon_rank_parent)
    for i in range(count):
        name = f"Genus{i:03d}"
        _insert(name, f"{parent_path}|{name}", taxon_rank="genus")


def test_zoom_returns_alpha_nodes_when_over_limit():
    _insert_many_genera("Fabaceae", 201)

    resp = client.get("/api/taxonomy/zoom?node_id=Fabaceae&depth=1")
    assert resp.status_code == 200
    nodes = resp.json()
    ranks = {n["rank"] for n in nodes}
    assert "alpha" in ranks
    assert "genus" not in ranks
    alpha_nodes = [n for n in nodes if n["rank"] == "alpha"]
    assert all(n["node_id"].startswith("__alpha__Fabaceae|") for n in alpha_nodes)
    assert all(n["name"].startswith("[") for n in alpha_nodes)


def test_zoom_shows_all_children_when_under_limit():
    _insert_many_genera("Rosaceae", 5)

    resp = client.get("/api/taxonomy/zoom?node_id=Rosaceae&depth=1")
    assert resp.status_code == 200
    nodes = resp.json()
    assert all(n["rank"] == "genus" for n in nodes)
    assert len(nodes) == 5


def test_alpha_endpoint_returns_children_for_letter():
    _insert("Fabaceae", "Fabaceae", taxon_rank="family")
    _insert("Acacia",   "Fabaceae|Acacia",   taxon_rank="genus")
    _insert("Albizia",  "Fabaceae|Albizia",  taxon_rank="genus")
    _insert("Bauhinia", "Fabaceae|Bauhinia", taxon_rank="genus")

    resp = client.get("/api/taxonomy/alpha?node_id=Fabaceae&letter=A")
    assert resp.status_code == 200
    names = {n["name"] for n in resp.json()}
    assert names == {"Acacia", "Albizia"}

    resp = client.get("/api/taxonomy/alpha?node_id=Fabaceae&letter=Z")
    assert resp.status_code == 200
    assert resp.json() == []


def test_alpha_endpoint_includes_structural_synonym_genera():
    """A SYNONYM genus with ACCEPTED descendants must appear in alpha results."""
    _insert("Apidae",       "Apidae",            taxon_rank="family")
    _insert("Apis",         "Apidae|Apis",        taxon_rank="genus", taxonomic_status="SYNONYM")
    _insert("Apis cerana",  "Apidae|Apis|Apis cerana",  taxon_rank="species")

    resp = client.get("/api/taxonomy/alpha?node_id=Apidae&letter=A")
    assert resp.status_code == 200
    names = {n["name"] for n in resp.json()}
    assert "Apis" in names


def test_unclassified_returns_alpha_when_over_limit():
    # Viruses kingdom: expected child rank = "phylum"; insert 201 "family" orphans
    _insert("Viruses", "Viruses", taxon_rank="kingdom")
    for i in range(201):
        name = f"Viridae{i:03d}"
        _insert(name, f"Viruses|{name}", taxon_rank="family")

    resp = client.get("/api/taxonomy/unclassified?node_id=Viruses")
    assert resp.status_code == 200
    nodes = resp.json()
    ranks = {n["rank"] for n in nodes}
    assert "alpha" in ranks
    assert "family" not in ranks
    assert all(n["node_id"].startswith("__alpha____unclassified__Viruses|") for n in nodes if n["rank"] == "alpha")


def test_unclassified_letter_param_filters_children():
    _insert("Viruses", "Viruses", taxon_rank="kingdom")
    _insert("Adenoviridae", "Viruses|Adenoviridae", taxon_rank="family")
    _insert("Bunyaviridae", "Viruses|Bunyaviridae", taxon_rank="family")

    resp = client.get("/api/taxonomy/unclassified?node_id=Viruses&letter=A")
    assert resp.status_code == 200
    names = {n["name"] for n in resp.json()}
    assert names == {"Adenoviridae"}


# --- GET /api/species/{name}/image ---

from app import image_utils as _image_utils_mod


def test_image_endpoint_fetches_and_caches_result(monkeypatch):
    _insert('Apis mellifera', 'Animalia|Apis mellifera', primary_image_url=None)
    monkeypatch.setattr(_image_utils_mod, 'fetch_image',
        lambda name, common_names=None, taxon_path=None, **kw: ('https://example.com/bee.jpg', '© Example'))
    resp = client.get('/api/species/Apis%20mellifera/image')
    assert resp.status_code == 200
    body = resp.json()
    assert body['url'] == 'https://example.com/bee.jpg'
    assert body['attribution'] == '© Example'
    # verify DB was updated
    row = database.get_species('Apis mellifera')
    assert row['primary_image_url'] == 'https://example.com/bee.jpg'


def test_image_endpoint_returns_404_for_none_sentinel(monkeypatch):
    _insert('Apis mellifera', 'Animalia|Apis mellifera', primary_image_url='__none__')
    called = []
    monkeypatch.setattr(_image_utils_mod, 'fetch_image',
        lambda *a, **kw: called.append(True) or None)
    resp = client.get('/api/species/Apis%20mellifera/image')
    assert resp.status_code == 404
    assert called == []   # fetch_image was NOT called


def test_image_endpoint_force_bypasses_none_sentinel(monkeypatch):
    _insert('Apis mellifera', 'Animalia|Apis mellifera', primary_image_url='__none__')
    monkeypatch.setattr(_image_utils_mod, 'fetch_image',
        lambda name, common_names=None, taxon_path=None, **kw: ('https://example.com/new.jpg', '© New'))
    resp = client.get('/api/species/Apis%20mellifera/image?force=true')
    assert resp.status_code == 200
    assert resp.json()['url'] == 'https://example.com/new.jpg'


def test_image_endpoint_stores_none_sentinel_when_all_fail(monkeypatch):
    _insert('Apis mellifera', 'Animalia|Apis mellifera', primary_image_url=None)
    monkeypatch.setattr(_image_utils_mod, 'fetch_image',
        lambda name, common_names=None, taxon_path=None, **kw: None)
    resp = client.get('/api/species/Apis%20mellifera/image')
    assert resp.status_code == 404
    row = database.get_species('Apis mellifera')
    assert row['primary_image_url'] == '__none__'


def test_image_endpoint_404_for_unknown_species():
    resp = client.get('/api/species/Unknown%20xyz%2099999/image')
    assert resp.status_code == 404


def test_image_endpoint_force_does_not_store_sentinel_when_all_fail(monkeypatch):
    _insert('Apis mellifera', 'Animalia|Apis mellifera',
            primary_image_url='https://old.com/old.jpg')
    monkeypatch.setattr(_image_utils_mod, 'fetch_image',
        lambda name, common_names=None, taxon_path=None, **kw: None)
    resp = client.get('/api/species/Apis%20mellifera/image?force=true')
    assert resp.status_code == 404
    # __none__ sentinel must NOT be written when force=True (old URL was valid, just temporarily broken)
    row = database.get_species('Apis mellifera')
    assert row['primary_image_url'] == 'https://old.com/old.jpg'


# --- /api/species/{name}/traits (Increment 12) ---

import json as _json
from app import trait_utils
from app.database import TraitValue

_LEO = "Animalia|Chordata|Mammalia|Carnivora|Felidae|Panthera|Panthera leo"
_EST = "Estimated from Wikipedia description"


def _stages(monkeypatch, sourced=({}, True), estimated=({}, True)):
    """Patch both stages; records the row each one was handed."""
    calls = {"sourced": [], "estimated": []}
    def _run(stage, result):
        def _f(row):
            calls[stage].append(dict(row))
            return result(row) if callable(result) else result
        return _f
    monkeypatch.setattr(trait_utils, "run_sourced_stage", _run("sourced", sourced))
    monkeypatch.setattr(trait_utils, "run_estimate_stage", _run("estimated", estimated))
    return calls


def _sources_of(name):
    return database.parse_trait_sources(database.get_species(name)["trait_sources"])


def test_traits_route_not_shadowed_by_species_route(monkeypatch):
    _insert("Panthera leo", _LEO)
    _stages(monkeypatch)
    resp = client.get("/api/species/Panthera leo/traits")
    assert resp.status_code == 200
    assert resp.json()["scientific_name"] == "Panthera leo"
    assert "values" in resp.json()


def test_traits_sourced_stage_writes_and_marks(monkeypatch):
    _insert("Panthera leo", _LEO)
    _stages(monkeypatch, sourced=({"habitat_type": TraitValue("Savanna", "IUCN Red List")}, True))
    body = client.get("/api/species/Panthera leo/traits?stage=sourced").json()
    assert body["values"]["habitat_type"] == "Savanna"
    assert body["provenance"]["habitat_type"] == {"source": "IUCN Red List", "estimated": False}
    assert body["traits_sourced"] is True and body["trait_eligible"] is True
    assert database.get_species("Panthera leo")["habitat_type"] == "Savanna"
    assert "_sourced" in _sources_of("Panthera leo")


def test_traits_marker_set_skips_network(monkeypatch):
    _insert("Panthera leo", _LEO, trait_sources='{"_sourced": "2026-11-03"}')
    calls = _stages(monkeypatch)
    body = client.get("/api/species/Panthera leo/traits?stage=sourced").json()
    assert calls["sourced"] == [] and body["traits_sourced"] is True


def test_traits_force_reruns_stage(monkeypatch):
    _insert("Panthera leo", _LEO, trait_sources='{"_sourced": "2026-11-03"}')
    calls = _stages(monkeypatch)
    client.get("/api/species/Panthera leo/traits?stage=sourced&force=true")
    assert len(calls["sourced"]) == 1


def test_traits_source_down_leaves_unmarked(monkeypatch):
    _insert("Panthera leo", _LEO)
    _stages(monkeypatch, sourced=({"habitat_type": TraitValue("Savanna", "IUCN Red List")}, False))
    body = client.get("/api/species/Panthera leo/traits?stage=sourced").json()
    assert body["values"]["habitat_type"] == "Savanna"
    assert body["traits_sourced"] is False
    assert "_sourced" not in _sources_of("Panthera leo")


def test_traits_genus_not_eligible(monkeypatch):
    _insert("Panthera", "Animalia|Chordata|Panthera", taxon_rank="genus")
    calls = _stages(monkeypatch)
    body = client.get("/api/species/Panthera/traits?stage=sourced").json()
    assert body["trait_eligible"] is False
    assert calls == {"sourced": [], "estimated": []}


def test_traits_estimate_stage_requires_eligible_rank(monkeypatch):
    _insert("Panthera", "Animalia|Chordata|Panthera", taxon_rank="genus", wikipedia_abstract="A genus.")
    calls = _stages(monkeypatch)
    resp = client.get("/api/species/Panthera/traits?stage=estimated")
    assert resp.status_code == 200 and calls == {"sourced": [], "estimated": []}


def test_traits_estimated_runs_sourced_first_and_marks_both(monkeypatch):
    _insert("Panthera leo", _LEO, wikipedia_abstract="Lions are nocturnal.")
    calls = _stages(monkeypatch, estimated=({"activity_period": TraitValue("nocturnal", _EST, True)}, True))
    body = client.get("/api/species/Panthera leo/traits?stage=estimated").json()
    assert len(calls["sourced"]) == 1 and len(calls["estimated"]) == 1
    assert body["provenance"]["activity_period"] == {"source": _EST, "estimated": True}
    assert body["traits_sourced"] is True and body["traits_estimated"] is True


def test_traits_estimate_uses_freshly_fetched_abstract(monkeypatch):
    _insert("Panthera leo", _LEO)
    calls = _stages(monkeypatch,
                    sourced=({"wikipedia_abstract": TraitValue("Lions are nocturnal.", "Wikipedia")}, True))
    client.get("/api/species/Panthera leo/traits?stage=estimated")
    assert calls["estimated"][0]["wikipedia_abstract"] == "Lions are nocturnal."


def test_species_record_includes_provenance(monkeypatch):
    _insert("Panthera leo", _LEO, iucn_status="VU",
            trait_sources='{"_sourced": "2026-11-03"}')
    body = client.get("/api/species/Panthera leo").json()
    assert body["provenance"]["iucn_status"] == {"source": "IUCN Red List", "estimated": False}
    assert body["traits_sourced"] is True and body["traits_estimated"] is False
    assert body["trait_eligible"] is True


def test_traits_unknown_stage_422_and_missing_species_404(monkeypatch):
    _insert("Panthera leo", _LEO)
    _stages(monkeypatch)
    assert client.get("/api/species/Panthera leo/traits?stage=bogus").status_code == 422
    assert client.get("/api/species/Nonexistus fakeus/traits").status_code == 404


def test_traits_corrupt_trait_sources_does_not_500(monkeypatch):
    _insert("Panthera leo", _LEO, trait_sources="{oops")
    calls = _stages(monkeypatch, sourced=({"habitat_type": TraitValue("Savanna", "IUCN Red List")}, True))
    resp = client.get("/api/species/Panthera leo/traits?stage=sourced")
    assert resp.status_code == 200 and len(calls["sourced"]) == 1
    stored = database.get_species("Panthera leo")["trait_sources"]
    assert "_sourced" in _json.loads(stored)


def test_traits_db_locked_still_returns_values(monkeypatch):
    _insert("Panthera leo", _LEO)
    _stages(monkeypatch, sourced=({"habitat_type": TraitValue("Savanna", "IUCN Red List")}, True))
    monkeypatch.setattr(database, "update_species_traits", lambda *a, **k: False)
    body = client.get("/api/species/Panthera leo/traits?stage=sourced").json()
    assert body["values"]["habitat_type"] == "Savanna"
    assert body["provenance"]["habitat_type"]["source"] == "IUCN Red List"
    assert body["traits_sourced"] is False


def test_traits_offline_writes_no_estimated_marker(monkeypatch):
    # Real stage functions; every source down. No abstract arrives, so the
    # estimate stage must not be marked done (Review Focus 3).
    _insert("Panthera leo", _LEO)
    def _down(*a, **k):
        raise trait_utils.SourceUnavailable("offline")
    for fn in ("iucn_traits", "gbif_traits", "wikidata_traits", "wikipedia_abstract"):
        monkeypatch.setattr(trait_utils, fn, _down)
    monkeypatch.setattr(trait_utils, "_call_estimator", lambda a: pytest.fail("no abstract, no LLM call"))
    body = client.get("/api/species/Panthera leo/traits?stage=estimated").json()
    assert body["traits_sourced"] is False and body["traits_estimated"] is False
    assert _sources_of("Panthera leo") == {}



def test_search_and_species_include_extinct_flag():
    _insert("Sceparnodon ramsayi", "Animalia|Vombatidae|Sceparnodon|Sceparnodon ramsayi")
    conn = database.get_connection()
    conn.execute("UPDATE species SET extinct = 1 WHERE scientific_name = 'Sceparnodon ramsayi'")
    conn.commit(); conn.close()
    assert client.get("/api/search", params={"q": "Sceparnodon"}).json()[0]["extinct"] is True
    assert client.get("/api/species/Sceparnodon ramsayi").json()["extinct"] is True


# --- Catalogue of Life levels (Increment 16) ---

def _names(nodes):
    return [n["name"] for n in nodes]


def test_stand_in_level_is_a_real_node_not_unclassified():
    _insert("Gastropoda", "Animalia|Mollusca|Gastropoda", taxon_rank="class")
    _insert("Helicoidei", "Animalia|Mollusca|Gastropoda|Helicoidei", taxon_rank="infraorder")
    _insert("Neogastropoda", "Animalia|Mollusca|Gastropoda|Neogastropoda", taxon_rank="order")
    nodes = client.get("/api/taxonomy/zoom", params={"node_id": "Animalia|Mollusca|Gastropoda"}).json()
    assert sorted(_names(nodes)) == ["Helicoidei", "Neogastropoda"]
    assert {n["rank"] for n in nodes} == {"infraorder", "order"}


def test_stand_in_level_lists_the_families_and_genera_below_it():
    base = "Animalia|Mollusca|Gastropoda|Helicoidei"
    _insert("Helicoidei", base, taxon_rank="infraorder")
    _insert("Camaenidae", f"{base}|Camaenidae", taxon_rank="family")
    _insert("Acusta", f"{base}|Acusta", taxon_rank="genus")
    assert sorted(_names(client.get("/api/taxonomy/zoom", params={"node_id": base}).json())) == ["Acusta", "Camaenidae"]


def test_stand_in_below_an_order_is_a_real_node():
    _insert("Diptera", "Animalia|Arthropoda|Insecta|Diptera", taxon_rank="order")
    _insert("Brachycera", "Animalia|Arthropoda|Insecta|Diptera|Brachycera", taxon_rank="suborder")
    nodes = client.get("/api/taxonomy/zoom", params={"node_id": "Animalia|Arthropoda|Insecta|Diptera"}).json()
    assert _names(nodes) == ["Brachycera"]


def test_genus_directly_under_a_class_stays_unclassified():
    _insert("Insecta", "Animalia|Arthropoda|Insecta", taxon_rank="class")
    _insert("Foo", "Animalia|Arthropoda|Insecta|Foo", taxon_rank="genus")
    names = _names(client.get("/api/taxonomy/zoom", params={"node_id": "Animalia|Arthropoda|Insecta"}).json())
    assert names == ["[Unclassified] (1)"]


def test_bacteria_opens_on_its_kingdoms():
    _insert("Bacillati", "Bacteria|Bacillati", taxon_rank="kingdom")
    _insert("Bacillota", "Bacteria|Bacillati|Bacillota", taxon_rank="phylum")
    assert _names(client.get("/api/taxonomy/zoom", params={"node_id": "Bacteria"}).json()) == ["Bacillati"]


def test_viruses_open_on_their_kingdoms():
    _insert("Viruses", "Viruses", taxon_rank="unranked")
    _insert("Orthornavirae", "Viruses|Orthornavirae", taxon_rank="kingdom")
    assert _names(client.get("/api/taxonomy/zoom", params={"node_id": "Viruses"}).json()) == ["Orthornavirae"]


def test_species_opens_on_its_subspecies():
    base = "Animalia|Chordata|Mammalia|Carnivora|Felidae|Panthera|Panthera leo"
    _insert("Panthera leo", base)
    _insert("Panthera leo leo", f"{base}|Panthera leo leo", taxon_rank="subspecies")
    assert _names(client.get("/api/taxonomy/zoom", params={"node_id": base}).json()) == ["Panthera leo leo"]


def _insert_outside_tree(name="Fossilus antiquus"):
    conn = database.get_connection()
    conn.execute(
        "INSERT INTO species (scientific_name, taxon_rank, taxonomic_status, common_names, extinct) "
        "VALUES (?, 'species', 'GBIF_ONLY', '[]', 1)",
        (name,),
    )
    conn.commit()
    conn.close()


def test_row_outside_the_tree_is_found_and_opens():
    _insert_outside_tree()
    hit = client.get("/api/search", params={"q": "Fossilus"}).json()[0]
    assert hit["taxon_path"] is None
    assert hit["taxonomic_status"] == "GBIF_ONLY"
    detail = client.get("/api/species/Fossilus antiquus").json()
    assert detail["taxon_path"] is None
    assert detail["extinct"] is True


def test_row_outside_the_tree_never_appears_as_a_node():
    _insert("Animalia", "Animalia", taxon_rank="kingdom")
    _insert_outside_tree()
    root = client.get("/api/taxonomy/root").json()
    assert "Fossilus antiquus" not in str(root)
    assert "Fossilus antiquus" not in str(client.get("/api/taxonomy/zoom", params={"node_id": "Animalia"}).json())


def test_traits_for_a_row_outside_the_tree_do_not_crash(monkeypatch):
    from app import trait_utils
    monkeypatch.setattr(trait_utils, "run_sourced_stage", lambda row: ({}, True))
    _insert_outside_tree()
    assert client.get("/api/species/Fossilus antiquus/traits").status_code == 200


def test_homonym_node_names_its_own_row_but_shows_the_plain_name():
    family = "Plantae|Tracheophyta|Liliopsida|Asparagales|Orchidaceae"
    _insert("Acrocodia [Orchidaceae]", f"{family}|Acrocodia", taxon_rank="genus")
    node = client.get("/api/taxonomy/zoom", params={"node_id": family}).json()[0]
    assert node["name"] == "Acrocodia"
    assert node["scientific_name"] == "Acrocodia [Orchidaceae]"


# --- Increment 30: old names ---

def _old_names_seed():
    _insert("Acrocodia indica", "Animalia|Acrocodia|Acrocodia indica",
            common_names=database.serialize_common_names(["Malayan tapir"]))
    _insert("Tapirus indicus", "Animalia|Acrocodia|Tapirus indicus", taxonomic_status="SYNONYM",
            common_names=database.serialize_common_names(["Malayan Tapir"]))
    conn = database.get_connection()
    conn.execute("UPDATE species SET accepted_name = 'Acrocodia indica' WHERE scientific_name = 'Tapirus indicus'")
    conn.commit()
    conn.close()


def test_species_detail_links_an_old_name_to_its_current_name():
    _old_names_seed()
    body = client.get("/api/species/Tapirus indicus").json()
    assert body["current_name"]["scientific_name"] == "Acrocodia indica"
    assert body["current_name"]["source"] == "Catalogue of Life"
    assert client.get("/api/species/Acrocodia indica").json()["current_name"] is None


def test_search_results_carry_the_accepted_name():
    _old_names_seed()
    hits = {h["scientific_name"]: h for h in client.get("/api/search", params={"q": "Malayan"}).json()}
    assert hits["Tapirus indicus"]["accepted_name"] == "Acrocodia indica"
    assert hits["Acrocodia indica"]["accepted_name"] is None


def test_traits_run_the_name_check_once_for_rows_sourced_before_it(monkeypatch):
    from app import trait_utils
    from app.database import TraitValue
    _old_names_seed()
    _insert("Tapirus malayanus", "Animalia|Tapirus|Tapirus malayanus",
            trait_sources='{"_sourced": "2026-11-04", "_estimated": "2026-11-04"}')
    calls = []

    def _names(row):
        calls.append(row["scientific_name"])
        return {"accepted_name": TraitValue("Tapirus indicus", "Wikidata")}, True
    monkeypatch.setattr(trait_utils, "run_name_stage", _names)
    monkeypatch.setattr(trait_utils, "run_sourced_stage", lambda row: (_ for _ in ()).throw(AssertionError))

    body = client.get("/api/species/Tapirus malayanus/traits", params={"stage": "estimated"}).json()
    assert body["current_name"]["scientific_name"] == "Acrocodia indica"
    assert body["current_name"]["source"] == "Wikidata"
    client.get("/api/species/Tapirus malayanus/traits", params={"stage": "estimated"})
    assert calls == ["Tapirus malayanus"]


# --- Increment 31: picture retry ---

import datetime as _dt


def _capture_fetch(monkeypatch, result=None, raises=None):
    seen = {}
    def fake(name, common_names=None, taxon_path=None, **kw):
        seen.update(name=name, **kw)
        if raises:
            raise raises
        return result
    monkeypatch.setattr(_image_utils_mod, 'fetch_image', fake)
    return seen


def test_image_endpoint_passes_taxon_rank(monkeypatch):
    _insert('Tyto furcata bondi', 'Animalia|Tyto furcata bondi', taxon_rank='subspecies')
    seen = _capture_fetch(monkeypatch, ('https://x/owl.jpg', '© iNat'))
    assert client.get('/api/species/Tyto%20furcata%20bondi/image').status_code == 200
    assert seen['rank'] == 'subspecies' and not seen.get('wide')


def test_image_retry_runs_wide_search_with_current_name(monkeypatch):
    _insert('Acrocodia indica', 'Animalia|Acrocodia indica')
    _insert('Tapirus indicus', 'Animalia|Tapirus indicus', taxonomic_status='SYNONYM')
    conn = database.get_connection()
    conn.execute("UPDATE species SET accepted_name='Acrocodia indica' WHERE scientific_name='Tapirus indicus'")
    conn.commit()
    conn.close()
    seen = _capture_fetch(monkeypatch, ('https://x/tapir.jpg', '© W (picture of Acrocodia indica)'))
    resp = client.get('/api/species/Tapirus%20indicus/image?retry=true')
    assert resp.status_code == 200
    assert seen['wide'] is True and seen['current_name'] == 'Acrocodia indica'


def test_image_retry_ignores_none_sentinel(monkeypatch):
    _insert('Anoxycalyx ijimai', 'Animalia|Anoxycalyx ijimai', primary_image_url='__none__')
    _capture_fetch(monkeypatch, ('https://x/sponge.jpg', '© NHM (CC BY 4.0) via GBIF (museum specimen)'))
    resp = client.get('/api/species/Anoxycalyx%20ijimai/image?retry=true')
    assert resp.status_code == 200
    assert database.get_species('Anoxycalyx ijimai')['primary_image_url'] == 'https://x/sponge.jpg'


def test_image_retry_miss_records_date(monkeypatch):
    _insert('Neomonas', 'Protozoa|Neomonas', taxon_rank='genus', primary_image_url='__none__')
    _capture_fetch(monkeypatch, None)
    resp = client.get('/api/species/Neomonas/image?retry=true')
    today = _dt.date.today().isoformat()
    assert resp.status_code == 404
    assert resp.json()['detail'] == {'message': 'No image found', 'searched_again': today}
    row = database.get_species('Neomonas')
    assert row['primary_image_url'] == '__none__'
    assert row['image_attribution'] == f'searched again {today}'


def test_image_retry_miss_keeps_a_real_url(monkeypatch):
    _insert('Apis mellifera', 'Animalia|Apis mellifera', primary_image_url='https://old.com/old.jpg')
    _capture_fetch(monkeypatch, None)
    assert client.get('/api/species/Apis%20mellifera/image?retry=true').status_code == 404
    assert database.get_species('Apis mellifera')['primary_image_url'] == 'https://old.com/old.jpg'


def test_image_outage_returns_503_and_stores_nothing(monkeypatch):
    _insert('Apis mellifera', 'Animalia|Apis mellifera', primary_image_url=None)
    _capture_fetch(monkeypatch, raises=_image_utils_mod.ImagesUnavailable('_wikipedia_image'))
    resp = client.get('/api/species/Apis%20mellifera/image')
    assert resp.status_code == 503
    assert resp.json()['detail'] == "A picture source didn't answer; try again later"
    assert database.get_species('Apis mellifera')['primary_image_url'] is None


def test_image_retry_outage_keeps_the_sentinel(monkeypatch):
    _insert('Neomonas', 'Protozoa|Neomonas', taxon_rank='genus', primary_image_url='__none__')
    _capture_fetch(monkeypatch, raises=_image_utils_mod.ImagesUnavailable('_gbif_image'))
    assert client.get('/api/species/Neomonas/image?retry=true').status_code == 503
    row = database.get_species('Neomonas')
    assert row['primary_image_url'] == '__none__' and not row['image_attribution']


def test_image_retry_passes_the_current_names_lineage_and_rank(monkeypatch):
    _insert("Acrocodia indica", "Animalia|Chordata|Acrocodia indica")
    _insert("Tapirus indicus", "Animalia|Tapirus indicus", taxonomic_status="SYNONYM")
    conn = database.get_connection()
    conn.execute("UPDATE species SET accepted_name='Acrocodia indica' WHERE scientific_name='Tapirus indicus'")
    conn.commit()
    conn.close()
    seen = _capture_fetch(monkeypatch, None)
    client.get("/api/species/Tapirus%20indicus/image?retry=true")
    assert seen["current_path"] == "Animalia|Chordata|Acrocodia indica"
    assert seen["current_rank"] == "species"


# --- Increment 32: Other pictures ---

def _set(name, **cols):
    conn = database.get_connection()
    for col, val in cols.items():
        conn.execute(f"UPDATE species SET {col} = ? WHERE scientific_name = ?", (val, name))
    conn.commit()
    conn.close()


def test_candidates_route_excludes_current_and_rejected(monkeypatch):
    _insert("Oreamnos americanus", "Animalia|Oreamnos americanus", primary_image_url="https://w/snake.jpg")
    _set("Oreamnos americanus", rejected_images='["https://old/1.jpg"]')
    seen = {}
    def fake(name, common_names=None, taxon_path=None, **kw):
        seen.update(name=name, **kw)
        return [{"url": "https://i/goat.jpg", "attribution": "(c) a", "source": "iNaturalist"}], False
    monkeypatch.setattr(_image_utils_mod, "image_candidates", fake)
    resp = client.get("/api/species/Oreamnos%20americanus/image/candidates")
    assert resp.status_code == 200
    assert resp.json() == {"candidates": [{"url": "https://i/goat.jpg", "attribution": "(c) a",
                                           "source": "iNaturalist"}], "unavailable": False}
    assert seen["exclude"] == {"https://w/snake.jpg", "https://old/1.jpg"}
    assert seen["rank"] == "species"


def test_candidates_route_homonym_key(monkeypatch):
    _insert("Bacteria laesa [Phasmatidae]", "Animalia|Bacteria laesa [Phasmatidae]")
    monkeypatch.setattr(_image_utils_mod, "image_candidates", lambda *a, **k: ([], True))
    resp = client.get("/api/species/Bacteria%20laesa%20%5BPhasmatidae%5D/image/candidates")
    assert resp.status_code == 200 and resp.json() == {"candidates": [], "unavailable": True}


def test_candidates_route_unknown_species():
    assert client.get("/api/species/Nope%20nope/image/candidates").status_code == 404


def test_choose_route_stores_and_rejects():
    _insert("Oreamnos americanus", "Animalia|Oreamnos americanus", primary_image_url="https://w/snake.jpg")
    resp = client.put("/api/species/Oreamnos%20americanus/image",
                      json={"url": "https://i/goat.jpg", "attribution": "(c) a"})
    assert resp.status_code == 200 and resp.json() == {"url": "https://i/goat.jpg", "attribution": "(c) a"}
    row = database.get_species("Oreamnos americanus")
    assert row["primary_image_url"] == "https://i/goat.jpg"
    assert database.parse_rejected_images(row["rejected_images"]) == ["https://w/snake.jpg"]


def test_choose_route_rejects_non_http_url():
    _insert("Oreamnos americanus", "Animalia|Oreamnos americanus")
    for bad in ("javascript:alert(1)", "data:image/png;base64,xx", "__none__", ""):
        resp = client.put("/api/species/Oreamnos%20americanus/image", json={"url": bad, "attribution": ""})
        assert resp.status_code == 400, bad


def test_choose_route_unknown_species():
    resp = client.put("/api/species/Nope%20nope/image", json={"url": "https://x/1.jpg", "attribution": ""})
    assert resp.status_code == 404


def test_image_route_passes_rejected_as_exclude(monkeypatch):
    _insert("Oreamnos americanus", "Animalia|Oreamnos americanus")
    _set("Oreamnos americanus", rejected_images='["https://w/snake.jpg"]')
    seen = _capture_fetch(monkeypatch, ("https://i/goat.jpg", "(c) a"))
    client.get("/api/species/Oreamnos%20americanus/image")
    assert seen["exclude"] == {"https://w/snake.jpg"}


# --- Increment 32 review: a lookup never overwrites a choice made while it ran ---

def test_image_route_does_not_overwrite_a_choice_made_meanwhile(monkeypatch):
    _insert("Oreamnos americanus", "Animalia|Oreamnos americanus", primary_image_url=None)
    def slow_lookup(name, common_names=None, taxon_path=None, **kw):
        database.choose_species_image(name, "https://i/chosen.jpg", "(c) chosen")   # the user, meanwhile
        return ("https://w/auto.jpg", "© auto")
    monkeypatch.setattr(_image_utils_mod, "fetch_image", slow_lookup)
    resp = client.get("/api/species/Oreamnos%20americanus/image")
    assert resp.status_code == 200 and resp.json()["url"] == "https://i/chosen.jpg"
    assert database.get_species("Oreamnos americanus")["primary_image_url"] == "https://i/chosen.jpg"


def test_image_retry_miss_does_not_overwrite_a_choice_made_meanwhile(monkeypatch):
    _insert("Neomonas", "Protozoa|Neomonas", taxon_rank="genus", primary_image_url="__none__")
    def slow_miss(name, common_names=None, taxon_path=None, **kw):
        database.choose_species_image(name, "https://g/chosen.jpg", "© chosen via GBIF")
        return None
    monkeypatch.setattr(_image_utils_mod, "fetch_image", slow_miss)
    resp = client.get("/api/species/Neomonas/image?retry=true")
    assert resp.status_code == 200 and resp.json()["url"] == "https://g/chosen.jpg"
    assert database.get_species("Neomonas")["primary_image_url"] == "https://g/chosen.jpg"


# --- Increment 33: a picture that failed to load is skipped by the replacement lookup ---

def test_image_route_skips_the_failed_picture_without_rejecting_it(monkeypatch):
    _insert("Oreamnos americanus", "Animalia|Oreamnos americanus", primary_image_url="https://w/dead.jpg")
    _set("Oreamnos americanus", rejected_images='["https://w/snake.jpg"]')
    seen = _capture_fetch(monkeypatch, ("https://i/goat.jpg", "(c) a"))
    resp = client.get("/api/species/Oreamnos%20americanus/image",
                      params={"force": "true", "failed": "https://w/dead.jpg"})
    assert resp.status_code == 200 and resp.json()["url"] == "https://i/goat.jpg"
    assert seen["exclude"] == {"https://w/snake.jpg", "https://w/dead.jpg"}
    row = database.get_species("Oreamnos americanus")
    assert database.parse_rejected_images(row["rejected_images"]) == ["https://w/snake.jpg"]


# ── Increment 34: range map data ─────────────────────────────────────────────

def _countries(name, *pairs):
    conn = database.get_connection()
    conn.executemany("INSERT INTO species_countries (country, scientific_name, records) VALUES (?, ?, ?)",
                     [(c, name, n) for c, n in pairs])
    conn.commit()
    conn.close()


def test_range_route_splits_native_and_elsewhere():
    # Real places.json: India, China, Mongolia, Nepal hold the snow leopard; 6 US records are strays
    _insert("Panthera uncia", "Animalia|Panthera uncia")
    _countries("Panthera uncia", ("IN", 97), ("CN", 59), ("MN", 45), ("NP", 10), ("US", 6))
    resp = client.get("/api/species/Panthera%20uncia/range")
    assert resp.status_code == 200
    body = resp.json()
    assert [c["code"] for c in body["native"]] == ["IN", "CN", "MN", "NP"]
    assert body["native"][0] == {"code": "IN", "name": "India", "records": 97}
    assert body["elsewhere"] == [{"code": "US", "name": "United States of America", "records": 6}]


def test_range_route_empty_without_records():
    _insert("Panthera onca", "Animalia|Panthera onca")
    assert client.get("/api/species/Panthera%20onca/range").json() == {"native": [], "elsewhere": []}


def test_range_route_unknown_species():
    assert client.get("/api/species/Nope%20nope/range").status_code == 404
