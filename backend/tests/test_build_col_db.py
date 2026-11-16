"""Catalogue of Life switch: data/build_col_db.py turns the COL trial DB into the app's table."""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "data"))
import build_col_db as bc  # noqa: E402
import import_col  # noqa: E402

E = "domain:Eukaryota|kingdom:Animalia"
BARBUS = (f"{E}|phylum:Chordata|subphylum:Vertebrata|gigaclass:Actinopterygii|class:Teleostei"
          "|order:Cypriniformes|family:Cyprinidae|subfamily:Barbinae|genus:Barbus|species:Barbus barbus")
SNAIL = (f"{E}|phylum:Mollusca|class:Gastropoda|subclass:Heterobranchia|superorder:Eupulmonata"
         "|infraorder:Helicoidei|genus:Acusta|species:Acusta ravida")
MILLIPEDE = (f"{E}|phylum:Arthropoda|class:Diplopoda|superorder:Merocheta|suborder:Dalodesmidea"
             "|family:Dalodesmidae|genus:Dasystigma|species:Dasystigma margaretae")


@pytest.mark.parametrize("lineage,want", [
    (BARBUS, "Animalia|Chordata|Teleostei|Cypriniformes|Cyprinidae|Barbus|Barbus barbus"),
    (SNAIL, "Animalia|Mollusca|Gastropoda|Helicoidei|Acusta|Acusta ravida"),
    (MILLIPEDE, "Animalia|Arthropoda|Diplopoda|Dalodesmidea|Dalodesmidae|Dasystigma|Dasystigma margaretae"),
    (f"{E}|phylum:Chordata|class:Mammalia|order:Carnivora|suborder:Feliformia|family:Felidae|genus:Panthera"
     "|species:Panthera leo|subspecies:Panthera leo leo",
     "Animalia|Chordata|Mammalia|Carnivora|Felidae|Panthera|Panthera leo|Panthera leo leo"),
    (f"{E}|species:Brephosceles cygni", "Animalia|Brephosceles cygni"),
    (f"{E}|phylum:Arthropoda|class:Insecta|order:Lepidoptera|family:Nymphalidae|genus:Danaus"
     "|subgenus:Danaus (Danaus)|species:Danaus (Danaus) plexippus",
     "Animalia|Arthropoda|Insecta|Lepidoptera|Nymphalidae|Danaus|Danaus plexippus"),
    ("domain:Bacteria|kingdom:Bacillati|phylum:Bacillota", "Bacteria|Bacillati|Bacillota"),
    ("unranked:Viruses|realm:Riboviria|kingdom:Orthornavirae|phylum:Pisuviricota",
     "Viruses|Orthornavirae|Pisuviricota"),
])
def test_tree_path_uses_main_levels_and_one_stand_in_per_gap(lineage, want):
    assert bc.tree_path(lineage) == want


def test_name_is_stored_without_the_subgenus_col_writes_inside_it():
    assert bc.step_name("species", "Danaus (Danaus) plexippus") == "Danaus plexippus"


@pytest.mark.parametrize("status,want", [
    ("accepted", "ACCEPTED"), ("provisionally accepted", "ACCEPTED"),
    ("synonym", "SYNONYM"), ("ambiguous synonym", "SYNONYM"), ("misapplied", "SYNONYM"),
])
def test_status_maps_to_the_apps_two_values(status, want):
    assert bc.map_status(status) == want


@pytest.mark.parametrize("name,rank,dropped", [
    ("BOLD:ADW1988", "unranked", True),
    ("SH1234567.09FU", "unranked", True),
    ("Aspilota vector", "unranked", False),
    ("Viruses", "unranked", False),
    ("BOLDia minor", "species", False),
])
def test_only_dna_clusters_are_dropped(name, rank, dropped):
    assert bc.is_dna_cluster(name, rank) is dropped


FIXES = bc.Fixes(
    family={("Acusta", "Mollusca"): ("Camaenidae", "WoRMS")},
    order={("Dalodesmidae", "Arthropoda"): ("Polydesmida", "WoRMS,IRMNG")},
)


def test_confirmed_family_is_added_and_the_stand_in_remains_for_the_missing_order():
    assert bc.tree_path(SNAIL, FIXES, {}) == "Animalia|Mollusca|Gastropoda|Helicoidei|Camaenidae|Acusta|Acusta ravida"


def test_confirmed_order_applies_to_everything_in_the_family():
    assert bc.tree_path(MILLIPEDE, FIXES, {}) == (
        "Animalia|Arthropoda|Diplopoda|Polydesmida|Dalodesmidae|Dasystigma|Dasystigma margaretae"
    )
    family_row = f"{E}|phylum:Arthropoda|class:Diplopoda|superorder:Merocheta|suborder:Dalodesmidea|family:Dalodesmidae"
    assert bc.tree_path(family_row, FIXES, {}) == "Animalia|Arthropoda|Diplopoda|Polydesmida|Dalodesmidae"


def test_fix_for_a_homonym_in_another_phylum_is_ignored():
    other = f"{E}|phylum:Chordata|class:Mammalia|genus:Acusta|species:Acusta other"
    assert bc.tree_path(other, FIXES, {}) == "Animalia|Chordata|Mammalia|Acusta|Acusta other"


def test_attached_family_brings_the_order_col_gives_it():
    family_lineages = {"Camaenidae": [f"{E}|phylum:Mollusca|class:Gastropoda|order:Stylommatophora|family:Camaenidae"]}
    assert bc.tree_path(SNAIL, FIXES, family_lineages) == (
        "Animalia|Mollusca|Gastropoda|Stylommatophora|Camaenidae|Acusta|Acusta ravida"
    )


def test_genus_attached_to_a_family_takes_the_familys_place_not_its_own_order_fix():
    # Sources confirm an order for the genus but disagree about the family's order. The
    # family must not end up in two places, or with its order below it.
    fixes = bc.Fixes(
        family={("Acusta", "Mollusca"): ("Camaenidae", "WoRMS")},
        order={("Acusta", "Mollusca"): ("Stylommatophora", "WoRMS")},
    )
    family = f"{E}|phylum:Mollusca|class:Gastropoda|subclass:Heterobranchia|superorder:Eupulmonata|family:Camaenidae"
    families = {"Camaenidae": [family]}
    assert bc.tree_path(SNAIL, fixes, families) == "Animalia|Mollusca|Gastropoda|Eupulmonata|Camaenidae|Acusta|Acusta ravida"
    assert bc.tree_path(family, fixes, families) == "Animalia|Mollusca|Gastropoda|Eupulmonata|Camaenidae"


def test_order_fix_on_a_genus_without_family_goes_above_the_genus():
    fixes = bc.Fixes(family={}, order={("Thlipsuropsis", "Arthropoda"): ("Platycopida", "WoRMS")})
    lineage = f"{E}|phylum:Arthropoda|class:Ostracoda|genus:Thlipsuropsis|species:Thlipsuropsis digitata"
    assert bc.tree_path(lineage, fixes, {}) == "Animalia|Arthropoda|Ostracoda|Platycopida|Thlipsuropsis|Thlipsuropsis digitata"


def test_order_fix_on_a_family_new_to_col_goes_above_the_family():
    fixes = bc.Fixes(family={("Foo", "Arthropoda"): ("Fooidae", "WoRMS")}, order={("Fooidae", "Arthropoda"): ("Fooida", "WoRMS")})
    lineage = f"{E}|phylum:Arthropoda|class:Ostracoda|genus:Foo|species:Foo bar"
    assert bc.tree_path(lineage, fixes, {}) == "Animalia|Arthropoda|Ostracoda|Fooida|Fooidae|Foo|Foo bar"


def test_confirmed_order_known_to_col_brings_its_own_lineage():
    # Fossil turtle family COL gives no phylum: Testudines must not become a child of Animalia.
    fixes = bc.Fixes(family={}, order={("Foochelyidae", ""): ("Testudines", "PaleoBioDB")})
    known = {"Testudines": [f"{E}|phylum:Chordata|class:Reptilia|order:Testudines"]}
    lineage = f"{E}|family:Foochelyidae|genus:Foochelys|species:Foochelys bar"
    assert bc.tree_path(lineage, fixes, known) == "Animalia|Chordata|Reptilia|Testudines|Foochelyidae|Foochelys|Foochelys bar"


def test_order_fix_is_refused_if_col_places_that_order_elsewhere():
    fixes = bc.Fixes(family={}, order={("Foornis", "Chordata"): ("Saurischia", "PaleoBioDB")})
    known = {"Saurischia": [f"{E}|phylum:Chordata|superorder:Dinosauria|order:Saurischia"]}
    lineage = f"{E}|phylum:Chordata|class:Aves|genus:Foornis|species:Foornis bar"
    assert bc.tree_path(lineage, fixes, known) == "Animalia|Chordata|Aves|Foornis|Foornis bar"


def test_genus_lineage_stops_at_the_genus():
    assert bc.genus_lineage(f"{E}|family:F|genus:G|subgenus:S|species:G s") == f"{E}|family:F|genus:G"
    assert bc.genus_lineage(f"{E}|family:F") is None


def test_species_col_leaves_blank_inherits_its_genus_being_extinct(tmp_path):
    col = sqlite3.connect(tmp_path / "col.db")
    col.executescript(import_col.SCHEMA)
    base = f"{E}|phylum:Chordata|class:Aves"
    col.executemany(
        "INSERT INTO name_usage (id, status, rank, scientific_name, lineage, extinct) VALUES (?, 'accepted', ?, ?, ?, ?)",
        [("K", "kingdom", "Animalia", E, None), ("P", "phylum", "Chordata", f"{E}|phylum:Chordata", None),
         ("C", "class", "Aves", base, None),
         ("G1", "genus", "Gone", f"{base}|genus:Gone", 1), ("G2", "genus", "Here", f"{base}|genus:Here", None),
         ("S1", "species", "Gone blank", f"{base}|genus:Gone|species:Gone blank", None),
         ("S2", "species", "Gone alive", f"{base}|genus:Gone|species:Gone alive", 0),
         ("S3", "species", "Here blank", f"{base}|genus:Here|species:Here blank", None)],
    )
    col.commit()
    col.close()
    old = sqlite3.connect(tmp_path / "old.db")
    old.executescript("CREATE TABLE species (scientific_name TEXT PRIMARY KEY, taxon_path TEXT, taxon_rank TEXT, common_names TEXT, taxonomic_status TEXT)")
    old.close()
    bc.build(str(tmp_path / "col.db"), str(tmp_path / "old.db"), str(tmp_path / "new.db"), bc.Fixes({}, {}))
    conn = sqlite3.connect(tmp_path / "new.db")
    flags = dict(conn.execute("SELECT scientific_name, extinct FROM species WHERE taxon_rank = 'species'"))
    conn.close()
    assert flags == {"Gone blank": 1, "Gone alive": 0, "Here blank": None}


def test_fix_is_refused_if_it_would_change_a_level_col_states():
    # COL puts the genus in Ophiurida but the family in Ophiacanthida: leave COL as it is.
    lineage = f"{E}|phylum:Echinodermata|class:Ophiuroidea|order:Ophiurida|genus:Ophiolancea|species:Ophiolancea s"
    fixes = bc.Fixes(family={("Ophiolancea", "Echinodermata"): ("Ophiacanthidae", "WoRMS")}, order={})
    families = {"Ophiacanthidae": [f"{E}|phylum:Echinodermata|class:Ophiuroidea|order:Ophiacanthida|family:Ophiacanthidae"]}
    assert bc.tree_path(lineage, fixes, families) == "Animalia|Echinodermata|Ophiuroidea|Ophiurida|Ophiolancea|Ophiolancea s"


def test_synonym_sits_beside_its_accepted_taxon():
    accepted = "Animalia|Chordata|Mammalia|Perissodactyla|Tapiridae|Acrocodia|Acrocodia indica"
    assert bc.synonym_path(accepted, "Tapirus indicus") == (
        "Animalia|Chordata|Mammalia|Perissodactyla|Tapiridae|Acrocodia|Tapirus indicus"
    )


def _old(path="Animalia|Chordata|Mammalia|Carnivora|Felidae|Panthera|Panthera leo", rank="species", **extra):
    return {"taxon_path": path, "taxon_rank": rank, **extra}


@pytest.mark.parametrize("new_path,new_rank,old,same", [
    ("Animalia|Chordata|Mammalia|Carnivora|Felidae|Panthera|Panthera leo", "species", _old(), True),
    # Moved within the phylum: still the same animal.
    ("Animalia|Chordata|Reptilia|Squamata|Lacertidae|Foo|Foo bar", "species",
     _old("Animalia|Chordata|Squamata|Lacertidae|Foo|Foo bar"), True),
    # "Zebra": an old snail genus in GBIF, a horse synonym in COL.
    ("Animalia|Chordata|Mammalia|Perissodactyla|Equidae|Zebra", "genus",
     _old("Animalia|Mollusca|Gastropoda|Stylommatophora|Orthalicidae|Zebra", "genus"), False),
    ("Plantae|Tracheophyta|Asterales|Abelia", "genus", _old("Animalia|Arthropoda|Insecta|Abelia", "genus"), False),
    ("Animalia|Arthropoda|Insecta|Coleoptera|Foo", "genus",
     _old("Animalia|Arthropoda|Insecta|Coleoptera|Foo", "family"), False),
])
def test_same_taxon_guards_data_against_homonyms(new_path, new_rank, old, same):
    assert bc.same_taxon(new_path, new_rank, old) is same


def test_col_extinct_value_is_used_with_its_source():
    updates = bc.extinct_update(col_extinct=1, old={"extinct": None, "iucn_status": None, "trait_sources": None})
    assert updates["extinct"] == 1
    assert json.loads(updates["trait_sources"])["extinct"] == {"source": "Catalogue of Life", "estimated": False}


def test_col_extinct_does_not_override_a_living_iucn_status():
    updates = bc.extinct_update(col_extinct=1, old={"extinct": 0, "iucn_status": "LC", "trait_sources": None})
    assert updates == {"extinct": 0}


@pytest.mark.parametrize("before", [None, 0])
def test_iucn_extinct_marks_the_row_extinct(before):
    values = {"iucn_status": "EX", "extinct": before, "trait_sources": None}
    bc.apply_iucn_extinct(values)
    assert values["extinct"] == 1
    assert json.loads(values["trait_sources"])["extinct"] == {"source": "IUCN Red List", "estimated": False}


@pytest.mark.parametrize("status", [None, "LC", "EW", "CR"])
def test_other_iucn_statuses_leave_the_flag_alone(status):
    values = {"iucn_status": status, "extinct": None, "trait_sources": None}
    bc.apply_iucn_extinct(values)
    assert values == {"iucn_status": status, "extinct": None, "trait_sources": None}


def test_iucn_extinct_keeps_an_existing_extinct_source():
    sources = '{"extinct": {"source": "Catalogue of Life", "estimated": false}}'
    values = {"iucn_status": "EX", "extinct": 1, "trait_sources": sources}
    bc.apply_iucn_extinct(values)
    assert values["trait_sources"] == sources


def test_flag_derived_from_the_old_tree_is_not_carried():
    # "All species extinct" was true of the old group, not necessarily of the new one.
    sources = json.dumps({"extinct": {"source": "Derived: all 6 accepted species extinct", "estimated": False}})
    updates = bc.extinct_update(col_extinct=None, old={"extinct": 1, "iucn_status": None, "trait_sources": sources})
    assert updates["extinct"] is None
    assert "extinct" not in json.loads(updates["trait_sources"])


def test_flag_stays_when_col_is_silent():
    sources = json.dumps({"extinct": {"source": "GBIF (Paleobiology)", "estimated": False}})
    assert bc.extinct_update(col_extinct=None, old={"extinct": 1, "iucn_status": None, "trait_sources": sources})["extinct"] == 1


def test_common_names_keep_reviewed_first_name_and_add_cols():
    assert bc.merge_common_names(["Mammals", "Mammal"], ["mammals", "Beasts"]) == ["Mammals", "Mammal", "Beasts"]


# ── Whole build on a small real ColDP-shaped database ─────────────────────────

CAT = f"{E}|phylum:Chordata|class:Mammalia|order:Carnivora|family:Felidae|genus:Panthera|species:Panthera leo"
RED = f"{E}|phylum:Chordata|class:Mammalia|order:Perissodactyla|family:Tapiridae|genus:Acrocodia|species:Acrocodia indica"
USAGES = [
    ("D1", None, "accepted", "domain", "Eukaryota", "domain:Eukaryota", None, 0),
    ("K1", "D1", "accepted", "kingdom", "Animalia", E, None, 0),
    ("P1", "K1", "accepted", "phylum", "Chordata", f"{E}|phylum:Chordata", None, 0),
    ("V1", "P1", "accepted", "subphylum", "Vertebrata", f"{E}|phylum:Chordata|subphylum:Vertebrata", None, 0),
    ("C1", "V1", "accepted", "class", "Mammalia", f"{E}|phylum:Chordata|class:Mammalia", None, 0),
    ("O1", "C1", "accepted", "order", "Carnivora", f"{E}|phylum:Chordata|class:Mammalia|order:Carnivora", None, 0),
    ("F1", "O1", "accepted", "family", "Felidae", f"{E}|phylum:Chordata|class:Mammalia|order:Carnivora|family:Felidae", None, 0),
    ("G1", "F1", "accepted", "genus", "Panthera", f"{E}|phylum:Chordata|class:Mammalia|order:Carnivora|family:Felidae|genus:Panthera", None, 0),
    ("S1", "G1", "accepted", "species", "Panthera leo", CAT, 0, 0),
    ("MOTH", "G9", "synonym", "genus", "Panthera", f"{E}|phylum:Arthropoda|genus:Pantherodes", None, 0),
    ("T1", "F2", "accepted", "species", "Acrocodia indica", RED, 0, 0),
    ("F2", "O2", "accepted", "family", "Tapiridae", f"{E}|phylum:Chordata|class:Mammalia|order:Perissodactyla|family:Tapiridae", None, 0),
    ("O2", "C1", "accepted", "order", "Perissodactyla", f"{E}|phylum:Chordata|class:Mammalia|order:Perissodactyla", None, 0),
    ("G2", "F2", "accepted", "genus", "Acrocodia", f"{E}|phylum:Chordata|class:Mammalia|order:Perissodactyla|family:Tapiridae|genus:Acrocodia", None, 0),
    ("SYN", "T1", "synonym", "species", "Tapirus indicus", RED, None, 0),
    ("BOLD", "G1", "accepted", "unranked", "BOLD:AAA0001", CAT, None, 1),
    ("PL1", None, "accepted", "kingdom", "Plantae", "domain:Eukaryota|kingdom:Plantae", None, 0),
    ("PG", "PL1", "accepted", "genus", "Acrocodia", "domain:Eukaryota|kingdom:Plantae|genus:Acrocodia", None, 1),
    ("PS", "PG", "accepted", "species", "Acrocodia herba", "domain:Eukaryota|kingdom:Plantae|genus:Acrocodia|species:Acrocodia herba", None, 1),
]


@pytest.fixture
def built(tmp_path):
    col = sqlite3.connect(tmp_path / "col.db")
    col.executescript(import_col.SCHEMA)
    col.executemany(
        "INSERT INTO name_usage (id, parent_id, status, rank, scientific_name, lineage, extinct, merged) VALUES (?,?,?,?,?,?,?,?)",
        USAGES,
    )
    col.execute("INSERT INTO vernacular (taxon_id, name, language) VALUES ('S1', 'lion', 'eng'), ('S1', 'leeuw', 'nld')")
    col.commit()
    col.close()

    old = sqlite3.connect(tmp_path / "old.db")
    old.executescript("""CREATE TABLE species (scientific_name TEXT PRIMARY KEY, taxon_path TEXT, taxon_rank TEXT,
        common_names TEXT, taxonomic_status TEXT, body_mass REAL, body_length REAL, max_lifespan REAL, metabolic_rate REAL,
        reproduction_strategy TEXT, geo_bounding_box TEXT, habitat_type TEXT, elevation_limits TEXT, trophic_level TEXT,
        activity_period TEXT, iucn_status TEXT, population_trend TEXT, primary_image_url TEXT, image_attribution TEXT,
        wikipedia_abstract TEXT, taxon_depth INTEGER, trait_sources TEXT, extinct INTEGER)""")
    rows = [
        ("Panthera leo", "Animalia|Chordata|Mammalia|Carnivora|Felidae|Panthera|Panthera leo", "species", '["Lion"]', "ACCEPTED",
         "VU", "http://lion.jpg", "abstract about lions", None, None),
        # In GBIF under the old name; in COL a synonym of Acrocodia indica.
        ("Tapirus indicus", "Animalia|Chordata|Mammalia|Perissodactyla|Tapiridae|Tapirus|Tapirus indicus", "species", '["Malayan tapir"]',
         "ACCEPTED", "EN", "http://tapir.jpg", None, None, None),
        ("Fossilus antiquus", "Animalia|Chordata|Mammalia|Fossilidae|Fossilus|Fossilus antiquus", "species", "[]", "ACCEPTED",
         None, None, None, None, 1),
        ("Junk synonym", "Animalia|Chordata|Junk|Junk synonym", "species", "[]", "SYNONYM", None, None, None, None, None),
        ("Oldname withdata", "Animalia|Chordata|Oldname|Oldname withdata", "species", "[]", "SYNONYM", "LC", None, None, None, None),
    ]
    old.executemany(
        "INSERT INTO species (scientific_name, taxon_path, taxon_rank, common_names, taxonomic_status, iucn_status, "
        "primary_image_url, wikipedia_abstract, trait_sources, extinct) VALUES (?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    old.commit()
    old.close()

    target = tmp_path / "new.db"
    summary = bc.build(str(tmp_path / "col.db"), str(tmp_path / "old.db"), str(target), bc.Fixes({}, {}))
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    yield conn, summary
    conn.close()


def _row(conn, name):
    row = conn.execute("SELECT * FROM species WHERE scientific_name = ?", (name,)).fetchone()
    return dict(row) if row else None


def test_build_marks_iucn_extinct_rows_extinct(tmp_path):
    col = sqlite3.connect(tmp_path / "col.db")
    col.executescript(import_col.SCHEMA)
    base = "domain:Eukaryota|kingdom:Animalia|phylum:Chordata|class:Mammalia|order:Rodentia|family:Muridae|genus:Melomys"
    col.executemany(
        "INSERT INTO name_usage (id, parent_id, status, rank, scientific_name, lineage, extinct, merged) VALUES (?,?,?,?,?,?,?,?)",
        [("A", None, "accepted", "species", "Melomys rubicola", f"{base}|species:Melomys rubicola", 0, 0),
         ("B", None, "accepted", "species", "Melomys accepted", f"{base}|species:Melomys accepted", None, 0),
         ("C", "B", "synonym", "species", "Melomys oldname", f"{base}|species:Melomys accepted", None, 0)],
    )
    col.commit()
    col.close()
    old = sqlite3.connect(tmp_path / "old.db")
    old.executescript("""CREATE TABLE species (scientific_name TEXT PRIMARY KEY, taxon_path TEXT, taxon_rank TEXT,
        common_names TEXT, taxonomic_status TEXT, iucn_status TEXT, trait_sources TEXT, extinct INTEGER)""")
    old.executemany("INSERT INTO species VALUES (?,?,?,?,?,?,?,?)", [
        ("Melomys rubicola", "Animalia|Chordata|Melomys|Melomys rubicola", "species", "[]", "ACCEPTED", "EX", None, None),
        ("Melomys oldname", "Animalia|Chordata|Melomys|Melomys oldname", "species", "[]", "ACCEPTED", "EX", None, None),
        ("Fossilus gone", "Animalia|Chordata|Fossilus|Fossilus gone", "species", "[]", "ACCEPTED", "EX", None, None),
    ])
    old.commit()
    old.close()
    bc.build(str(tmp_path / "col.db"), str(tmp_path / "old.db"), str(tmp_path / "new.db"), bc.Fixes({}, {}))
    conn = sqlite3.connect(tmp_path / "new.db")
    conn.row_factory = sqlite3.Row
    assert _row(conn, "Melomys rubicola")["extinct"] == 1  # beats COL saying living
    assert _row(conn, "Melomys accepted")["extinct"] == 1  # status filled from its synonym
    assert _row(conn, "Melomys oldname")["extinct"] == 1
    assert _row(conn, "Fossilus gone")["extinct"] == 1  # outside the tree too
    conn.close()


def test_land_snail_family_moves_under_its_order():
    lineage = ("domain:Eukaryota|kingdom:Animalia|phylum:Mollusca|class:Gastropoda|subclass:Heterobranchia"
               "|infraorder:Helicoidei|family:Helicidae|genus:Helix|species:Helix pomatia")
    fixes = bc.Fixes({}, {("Helicidae", "Mollusca"): ("Stylommatophora", "IRMNG,NCBI,WoRMS,iNaturalist")})
    assert bc.tree_path(lineage, fixes, {}) == "Animalia|Mollusca|Gastropoda|Stylommatophora|Helicidae|Helix|Helix pomatia"


def test_data_carries_across_by_name(built):
    conn, _ = built
    lion = _row(conn, "Panthera leo")
    assert (lion["iucn_status"], lion["primary_image_url"], lion["wikipedia_abstract"]) == ("VU", "http://lion.jpg", "abstract about lions")
    assert lion["taxon_path"] == "Animalia|Chordata|Mammalia|Carnivora|Felidae|Panthera|Panthera leo"
    assert json.loads(lion["common_names"]) == ["Lion"]
    assert lion["extinct"] == 0
    assert lion["col_id"] == "S1"


def test_synonym_data_also_fills_the_accepted_species(built):
    conn, summary = built
    assert _row(conn, "Acrocodia indica")["iucn_status"] == "EN"
    assert _row(conn, "Acrocodia indica")["primary_image_url"] == "http://tapir.jpg"
    syn = _row(conn, "Tapirus indicus")
    assert syn["taxonomic_status"] == "SYNONYM"
    assert syn["accepted_name"] == "Acrocodia indica"
    assert syn["iucn_status"] == "EN"
    assert summary["filled_from_synonym"] == 1


def test_fossil_col_lacks_stays_in_the_db_but_out_of_the_tree(built):
    conn, summary = built
    fossil = _row(conn, "Fossilus antiquus")
    assert fossil["taxonomic_status"] == "GBIF_ONLY"
    assert fossil["taxon_path"] is None
    assert fossil["gbif_taxon_path"] == "Animalia|Chordata|Mammalia|Fossilidae|Fossilus|Fossilus antiquus"
    assert fossil["extinct"] == 1
    assert summary["gbif_only_kept"] == 2


def test_gbif_only_synonym_is_kept_only_with_data(built):
    conn, _ = built
    assert _row(conn, "Junk synonym") is None
    assert _row(conn, "Oldname withdata")["iucn_status"] == "LC"


def test_dna_clusters_are_not_imported(built):
    conn, summary = built
    assert _row(conn, "BOLD:AAA0001") is None
    assert summary["dna_clusters_skipped"] == 1


def test_accepted_animal_beats_a_synonym_of_the_same_name(built):
    conn, _ = built
    assert _row(conn, "Panthera")["taxonomic_status"] == "ACCEPTED"
    assert _row(conn, "Panthera")["taxon_path"].endswith("Felidae|Panthera")


def test_accepted_homonym_keeps_a_row_so_its_tree_branch_stays_reachable(built):
    conn, _ = built
    animal = _row(conn, "Acrocodia")
    assert animal["taxon_path"].startswith("Animalia")
    rows = conn.execute("SELECT scientific_name FROM species WHERE taxon_path = 'Plantae|Acrocodia'").fetchall()
    assert [r[0] for r in rows] == ["Acrocodia [Plantae]"]
    assert _row(conn, "Acrocodia herba")["taxon_path"] == "Plantae|Acrocodia|Acrocodia herba"


def test_intermediate_rank_with_no_tree_role_has_no_path(built):
    conn, _ = built
    vertebrata = _row(conn, "Vertebrata")
    assert vertebrata["taxon_path"] is None
    assert vertebrata["taxonomic_status"] == "ACCEPTED"


def test_taxon_depth_is_stored(built):
    conn, _ = built
    assert _row(conn, "Panthera leo")["taxon_depth"] == 6


def test_every_tree_path_has_rows_for_all_its_ancestors(built):
    conn, summary = built
    assert summary["paths_missing_a_node"] == 0


def test_fixed_group_gets_a_node_row_and_an_audit_record(tmp_path):
    col = sqlite3.connect(tmp_path / "col.db")
    col.executescript(import_col.SCHEMA)
    col.executemany(
        "INSERT INTO name_usage (id, parent_id, status, rank, scientific_name, lineage) VALUES (?,?,?,?,?,?)",
        [("K", None, "accepted", "kingdom", "Animalia", E),
         ("P", "K", "accepted", "phylum", "Mollusca", f"{E}|phylum:Mollusca"),
         ("C", "P", "accepted", "class", "Gastropoda", f"{E}|phylum:Mollusca|class:Gastropoda"),
         ("I", "C", "accepted", "infraorder", "Helicoidei", f"{E}|phylum:Mollusca|class:Gastropoda|infraorder:Helicoidei"),
         ("G", "I", "accepted", "genus", "Acusta", f"{E}|phylum:Mollusca|class:Gastropoda|infraorder:Helicoidei|genus:Acusta"),
         ("S", "G", "accepted", "species", "Acusta ravida", SNAIL)],
    )
    col.commit()
    col.close()
    old = sqlite3.connect(tmp_path / "old.db")
    old.executescript("CREATE TABLE species (scientific_name TEXT PRIMARY KEY, taxon_path TEXT, taxon_rank TEXT, common_names TEXT, taxonomic_status TEXT)")
    old.close()
    summary = bc.build(str(tmp_path / "col.db"), str(tmp_path / "old.db"), str(tmp_path / "new.db"),
                       bc.Fixes(family={("Acusta", "Mollusca"): ("Camaenidae", "WoRMS")}, order={}))
    conn = sqlite3.connect(tmp_path / "new.db")
    conn.row_factory = sqlite3.Row
    node = _row(conn, "Camaenidae")
    assert node["taxon_rank"] == "family"
    assert node["taxon_path"] == "Animalia|Mollusca|Gastropoda|Helicoidei|Camaenidae"
    assert node["taxonomic_status"] == "ACCEPTED"
    audit = dict(conn.execute("SELECT * FROM taxon_fixes").fetchone())
    assert (audit["level"], audit["grp"], audit["value"], audit["sources"]) == ("family", "Acusta", "Camaenidae", "WoRMS")
    assert summary["fixes_applied"] == 1
    assert summary["paths_missing_a_node"] == 0
    conn.close()


def test_row_key_is_unique_even_for_same_name_and_parent():
    taken = {"Foo"}
    first = bc.unique_key("Foo", "Animalia|Chordata|Bar|Foo", taken)
    second = bc.unique_key("Foo", "Animalia|Mollusca|Bar|Foo", taken)
    assert first == "Foo [Bar]"
    assert second == "Foo [Animalia|Mollusca|Bar|Foo]"
    assert bc.unique_key("Baz", "Animalia|Baz", taken) == "Baz"
    assert taken == {"Foo", "Foo [Bar]", "Foo [Animalia|Mollusca|Bar|Foo]", "Baz"}


def test_homonyms_with_same_named_parents_and_a_fix_node_all_get_rows(tmp_path):
    col = sqlite3.connect(tmp_path / "col.db")
    col.executescript(import_col.SCHEMA)
    a = f"{E}|phylum:Mollusca"
    b = f"{E}|phylum:Annelida"
    c = f"{E}|phylum:Bryozoa"
    col.executemany(
        "INSERT INTO name_usage (id, status, rank, scientific_name, lineage) VALUES (?, 'accepted', ?, ?, ?)",
        [("K", "kingdom", "Animalia", E),
         ("PA", "phylum", "Mollusca", a), ("PB", "phylum", "Annelida", b), ("PC", "phylum", "Bryozoa", c),
         ("BA", "class", "Bar", f"{a}|class:Bar"), ("BB", "class", "Bar", f"{b}|class:Bar"), ("BC", "class", "Bar", f"{c}|class:Bar"),
         ("F1", "family", "Foo", f"{a}|class:Bar|family:Foo"),
         ("F2", "family", "Foo", f"{b}|class:Bar|family:Foo"),
         ("G", "genus", "Gen", f"{c}|class:Bar|genus:Gen")],
    )
    col.commit()
    col.close()
    old = sqlite3.connect(tmp_path / "old.db")
    old.executescript("CREATE TABLE species (scientific_name TEXT PRIMARY KEY, taxon_path TEXT, taxon_rank TEXT, common_names TEXT, taxonomic_status TEXT)")
    old.close()
    fixes = bc.Fixes(family={("Gen", "Bryozoa"): ("Baz", "WoRMS")}, order={})
    summary = bc.build(str(tmp_path / "col.db"), str(tmp_path / "old.db"), str(tmp_path / "new.db"), fixes)
    conn = sqlite3.connect(tmp_path / "new.db")
    paths = {r[0] for r in conn.execute("SELECT taxon_path FROM species WHERE taxon_rank = 'family'")}
    conn.close()
    assert paths == {"Animalia|Mollusca|Bar|Foo", "Animalia|Annelida|Bar|Foo", "Animalia|Bryozoa|Bar|Baz"}
    assert summary["paths_missing_a_node"] == 0


def test_only_confirmed_verdicts_become_fixes(tmp_path):
    verdicts = tmp_path / "verdicts.tsv"
    rows = [
        ("level", "group", "gbif_value", "phylum", "species", "verdict", "agree", "disagree"),
        ("family", "Acusta", "Camaenidae", "Mollusca", "3", "confirmed", "WoRMS,NCBI", ""),
        ("order", "Julidae", "Julida", "Arthropoda", "9", "confirmed", "IRMNG", ""),
        ("family", "Trichobius", "Hippoboscidae", "Arthropoda", "71", "conflict", "IRMNG", "NCBI=Streblidae"),
        ("order", "Helicidae", "Stylommatophora", "Mollusca", "497", "majority", "IRMNG,NCBI", "ITIS=Helicida"),
        ("order", "Eimeria", "Columbiformes", "", "16", "no_evidence", "", ""),
    ]
    verdicts.write_text("".join("\t".join(r) + "\n" for r in rows), encoding="utf-8")
    fixes = bc.load_fixes(verdicts)
    assert fixes.family == {("Acusta", "Mollusca"): ("Camaenidae", "WoRMS,NCBI")}
    assert fixes.order == {("Julidae", "Arthropoda"): ("Julida", "IRMNG"),
                           ("Helicidae", "Mollusca"): ("Stylommatophora", "IRMNG,NCBI")}


def test_existing_target_is_refused(tmp_path):
    target = tmp_path / "species.db"
    target.write_bytes(b"precious")
    with pytest.raises(FileExistsError):
        bc.build("x", "y", str(target), bc.Fixes({}, {}))
    assert target.read_bytes() == b"precious"


def test_a_rebuild_carries_the_pictures_the_user_rejected():
    assert "rejected_images" in bc._CARRIED and "rejected_images" in bc._COLUMNS
    assert bc._old_row_fields({"rejected_images": '["https://w/snake.jpg"]'}) == \
        {"rejected_images": '["https://w/snake.jpg"]'}
