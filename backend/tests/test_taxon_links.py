"""Tests for taxon_links.py (subject_names gives item texts; subject_rows resolves them to keys) — the chat's subjects and where the answer mentions them."""

from app import taxon_queries
from app.taxon_links import subject_names
from tests.test_llm_agent import (_EAGLE_OWL, _LION_RESULT, _SPOTTED, _STRIGIDAE_ROW, _STRIGIFORMES,
                                  _rank, _stats, _taxonomy)


# ── Task 1: subject names from tool output ────────────────────────────────────

def test_lookup_subject_is_the_species():
    assert subject_names("lookup_species", _LION_RESULT) == ["Panthera leo"]


def test_find_species_subject_is_the_first_match_only(monkeypatch):
    from app.llm_agent import find_species
    milesi = dict(_EAGLE_OWL, scientific_name="Bubo milesi", common_names="[]",
                  taxon_path="Animalia|Chordata|Aves|Strigiformes|Strigidae|Bubo|Bubo milesi")
    monkeypatch.setattr(taxon_queries, "find_matches", lambda name, limit=5: [_EAGLE_OWL, milesi])
    out = find_species.invoke({"name": "eagle owl"})
    assert subject_names("find_species", out) == ["Bubo bubo"]


def test_ranking_subjects_are_the_entries_not_the_group(monkeypatch):
    out, _ = _rank(monkeypatch)
    assert subject_names("rank_species_by_trait", out) == ["Bubo bubo (Eurasian eagle-owl)", "Tyto alba"]


def test_group_stats_subject_is_the_group_not_the_examples(monkeypatch):
    out = _stats(monkeypatch)
    assert subject_names("group_stats", out) == ["Strigiformes (Owls, order)"]


def test_taxonomy_subjects_are_subject_members_and_relatives(monkeypatch):
    mammalia = {"scientific_name": "Mammalia", "taxon_rank": "class", "common_names": '["Mammals"]',
                "taxon_path": "Animalia|Chordata|Mammalia"}
    carnivora = {"scientific_name": "Carnivora", "taxon_rank": "order", "common_names": '["Carnivores"]'}
    cetacea = {"scientific_name": "Cetacea", "taxon_rank": "order", "common_names": "[]"}
    group_out, _ = _taxonomy(monkeypatch, mammalia, (2, [carnivora, cetacea]), ranks={"order": 2})
    assert subject_names("taxonomy_of", group_out) == ["Mammalia (Mammals, class)", "Carnivora (Carnivores)", "Cetacea"]

    perdita = {"scientific_name": "Strix perdita", "taxon_rank": "species", "common_names": '["Lost owl"]'}
    species_out, _ = _taxonomy(monkeypatch, _SPOTTED, (2, [_SPOTTED, perdita]))
    names = subject_names("taxonomy_of", species_out)
    assert names == ["Strix occidentalis (Spotted owl, species)", "Strix perdita (Lost owl)"]
    assert "Chordata" not in names and "Strigidae" not in names


def test_taxonomy_without_members_has_only_the_subject(monkeypatch):
    out, _ = _taxonomy(monkeypatch, _STRIGIDAE_ROW, ranks={})
    assert subject_names("taxonomy_of", out) == ["Strigidae (Owls, family)"]


def test_semantic_search_subjects():
    out = ("- **Moloch horridus** (Thorny devil) [species]\n  A lizard.\n"
           "- **Bubo bubo** (no common name) [species]\n  x")
    assert subject_names("semantic_search_species", out) == ["Moloch horridus", "Bubo bubo"]


def test_no_subjects_for_failures_and_images():
    assert subject_names("lookup_species", "DATABASE RESULT: No species found with scientific name 'X'.") == []
    assert subject_names("get_species_image", '{"url": "u"}') == []
    assert subject_names("rank_species_by_trait", "DATABASE RESULT: No species in X has a recorded mass.") == []
    assert subject_names("lookup_species", "") == []


def test_homonym_key_is_kept_whole():
    out = ("DATABASE RESULT: FOUND — top 1 by max lifespan among 3 species in X with a recorded max lifespan.\n"
           "- #1 Bubo [Strigidae] (Eagle-owls): 5 years")
    assert subject_names("rank_species_by_trait", out) == ["Bubo [Strigidae] (Eagle-owls)"]


def test_duplicates_are_dropped():
    out = "- **Bubo bubo** (x) [species]\n  a\n- **Bubo bubo** (x) [species]\n  b"
    assert subject_names("semantic_search_species", out) == ["Bubo bubo"]


# ── Task 2: subject rows and matching in the answer ───────────────────────────

import pytest
from app import database
from app.taxon_links import match_links, subject_rows

_KOALA = {"scientific_name": "Phascolarctos cinereus", "taxon_path": "Animalia|Chordata|Phascolarctos cinereus",
          "taxon_rank": "species", "common_names": '["Koala", "Koala bear"]'}


def test_common_name_plural_possessive_and_case():
    links = match_links("Database: Koalas eat eucalyptus. The koala's diet is narrow.", [_KOALA])
    assert [l["text"] for l in links] == ["Koalas", "koala"]
    assert {l["scientific_name"] for l in links} == {"Phascolarctos cinereus"}
    assert links[0] == {"text": "Koalas", "scientific_name": "Phascolarctos cinereus",
                        "taxon_path": _KOALA["taxon_path"], "taxon_rank": "species"}


def test_es_plural():
    row = {"scientific_name": "Vulpes vulpes", "taxon_path": "p", "taxon_rank": "species",
           "common_names": '["Red fox"]'}
    assert [l["text"] for l in match_links("Red foxes and a red fox.", [row])] == ["Red foxes", "red fox"]


def test_scientific_name_exact_case_only():
    assert match_links("phascolarctos cinereus", [_KOALA]) == []
    assert match_links("(*Phascolarctos cinereus*)", [_KOALA])[0]["text"] == "Phascolarctos cinereus"


def test_longest_match_wins_and_word_boundaries():
    assert [l["text"] for l in match_links("The Koala bear. Koalabear.", [_KOALA])] == ["Koala bear"]


def test_no_match_inside_a_longer_scientific_name():
    genus = {"scientific_name": "Panthera", "taxon_path": "p", "taxon_rank": "genus", "common_names": "[]"}
    uncia = {"scientific_name": "Panthera uncia", "taxon_path": "p|u", "taxon_rank": "species",
             "common_names": '["Snow leopard"]'}
    links = match_links("Panthera uncia is in Panthera.", [genus, uncia])
    assert [(l["text"], l["scientific_name"]) for l in links] == [
        ("Panthera uncia", "Panthera uncia"), ("Panthera", "Panthera")]


def test_unmentioned_subject_and_other_animals_get_no_link():
    whale = {"scientific_name": "Balaenoptera musculus", "taxon_path": "p", "taxon_rank": "species",
             "common_names": '["Blue whale"]'}
    links = match_links("Database: The blue whale eats krill.", [whale, _KOALA])
    assert [l["text"] for l in links] == ["blue whale"]


def test_homonym_key_matches_its_plain_name():
    row = {"scientific_name": "Bubo [Strigidae]", "taxon_path": "p", "taxon_rank": "genus", "common_names": "[]"}
    assert match_links("The genus Bubo.", [row]) == [
        {"text": "Bubo", "scientific_name": "Bubo [Strigidae]", "taxon_path": "p", "taxon_rank": "genus"}]


def test_names_with_regex_characters_match_literally():
    row = {"scientific_name": "Lachenalia x", "taxon_path": "p", "taxon_rank": "species",
           "common_names": '["Lutzeyer\u2019s lachenalia", "a+b (c)"]'}
    assert [l["text"] for l in match_links("Lutzeyer\u2019s lachenalia and a+b (c).", [row])] == \
        ["Lutzeyer\u2019s lachenalia", "a+b (c)"]


def test_short_common_names_and_empty_input_are_ignored():
    row = {"scientific_name": "Ox x", "taxon_path": "p", "taxon_rank": "species", "common_names": '["Ox", ""]'}
    assert match_links("An ox.", [row]) == []
    assert match_links("", [_KOALA]) == [] and match_links("Koala", []) == []


def test_null_path_and_bad_common_names():
    row = {"scientific_name": "Gbif onlyus", "taxon_path": None, "taxon_rank": "species", "common_names": None}
    assert match_links("Gbif onlyus lives.", [row]) == [
        {"text": "Gbif onlyus", "scientific_name": "Gbif onlyus", "taxon_path": None, "taxon_rank": "species"}]


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    conn = database.get_connection()
    for name in ("Bubo bubo", "Tyto alba", "Strix aluco"):
        conn.execute("INSERT INTO species (scientific_name, taxon_path, taxon_rank, common_names) "
                     "VALUES (?, ?, 'species', '[]')", (name, "Animalia|" + name))
    conn.commit()
    conn.close()


def test_subject_rows_by_primary_key_in_order(isolated_db):
    assert [r["scientific_name"] for r in subject_rows(["Tyto alba", "Nope", "Bubo bubo"])] == \
        ["Tyto alba", "Bubo bubo"]
    assert subject_rows([]) == []
    assert subject_rows(["tyto alba"]) == []   # exact keys only


# ── Final review fixes ────────────────────────────────────────────────────────

def test_subgenus_subject_is_not_cut_to_its_genus(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    conn = database.get_connection()
    for name, rank in (("Aedes", "genus"), ("Aedes (Stegomyia)", "subgenus"), ("Bubo bubo", "species")):
        conn.execute("INSERT INTO species (scientific_name, taxon_path, taxon_rank, common_names) "
                     "VALUES (?, ?, ?, '[]')", (name, "A|" + name, rank))
    conn.commit()
    conn.close()
    out = "DATABASE RESULT: FOUND — Aedes (Stegomyia) is in the database."
    assert [r["scientific_name"] for r in subject_rows(subject_names("lookup_species", out))] ==         ["Aedes (Stegomyia)"]
    out = "DATABASE RESULT: FOUND — statistics for Aedes (Stegomyia) (Tiger mosquitoes, subgenus)."
    assert [r["scientific_name"] for r in subject_rows(subject_names("group_stats", out))] ==         ["Aedes (Stegomyia)"]
    assert [r["scientific_name"] for r in subject_rows(["Bubo bubo (Eurasian eagle-owl)", "Aedes (Nope)"])] ==         ["Bubo bubo", "Aedes"]


def test_a_one_word_common_name_inside_another_animals_name_is_not_linked():
    lion = {"scientific_name": "Panthera leo", "taxon_path": "p", "taxon_rank": "species",
            "common_names": '["Lion", "African lion"]'}
    text = "Database: Lions hunt. Mountain lions and sea-lions are not lions. The lion roars. African lions too."
    assert [l["text"] for l in match_links(text, [lion])] == ["Lions", "lion", "African lions"]


# ── Scientific names anywhere in the answer (the user's call, 2026-11-11) ─────

from app.taxon_links import named_rows


@pytest.fixture
def penguin_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    conn = database.get_connection()
    rows = [("Pygoscelis adeliae", "A|Pygoscelis|Pygoscelis adeliae", "species", "ACCEPTED", '["Adelie penguin"]'),
            ("Aptenodytes forsteri", "A|Aptenodytes|Aptenodytes forsteri", "species", "ACCEPTED", '["Emperor penguin"]'),
            ("Eudyptes chrysocome filholi", "A|E|Eudyptes chrysocome filholi", "subspecies", "ACCEPTED", "[]"),
            ("Spheniscus oldus", "A|S|Spheniscus oldus", "species", "SYNONYM", "[]"),
            ("Gbif onlyus", None, "species", "GBIF_ONLY", "[]"),
            ("Pygoscelis", "A|Pygoscelis", "genus", "ACCEPTED", "[]")]
    conn.executemany("INSERT INTO species (scientific_name, taxon_path, taxon_rank, taxonomic_status, common_names) "
                     "VALUES (?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()


def test_named_rows_finds_species_in_the_tree_by_exact_name(penguin_db):
    text = ("From general knowledge: the Adelie penguin (Pygoscelis adeliae), the Emperor penguin "
            "(*Aptenodytes forsteri*), Eudyptes chrysocome filholi, Spheniscus oldus, Gbif onlyus, "
            "pygoscelis adeliae and the genus Pygoscelis.")
    rows = named_rows(text)
    assert [r["scientific_name"] for r in rows] == \
        ["Pygoscelis adeliae", "Aptenodytes forsteri", "Eudyptes chrysocome filholi"]
    assert all(r["common_names"] == "[]" for r in rows)   # common names link only for looked-up subjects
    assert [l["text"] for l in match_links(text, rows)] == \
        ["Pygoscelis adeliae", "Aptenodytes forsteri", "Eudyptes chrysocome filholi"]


def test_named_rows_without_names(penguin_db):
    assert named_rows("") == [] and named_rows("Penguins live in Antarctica.") == []


def test_semantic_search_with_a_named_species_leads_with_it():
    out = ("DATABASE RESULT: FOUND — Phascolarctos cinereus is in the database.\n"
           "**Phascolarctos cinereus** (species rank)\nEND OF DATABASE RESULT. x\n\n"
           "Other species from semantic search:\n- **Vombatus ursinus** (Wombat) [species]\n  a")
    assert subject_names("semantic_search_species", out) == ["Phascolarctos cinereus", "Vombatus ursinus"]


def test_taxonomy_only_living_species_is_a_subject():
    out = ("DATABASE RESULT: FOUND — classification of Phascolarctidae (Koalas, family).\n"
           "- Lineage: Animalia → Phascolarctidae\n"
           "- Only living species: Phascolarctos cinereus (Koala)\nEND OF DATABASE RESULT.")
    assert subject_names("taxonomy_of", out) == ["Phascolarctidae (Koalas, family)",
                                                 "Phascolarctos cinereus (Koala)"]


def test_species_in_place_subjects():
    out = ("DATABASE RESULT: FOUND — 7 species in snakes (snake families) have a recorded range "
           "overlapping Netherlands (country); showing 2, closest fit first.\n"
           "- Species: Natrix helvetica (Banded Grass Snake); Vipera berus (common adder)\nEND OF DATABASE RESULT.")
    assert subject_names("species_in_place", out) == ["Natrix helvetica (Banded Grass Snake)",
                                                      "Vipera berus (common adder)"]
