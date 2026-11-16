"""data/enrich_wikipedia.py: which species it asks for, and what it writes."""

import sys
from pathlib import Path

import pytest

from app import database

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "data"))
import enrich_wikipedia as wiki  # noqa: E402

RESULT = {"abstract": "A sea anemone.", "image_url": "https://wiki/img.jpg",
          "attribution": "https://en.wikipedia.org/wiki/Metridium_senile"}


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    database.get_connection().close()


@pytest.fixture
def conn():
    c = database.get_connection()
    yield c
    c.close()


def _add(conn, name, path="Animalia|Cnidaria|Anthozoa|Actiniaria|Metridiidae|Metridium|",
         common='["frilled anemone"]', **fields):
    cols = {"scientific_name": name, "taxon_path": path, "taxon_rank": "species",
            "taxonomic_status": "ACCEPTED", "common_names": common, **fields}
    conn.execute(f"INSERT INTO species ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                 list(cols.values()))
    conn.commit()


def test_user_agent_names_the_app_and_a_contact():
    assert wiki.USER_AGENT.startswith("AnimalKingdomApp/")
    assert "contact" in wiki.USER_AGENT


def test_select_animals_only_skips_other_kingdoms(conn):
    _add(conn, "Metridium senile")
    _add(conn, "Quercus robur", path="Plantae|Tracheophyta|Magnoliopsida|Fagales|Fagaceae|Quercus|")
    assert wiki.select_names(conn, 100, only_with_common_names=True, animals_only=True) == ["Metridium senile"]
    assert len(wiki.select_names(conn, 100, only_with_common_names=True, animals_only=False)) == 2


def test_select_skips_species_with_abstract_or_without_common_name(conn):
    _add(conn, "Metridium senile")
    _add(conn, "Metridium farcimen", wikipedia_abstract="Known.")
    _add(conn, "Metridium dianthus", common="[]")
    assert wiki.select_names(conn, 100, only_with_common_names=True, animals_only=True) == ["Metridium senile"]


def test_save_result_keeps_an_existing_image(conn):
    _add(conn, "Metridium senile", primary_image_url="https://inat/photo.jpg", image_attribution="iNaturalist")
    wiki.save_result(conn, "Metridium senile", RESULT)
    row = conn.execute("SELECT * FROM species").fetchone()
    assert row["wikipedia_abstract"] == "A sea anemone."
    assert row["primary_image_url"] == "https://inat/photo.jpg"
    assert row["image_attribution"] == "iNaturalist"


def test_save_result_without_thumbnail_keeps_an_existing_image(conn):
    _add(conn, "Metridium senile", primary_image_url="https://inat/photo.jpg", image_attribution="iNaturalist")
    wiki.save_result(conn, "Metridium senile", {**RESULT, "image_url": None})
    row = conn.execute("SELECT * FROM species").fetchone()
    assert row["primary_image_url"] == "https://inat/photo.jpg"
    assert row["image_attribution"] == "iNaturalist"


def test_save_result_fills_a_missing_image(conn):
    _add(conn, "Metridium senile")
    wiki.save_result(conn, "Metridium senile", RESULT)
    row = conn.execute("SELECT * FROM species").fetchone()
    assert row["primary_image_url"] == "https://wiki/img.jpg"
    assert row["image_attribution"] == RESULT["attribution"]
