"""Live smoke test of the trait sources against the real services (R13).

Deselected by default; run with:  ..\.venv\Scripts\python -m pytest -m live -v
Catches API shape drift that the mocked unit tests cannot.
"""

import pytest

from app import trait_utils
from app.trait_utils import SourceUnavailable

pytestmark = pytest.mark.live

_ROWS = {
    "Panthera leo": "Animalia|Chordata|Mammalia|Carnivora|Felidae|Panthera|Panthera leo",
    "Ursus maritimus": "Animalia|Chordata|Mammalia|Carnivora|Ursidae|Ursus|Ursus maritimus",
    "Theraphosa blondi": "Animalia|Arthropoda|Arachnida|Araneae|Theraphosidae|Theraphosa|Theraphosa blondi",
    "Apis cerana": "Animalia|Arthropoda|Insecta|Hymenoptera|Apidae|Apis|Apis cerana",
}
_TYPES = {"habitat_type": str, "elevation_limits": str, "iucn_status": str, "population_trend": str,
          "geo_bounding_box": dict, "body_mass": float, "body_length": float, "max_lifespan": float,
          "wikipedia_abstract": str}


def _row(name):
    return {"scientific_name": name, "taxon_rank": "species", "taxon_path": _ROWS[name], "common_names": "[]"}


def _call(fn, *args):
    try:
        return fn(*args)
    except SourceUnavailable as e:
        pytest.skip(f"source temporarily unavailable: {e}")


@pytest.mark.parametrize("name", list(_ROWS))
def test_every_source_returns_expected_field_types(name):
    results = [
        _call(trait_utils.iucn_traits, name, _row(name)),
        _call(trait_utils.gbif_traits, name, _row(name)),
        _call(trait_utils.wikidata_traits, name, "species"),
        _call(trait_utils.wikipedia_abstract, name),
    ]
    for result in results:
        for field, tv in result.items():
            assert isinstance(tv.value, _TYPES[field]), (field, tv)
            assert tv.source and tv.estimated is False


def test_lion_iucn_habitat_present():
    out = _call(trait_utils.iucn_traits, "Panthera leo", _row("Panthera leo"))
    assert out["habitat_type"].value
    assert out["elevation_limits"].value == "0–4,200 m"


def test_spider_wikidata_mass():
    out = _call(trait_utils.wikidata_traits, "Theraphosa blondi", "species")
    assert out["body_mass"].value == pytest.approx(0.176, abs=1e-3)
