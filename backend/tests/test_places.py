"""Places for the chat's species_in_place tool: data/build_places.py (Natural Earth
polygons -> 0.5° cell rows) and app/places.py (name lookup, range-box overlap)."""

import json
import sys
from pathlib import Path

import pytest

from app import places

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "data"))
import build_places as bp  # noqa: E402


def _square(lon0, lat0, lon1, lat1):
    return [[[lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1], [lon0, lat0]]]


def _feature(props, *rings_list):
    if len(rings_list) == 1:
        geom = {"type": "Polygon", "coordinates": rings_list[0]}
    else:
        geom = {"type": "MultiPolygon", "coordinates": list(rings_list)}
    return {"type": "Feature", "properties": props, "geometry": geom}


# ── build: rasterising ────────────────────────────────────────────────────────

def test_cells_cover_the_inside_and_the_edge():
    rows = bp.rasterise([_square(4.0, 51.0, 6.0, 53.0)[0]])
    # lat 51.0-53.0 -> rows 282..285, lon 4.0-6.0 -> columns 368..371 (one more for the edge)
    assert set(rows) >= {282, 283, 284, 285}
    assert all(r in rows for r in range(282, 286))
    assert rows[283] == [[368, 372]]


def test_cells_of_separate_parts_stay_separate():
    rows = bp.rasterise([_square(0.0, 0.0, 1.0, 1.0)[0], _square(10.0, 0.0, 11.0, 1.0)[0]])
    assert rows[180] == [[360, 362], [380, 382]]


def test_runs_merge_neighbouring_cells():
    assert bp.runs([3, 4, 5, 9, 11, 12]) == [[3, 5], [9, 9], [11, 12]]


# ── build: places and names ───────────────────────────────────────────────────

def _units():
    nl = _feature({"ADMIN": "Netherlands", "GEOUNIT": "Netherlands", "NAME": "Netherlands",
                   "NAME_LONG": "Netherlands", "FORMAL_EN": "Kingdom of the Netherlands",
                   "NAME_ALT": None, "ISO_A2": "NL", "ISO_A2_EH": "NL"}, _square(3.4, 50.8, 7.2, 53.5))
    bq = _feature({"ADMIN": "Netherlands", "GEOUNIT": "Caribbean Netherlands",
                   "NAME": "Caribbean Netherlands", "NAME_LONG": "Caribbean Netherlands",
                   "ISO_A2": "BQ", "ISO_A2_EH": "BQ"},
                  _square(-68.4, 12.0, -68.2, 12.3))
    eng = _feature({"ADMIN": "United Kingdom", "GEOUNIT": "England", "NAME": "England",
                    "NAME_LONG": "England", "ISO_A2": "-99", "ISO_A2_EH": "GB"}, _square(-5.7, 50.0, 1.7, 55.8))
    sco = _feature({"ADMIN": "United Kingdom", "GEOUNIT": "Scotland", "NAME": "Scotland",
                    "NAME_LONG": "Scotland", "ISO_A2": "-99", "ISO_A2_EH": "GB"}, _square(-7.5, 54.6, -0.8, 60.8))
    return [nl, bq, eng, sco]


def test_country_without_its_overseas_parts():
    out = {p["name"]: p for p in bp.country_places(_units())}
    nl = out["Netherlands"]
    assert nl["kind"] == "country"
    assert nl["bbox"] == [50.8, 53.5, 3.4, 7.2]
    assert "Caribbean Netherlands" in out


def test_country_of_several_units_joins_them():
    out = {p["name"]: p for p in bp.country_places(_units())}
    uk = out["United Kingdom"]
    assert uk["bbox"] == [50.0, 60.8, -7.5, 1.7]
    assert "England" in out and "Scotland" in out


def test_countries_carry_gbif_country_codes():
    out = {p["name"]: p for p in bp.country_places(_units())}
    assert out["Netherlands"]["countries"] == ["NL"]
    assert out["Caribbean Netherlands"]["countries"] == ["BQ"]
    # -99 in ISO_A2 falls back to ISO_A2_EH; parts sharing the country's code get none
    assert out["United Kingdom"]["countries"] == ["GB"]
    assert "countries" not in out["England"]


def test_alias_holland_and_formal_name():
    nl = next(p for p in bp.country_places(_units()) if p["name"] == "Netherlands")
    assert {"holland", "kingdom of the netherlands"} <= set(nl["aliases"])


def test_region_names_are_title_cased_and_kinds_kept():
    feats = [_feature({"FEATURECLA": "Island", "NAME": "BORNEO", "NAMEALT": None, "NAME_EN": "Borneo"},
                      _square(108.6, -4.2, 119.3, 7.4)),
             _feature({"FEATURECLA": "Continent", "NAME": "EUROPE", "NAME_EN": "Europe"},
                      _square(-10.0, 35.0, 40.0, 71.0))]
    out = {p["name"]: p for p in bp.region_places(feats)}
    assert out["Borneo"]["kind"] == "island" and out["Europe"]["kind"] == "continent"


def test_sea_names():
    feats = [_feature({"featurecla": "sea", "name": "North Sea", "namealt": None, "name_en": "North Sea"},
                      _square(-2.0, 51.0, 8.0, 61.0))]
    assert bp.sea_places(feats)[0]["name"] == "North Sea"
    assert bp.sea_places(feats)[0]["kind"] == "sea"


# ── runtime: lookup and overlap ───────────────────────────────────────────────

@pytest.fixture
def place_file(tmp_path, monkeypatch):
    data = [
        {"name": "Netherlands", "kind": "country", "aliases": ["holland"], "bbox": [50.8, 53.5, 3.4, 7.2],
         "countries": ["NL"],
         "rows": {str(r): [[366, 374]] for r in range(281, 287)}},
        {"name": "Ireland", "kind": "island", "aliases": [], "bbox": [51.4, 55.4, -10.5, -6.0],
         "rows": {"283": [[339, 348]]}},
        {"name": "Ireland", "kind": "country", "aliases": ["eire"], "bbox": [51.4, 55.4, -10.5, -6.0],
         "rows": {"283": [[339, 347]]}, "countries": ["IE"]},
        {"name": "Mediterranean Sea", "kind": "sea", "aliases": ["the mediterranean"],
         "bbox": [30.0, 46.0, -6.0, 36.0], "rows": {"260": [[348, 432]]}},
    ]
    path = tmp_path / "places.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(places, "PLACES_PATH", path)
    places._load.cache_clear(); places._by_code.cache_clear()
    yield path
    places._load.cache_clear(); places._by_code.cache_clear()


def test_find_place_by_alias_any_case(place_file):
    assert places.find_place("Holland").name == "Netherlands"
    assert places.find_place("the netherlands").name == "Netherlands"


def test_place_country_codes(place_file):
    assert places.find_place("holland").countries == ("NL",)
    assert places.find_place("the mediterranean").countries == ()


def test_find_place_prefers_the_country(place_file):
    assert places.find_place("ireland").kind == "country"


def test_find_place_unknown(place_file):
    assert places.find_place("Atlantis") is None


def test_find_place_strips_in_and_the(place_file):
    assert places.find_place("in the Mediterranean").name == "Mediterranean Sea"


def test_overlap_box_inside_the_place(place_file):
    nl = places.find_place("netherlands")
    assert nl.overlaps(52.0, 52.2, 5.0, 5.2)


def test_overlap_box_around_the_place(place_file):
    assert places.find_place("netherlands").overlaps(38.0, 61.6, -8.1, 57.7)


def test_no_overlap_box_elsewhere(place_file):
    nl = places.find_place("netherlands")
    assert not nl.overlaps(40.0, 49.0, -2.0, 16.0)     # south of it
    assert not nl.overlaps(51.0, 53.0, 10.0, 20.0)     # east of it


def test_overlap_at_the_cell_edge(place_file):
    # lon 7.2 lies in column 374, the place's last column
    assert places.find_place("netherlands").overlaps(52.0, 52.5, 7.2, 9.0)


# ── build: review fixes ───────────────────────────────────────────────────────

def test_parts_of_a_joined_country_keep_their_own_names():
    out = bp.country_places(_units())
    uk = next(p for p in out if p["name"] == "United Kingdom")
    assert "england" not in uk["aliases"] and "scotland" not in uk["aliases"]


def test_sea_layer_skips_rivers():
    feats = [_feature({"featurecla": "river", "name": "Amazon", "name_en": "Amazon"},
                      _square(-52.0, -1.0, -49.0, 1.0))]
    assert bp.sea_places(feats) == []


def test_extra_places_include_the_galapagos():
    gal = next(p for p in bp.extra_places() if p["name"] == "Galápagos Islands")
    assert "galapagos" in gal["aliases"] and gal["kind"] == "island group"
    assert gal["rows"]


# ── Increment 27: a species' countries ───────────────────────────────────────

def test_country_by_code_prefers_the_country(place_file):
    assert places.country_by_code("NL").name == "Netherlands"
    assert places.country_by_code("IE").kind == "country"
    assert places.country_by_code("ZZ") is None


def _strip(code, row0, row1, col0, col1):
    """A country covering grid rows row0..row1 and columns col0..col1."""
    lat0, lat1 = row0 * 0.5 - 90, (row1 + 1) * 0.5 - 90
    lon0, lon1 = col0 * 0.5 - 180, (col1 + 1) * 0.5 - 180
    return {"name": f"Land {code}", "kind": "country", "aliases": [], "bbox": [lat0, lat1, lon0, lon1],
            "rows": {str(r): [[col0, col1]] for r in range(row0, row1 + 1)}, "countries": [code]}


@pytest.fixture
def map_file(tmp_path, monkeypatch):
    # A chain A-B-C of neighbours (B touches A, C is one cell from B), D far away,
    # E a big country elsewhere with its own records
    data = [_strip("AA", 200, 210, 500, 520), _strip("BB", 200, 210, 521, 540),
            _strip("CC", 200, 210, 542, 560), _strip("DD", 300, 310, 100, 120),
            _strip("EE", 100, 140, 300, 380)]
    path = tmp_path / "places.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(places, "PLACES_PATH", path)
    places._load.cache_clear(); places._by_code.cache_clear()
    yield path
    places._load.cache_clear(); places._by_code.cache_clear()


def test_native_countries_follow_neighbours_of_the_main_ones(map_file):
    # AA holds most records; BB and CC are reached through neighbours; DD (zoo) is not
    inside, others = places.native_countries([("AA", 900), ("DD", 6), ("CC", 3), ("BB", 2)])
    assert inside == [("Land AA", 900), ("Land CC", 3), ("Land BB", 2)]
    assert others == 1


def test_native_countries_start_from_every_well_recorded_country(map_file):
    # EE has 5% of the records: a population of its own (red foxes in Australia)
    inside, others = places.native_countries([("AA", 900), ("EE", 50), ("DD", 6)])
    assert [n for n, _ in inside] == ["Land AA", "Land EE"] and others == 1


def test_native_countries_need_records_to_start_from(map_file):
    # 3% of the records but under 20 of them: not a starting point
    inside, others = places.native_countries([("AA", 500), ("DD", 15)])
    assert [n for n, _ in inside] == ["Land AA"] and others == 1


def test_native_countries_unknown_codes_and_empty(map_file):
    assert places.native_countries([("ZZ", 50), ("AA", 10)]) == ([("Land AA", 10)], 1)
    assert places.native_countries([]) == ([], 0)


def test_native_countries_not_across_a_listed_strait(map_file, monkeypatch):
    monkeypatch.setattr(places, "NOT_NEIGHBOURS", {frozenset({"AA", "BB"})})
    inside, others = places.native_countries([("AA", 900), ("BB", 3), ("CC", 3)])
    assert [n for n, _ in inside] == ["Land AA"] and others == 2



# ── Increment 29: continents as lists of countries ───────────────────────────

def _built(name, kind, rows, codes=(), continent=None):
    out = {"name": name, "kind": kind, "aliases": [], "bbox": [0, 0, 0, 0],
           "rows": {str(r): runs for r, runs in rows.items()}}
    if codes:
        out["countries"] = sorted(codes)
    if continent:
        out["_continent"] = continent
    return out


def test_continents_get_their_countries_codes():
    europe = _built("Europe", "continent", {280: [[360, 400]]})
    asia = _built("Asia", "continent", {280: [[401, 600]]})
    oceania = _built("Australia", "continent", {100: [[600, 650]]})
    built = [europe, asia, oceania,
             _built("Netherlands", "country", {280: [[365, 370]]}, ["NL"], "Europe"),
             # The UK lies outside Europe's mainland outline: the CONTINENT field decides
             _built("United Kingdom", "country", {290: [[350, 355]]}, ["GB"], "Europe"),
             _built("New Zealand", "country", {90: [[700, 710]]}, ["NZ"], "Oceania"),
             # 20 of 100 cells on Europe's outline: on both continents
             _built("Russia", "country", {280: [[381, 480]]}, ["RU"], "Europe"),
             _built("Somewhere", "country", {10: [[1, 2]]})]
    bp.assign_continents(built)
    assert europe["countries"] == ["GB", "NL", "RU"] and europe["partial"] == ["RU"]
    assert asia["countries"] == ["RU"] and asia["partial"] == ["RU"]
    assert oceania["countries"] == ["NZ"] and "partial" not in oceania
    assert "oceania" in oceania["aliases"]
    assert all("_continent" not in p for p in built)


def test_place_partial_codes(tmp_path, monkeypatch):
    data = [{"name": "Europe", "kind": "continent", "aliases": [], "bbox": [35, 72, -25, 60],
             "rows": {"280": [[360, 400]]}, "countries": ["NL", "RU"], "partial": ["RU"]}]
    path = tmp_path / "places.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(places, "PLACES_PATH", path)
    places._load.cache_clear(); places._by_code.cache_clear()
    try:
        europe = places.find_place("europe")
        assert europe.countries == ("NL", "RU") and europe.partial == ("RU",)
    finally:
        places._load.cache_clear(); places._by_code.cache_clear()



def test_country_by_code_ignores_continents(tmp_path, monkeypatch):
    data = [{"name": "South America", "kind": "continent", "aliases": [], "bbox": [-56, 13, -82, -34],
             "rows": {"170": [[200, 260]]}, "countries": ["BR", "GF"]},
            {"name": "French Guiana", "kind": "country part", "aliases": [], "bbox": [2, 6, -55, -51],
             "rows": {"188": [[249, 257]]}, "countries": ["GF"]}]
    path = tmp_path / "places.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(places, "PLACES_PATH", path)
    places._load.cache_clear(); places._by_code.cache_clear()
    try:
        assert places.country_by_code("GF").name == "French Guiana"
        assert places.country_by_code("BR") is None
    finally:
        places._load.cache_clear(); places._by_code.cache_clear()
