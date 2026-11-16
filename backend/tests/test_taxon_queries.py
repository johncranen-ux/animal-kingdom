"""Tests for taxon_queries.py — name resolution, rankings, group stats, lineage."""

import pytest
from app import database, taxon_queries

_OWLS = "Animalia|Chordata|Aves|Strigiformes"
_STRIGIDAE = _OWLS + "|Strigidae"


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Point every test at a fresh temp database."""
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))


def _add(name, path, rank="species", status="ACCEPTED", common="[]", **fields):
    cols = {"scientific_name": name, "taxon_path": path, "taxon_rank": rank,
            "taxonomic_status": status, "common_names": common, **fields}
    conn = database.get_connection()
    conn.execute(f"INSERT INTO species ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                 list(cols.values()))
    conn.commit()
    conn.close()


@pytest.fixture
def seed():
    _add("Animalia", "Animalia", "kingdom")
    _add("Chordata", "Animalia|Chordata", "phylum")
    _add("Aves", "Animalia|Chordata|Aves", "class", common='["Birds"]')
    _add("Strigiformes", _OWLS, "order", common='["Owls", "Owl"]')
    _add("Strigidae", _STRIGIDAE, "family", common='["Owls", "True Owls"]')
    _add("Bubo", _STRIGIDAE + "|Bubo", "genus")
    _add("Bubo bubo", _STRIGIDAE + "|Bubo|Bubo bubo", common='["Eurasian eagle-owl"]',
         max_lifespan=68, iucn_status="LC")
    _add("Tyto", _STRIGIDAE + "|Tyto", "genus")
    _add("Tyto alba", _STRIGIDAE + "|Tyto|Tyto alba", common='["Barn owl"]',
         max_lifespan=34, iucn_status="LC", population_trend="Stable")
    _add("Strix", _STRIGIDAE + "|Strix", "genus")
    _add("Strix occidentalis", _STRIGIDAE + "|Strix|Strix occidentalis",
         common='["Spotted owl"]', iucn_status="NT", population_trend="Decreasing")
    _add("Strix perdita", _STRIGIDAE + "|Strix|Strix perdita", iucn_status="EN")
    _add("Strix fossilis", _STRIGIDAE + "|Strix|Strix fossilis", extinct=1)
    _add("Strix ghost", _STRIGIDAE + "|Strix|Strix ghost", status="SYNONYM", max_lifespan=999)
    _add("Strix orphana", None, status="GBIF_ONLY", max_lifespan=500)
    _add("Plantae", "Plantae", "kingdom")
    _add("Pinus longaeva", "Plantae|Pinophyta|Pinopsida|Pinales|Pinaceae|Pinus|Pinus longaeva",
         max_lifespan=5062)


# ── Task 2: name resolution ───────────────────────────────────────────────────

def test_resolve_taxon_prefers_broadest_group_for_shared_common_name(seed):
    assert taxon_queries.resolve_taxon("owls")["scientific_name"] == "Strigiformes"


def test_resolve_taxon_scientific_name_any_case(seed):
    assert taxon_queries.resolve_taxon("bubo bubo")["scientific_name"] == "Bubo bubo"


def test_resolve_taxon_singular_common_name(seed):
    assert taxon_queries.resolve_taxon("Owl")["scientific_name"] == "Strigiformes"


def test_resolve_taxon_plural_of_a_singular_common_name(seed):
    assert taxon_queries.resolve_taxon("barn owls")["scientific_name"] == "Tyto alba"


def test_resolve_taxon_unknown_is_none(seed):
    assert taxon_queries.resolve_taxon("owlz") is None


def test_resolve_taxon_skips_rows_outside_tree(seed):
    assert taxon_queries.resolve_taxon("Strix orphana") is None


def test_find_matches_skips_synonyms_and_rows_outside_tree(seed):
    names = [r["scientific_name"] for r in taxon_queries.find_matches("Strix")]
    assert names and "Strix ghost" not in names and "Strix orphana" not in names


def test_find_matches_respects_limit(seed):
    assert len(taxon_queries.find_matches("Strix", limit=2)) == 2


# ── Task 3: rankings ──────────────────────────────────────────────────────────

def test_rank_by_trait_highest_within_group(seed):
    n, rows = taxon_queries.rank_by_trait("max_lifespan", _OWLS, True, 10)
    assert [r["scientific_name"] for r in rows] == ["Bubo bubo", "Tyto alba"] and n == 2


def test_rank_by_trait_excludes_synonyms_outside_tree_and_plants(seed):
    _, rows = taxon_queries.rank_by_trait("max_lifespan", "Animalia", True, 10)
    names = {r["scientific_name"] for r in rows}
    assert not names & {"Strix ghost", "Strix orphana", "Pinus longaeva"}
    assert all(r["taxon_path"] for r in rows)


@pytest.fixture
def seed_ranges(seed):
    conn = database.get_connection()
    for name, bbox in (("Bubo bubo", '{"lat_min": -5, "lat_max": 70, "records": 1500}'),
                       ("Tyto alba", '{"lat_min": -40, "lat_max": 60, "lon_min": 1, "lon_max": 2, "records": 1000}'),
                       # a small sample: one stray record can still set its edges
                       ("Strix occidentalis", '{"lat_min": -80, "lat_max": 89, "records": 999}'),
                       # an old raw min/max range (zoo records included), no record count
                       ("Strix perdita", '{"lat_min": -85, "lat_max": 88}'),
                       # broken: no northern edge
                       ("Strix fossilis", '{"lat_min": 0, "records": 5000}'),
                       ("Strix ghost", '{"lat_min": -80, "lat_max": 89}')):
        conn.execute("UPDATE species SET geo_bounding_box = ? WHERE scientific_name = ?", (bbox, name))
    conn.commit()
    conn.close()


def test_rank_by_northern_edge(seed_ranges):
    n, rows = taxon_queries.rank_by_trait("lat_max", _OWLS, True, 10)
    assert n == 2 and [r["scientific_name"] for r in rows] == ["Bubo bubo", "Tyto alba"]
    assert rows[0]["rank_value"] == 70


def test_rank_by_southern_edge_highest_is_furthest_south(seed_ranges):
    n, rows = taxon_queries.rank_by_trait("lat_south", _OWLS, True, 10)
    assert n == 2 and rows[0]["scientific_name"] == "Tyto alba" and rows[0]["rank_value"] == 40


def test_rank_by_trait_existing_column_has_rank_value(seed):
    _, rows = taxon_queries.rank_by_trait("max_lifespan", _OWLS, True, 1)
    assert rows[0]["rank_value"] == 68


def test_range_aliases():
    assert taxon_queries.TRAITS["northernmost"] == ("lat_max", "°")
    assert taxon_queries.TRAITS["furthest_south"] == ("lat_south", "°")
    assert taxon_queries.RANGE_COLUMNS == {"lat_max", "lat_south"}


def test_rank_by_trait_lowest(seed):
    _, rows = taxon_queries.rank_by_trait("max_lifespan", _OWLS, False, 10)
    assert rows[0]["scientific_name"] == "Tyto alba"


def test_rank_by_trait_limit(seed):
    n, rows = taxon_queries.rank_by_trait("max_lifespan", _OWLS, True, 1)
    assert n == 2 and len(rows) == 1


def test_rank_by_trait_no_values(seed):
    assert taxon_queries.rank_by_trait("body_length", _OWLS, True, 10) == (0, [])


def test_rank_by_trait_rejects_unknown_column(seed):
    with pytest.raises(ValueError):
        taxon_queries.rank_by_trait("scientific_name; DROP TABLE species", _OWLS, True, 10)


# ── Task 4: group statistics ──────────────────────────────────────────────────

def test_group_summary_counts_only_accepted_species(seed):
    s = taxon_queries.group_summary(_OWLS)
    assert s["species"] == 5 and s["extinct"] == 1      # Strix ghost (synonym) not counted
    assert s["iucn"] == {"EN": 1, "NT": 1, "LC": 2}
    assert list(s["iucn"]) == ["EN", "NT", "LC"]
    assert s["trends"] == {"Decreasing": 1, "Stable": 1}


def test_group_summary_threatened_examples_most_threatened_first(seed):
    _add("Strix zeta", _STRIGIDAE + "|Strix|Strix zeta", iucn_status="CR")
    _add("Strix alpha", _STRIGIDAE + "|Strix|Strix alpha", iucn_status="VU")
    names = [r["scientific_name"] for r in taxon_queries.group_summary(_OWLS)["threatened"]]
    assert names == ["Strix zeta", "Strix perdita", "Strix alpha"]


def test_group_summary_example_limit(seed):
    _add("Strix zeta", _STRIGIDAE + "|Strix|Strix zeta", iucn_status="CR")
    assert len(taxon_queries.group_summary(_OWLS, examples=1)["threatened"]) == 1


def test_group_summary_empty_group(seed):
    s = taxon_queries.group_summary("Animalia|Chordata|Aves|Strigiformes|Strigidae|Bubo|Bubo bubo")
    assert s == {"species": 0, "extinct": 0, "iucn": {}, "trends": {}, "threatened": []}


# ── Task 5: lineage and members ───────────────────────────────────────────────

def test_lineage_from_kingdom_down_with_common_names(seed):
    nodes = taxon_queries.lineage(_STRIGIDAE + "|Bubo|Bubo bubo")
    assert [n["name"] for n in nodes] == [
        "Animalia", "Chordata", "Aves", "Strigiformes", "Strigidae", "Bubo", "Bubo bubo"]
    assert nodes[3] == {"name": "Strigiformes", "rank": "order", "common": "Owls"}
    assert nodes[1]["common"] == ""


def test_lineage_tolerates_a_level_without_a_row(seed):
    nodes = taxon_queries.lineage("Plantae|Pinophyta|Pinopsida")
    assert [n["name"] for n in nodes] == ["Plantae", "Pinophyta", "Pinopsida"]
    assert nodes[1] == {"name": "Pinophyta", "rank": "", "common": ""}


def test_members_count_and_exclude_synonyms(seed):
    n, rows = taxon_queries.members(_STRIGIDAE + "|Strix")
    names = [r["scientific_name"] for r in rows]
    assert n == 3 and "Strix ghost" not in names
    assert names[0] == "Strix occidentalis"          # common-named first
    assert names[1:] == ["Strix fossilis", "Strix perdita"]


def test_members_direct_children_only_and_limit(seed):
    n, rows = taxon_queries.members(_OWLS, limit=15)
    assert n == 1 and [r["scientific_name"] for r in rows] == ["Strigidae"]
    n, rows = taxon_queries.members(_STRIGIDAE, limit=2)
    assert n == 3 and len(rows) == 2


# ── Review fixes ──────────────────────────────────────────────────────────────

def test_resolve_taxon_groups_only_skips_species(seed):
    assert taxon_queries.resolve_taxon("barn owls")["scientific_name"] == "Tyto alba"
    assert taxon_queries.resolve_taxon("barn owls", groups_only=True) is None
    assert taxon_queries.resolve_taxon("Bubo bubo", groups_only=True) is None
    assert taxon_queries.resolve_taxon("owls", groups_only=True)["scientific_name"] == "Strigiformes"


_REPTILIA = "Animalia|Chordata|Reptilia"


def test_resolve_taxon_prefers_a_first_common_name_one_level_down(seed):
    _add("Squamata", _REPTILIA + "|Squamata", "order", common='["Lizards", "Snakes"]')
    _add("Serpentes", _REPTILIA + "|Squamata|Serpentes", "suborder", common='["Snakes"]')
    _add("Naja naja", _REPTILIA + "|Squamata|Serpentes|Elapidae|Naja|Naja naja")
    assert taxon_queries.resolve_taxon("snakes")["scientific_name"] == "Serpentes"
    assert taxon_queries.resolve_taxon("snake")["scientific_name"] == "Serpentes"


def test_resolve_taxon_ignores_groups_without_species(seed):
    _add("Squamata", _REPTILIA + "|Squamata", "order", common='["Lizards", "Snakes"]')
    _add("Serpentes", _REPTILIA + "|Squamata|Serpentes", "suborder", common='["Snakes"]')
    _add("Naja naja", _REPTILIA + "|Squamata|Elapidae|Naja|Naja naja")   # families sit under the order
    assert taxon_queries.resolve_taxon("snakes")["scientific_name"] == "Squamata"


def test_resolve_taxon_first_name_match_far_below_does_not_win(seed):
    _add("Testudines", _REPTILIA + "|Testudines", "order", common='["Tortoises", "Turtles"]')
    _add("Chelonia", _REPTILIA + "|Testudines|Cheloniidae|Chelonia", "genus", common='["turtle"]')
    _add("Chelonia mydas", _REPTILIA + "|Testudines|Cheloniidae|Chelonia|Chelonia mydas")
    assert taxon_queries.resolve_taxon("turtles")["scientific_name"] == "Testudines"


def test_child_rank_counts_and_members_by_rank(seed):
    _add("Aegotheles", "Animalia|Chordata|Aves|Aegotheles", "genus")   # genus placed under the class
    assert taxon_queries.child_rank_counts("Animalia|Chordata|Aves") == {"order": 1, "genus": 1}
    n, rows = taxon_queries.members("Animalia|Chordata|Aves", rank="order")
    assert n == 1 and [r["scientific_name"] for r in rows] == ["Strigiformes"]


def test_resolve_taxon_prefers_the_form_as_typed(seed):
    _add("Serpentes [Squamata]", _REPTILIA + "|Squamata|Serpentes", "suborder", common='["Snakes"]')
    _add("Naja naja", _REPTILIA + "|Squamata|Serpentes|Elapidae|Naja|Naja naja")
    _add("Serpentes", _REPTILIA + "|Ophidia|Serpentes", "suborder", common='["snake"]')
    _add("Vipera berus", _REPTILIA + "|Ophidia|Serpentes|Viperidae|Vipera|Vipera berus")
    assert taxon_queries.resolve_taxon("snakes")["scientific_name"] == "Serpentes [Squamata]"


def test_resolve_taxon_depth_before_the_typed_form(seed):
    mammals = "Animalia|Chordata|Mammalia"
    _add("Chiroptera", mammals + "|Chiroptera", "order", common='["Bat", "Bats"]')
    _add("Vespertilionidae", mammals + "|Chiroptera|Vespertilionidae", "family", common='["Bats"]')
    _add("Myotis myotis", mammals + "|Chiroptera|Vespertilionidae|Myotis|Myotis myotis")
    assert taxon_queries.resolve_taxon("bats")["scientific_name"] == "Chiroptera"


# ── Increment 20: deferred minors ─────────────────────────────────────────────

def test_resolve_taxon_treats_like_wildcards_literally(seed):
    assert taxon_queries.resolve_taxon("Ow_s") is None
    assert taxon_queries.resolve_taxon("%") is None


def test_lineage_common_name_prefers_latin_script(seed):
    _add("Sebastes", "Animalia|Chordata|Sebastes", "genus",
         common='["平鮋属", "Rockfishes"]')
    assert taxon_queries.lineage("Animalia|Chordata|Sebastes")[2]["common"] == "Rockfishes"


# ── Increment 21 ──────────────────────────────────────────────────────────────

def test_resolve_taxon_tie_goes_to_the_better_known_species(seed):
    # "snow leopard" is also the first common name of a moth, Obtusipalpis pardalis
    _add("Obtusipalpis pardalis", "Animalia|Arthropoda|Insecta|Lepidoptera|Crambidae|Obtusipalpis|Obtusipalpis pardalis",
         common='["Snow Leopard"]', wikipedia_abstract="A moth.")
    _add("Panthera uncia", "Animalia|Chordata|Mammalia|Carnivora|Felidae|Panthera|Panthera uncia",
         common='["snow leopard", "Ounce"]', wikipedia_abstract="A big cat.", iucn_status="VU",
         primary_image_url="https://example.org/u.jpg")
    assert taxon_queries.resolve_taxon("snow leopard")["scientific_name"] == "Panthera uncia"


def test_closest_name_fixes_a_typo(seed):
    # llama3.1:8b copies "Cinachyra antarctica" as "Cinachyrya antarctica"
    assert taxon_queries.closest_name("Strix occidentalus") == "Strix occidentalis"
    assert taxon_queries.closest_name("Tyto albba") == "Tyto alba"


def test_closest_name_none_when_nothing_is_close(seed):
    assert taxon_queries.closest_name("Panthera leo") is None
    assert taxon_queries.closest_name("Strix ghostt") is None   # synonyms are not offered
    assert taxon_queries.closest_name("") is None


def test_resolve_taxon_falls_back_to_the_closest_scientific_name(seed):
    assert taxon_queries.resolve_taxon("Tyto albba")["scientific_name"] == "Tyto alba"


def test_species_count_counts_accepted_species_in_the_tree(seed):
    # Bubo bubo, Tyto alba and three Strix species; not the synonym or the GBIF-only row
    assert taxon_queries.species_count(_OWLS) == 5
    assert taxon_queries.species_count("Animalia|Chordata|Mammalia") == 0


def test_species_count_living_only_leaves_out_extinct(seed):
    # Strix fossilis is extinct
    assert taxon_queries.species_count(_OWLS, living_only=True) == 4


def test_range_ranking_needs_1000_wild_records(seed_ranges):
    # Strix occidentalis (999 records) and Strix perdita (old range, no count) would lead
    assert taxon_queries.RANK_MIN_RECORDS == 1000
    for column in ("lat_max", "lat_south"):
        n, rows = taxon_queries.rank_by_trait(column, _OWLS, True, 10)
        assert n == 2 and {r["scientific_name"] for r in rows} == {"Bubo bubo", "Tyto alba"}


# ── Increment 25: species named in a question ─────────────────────────────────

_KOALAS = "Animalia|Chordata|Mammalia|Diprotodontia|Phascolarctidae"


@pytest.fixture
def koala_seed(seed):
    _add("Mammalia", "Animalia|Chordata|Mammalia", "class")
    _add("Diprotodontia", "Animalia|Chordata|Mammalia|Diprotodontia", "order")
    _add("Phascolarctidae", _KOALAS, "family", common='["Koalas", "koala"]')
    _add("Phascolarctos", _KOALAS + "|Phascolarctos", "genus", common='["Koalas", "koala"]')
    _add("Phascolarctos cinereus", _KOALAS + "|Phascolarctos|Phascolarctos cinereus",
         common='["Koala", "Koala Bear"]')
    _add("Phascolarctos stirtoni", _KOALAS + "|Phascolarctos|Phascolarctos stirtoni", extinct=1)
    # The plant genus Panda and the giant panda, known as "panda"
    _add("Panda", "Plantae|Tracheophyta|Panda", "genus", common='["kana trees"]')
    _add("Panda oleosa", "Plantae|Tracheophyta|Panda|Panda oleosa")
    _add("Ailuropoda melanoleuca", "Animalia|Chordata|Mammalia|Carnivora|Ursidae|Ailuropoda|"
         "Ailuropoda melanoleuca", common='["Giant Panda", "Panda"]')


def test_sole_living_species_skips_fossils(koala_seed):
    row = taxon_queries.sole_living_species(_KOALAS)
    assert row["scientific_name"] == "Phascolarctos cinereus"


def test_sole_living_species_none_for_several(seed):
    assert taxon_queries.sole_living_species(_OWLS) is None


def test_named_species_finds_a_species_through_its_group(koala_seed):
    assert taxon_queries.named_species("koalas diet")["scientific_name"] == "Phascolarctos cinereus"


def test_named_species_multi_word_name(koala_seed):
    assert taxon_queries.named_species("what does the barn owl eat")["scientific_name"] == "Tyto alba"


def test_named_species_none_for_a_group_of_many(koala_seed):
    assert taxon_queries.named_species("owls hunting at night") is None


def test_named_species_none_without_a_name(koala_seed):
    assert taxon_queries.named_species("a striped horse-like animal") is None


def test_named_species_only_animals(koala_seed):
    assert taxon_queries.named_species("kana trees") is None


def test_named_species_skips_long_descriptions(koala_seed):
    assert taxon_queries.named_species("grey tree climbing marsupial eating leaves koala") is None


def test_resolve_taxon_lowercase_name_prefers_the_animal(koala_seed):
    assert taxon_queries.resolve_taxon("panda")["scientific_name"] == "Ailuropoda melanoleuca"


def test_resolve_taxon_capitalised_scientific_name_still_wins(koala_seed):
    assert taxon_queries.resolve_taxon("Panda")["scientific_name"] == "Panda"


def test_resolve_taxon_lowercase_plant_without_animal_rival(koala_seed):
    assert taxon_queries.resolve_taxon("panda oleosa")["scientific_name"] == "Panda oleosa"


def test_resolve_taxon_first_name_one_level_down_must_be_below_the_match(koala_seed):
    # The panda catfish has "panda" as its first common name, one level below the
    # giant panda's genus; only a subgroup of the broader match may win that way
    _add("Ailuropoda", "Animalia|Chordata|Mammalia|Carnivora|Ursidae|Ailuropoda", "genus",
         common='["giant panda", "Pandas"]')
    _add("Corydoras panda", "Animalia|Chordata|Actinopterygii|Siluriformes|Callichthyidae|Corydoras|"
         "Corydoras panda", common='["panda", "panda corydoras"]')
    assert taxon_queries.resolve_taxon("panda")["scientific_name"] == "Ailuropoda"
    assert taxon_queries.named_species("where do pandas live")["scientific_name"] == "Ailuropoda melanoleuca"


def test_resolve_taxon_lowercase_name_of_an_empty_genus_gives_way(koala_seed):
    # COL has an empty wombat genus "Koala"
    _add("Koala", "Animalia|Chordata|Mammalia|Diprotodontia|Vombatidae|Koala", "genus")
    assert taxon_queries.resolve_taxon("koala")["scientific_name"] == "Phascolarctidae"
    assert taxon_queries.resolve_taxon("Koala")["scientific_name"] == "Koala"
    assert taxon_queries.named_species("where do koalas live")["scientific_name"] == "Phascolarctos cinereus"


def test_resolve_taxon_lowercase_living_genus_still_wins(seed):
    assert taxon_queries.resolve_taxon("strix")["scientific_name"] == "Strix"


# ── Increment 26: species in a place ──────────────────────────────────────────

import json as _json  # noqa: E402

_SQUAMATA = "Animalia|Chordata|Reptilia|Squamata"


def _box(lat_min, lat_max, lon_min, lon_max, records=50_000):
    return _json.dumps({"lat_min": lat_min, "lat_max": lat_max, "lon_min": lon_min,
                        "lon_max": lon_max, "records": records})


class _NL:
    """The Netherlands as a plain box (places.Place stand-in)."""
    name, kind, bbox = "Netherlands", "country", [50.8, 53.5, 3.4, 7.2]

    def overlaps(self, la0, la1, lo0, lo1):
        return la0 <= 53.5 and la1 >= 50.8 and lo0 <= 7.2 and lo1 >= 3.4


@pytest.fixture
def reptiles(seed):
    _add("Reptilia", "Animalia|Chordata|Reptilia", "class", common='["Reptiles"]')
    _add("Squamata", _SQUAMATA, "order", common='["Lizards", "Snakes"]')
    _add("Colubridae", _SQUAMATA + "|Colubridae", "family", common='["Colubrids"]')
    _add("Viperidae", _SQUAMATA + "|Viperidae", "family", common='["Vipers"]')
    _add("Lacertidae", _SQUAMATA + "|Lacertidae", "family", common='["Lacertids"]')
    _add("Natrix natrix", _SQUAMATA + "|Colubridae|Natrix|Natrix natrix", common='["grass snake"]',
         geo_bounding_box=_box(38.0, 61.6, -8.1, 57.7, 144_076))
    _add("Coronella austriaca", _SQUAMATA + "|Colubridae|Coronella|Coronella austriaca",
         common='["smooth snake"]', geo_bounding_box=_box(40.3, 59.8, -8.2, 47.4, 68_131))
    _add("Vipera aspis", _SQUAMATA + "|Viperidae|Vipera|Vipera aspis", common='["asp viper"]',
         geo_bounding_box=_box(37.0, 49.0, -2.0, 16.0, 30_000))
    _add("Vipera berus", _SQUAMATA + "|Viperidae|Vipera|Vipera berus", common='["adder"]',
         geo_bounding_box=_box(45.0, 65.8, -5.5, 60.7, 127_461))
    _add("Vipera rara", _SQUAMATA + "|Viperidae|Vipera|Vipera rara",
         geo_bounding_box=_box(45.0, 65.8, -5.5, 60.7, 40))           # too few records
    _add("Lacerta agilis", _SQUAMATA + "|Lacertidae|Lacerta|Lacerta agilis", common='["sand lizard"]',
         geo_bounding_box=_box(43.1, 58.4, -3.1, 83.1, 220_696))


def test_place_groups_snakes_are_the_snake_families(reptiles):
    label, paths = taxon_queries.place_group("snakes")
    assert label == "snakes (snake families)"
    assert sorted(paths) == [_SQUAMATA + "|Colubridae", _SQUAMATA + "|Viperidae"]


def test_place_groups_other_names_resolve_as_groups(reptiles):
    label, paths = taxon_queries.place_group("reptiles")
    assert label.startswith("Reptilia") and paths == ["Animalia|Chordata|Reptilia"]
    assert taxon_queries.place_group("dragons") is None


def test_species_in_place_closest_fit_first(reptiles):
    # Share of each range box inside the place's box: smooth snake 0.0095, adder 0.0075,
    # grass snake 0.0066; a worldwide species would come last
    _, paths = taxon_queries.place_group("snakes")
    close, n, ranged, rows = taxon_queries.species_in_place(paths, _NL(), 10)
    assert [r["scientific_name"] for r in rows] == ["Coronella austriaca", "Vipera berus", "Natrix natrix"]
    assert close == n == 3 and ranged == 4   # Vipera aspis has a range elsewhere; Vipera rara too few records
    assert rows[2]["records"] == 144_076


def test_species_in_place_endemic_before_a_widespread_species(reptiles):
    _add("Natrix endemica", _SQUAMATA + "|Colubridae|Natrix|Natrix endemica",
         geo_bounding_box=_box(51.0, 53.0, 4.0, 7.0, 1_200))
    _, paths = taxon_queries.place_group("snakes")
    _, _, _, rows = taxon_queries.species_in_place(paths, _NL(), 10)
    assert rows[0]["scientific_name"] == "Natrix endemica" and rows[0]["fit"] == 1.0


def test_species_in_place_limit_keeps_the_count(reptiles):
    _, paths = taxon_queries.place_group("snakes")
    close, n, _, rows = taxon_queries.species_in_place(paths, _NL(), 1)
    assert n == 3 and len(rows) == 1


def test_species_in_place_skips_hybrids(reptiles):
    _add("Natrix natrix x Natrix helvetica", _SQUAMATA + "|Colubridae|Natrix|Natrix natrix x Natrix helvetica",
         geo_bounding_box=_box(51.0, 53.0, 4.0, 7.0, 5_000))
    _, paths = taxon_queries.place_group("snakes")
    close, n, _, rows = taxon_queries.species_in_place(paths, _NL(), 10)
    assert n == 3 and all(" x " not in r["scientific_name"] for r in rows)


def test_living_species_count_over_several_groups(reptiles):
    _add("Vipera fossilis", _SQUAMATA + "|Viperidae|Vipera|Vipera fossilis", extinct=1)
    _, paths = taxon_queries.place_group("snakes")
    assert taxon_queries.living_species_count(paths) == 5


def test_species_in_place_lists_no_far_worse_fits(reptiles):
    # An escaped pet: a range box from America to Europe fits the place 100x worse
    _add("Pantherophis guttatus", _SQUAMATA + "|Colubridae|Pantherophis|Pantherophis guttatus",
         common='["corn snake"]', geo_bounding_box=_box(25.0, 53.0, -100.0, 3.6, 60_000))
    _, paths = taxon_queries.place_group("snakes")
    close, n, _, rows = taxon_queries.species_in_place(paths, _NL(), 10)
    assert close == 3 and n == 4
    assert "Pantherophis guttatus" not in [r["scientific_name"] for r in rows]


def test_species_in_place_same_result_for_a_large_group(reptiles, monkeypatch):
    # Large groups take the status index instead of the path index: same answer
    small = taxon_queries.species_in_place(["Animalia"], _NL(), 10)
    monkeypatch.setattr(taxon_queries, "_LARGE_GROUP_ROWS", 3)
    assert taxon_queries._is_large(database.get_connection(), "Animalia")
    large = taxon_queries.species_in_place(["Animalia"], _NL(), 10)
    assert [r["scientific_name"] for r in large[3]] == [r["scientific_name"] for r in small[3]]
    assert large[:3] == small[:3]
    assert taxon_queries.living_species_count(["Animalia"]) == taxon_queries.species_count("Animalia", living_only=True)


# ── Increment 26: species in a country (GBIF country records) ────────────────

def _country(code, name, records):
    c = database.get_connection()
    c.execute("INSERT INTO species_countries VALUES (?, ?, ?)", (code, name, records))
    c.commit()
    c.close()


@pytest.fixture
def nl_records(reptiles):
    _country("NL", "Natrix natrix", 9_000)
    _country("NL", "Vipera berus", 4_000)
    _country("NL", "Coronella austriaca", 600)
    _country("NL", "Lacerta agilis", 3_000)                      # a lizard, not a snake
    _country("NL", "Vipera aspis", 2)                            # a stray record
    _country("BE", "Vipera aspis", 50)
    _country("BE", "Natrix natrix", 1_000)
    _country("IE", "Lacerta agilis", 1)


def test_has_country_records(nl_records):
    assert taxon_queries.has_country_records(["NL"])
    assert not taxon_queries.has_country_records(["FR"])
    assert not taxon_queries.has_country_records([])


def test_species_in_country_most_recorded_first(nl_records):
    _, paths = taxon_queries.place_group("snakes")
    n, few, rows = taxon_queries.species_in_country(paths, ["NL"], 10)
    assert [r["scientific_name"] for r in rows] == ["Natrix natrix", "Vipera berus", "Coronella austriaca"]
    assert (n, few) == (3, 1)                  # Vipera aspis: below the record minimum
    assert rows[0]["records"] == 9_000


def test_species_in_country_lists_no_far_less_recorded_species(nl_records):
    # An escaped pet seen 85 times: under 1% of the grass snake's 9,000 records
    _add("Elaphe schrenckii", _SQUAMATA + "|Colubridae|Elaphe|Elaphe schrenckii")
    _country("NL", "Elaphe schrenckii", 85)
    _, paths = taxon_queries.place_group("snakes")
    n, rare, rows = taxon_queries.species_in_country(paths, ["NL"], 10)
    assert (n, rare) == (3, 2)
    assert "Elaphe schrenckii" not in [r["scientific_name"] for r in rows]


def test_species_in_country_sums_several_codes_and_keeps_limit(nl_records):
    _, paths = taxon_queries.place_group("snakes")
    n, few, rows = taxon_queries.species_in_country(paths, ["NL", "BE"], 1)
    assert (n, few) == (3, 1) and len(rows) == 1   # Vipera aspis: 2 + 50 records, under 1% of 9,000
    assert rows[0]["scientific_name"] == "Natrix natrix" and rows[0]["records"] == 10_000


def test_species_in_country_skips_hybrids_and_synonyms(nl_records):
    _add("Natrix natrix x Natrix helvetica", _SQUAMATA + "|Colubridae|Natrix|Natrix natrix x Natrix helvetica")
    _country("NL", "Natrix natrix x Natrix helvetica", 100)
    _, paths = taxon_queries.place_group("snakes")
    n, _, rows = taxon_queries.species_in_country(paths, ["NL"], 10)
    assert n == 3


def test_species_in_country_none_in_the_group(nl_records):
    _, paths = taxon_queries.place_group("snakes")
    assert taxon_queries.species_in_country(paths, ["IE"], 10) == (0, 0, [])


# ── Increment 27: countries of one species ───────────────────────────────────

def test_countries_of_a_species_most_records_first(nl_records):
    assert taxon_queries.countries_of("Natrix natrix") == [("NL", 9_000), ("BE", 1_000)]
    assert taxon_queries.countries_of("Unknown sp") == []


# ── Increment 27: a well-known species beats an unrelated group of that name ──

_NYMPH = "Animalia|Arthropoda|Insecta|Lepidoptera|Nymphalidae"
_FELIDAE = "Animalia|Chordata|Mammalia|Carnivora|Felidae"


@pytest.fixture
def tigers(seed):
    _add("Parantica", _NYMPH + "|Parantica", "genus", common='["Tigers"]')
    _add("Parantica aglea", _NYMPH + "|Parantica|Parantica aglea", common='["glassy tiger"]')
    _add("Panthera tigris", _FELIDAE + "|Panthera|Panthera tigris", common='["Tiger", "Bengal tiger"]',
         wikipedia_abstract="The tiger is the largest living cat species.",
         geo_bounding_box=_box(-2.35, 49.1, 75.64, 136.88, 5_245))


def test_tiger_is_the_species_not_the_butterfly_genus(tigers):
    assert taxon_queries.resolve_taxon("tiger")["scientific_name"] == "Panthera tigris"
    assert taxon_queries.resolve_taxon("tigers")["scientific_name"] == "Panthera tigris"


def test_group_questions_still_get_the_group(tigers):
    assert taxon_queries.resolve_taxon("tigers", groups_only=True)["scientific_name"] == "Parantica"


def test_a_species_inside_the_group_does_not_beat_it(seed):
    _add("Testudines", "Animalia|Chordata|Reptilia|Testudines", "order", common='["Turtles"]')
    _add("Testudo turtle", "Animalia|Chordata|Reptilia|Testudines|Testudinidae|Testudo|Testudo turtle",
         common='["Turtle"]', wikipedia_abstract="A turtle.")
    assert taxon_queries.resolve_taxon("turtle")["scientific_name"] == "Testudines"


def test_a_rarely_observed_species_does_not_beat_the_group(tigers):
    # The aquarium catfish Corydoras panda ("panda") against the giant panda's genus
    conn = database.get_connection()
    conn.execute("UPDATE species SET geo_bounding_box = ? WHERE scientific_name = 'Panthera tigris'",
                 (_box(-2.35, 49.1, 75.64, 136.88, 40),))
    conn.commit()
    conn.close()
    assert taxon_queries.resolve_taxon("tiger")["scientific_name"] == "Parantica"


def test_an_unknown_species_does_not_beat_the_group(tigers):
    conn = database.get_connection()
    conn.execute("UPDATE species SET wikipedia_abstract = NULL WHERE scientific_name = 'Panthera tigris'")
    conn.commit()
    conn.close()
    assert taxon_queries.resolve_taxon("tiger")["scientific_name"] == "Parantica"



# ── Increment 28: groups COL has no single taxon for ─────────────────────────

_ELASMO = "Animalia|Chordata|Elasmobranchii"
_MAMMALIA = "Animalia|Chordata|Mammalia"


@pytest.fixture
def listed_groups(reptiles):
    _add("Lacertidae sp", _SQUAMATA + "|Lacertidae|Lacerta|Lacertidae sp")
    _add("Amphisbaenidae", _SQUAMATA + "|Amphisbaenidae", "family", common='["Worm lizards"]')
    _add("Amphisbaena alba", _SQUAMATA + "|Amphisbaenidae|Amphisbaena|Amphisbaena alba")
    _add("Elasmobranchii", _ELASMO, "class", common='["Elasmobranch"]')
    _add("Lamniformes", _ELASMO + "|Lamniformes", "order", common='["Mackerel Sharks"]')
    _add("Carcharodon carcharias", _ELASMO + "|Lamniformes|Lamnidae|Carcharodon|Carcharodon carcharias",
         common='["Great white shark"]', max_lifespan=70, iucn_status="VU")
    _add("Rajiformes", _ELASMO + "|Rajiformes", "order", common='["Skates and rays"]')
    _add("Raja clavata", _ELASMO + "|Rajiformes|Rajidae|Raja|Raja clavata", max_lifespan=16)
    _add("Mammalia", _MAMMALIA, "class", common='["Mammals"]')
    _add("Diprotodontia", _MAMMALIA + "|Diprotodontia", "order", common='["koalas, wombats"]')
    _add("Phascolarctos cinereus", _MAMMALIA + "|Diprotodontia|Phascolarctidae|Phascolarctos|Phascolarctos cinereus",
         common='["Koala"]', max_lifespan=18, iucn_status="VU")
    _add("Didelphimorphia", _MAMMALIA + "|Didelphimorphia", "order", common='["American opossums", "Marsupials"]')
    _add("Didelphis virginiana", _MAMMALIA + "|Didelphimorphia|Didelphidae|Didelphis|Didelphis virginiana",
         common='["Virginia opossum"]', max_lifespan=6, iucn_status="LC")
    _add("Carnivora", _MAMMALIA + "|Carnivora", "order")
    _add("Canis lupus", _MAMMALIA + "|Carnivora|Canidae|Canis|Canis lupus", max_lifespan=20)


def test_group_paths_lists(listed_groups):
    name, label, paths = taxon_queries.group_paths("sharks")
    assert (name, paths) == ("sharks", [_ELASMO + "|Lamniformes"])
    assert label == "sharks (shark orders)"
    _, _, paths = taxon_queries.group_paths("Marsupials")
    assert sorted(paths) == [_MAMMALIA + "|Didelphimorphia", _MAMMALIA + "|Diprotodontia"]
    _, _, paths = taxon_queries.group_paths("lizard")
    assert paths == [_SQUAMATA + "|Lacertidae"]          # not the snakes, not the worm lizards
    _, label, paths = taxon_queries.group_paths("snakes")
    assert label == "snakes (snake families)" and len(paths) == 2


def test_group_paths_other_names_resolve(listed_groups):
    name, label, paths = taxon_queries.group_paths("owls")
    assert name == "Strigiformes" and label == "Strigiformes (Owls, order)" and paths == [_OWLS]
    assert taxon_queries.group_paths("dragons") is None


def test_rank_by_trait_over_several_paths(listed_groups):
    _, _, paths = taxon_queries.group_paths("marsupials")
    n, rows = taxon_queries.rank_by_trait("max_lifespan", paths, True, 1)
    assert n == 2 and [r["scientific_name"] for r in rows] == ["Phascolarctos cinereus"]
    n, rows = taxon_queries.rank_by_trait("max_lifespan", paths, False, 5)
    assert [r["scientific_name"] for r in rows] == ["Didelphis virginiana", "Phascolarctos cinereus"]


def test_counts_over_several_paths(listed_groups):
    _, _, paths = taxon_queries.group_paths("marsupials")
    assert taxon_queries.species_count(paths) == 2
    s = taxon_queries.group_summary(paths)
    assert s["species"] == 2 and s["iucn"] == {"VU": 1, "LC": 1}
    assert [r["scientific_name"] for r in s["threatened"]] == ["Phascolarctos cinereus"]



# ── Increment 29: continents through their countries ─────────────────────────

class _Europe:
    """Europe from 35°N to 72°N, 25°W to 60°E (places.Place stand-in)."""
    name, kind, bbox = "Europe", "continent", [35.0, 72.0, -25.0, 60.0]

    def overlaps(self, la0, la1, lo0, lo1):
        return la0 <= 72.0 and la1 >= 35.0 and lo0 <= 60.0 and lo1 >= -25.0


def test_species_in_continent_partial_country_needs_the_box(nl_records):
    # An Asian snake recorded in Russia only: Russia is partly European, the box is in Asia
    _add("Elaphe dione", _SQUAMATA + "|Colubridae|Elaphe|Elaphe dione",
         geo_bounding_box=_box(40.0, 55.0, 70.0, 130.0, 5_000))
    _country("RU", "Elaphe dione", 3_000)
    _country("RU", "Vipera berus", 2_000)              # its box reaches Europe: counts
    _, paths = taxon_queries.place_group("snakes")
    n, _, rows = taxon_queries.species_in_country(paths, ["NL", "RU"], 10, partial=["RU"], place=_Europe())
    names = [r["scientific_name"] for r in rows]
    assert "Elaphe dione" not in names
    assert next(r for r in rows if r["scientific_name"] == "Vipera berus")["records"] == 6_000
