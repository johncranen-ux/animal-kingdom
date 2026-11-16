"""Tests for llm_agent.py — Ollama is fully mocked."""

import json
import pytest
from unittest.mock import patch, AsyncMock, MagicMock


@pytest.fixture(autouse=True)
def _no_named_rows(monkeypatch):
    """Stream tests don't read the real species.db for scientific names in the answer;
    a test that needs them patches taxon_links.named_rows itself."""
    from app import taxon_links
    monkeypatch.setattr(taxon_links, "named_rows", lambda text: [])


@pytest.fixture(autouse=True)
def _no_named_species(monkeypatch):
    """Semantic search and taxonomy_of don't read the real species.db for a species named
    in the query; tests that need one patch these themselves."""
    from app import taxon_queries
    monkeypatch.setattr(taxon_queries, "named_species", lambda text: None)
    monkeypatch.setattr(taxon_queries, "sole_living_species", lambda path: None)


@pytest.fixture(autouse=True)
def _no_countries(monkeypatch):
    """lookup_species doesn't read the real species_countries table; tests that need
    countries patch taxon_queries.countries_of themselves."""
    from app import taxon_queries
    monkeypatch.setattr(taxon_queries, "countries_of", lambda name: [])


# ── Tool registration ─────────────────────────────────────────────────────────

def test_tools_have_correct_names():
    from app.llm_agent import lookup_species, semantic_search_species, get_species_image
    assert lookup_species.name == "lookup_species"
    assert semantic_search_species.name == "semantic_search_species"
    assert get_species_image.name == "get_species_image"
    from app.llm_agent import find_species
    assert find_species.name == "find_species"


def test_tools_have_descriptions():
    from app.llm_agent import lookup_species, semantic_search_species, get_species_image
    assert lookup_species.description
    assert semantic_search_species.description
    assert get_species_image.description
    from app.llm_agent import find_species
    assert find_species.description


def test_build_agent_returns_agent():
    from app.llm_agent import build_agent
    mock_llm = MagicMock()
    mock_llm.bind_tools = MagicMock(return_value=mock_llm)
    with patch("app.llm_agent.get_llm", return_value=mock_llm):
        agent = build_agent()
    assert agent is not None


# ── lookup_species ─────────────────────────────────────────────────────────────

def test_lookup_species_not_found():
    from app.llm_agent import lookup_species
    with patch("app.llm_agent.database.get_species", return_value=None):
        result = lookup_species.invoke({"scientific_name": "Fakeus nonexistus"})
    assert "no species found" in result.lower()
    assert "Fakeus nonexistus" in result


def test_lookup_species_handles_a_row_outside_the_tree():
    from app.llm_agent import lookup_species
    row = {"scientific_name": "Fossilus antiquus", "taxon_rank": "species", "taxon_path": None,
           "taxonomic_status": "GBIF_ONLY", "extinct": 1, "common_names": "[]"}
    with patch("app.llm_agent.database.get_species", return_value=row), \
         patch("app.llm_agent._with_sourced_traits", side_effect=lambda r: r):
        result = lookup_species.invoke({"scientific_name": "Fossilus antiquus"})
    assert "FOUND" in result
    assert "- Lineage: not in the classification" in result


def test_lookup_species_returns_markdown_fields():
    from app.llm_agent import lookup_species
    fake_row = {
        "scientific_name": "Panthera leo",
        "taxon_rank": "species",
        "common_names": '["Lion","African lion"]',
        "taxon_path": "Animalia|Chordata|Mammalia|Carnivora|Felidae|Panthera|Panthera leo",
        "taxonomic_status": "ACCEPTED",
        "body_mass": 190.0,
        "body_length": 2.5,
        "max_lifespan": 16.0,
        "habitat_type": "savanna",
        "trophic_level": "carnivore",
        "iucn_status": "VU",
        "population_trend": "decreasing",
        "geo_bounding_box": '{"lat_min":-35,"lat_max":10,"lon_min":-18,"lon_max":51}',
        "wikipedia_abstract": "The lion is a large cat of the genus Panthera.",
        "primary_image_url": None,
        "image_attribution": None,
        "metabolic_rate": None,
        "reproduction_strategy": None,
        "elevation_limits": None,
        "activity_period": None,
    }
    with patch("app.llm_agent.database.get_species", return_value=fake_row):
        result = lookup_species.invoke({"scientific_name": "Panthera leo"})
    assert "Panthera leo" in result
    assert "Lion" in result
    assert "VU" in result
    assert "carnivore" in result
    assert "190" in result
    assert "savanna" in result
    assert "lion is a large cat" in result


def test_lookup_species_skips_none_fields():
    from app.llm_agent import lookup_species
    fake_row = {
        "scientific_name": "Rare species",
        "taxon_rank": "species",
        "common_names": None,
        "taxon_path": "Animalia|Rare species",
        "taxonomic_status": "ACCEPTED",
        "body_mass": None,
        "body_length": None,
        "max_lifespan": None,
        "habitat_type": None,
        "trophic_level": None,
        "iucn_status": None,
        "population_trend": None,
        "geo_bounding_box": None,
        "wikipedia_abstract": None,
        "primary_image_url": None,
        "image_attribution": None,
        "metabolic_rate": None,
        "reproduction_strategy": None,
        "elevation_limits": None,
        "activity_period": None,
    }
    with patch("app.llm_agent.database.get_species", return_value=fake_row):
        result = lookup_species.invoke({"scientific_name": "Rare species"})
    assert "Rare species" in result
    assert "None" not in result


def test_lookup_species_states_what_is_not_recorded():
    # The LLM mislabels general knowledge as "Database:" unless the result
    # spells out its own boundary (e.g. cat breeds, lion diet).
    from app.llm_agent import lookup_species
    fake_row = {
        "scientific_name": "Felis catus",
        "taxon_rank": "species",
        "common_names": '["Cat"]',
        "taxon_path": "Animalia|Felis|Felis catus",
        "taxonomic_status": "ACCEPTED",
        "body_mass": 3.9,
        "max_lifespan": 30.0,
    }
    with patch("app.llm_agent.database.get_species", return_value=fake_row):
        result = lookup_species.invoke({"scientific_name": "Felis catus"})
    not_recorded = next(l for l in result.splitlines() if l.startswith("- Not recorded:"))
    assert "habitat" in not_recorded and "diet" in not_recorded
    assert "body mass" not in not_recorded
    assert "END OF DATABASE RESULT" in result
    assert "From general knowledge:" in result


# ── semantic_search_species ───────────────────────────────────────────────────

def test_semantic_search_empty_store():
    from app.llm_agent import semantic_search_species
    with patch("app.llm_agent.vector_db.semantic_search", return_value=[]):
        result = semantic_search_species.invoke({"query": "big cats"})
    assert "no results" in result.lower() or "lookup_species" in result.lower()


def test_semantic_search_formats_results():
    from app.llm_agent import semantic_search_species
    fake_results = [
        {
            "scientific_name": "Panthera leo",
            "common_names": ["Lion"],
            "taxon_rank": "species",
            "distance": 0.12,
            "abstract_snippet": "The lion is a large cat.",
        }
    ]
    with patch("app.llm_agent.vector_db.semantic_search", return_value=fake_results):
        result = semantic_search_species.invoke({"query": "big cats Africa"})
    assert "Panthera leo" in result
    assert "Lion" in result
    assert "lion is a large cat" in result


# ── get_species_image ─────────────────────────────────────────────────────────

def test_get_species_image_species_not_found():
    from app.llm_agent import get_species_image
    with patch("app.llm_agent.database.get_species", return_value=None):
        result = get_species_image.invoke({"scientific_name": "Fakeus sp"})
    data = json.loads(result)
    assert "error" in data


def test_get_species_image_returns_db_url():
    from app.llm_agent import get_species_image
    fake_row = {
        "primary_image_url": "https://example.com/lion.jpg",
        "image_attribution": "CC BY-SA 4.0 Wikimedia",
    }
    with patch("app.llm_agent.database.get_species", return_value=fake_row):
        result = get_species_image.invoke({"scientific_name": "Panthera leo"})
    data = json.loads(result)
    assert data["url"] == "https://example.com/lion.jpg"
    assert "CC BY-SA" in data["attribution"]
    assert data["source"] == "database"


def test_get_species_image_fallback_to_wikipedia():
    from app.llm_agent import get_species_image
    fake_row = {"primary_image_url": None, "image_attribution": None, "common_names": None}
    with patch("app.llm_agent.database.get_species", return_value=fake_row), \
         patch("app.llm_agent.image_utils.fetch_image",
               return_value=("https://wiki.org/lion.jpg", "© Wikipedia")), \
         patch("app.llm_agent.database.update_species_image"):
        result = get_species_image.invoke({"scientific_name": "Panthera leo"})
    data = json.loads(result)
    assert data["url"] == "https://wiki.org/lion.jpg"
    assert data["source"] == "fetched"


def test_get_species_image_fallback_to_inaturalist():
    from app.llm_agent import get_species_image
    fake_row = {"primary_image_url": None, "image_attribution": None, "common_names": None}
    with patch("app.llm_agent.database.get_species", return_value=fake_row), \
         patch("app.llm_agent.image_utils.fetch_image",
               return_value=("https://inaturalist.org/lion.jpg", "© iNat")), \
         patch("app.llm_agent.database.update_species_image"):
        result = get_species_image.invoke({"scientific_name": "Panthera leo"})
    data = json.loads(result)
    assert data["url"] == "https://inaturalist.org/lion.jpg"
    assert data["source"] == "fetched"


def test_get_species_image_no_image_anywhere():
    from app.llm_agent import get_species_image
    fake_row = {"primary_image_url": None, "image_attribution": None, "common_names": None}
    with patch("app.llm_agent.database.get_species", return_value=fake_row), \
         patch("app.llm_agent.image_utils.fetch_image", return_value=None):
        result = get_species_image.invoke({"scientific_name": "Panthera leo"})
    data = json.loads(result)
    assert "error" in data


def test_chat_image_tool_outage_is_not_cached():
    from app.llm_agent import get_species_image
    from app.image_utils import ImagesUnavailable
    fake_row = {"primary_image_url": None, "image_attribution": None, "common_names": None,
                "taxon_rank": "species"}
    with patch("app.llm_agent.database.get_species", return_value=fake_row), \
         patch("app.llm_agent.image_utils.fetch_image", side_effect=ImagesUnavailable("x")), \
         patch("app.llm_agent.database.update_species_image") as update:
        result = get_species_image.invoke({"scientific_name": "Panthera leo"})
    assert json.loads(result) == {"error": "Picture sources are unavailable right now."}
    update.assert_not_called()


def test_chat_image_tool_passes_the_rank():
    from app.llm_agent import get_species_image
    fake_row = {"primary_image_url": None, "image_attribution": None, "common_names": None,
                "taxon_rank": "subspecies", "taxon_path": "Animalia|Tyto furcata bondi"}
    with patch("app.llm_agent.database.get_species", return_value=fake_row), \
         patch("app.llm_agent.image_utils.fetch_image", return_value=("https://x/o.jpg", "© A")) as fetch, \
         patch("app.llm_agent.database.update_species_image"):
        get_species_image.invoke({"scientific_name": "Tyto furcata bondi"})
    assert fetch.call_args.kwargs["rank"] == "subspecies"

def test_chat_image_tool_passes_rejected_as_exclude():
    from app.llm_agent import get_species_image
    fake_row = {"primary_image_url": None, "image_attribution": None, "common_names": None,
                "taxon_rank": "species", "rejected_images": '["https://w/snake.jpg"]'}
    with patch("app.llm_agent.database.get_species", return_value=fake_row), \
         patch("app.llm_agent.image_utils.fetch_image", return_value=("https://i/g.jpg", "© A")) as fetch, \
         patch("app.llm_agent.database.update_species_image"):
        get_species_image.invoke({"scientific_name": "Oreamnos americanus"})
    assert fetch.call_args.kwargs["exclude"] == {"https://w/snake.jpg"}

# ── stream_response ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stream_response_yields_token_events():
    from app.llm_agent import stream_response
    from langchain_core.messages import AIMessageChunk

    token_chunk = AIMessageChunk(content="The lion")
    events = [
        {"event": "on_chat_model_stream", "data": {"chunk": token_chunk}},
        {"event": "on_chain_end", "data": {}},
    ]

    mock_agent = MagicMock()
    # No tool call: the answer is asked again, so each run gets fresh events
    mock_agent.astream_events = MagicMock(side_effect=lambda *a, **k: _async_iter(events))

    with patch("app.llm_agent.build_agent", return_value=mock_agent):
        chunks = []
        async for chunk in stream_response("Tell me about lions"):
            chunks.append(chunk)

    token_events = [c for c in chunks if '"type": "token"' in c]
    done_events = [c for c in chunks if '"type": "done"' in c]
    assert len(token_events) >= 1
    assert len(done_events) == 1
    assert "The lion" in token_events[0]


@pytest.mark.asyncio
async def test_stream_response_yields_image_event_on_tool_end():
    from app.llm_agent import stream_response

    image_payload = json.dumps({"url": "https://example.com/lion.jpg", "attribution": "CC"})
    events = [
        {
            "event": "on_tool_end",
            "name": "get_species_image",
            "data": {"output": image_payload},
        },
    ]

    mock_agent = MagicMock()
    mock_agent.astream_events = MagicMock(return_value=_async_iter(events))

    with patch("app.llm_agent.build_agent", return_value=mock_agent):
        chunks = []
        async for chunk in stream_response("Show me a lion"):
            chunks.append(chunk)

    image_events = [c for c in chunks if '"type": "image"' in c]
    assert len(image_events) == 1
    data = json.loads(image_events[0].replace("data: ", ""))
    assert data["url"] == "https://example.com/lion.jpg"


# ── _filter_json_blobs ────────────────────────────────────────────────────────

def test_filter_passes_plain_text():
    from app.llm_agent import _filter_json_blobs
    state = {"depth": 0, "buf": ""}
    assert _filter_json_blobs("hello world", state) == "hello world"


def test_filter_suppresses_tool_call_json():
    from app.llm_agent import _filter_json_blobs
    state = {"depth": 0, "buf": ""}
    blob = '{"name": "lookup_species", "parameters": {"scientific_name": "Panthera leo"}}'
    result = _filter_json_blobs(blob, state)
    assert result == ""
    assert state["depth"] == 0  # fully consumed


def test_filter_keeps_text_before_json():
    from app.llm_agent import _filter_json_blobs
    state = {"depth": 0, "buf": ""}
    text = 'Here is the answer. {"name": "lookup_species", "parameters": {}}'
    result = _filter_json_blobs(text, state)
    assert result == "Here is the answer. "


def test_filter_keeps_non_tool_json():
    from app.llm_agent import _filter_json_blobs
    state = {"depth": 0, "buf": ""}
    text = 'Range: {"lat_min": -35, "lat_max": 10}'
    result = _filter_json_blobs(text, state)
    assert '{"lat_min"' in result


def test_filter_handles_split_tokens():
    """JSON arriving across multiple token calls must still be suppressed."""
    from app.llm_agent import _filter_json_blobs
    state = {"depth": 0, "buf": ""}
    tokens = ['{"name"', ': "lookup_species"', ', "parameters": {}}']
    result = "".join(_filter_json_blobs(tok, state) for tok in tokens)
    assert result == ""


def test_filter_flushes_incomplete_brace_as_text():
    """Unterminated '{' that doesn't match tool-call pattern is preserved."""
    from app.llm_agent import _filter_json_blobs
    state = {"depth": 0, "buf": ""}
    # Stream ends with an unclosed brace — flush will emit it
    _ = _filter_json_blobs("{incomplete", state)
    assert state["buf"] == "{incomplete"
    assert state["depth"] == 1


async def _async_iter(items):
    for item in items:
        yield item


# ── Source-label verification ─────────────────────────────────────────────────

_LION_RESULT = "\n".join([
    "DATABASE RESULT: FOUND — Panthera leo is in the database.",
    "**Panthera leo** (species rank)",
    "- Common names: Lion, African lion",
    "- Lineage: Animalia → Chordata → Mammalia → Carnivora → Felidae → Panthera → Panthera leo",
    "- Taxonomic status: ACCEPTED",
    "- Body mass: 175.0 kg",
    "- Max lifespan: 28.0 years",
    "- IUCN status: VU",
    "- Population trend: Decreasing",
])


def _check(text: str, tool_output: str | None = _LION_RESULT) -> str:
    from app.llm_agent import LabelChecker
    checker = LabelChecker()
    if tool_output:
        checker.add_tool_output(tool_output)
    # Feed in small chunks to exercise buffering across token boundaries
    out = "".join(checker.feed(text[i:i + 7]) for i in range(0, len(text), 7))
    return out + checker.flush()


def test_label_kept_when_sentence_uses_db_value():
    text = "Database: Panthera leo has a body mass of 175 kg."
    assert _check(text) == text


def test_label_kept_for_iucn_name_and_trend():
    text = "Database: The lion is listed as Vulnerable and its population is decreasing."
    assert _check(text) == text


def test_label_kept_for_lineage_fact():
    text = "Database: The lion belongs to the family Felidae."
    assert _check(text) == text


def test_label_corrected_when_fact_not_in_result():
    text = "Database: Lions eat zebras, antelopes and wildebeest."
    assert _check(text) == "From general knowledge: Lions eat zebras, antelopes and wildebeest."


def test_label_corrected_per_sentence_within_segment():
    text = "Database: The lion weighs 175 kg. Its diet consists of zebras."
    assert _check(text) == (
        "Database: The lion weighs 175 kg. "
        "From general knowledge: Its diet consists of zebras."
    )


def test_general_knowledge_label_untouched():
    text = "From general knowledge: Lions live in prides. They hunt at night."
    assert _check(text) == text


def test_numbers_not_in_result_do_not_count():
    text = "Database: There are over 70 recognised cat breeds."
    assert _check(text) == "From general knowledge: There are over 70 recognised cat breeds."


def test_every_db_label_corrected_without_tool_result():
    text = "Database: Lions weigh 175 kg."
    assert _check(text, tool_output=None) == "From general knowledge: Lions weigh 175 kg."


def test_species_own_name_is_not_evidence():
    text = "Database: Panthera leo hunts in groups."
    assert _check(text) == "From general knowledge: Panthera leo hunts in groups."


def test_summary_overlap_counts_as_db_fact():
    summary = ("\n**Summary:** The lion is a large cat of the genus Panthera native to "
               "Africa and India. It has a muscular, broad-chested body and a short, rounded head.")
    text = "Database: The lion is native to Africa and India with a muscular, broad-chested body."
    assert _check(text, _LION_RESULT + summary) == text


_DEVIL = "\n".join([
    "DATABASE RESULT: FOUND — Moloch horridus is in the database.",
    "**Moloch horridus** (species rank)",
    "- Lineage: Animalia → Chordata → Reptilia → Squamata → Agamidae → Moloch → Moloch horridus",
    "\n**Summary:** The thorny devil is a species of lizard in the family Agamidae. "
    "It grows up to 21 cm (8.3 in) in total length.",
])


def test_summary_overlap_with_unsupported_number_is_general_knowledge():
    text = "Database: Moloch horridus is a species of lizard that can live up to 20 years in the wild."
    assert _check(text, _DEVIL) == (
        "From general knowledge: Moloch horridus is a species of lizard "
        "that can live up to 20 years in the wild.")


def test_summary_overlap_with_a_summary_number_keeps_its_label():
    text = "Database: This species of lizard grows up to 21 cm in total length."
    assert _check(text, _DEVIL) == text


@pytest.mark.asyncio
async def test_stream_response_corrects_mislabelled_sentence():
    from app.llm_agent import stream_response
    from langchain_core.messages import AIMessageChunk

    events = [
        {"event": "on_tool_start", "name": "lookup_species", "data": {"input": {}}},
        {"event": "on_tool_end", "name": "lookup_species", "data": {"output": _LION_RESULT}},
        {"event": "on_chat_model_stream",
         "data": {"chunk": AIMessageChunk(content="Database: Lions eat zebras.")}},
    ]
    mock_agent = MagicMock()
    mock_agent.astream_events = MagicMock(return_value=_async_iter(events))

    with patch("app.llm_agent.build_agent", return_value=mock_agent):
        text = ""
        async for chunk in stream_response("what does a lion eat"):
            if '"type": "token"' in chunk:
                text += json.loads(chunk[len("data: "):])["content"]
    assert text == "From general knowledge: Lions eat zebras."


# ── Increment 12: sourced traits in chat, "Database (estimated):" label ──────

from app import trait_utils
from app.database import TraitValue

_EST_SRC = "Estimated from Wikipedia description"


@pytest.fixture(autouse=True)
def _no_trait_network(monkeypatch):
    """lookup_species runs the sourced stage; keep every test here offline."""
    monkeypatch.setattr(trait_utils, "run_sourced_stage", lambda row: ({}, True))
    monkeypatch.setattr(trait_utils, "run_estimate_stage",
                        lambda row: pytest.fail("chat must never run the estimate stage"))
    monkeypatch.setattr("app.llm_agent.database.update_species_traits", lambda *a, **k: True)


def _lion_row(**kw):
    return {"scientific_name": "Panthera leo", "taxon_rank": "species", "common_names": '["Lion"]',
            "taxon_path": "Animalia|Chordata|Mammalia|Carnivora|Felidae|Panthera|Panthera leo",
            "taxonomic_status": "ACCEPTED", "trait_sources": None, **kw}


def test_lookup_species_runs_sourced_stage_once(monkeypatch):
    from app.llm_agent import lookup_species
    calls, writes = [], []
    def _stage(row):
        calls.append(row["scientific_name"])
        return {"habitat_type": TraitValue("Savanna", "IUCN Red List")}, True
    monkeypatch.setattr(trait_utils, "run_sourced_stage", _stage)
    monkeypatch.setattr("app.llm_agent.database.update_species_traits",
                        lambda *a, **k: writes.append(a) or True)
    stored = _lion_row(habitat_type="Savanna",
                       trait_sources='{"habitat_type": {"source": "IUCN Red List", "estimated": false}, "_sourced": "2026-11-03"}')
    rows = iter([_lion_row(), stored])
    with patch("app.llm_agent.database.get_species", side_effect=lambda n: next(rows)):
        result = lookup_species.invoke({"scientific_name": "Panthera leo"})
    assert calls == ["Panthera leo"] and len(writes) == 1 and writes[0][2] == "sourced"
    assert "- Habitat: Savanna" in result

    calls.clear()
    with patch("app.llm_agent.database.get_species", return_value=stored):
        lookup_species.invoke({"scientific_name": "Panthera leo"})
    assert calls == []


def test_lookup_species_tags_estimated_lines():
    from app.llm_agent import lookup_species
    row = _lion_row(activity_period="nocturnal", body_mass=190.0, trait_sources=(
        '{"_sourced": "2026-11-03", "activity_period": {"source": "%s", "estimated": true}}' % _EST_SRC))
    with patch("app.llm_agent.database.get_species", return_value=row):
        result = lookup_species.invoke({"scientific_name": "Panthera leo"})
    assert "- Activity period: nocturnal (estimated)" in result
    assert "- Body mass: 190 kg\n" in result + "\n" and "190 kg (estimated)" not in result


def test_lookup_species_lists_new_trait_lines():
    from app.llm_agent import lookup_species
    row = _lion_row(elevation_limits="0–4,200 m", reproduction_strategy="live birth",
                    trait_sources='{"_sourced": "2026-11-03"}')
    with patch("app.llm_agent.database.get_species", return_value=row):
        result = lookup_species.invoke({"scientific_name": "Panthera leo"})
    assert "- Elevation: 0–4,200 m" in result and "- Reproduction: live birth" in result


def test_lookup_species_survives_stage_failure(monkeypatch):
    from app.llm_agent import lookup_species
    def _boom(row):
        raise RuntimeError("source exploded")
    monkeypatch.setattr(trait_utils, "run_sourced_stage", _boom)
    with patch("app.llm_agent.database.get_species", return_value=_lion_row(iucn_status="VU")):
        result = lookup_species.invoke({"scientific_name": "Panthera leo"})
    assert "DATABASE RESULT: FOUND" in result and "- IUCN status: VU" in result


_EST_RESULT = _LION_RESULT + "\n- Activity period: nocturnal (estimated)\n- Body mass: 175.0 kg (estimated)"


def test_label_estimated_only_support_becomes_estimated_label():
    assert _check("Database: It is nocturnal.", _EST_RESULT) == "Database (estimated): It is nocturnal."


def test_label_estimated_without_support_becomes_general():
    assert _check("Database (estimated): It eats seals.", _EST_RESULT) == \
        "From general knowledge: It eats seals."


def test_label_estimated_kept_when_supported():
    text = "Database (estimated): Lions are mostly nocturnal."
    assert _check(text, _EST_RESULT) == text


def test_label_parsing_new_label_not_split():
    out = _check("Database (estimated): It is nocturnal.", _EST_RESULT)
    assert out == "Database (estimated): It is nocturnal." and "Database: (estimated)" not in out


def test_label_variants_normalised():
    assert _check("database (Estimated): It is nocturnal.", _EST_RESULT) == \
        "Database (estimated): It is nocturnal."
    assert _check("Database(estimated): It is nocturnal.", _EST_RESULT) == \
        "Database (estimated): It is nocturnal."


def test_value_in_both_sourced_and_estimated_counts_as_sourced():
    text = "Database: Panthera leo weighs 175 kg."
    assert _check(text, _EST_RESULT) == text


def test_label_estimated_upgraded_when_value_is_sourced():
    assert _check("Database (estimated): It is listed as VU.", _EST_RESULT) == \
        "Database: It is listed as VU."


def test_prompt_documents_estimated_label():
    from app.llm_agent import _SYSTEM_PROMPT, _DB_EST_LABEL
    assert _DB_EST_LABEL == "Database (estimated):"
    assert _DB_EST_LABEL in _SYSTEM_PROMPT and "(estimated)" in _SYSTEM_PROMPT


def test_lookup_species_rounds_converted_numbers():
    # Wikidata 6.2 oz → 0.17576704337500001 kg; the LLM writes "0.176 kg", which
    # must match the tool line or a database fact gets relabelled general knowledge
    from app.llm_agent import lookup_species
    row = _lion_row(body_mass=0.17576704337500001, body_length=2.5, max_lifespan=43.8,
                    trait_sources='{"_sourced": "2026-11-03"}')
    with patch("app.llm_agent.database.get_species", return_value=row):
        result = lookup_species.invoke({"scientific_name": "Panthera leo"})
    assert "- Body mass: 0.176 kg" in result
    assert "- Body length: 2.5 m" in result and "- Max lifespan: 43.8 years" in result
    assert _check("Database: It weighs about 0.176 kg.", result) == "Database: It weighs about 0.176 kg."


def test_label_kept_for_part_of_multi_value_habitat():
    # Live: IUCN habitat list paraphrased by the model was relabelled general knowledge
    result = _LION_RESULT + ("\n- Habitat: Grassland - Subtropical/Tropical Dry; Shrubland - Subtropical/Tropical Dry;"
                             " Savanna - Dry")
    text = "Database: The habitat of Panthera leo includes grassland, dry shrubland and dry savanna."
    assert _check(text, result) == text
    assert _check("Database: Lions live in rainforest.", result) == "From general knowledge: Lions live in rainforest."


# ── Final-review fixes ────────────────────────────────────────────────────────

def test_not_recorded_line_is_not_evidence():
    result = _LION_RESULT + "\n- Not recorded: body mass, lifespan, diet / trophic level, reproduction"
    assert _check("Database: Its lifespan is about 15 years in the wild.", result) == \
        "From general knowledge: Its lifespan is about 15 years in the wild."
    assert _check("Database: Its reproduction involves a long gestation.", result).startswith(
        "From general knowledge:")


def test_mixed_sourced_and_estimated_sentence_is_estimated():
    result = _EST_RESULT + "\n- Habitat: Savanna - Dry"
    assert _check("Database: Lions live in savanna and are nocturnal.", result) == \
        "Database (estimated): Lions live in savanna and are nocturnal."


# ── Increment 19: database query tools ────────────────────────────────────────

_EAGLE_OWL = {
    "scientific_name": "Bubo bubo", "taxon_rank": "species",
    "common_names": '["Eurasian eagle-owl"]',
    "taxon_path": "Animalia|Chordata|Aves|Strigiformes|Strigidae|Bubo|Bubo bubo",
}


def test_find_species_lists_matches_with_lineage(monkeypatch):
    from app import taxon_queries
    from app.llm_agent import find_species
    monkeypatch.setattr(taxon_queries, "find_matches", lambda name, limit=5: [_EAGLE_OWL])
    out = find_species.invoke({"name": "eagle owl"})
    assert out.startswith("DATABASE RESULT: FOUND — 1 match for 'eagle owl'.")
    assert "**Bubo bubo** (species rank)" in out
    assert "- Common names: Eurasian eagle-owl" in out
    assert "- Lineage: Animalia → Chordata → Aves → Strigiformes → Strigidae → Bubo → Bubo bubo" in out
    assert out.rstrip().splitlines()[-1].startswith("END OF DATABASE RESULT.")


def test_find_species_no_match_says_so(monkeypatch):
    from app import taxon_queries
    from app.llm_agent import find_species
    monkeypatch.setattr(taxon_queries, "find_matches", lambda name, limit=5: [])
    out = find_species.invoke({"name": "owlz"})
    assert out.startswith("DATABASE RESULT: No species")
    assert "From general knowledge:" in out


@pytest.mark.asyncio
async def test_stream_response_feeds_find_species_output_to_label_checker():
    from app.llm_agent import stream_response
    from langchain_core.messages import AIMessageChunk

    result = "\n".join([
        "DATABASE RESULT: FOUND — 1 match for 'eagle owl'.",
        "**Bubo bubo** (species rank)",
        "- Common names: Eurasian eagle-owl",
        "END OF DATABASE RESULT.",
    ])
    events = [
        {"event": "on_tool_start", "name": "find_species", "data": {"input": {}}},
        {"event": "on_tool_end", "name": "find_species", "data": {"output": result}},
        {"event": "on_chat_model_stream",
         "data": {"chunk": AIMessageChunk(content="Database: Its name is Eurasian eagle-owl.")}},
    ]
    mock_agent = MagicMock()
    mock_agent.astream_events = MagicMock(return_value=_async_iter(events))
    with patch("app.llm_agent.build_agent", return_value=mock_agent):
        text = ""
        async for chunk in stream_response("what is the eagle owl called"):
            if '"type": "token"' in chunk:
                text += json.loads(chunk[len("data: "):])["content"]
    assert text == "Database: Its name is Eurasian eagle-owl."


_STRIGIFORMES = {"scientific_name": "Strigiformes", "taxon_rank": "order",
                 "taxon_path": "Animalia|Chordata|Aves|Strigiformes", "common_names": '["Owls"]'}
_RANKED = [dict(_EAGLE_OWL, max_lifespan=68.0, rank_value=68.0),
           {"scientific_name": "Tyto alba", "taxon_rank": "species", "common_names": "[]",
            "taxon_path": "Animalia|Chordata|Aves|Strigiformes|Strigidae|Tyto|Tyto alba",
            "max_lifespan": 34.0, "rank_value": 34.0}]


resolved: list[dict] = []   # kwargs of the latest resolve_taxon calls


def _rank(monkeypatch, group_row=_STRIGIFORMES, ranked=(2, _RANKED), **args):
    from app import taxon_queries
    from app.llm_agent import rank_species_by_trait
    calls = []
    resolved.clear()
    monkeypatch.setattr(taxon_queries, "resolve_taxon", lambda name, **kw: resolved.append(kw) or group_row)
    def fake_rank(column, path, highest, limit):
        calls.append((column, path, highest, limit))
        return ranked
    monkeypatch.setattr(taxon_queries, "rank_by_trait", fake_rank)
    return rank_species_by_trait.invoke({"trait": "lifespan", "group": "owls", **args}), calls


def test_rank_tool_states_coverage_and_caveat(monkeypatch):
    out, calls = _rank(monkeypatch)
    assert calls == [("max_lifespan", "Animalia|Chordata|Aves|Strigiformes", True, 10)]
    assert "among 2 species in Strigiformes with a recorded max lifespan" in out
    assert "- #1 Bubo bubo (Eurasian eagle-owl): 68 years" in out
    assert "- #2 Tyto alba: 34 years" in out
    assert "maximum recorded or estimated" in out
    assert out.rstrip().splitlines()[-1].startswith("END OF DATABASE RESULT.")


def test_rank_tool_lowest_and_clamped_limit(monkeypatch):
    _, calls = _rank(monkeypatch, order="lowest", limit=500)
    assert calls[0][2:] == (False, 20)


def test_rank_tool_unknown_trait_lists_supported_ones(monkeypatch):
    out, calls = _rank(monkeypatch, trait="diet")
    assert not calls and out.startswith("DATABASE RESULT:")
    assert "lifespan" in out and "mass" in out and "length" in out


def test_rank_tool_unknown_group(monkeypatch):
    out, calls = _rank(monkeypatch, group_row=None)
    assert not calls and "No group found" in out and "From general knowledge:" in out


def test_rank_tool_no_values_in_group(monkeypatch):
    out, _ = _rank(monkeypatch, ranked=(0, []))
    assert "No species in Strigiformes has a recorded max lifespan" in out


def test_label_checker_accepts_ranked_name(monkeypatch):
    out, _ = _rank(monkeypatch)
    text = "Database: The longest-lived owl recorded is the Eurasian eagle-owl."
    assert _check(text, out) == text


def test_named_prefers_a_latin_script_common_name():
    from app.llm_agent import _named
    row = {"scientific_name": "Sebastes aleutianus",
           "common_names": '["\u963f\u7559\u7533\u5e73\u9b8b", "Rougheye rockfish"]'}
    assert _named(row) == "Sebastes aleutianus (Rougheye rockfish)"


_SUMMARY = {
    "species": 5, "extinct": 1, "iucn": {"EN": 1, "NT": 1, "LC": 2},
    "trends": {"Decreasing": 1, "Stable": 1},
    "threatened": [{"scientific_name": "Strix perdita", "common_names": '["Lost owl"]',
                    "iucn_status": "EN"}],
}


def _stats(monkeypatch, group_row=_STRIGIFORMES, summary=_SUMMARY):
    from app import taxon_queries
    from app.llm_agent import group_stats
    resolved.clear()
    monkeypatch.setattr(taxon_queries, "resolve_taxon", lambda name, **kw: resolved.append(kw) or group_row)
    monkeypatch.setattr(taxon_queries, "group_summary", lambda path, examples=5: summary)
    return group_stats.invoke({"group": "owls"})


def test_group_stats_tool_lines(monkeypatch):
    out = _stats(monkeypatch)
    assert out.startswith("DATABASE RESULT: FOUND")
    for line in ("- Accepted species: 5", "- Extinct, including fossil species: 1", "- IUCN-assessed species: 4",
                 "- IUCN EN (endangered): 1", "- IUCN LC (least concern): 2",
                 "- Population trend Decreasing: 1",
                 "- Threatened examples: Strix perdita (Lost owl, EN)"):
        assert line in out.splitlines()
    assert out.rstrip().splitlines()[-1].startswith("END OF DATABASE RESULT.")


def test_group_stats_tool_unknown_group(monkeypatch):
    out = _stats(monkeypatch, group_row=None)
    assert "No group found" in out


def test_group_stats_tool_notes_iucn_coverage_and_fossils(monkeypatch):
    out = _stats(monkeypatch)
    end = out.splitlines()[-1]
    assert "Only species assessed by the IUCN have a status" in end and "fossil" in end


def test_label_checker_accepts_threatened_example_without_code_as_phrase(monkeypatch):
    out = _stats(monkeypatch)
    assert _check("Database: The lost owl is one of them.", out) == "Database: The lost owl is one of them."
    assert _check("Database: Owls hunt en masse.", out).startswith("From general knowledge:")


_STRIGIDAE_ROW = {"scientific_name": "Strigidae", "taxon_rank": "family", "common_names": '["Owls"]',
                  "taxon_path": "Animalia|Chordata|Aves|Strigiformes|Strigidae"}
_SPOTTED = {"scientific_name": "Strix occidentalis", "taxon_rank": "species",
            "common_names": '["Spotted owl"]',
            "taxon_path": "Animalia|Chordata|Aves|Strigiformes|Strigidae|Strix|Strix occidentalis"}


def _lineage_of(path):
    commons = {"Animalia": "Animal", "Mammalia": "Mammals", "Aves": "Birds",
               "Strigiformes": "Owls", "Strigidae": "Owls"}
    return [{"name": n, "rank": "", "common": commons.get(n, "")} for n in path.split("|")]


def _taxonomy(monkeypatch, row, members=(0, []), ranks=None):
    from app import taxon_queries
    from app.llm_agent import taxonomy_of
    calls = []
    monkeypatch.setattr(taxon_queries, "resolve_taxon", lambda name, **kw: row)
    monkeypatch.setattr(taxon_queries, "lineage", _lineage_of)
    monkeypatch.setattr(taxon_queries, "child_rank_counts",
                        lambda path: ranks if ranks is not None else {"family": members[0]})
    def fake_members(path, limit=15, rank=None):
        calls.append((path, limit, rank))
        return members
    monkeypatch.setattr(taxon_queries, "members", fake_members)
    return taxonomy_of.invoke({"name": "x"}), calls


def test_taxonomy_of_group_lists_members(monkeypatch):
    out, calls = _taxonomy(monkeypatch, _STRIGIFORMES, (1, [_STRIGIDAE_ROW]))
    assert calls == [("Animalia|Chordata|Aves|Strigiformes", 15, "family")]
    assert "- Lineage: Animalia (Animal) → Chordata → Aves (Birds) → Strigiformes (Owls)" in out
    assert "- Members (family, 1 in total): Strigidae (Owls)" in out.splitlines()
    assert out.rstrip().splitlines()[-1].startswith("END OF DATABASE RESULT.")


def test_taxonomy_of_species_lists_relatives(monkeypatch):
    perdita = {"scientific_name": "Strix perdita", "taxon_rank": "species", "common_names": "[]"}
    out, calls = _taxonomy(monkeypatch, _SPOTTED, (2, [_SPOTTED, perdita]))
    assert calls == [("Animalia|Chordata|Aves|Strigiformes|Strigidae|Strix", 11, None)]
    rel = next(l for l in out.splitlines() if l.startswith("- Relatives in genus Strix:"))
    assert "Strix perdita" in rel and "occidentalis" not in rel


def test_taxonomy_of_unknown(monkeypatch):
    out, calls = _taxonomy(monkeypatch, None)
    assert "No species or group found" in out and not calls


def test_label_checker_accepts_member_name(monkeypatch):
    out, _ = _taxonomy(monkeypatch, _STRIGIFORMES, (1, [_STRIGIDAE_ROW]))
    assert _check("Database: Owls include the family Strigidae.", out) == \
        "Database: Owls include the family Strigidae."


def test_label_checker_reads_scientific_names_in_lineage(monkeypatch):
    out, _ = _taxonomy(monkeypatch, _SPOTTED, (1, [_SPOTTED]))
    assert _check("Database: It belongs to the order Strigiformes.", out) == \
        "Database: It belongs to the order Strigiformes."


# ── Increment 19 review fixes ─────────────────────────────────────────────────

def test_group_tools_resolve_groups_only(monkeypatch):
    _rank(monkeypatch)
    assert resolved == [{"groups_only": True}]
    _stats(monkeypatch)
    assert resolved == [{"groups_only": True}]


def test_rank_tool_ascending_means_lowest(monkeypatch):
    for word in ("ascending", "asc", "min", "minimum", "youngest", "fewest"):
        _, calls = _rank(monkeypatch, order=word)
        assert calls[0][2] is False, word


def test_taxonomy_of_lists_the_next_rank_and_counts_the_others(monkeypatch):
    aves = {"scientific_name": "Aves", "taxon_rank": "class", "common_names": '["Birds"]',
            "taxon_path": "Animalia|Chordata|Aves"}
    out, calls = _taxonomy(monkeypatch, aves, (42, [_STRIGIFORMES]),
                           ranks={"order": 42, "family": 71, "genus": 125})
    assert calls == [("Animalia|Chordata|Aves", 15, "order")]
    assert "- Members (order, 42 in total): Strigiformes (Owls)" in out.splitlines()
    assert "- Other direct children: family 71, genus 125" in out.splitlines()


def test_label_checker_ignores_common_names_of_lineage_and_members(monkeypatch):
    felis = {"scientific_name": "Felis", "taxon_rank": "genus", "common_names": '["Cat"]'}
    felidae = {"scientific_name": "Felidae", "taxon_rank": "family", "common_names": '["Cats"]',
               "taxon_path": "Animalia|Chordata|Mammalia|Carnivora|Felidae"}
    out, _ = _taxonomy(monkeypatch, felidae, (1, [felis]), ranks={"genus": 1})
    for text in ("Database: A cat can sleep 16 hours a day.",
                 "Database: The lion is the most social animal in Africa."):
        assert _check(text, out).startswith("From general knowledge:"), text
    assert _check("Database: Felidae includes the genus Felis.", out) == \
        "Database: Felidae includes the genus Felis."


def test_label_checker_group_counts_need_a_count_word(monkeypatch):
    out = _stats(monkeypatch, summary=dict(_SUMMARY, iucn={"CR": 4, "LC": 2}))
    assert _check("Database: Owls usually lay 2 to 4 eggs.", out).startswith("From general knowledge:")
    assert _check("Database: 4 owl species are critically endangered.", out) == \
        "Database: 4 owl species are critically endangered."


def test_label_checker_reads_thousands_separators():
    result = "DATABASE RESULT: FOUND — statistics for Mammalia.\n- Accepted species: 9642"
    assert _check("Database: Mammals have 9,642 accepted species.", result) == \
        "Database: Mammals have 9,642 accepted species."
    ranked = "DATABASE RESULT: FOUND — top 1.\n- #1 Anoxycalyx joubini: 15000 years"
    assert _check("Database: It can live 15,000 years.", ranked) == "Database: It can live 15,000 years."


def test_label_checker_group_lineage_keeps_its_parent(monkeypatch):
    out, _ = _taxonomy(monkeypatch, _STRIGIFORMES, (1, [_STRIGIDAE_ROW]))
    assert _check("Database: They are in the class Aves.", out) == "Database: They are in the class Aves."


# ── Increment 20: denials the database contradicts; deferred minors ───────────

_TURTLES = "\n".join([
    "DATABASE RESULT: FOUND — top 3 by max lifespan among 105 species in Testudines "
    "with a recorded max lifespan.",
    "- #1 Aldabrachelys gigantea (Aldabra giant tortoise): 152 years",
    "- #2 Terrapene carolina (American Box Turtle): 138 years",
    "- #3 Caretta caretta (Common Loggerhead Turtle): 77 years",
    "END OF DATABASE RESULT.",
])


def test_denial_contradicted_by_the_ranking_is_replaced_with_the_count():
    text = ("From general knowledge: While there are no turtles that have been recorded to live "
            "over 100 years, some species have been known to live up to 152 years. "
            "Database: The Aldabra giant tortoise has a recorded max lifespan of 152 years.")
    assert _check(text, _TURTLES) == (
        "Database: 2 of the 3 ranked species exceed 100 years. "
        "Database: The Aldabra giant tortoise has a recorded max lifespan of 152 years.")


def test_denial_below_a_threshold_contradicted_by_the_ranking():
    ranked = "\n".join(["DATABASE RESULT: FOUND — bottom 2 by body mass among 9 species in Strigidae.",
                        "- #1 Micrathene whitneyi (Elf owl): 0.04 kg",
                        "- #2 Glaucidium minutissimum: 0.05 kg"])
    assert _check("From general knowledge: No owl weighs less than 0.045 kg.", ranked) == \
        "Database: 1 of the 2 ranked species are below 0.045 kg."


def test_denial_the_ranking_supports_is_kept():
    for text in ("From general knowledge: No turtle lives longer than 200 years.",
                 "From general knowledge: Turtles have no teeth, and some live over 100 years."):
        assert _check(text, _TURTLES) == text, text


def test_denial_without_a_ranking_is_kept():
    text = "From general knowledge: No lion lives over 30 years."
    assert _check(text) == text


def test_rank_tool_accepts_trait_names_with_spaces(monkeypatch):
    for trait, column in (("body mass", "body_mass"), ("Max Lifespan", "max_lifespan"),
                          ("body-length", "body_length")):
        _, calls = _rank(monkeypatch, ranked=(0, []), trait=trait)
        assert calls and calls[0][0] == column, trait


def test_named_keeps_list_separators_out_of_common_names():
    from app.llm_agent import _named
    row = {"scientific_name": "Tyto alba", "common_names": '["Owl; barn: white"]'}
    assert _named(row) == "Tyto alba (Owl, barn - white)"


def test_find_species_lineage_evidence_only_for_the_first_match(monkeypatch):
    from app import taxon_queries
    from app.llm_agent import find_species
    barn = {"scientific_name": "Tyto alba", "taxon_rank": "species", "common_names": '["Barn owl"]',
            "taxon_path": "Animalia|Chordata|Aves|Strigiformes|Tytonidae|Tyto|Tyto alba"}
    monkeypatch.setattr(taxon_queries, "find_matches", lambda name, limit=5: [_EAGLE_OWL, barn])
    out = find_species.invoke({"name": "owl"})
    assert sum(l.startswith("- Lineage:") for l in out.splitlines()) == 1
    assert "- Lineage (other match): Animalia → Chordata → Aves → Strigiformes → Tytonidae" in out
    assert _check("Database: It belongs to the family Tytonidae.", out).startswith("From general knowledge:")
    assert _check("Database: It belongs to the family Strigidae.", out) == \
        "Database: It belongs to the family Strigidae."


def test_label_checker_subspecies_lineage_excludes_genus_and_species(monkeypatch):
    sub = {"scientific_name": "Panthera leo leo", "taxon_rank": "subspecies", "common_names": "[]",
           "taxon_path": "Animalia|Chordata|Mammalia|Carnivora|Felidae|Panthera|Panthera leo|Panthera leo leo"}
    out, _ = _taxonomy(monkeypatch, sub, ranks={})
    assert _check("Database: Panthera leo leo lives in North Africa.", out).startswith(
        "From general knowledge:")
    assert _check("Database: It is in the family Felidae.", out) == "Database: It is in the family Felidae."


# ── Increment 21: conversation memory, tool choice ────────────────────────────

async def _run_with_history(history):
    from app.llm_agent import stream_response
    mock_agent = MagicMock()
    mock_agent.astream_events = MagicMock(return_value=_async_iter([]))
    with patch("app.llm_agent.build_agent", return_value=mock_agent):
        async for _ in stream_response("what does it eat", history):
            pass
    return mock_agent.astream_events.call_args_list[0].args[0]["messages"]   # first attempt


@pytest.mark.asyncio
async def test_stream_response_sends_history_before_the_question():
    from langchain_core.messages import AIMessage, HumanMessage
    msgs = await _run_with_history([
        {"role": "user", "content": "what is the largest animal"},
        {"role": "assistant", "content": "Database: The Blue whale (Balaenoptera musculus)."}])
    assert [type(m) for m in msgs] == [HumanMessage, AIMessage, HumanMessage]
    assert msgs[1].content == "Database: The Blue whale (Balaenoptera musculus)."
    assert msgs[-1].content == "what does it eat"


@pytest.mark.asyncio
async def test_stream_response_caps_history():
    from app.llm_agent import HISTORY_MAX_MESSAGES, HISTORY_MAX_CHARS
    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i} " + "x" * 5000}
               for i in range(20)]
    msgs = await _run_with_history(history)
    assert len(msgs) == HISTORY_MAX_MESSAGES + 1
    assert msgs[0].content.startswith(f"m{20 - HISTORY_MAX_MESSAGES} ")
    assert all(len(m.content) <= HISTORY_MAX_CHARS for m in msgs[:-1])


@pytest.mark.asyncio
async def test_stream_response_without_history_sends_only_the_question():
    msgs = await _run_with_history(None)
    assert [m.content for m in msgs] == ["what does it eat"]


def test_follow_up_rules_only_in_the_prompt_of_a_conversation():
    from app import llm_agent
    with patch("app.llm_agent.get_llm"), patch("app.llm_agent.create_react_agent") as make:
        llm_agent.build_agent()
        assert "FOLLOW-UP QUESTIONS" not in make.call_args.kwargs["prompt"]
        llm_agent.build_agent(follow_up=True)
        assert "FOLLOW-UP QUESTIONS" in make.call_args.kwargs["prompt"]


@pytest.mark.asyncio
async def test_stream_response_asks_for_follow_up_rules_only_with_history():
    from app.llm_agent import stream_response
    for history, expected in ((None, False), ([], False),
                              ([{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}], True)):
        mock_agent = MagicMock()
        mock_agent.astream_events = MagicMock(return_value=_async_iter([]))
        with patch("app.llm_agent.build_agent", return_value=mock_agent) as build:
            async for _ in stream_response("q2", history):
                pass
        # called once more for the no-tool retry, with the same rules
        assert {c.kwargs["follow_up"] for c in build.call_args_list} == {expected}


def test_taxonomy_of_a_species_includes_its_facts(monkeypatch):
    # llama3.1:8b calls taxonomy_of for "what does the blue whale eat" or "where does the
    # snow leopard live"; the answer must still get the species' facts and gaps
    row = dict(_SPOTTED, taxonomic_status="ACCEPTED", trait_sources='{"_sourced": "2026-11-10"}',
               habitat_type="Old-growth forest", body_mass=0.6)
    with patch("app.llm_agent.database.get_species", return_value=row):
        out, _ = _taxonomy(monkeypatch, _SPOTTED, (1, [_SPOTTED]))
    lines = out.splitlines()
    assert "- Habitat: Old-growth forest" in lines and "- Body mass: 0.6 kg" in lines
    assert any(l.startswith("- Not recorded:") and "diet" in l for l in lines)
    assert sum(l.startswith("- Lineage:") for l in lines) == 1
    assert "From general knowledge" in lines[-1]
    assert _check("Database: It lives in old-growth forest.", out) == "Database: It lives in old-growth forest."
    assert _check("Database: It eats mice.", out).startswith("From general knowledge:")


def test_taxonomy_of_a_group_has_no_species_facts(monkeypatch):
    with patch("app.llm_agent.database.get_species", side_effect=AssertionError("no lookup for a group")):
        out, _ = _taxonomy(monkeypatch, _STRIGIFORMES, (1, [_STRIGIDAE_ROW]))
    assert "- Not recorded:" not in out


def test_lookup_species_falls_back_to_the_closest_name(monkeypatch):
    from app import taxon_queries
    from app.llm_agent import lookup_species
    row = _lion_row(scientific_name="Cinachyra antarctica", trait_sources='{"_sourced": "2026-11-10"}',
                    max_lifespan=1550.0)
    monkeypatch.setattr(taxon_queries, "closest_name",
                        lambda n: "Cinachyra antarctica" if n == "Cinachyrya antarctica" else None)
    with patch("app.llm_agent.database.get_species",
               side_effect=lambda n: row if n == "Cinachyra antarctica" else None):
        out = lookup_species.invoke({"scientific_name": "Cinachyrya antarctica"})
        missing = lookup_species.invoke({"scientific_name": "Nonexistus nonexistus"})
    assert out.splitlines()[0] == ("DATABASE RESULT: FOUND — Cinachyra antarctica is in the database "
                                   "(closest match to 'Cinachyrya antarctica').")
    assert "- Max lifespan: 1550 years" in out
    assert missing.startswith("DATABASE RESULT: No species found")


def test_label_goes_after_a_list_marker():
    ranked = "\n".join(["DATABASE RESULT: FOUND — top 2 by max lifespan among 9 species in Animalia.",
                        "- #1 Anoxycalyx joubini: 15000 years",
                        "- #2 Cinachyra antarctica: 1550 years"])
    text = ("From general knowledge: The top 2 animals are:\n"
            "Database: - #1 Anoxycalyx joubini: 15000 years\n- #2 Cinachyra antarctica: 1550 years")
    assert _check(text, ranked) == (
        "From general knowledge: The top 2 animals are:\n"
        "- Database: #1 Anoxycalyx joubini: 15000 years\n- #2 Cinachyra antarctica: 1550 years")


_LIST_ANSWER = ("From general knowledge: The top 2 animals are:\n"
                "- Database: #1 Anoxycalyx joubini: 15000 years\n"
                "- #2 Cinachyra antarctica (Antarctic sponge): 1550 years")


@pytest.mark.asyncio
async def test_list_position_in_a_follow_up_is_named():
    from app.llm_agent import stream_response
    history = [{"role": "user", "content": "top 2 oldest animals"},
               {"role": "assistant", "content": _LIST_ANSWER}]
    for question, expected in (
            ("what kind of animal is #1", "what kind of animal is #1 (#1 = Anoxycalyx joubini)"),
            ("and #2", "and #2 (#2 = Cinachyra antarctica)"),
            ("and #3", "and #3"),
            ("what about lions", "what about lions")):
        mock_agent = MagicMock()
        mock_agent.astream_events = MagicMock(return_value=_async_iter([]))
        with patch("app.llm_agent.build_agent", return_value=mock_agent):
            async for _ in stream_response(question, history):
                pass
        assert mock_agent.astream_events.call_args_list[0].args[0]["messages"][-1].content == expected


# ── Increment 22: chat model setting ──────────────────────────────────────────

def test_chat_model_defaults_and_env_override(monkeypatch):
    from app import llm_agent
    monkeypatch.delenv("AK_CHAT_MODEL", raising=False)
    assert llm_agent.chat_model() == llm_agent.OLLAMA_MODEL == "llama3.1:8b"
    monkeypatch.setenv("AK_CHAT_MODEL", "qwen3.8:27b")
    assert llm_agent.chat_model() == "qwen3.8:27b"
    monkeypatch.setenv("AK_CHAT_MODEL", "  ")
    assert llm_agent.chat_model() == "llama3.1:8b"


def test_get_llm_thinking_off_and_fixed_context(monkeypatch):
    from app import llm_agent
    monkeypatch.setenv("AK_CHAT_MODEL", "qwen3.8:27b")
    llm = llm_agent.get_llm()
    assert (llm.model, llm.reasoning, llm.temperature, llm.num_ctx) == ("qwen3.8:27b", False, 0, 16384)


@pytest.mark.asyncio
async def test_missing_model_error_names_the_model():
    # Ollama answers 404 "model 'x' not found"; the user must see that text
    from app.llm_agent import stream_response
    agent = MagicMock()
    agent.astream_events = MagicMock(side_effect=Exception("model 'qwen9:99b' not found (status code: 404)"))
    with patch("app.llm_agent.build_agent", return_value=agent):
        chunks = [c async for c in stream_response("hi")]
    errors = [json.loads(c[6:]) for c in chunks if '"type": "error"' in c]
    assert errors and "qwen9:99b" in errors[0]["detail"]


# ── Increment 22: sentences qwen3.8 writes about the tool results ─────────────

_BIRDS = "\n".join([
    "DATABASE RESULT: FOUND — top 1 by body mass among 1469 species in Aves with a recorded body mass.",
    "- #1 Struthio camelus (Common Ostrich): 111 kg",
    "END OF DATABASE RESULT. Values are the maximum recorded or estimated in the source, not typical values. "
    'Label these facts "Database:".'])


def test_label_checker_accepts_the_ranking_coverage_count():
    text = "Database: This ranking is based on 1,469 bird species in the database."
    assert _check(text, _BIRDS) == text


def test_label_checker_accepts_the_ranking_caveat():
    text = "Database: These values are maximum recorded or estimated masses, not typical ones."
    assert _check(text, _BIRDS) == text


def test_label_checker_accepts_a_not_recorded_statement_for_a_listed_field():
    result = _LION_RESULT + "\n- Not recorded: diet / trophic level, activity period"
    for text in ("Database: Diet / trophic level is not recorded in the database.",
                 "Database: The database does not record the diet of Panthera leo."):
        assert _check(text, result) == text, text
    # a field the result does hold is not "not recorded"
    assert _check("Database: Its IUCN status is not recorded.", result).startswith("From general knowledge:")
    # and a not-recorded field is still no evidence for a positive claim
    assert _check("Database: Its diet is mostly zebra.", result).startswith("From general knowledge:")


def test_label_checker_accepts_other_find_species_match_names(monkeypatch):
    from app import taxon_queries
    from app.llm_agent import find_species
    milesi = {"scientific_name": "Bubo milesi", "taxon_rank": "species", "common_names": '["Arabian eagle-owl"]',
              "taxon_path": "Animalia|Chordata|Aves|Strigiformes|Strigidae|Bubo|Bubo milesi"}
    monkeypatch.setattr(taxon_queries, "find_matches", lambda name, limit=5: [_EAGLE_OWL, milesi])
    out = find_species.invoke({"name": "eagle owl"})
    text = "Database: Other related eagle-owl species include *Bubo milesi*."
    assert _check(text, out) == text
    # the first match is the subject: its own name backs nothing
    assert _check("Database: Bubo bubo is a large owl.", out).startswith("From general knowledge:")


# ── Increment 22: an answer without a tool call is asked again ────────────────

async def _collect(stream) -> str:
    return "".join([json.loads(c[6:])["content"] async for c in stream if '"type": "token"' in c])


def _agent(events):
    a = MagicMock()
    a.astream_events = MagicMock(return_value=_async_iter(events))
    return a


def _tokens(text):
    from langchain_core.messages import AIMessageChunk
    return {"event": "on_chat_model_stream", "data": {"chunk": AIMessageChunk(content=text)}}


_TOOL = [{"event": "on_tool_start", "name": "lookup_species", "data": {"input": {}}},
         {"event": "on_tool_end", "name": "lookup_species", "data": {"output": _LION_RESULT}}]


@pytest.mark.asyncio
async def test_answer_without_a_tool_is_asked_again_with_a_nudge():
    from app.llm_agent import stream_response, _TOOL_NUDGE
    first = _agent([_tokens("From memory: lions are big.")])
    second = _agent(_TOOL + [_tokens("Database: Panthera leo has a body mass of 175 kg.")])
    with patch("app.llm_agent.build_agent", side_effect=[first, second]):
        text = await _collect(stream_response("how heavy is a lion"))
    assert text == "Database: Panthera leo has a body mass of 175 kg."
    assert second.astream_events.call_args.args[0]["messages"][-1].content == "how heavy is a lion" + _TOOL_NUDGE


@pytest.mark.asyncio
async def test_answer_with_a_tool_streams_once():
    from app.llm_agent import stream_response
    only = _agent(_TOOL + [_tokens("Database: Panthera leo has a body mass of 175 kg.")])
    with patch("app.llm_agent.build_agent", side_effect=[only]) as build:
        text = await _collect(stream_response("how heavy is a lion"))
    assert build.call_count == 1 and text == "Database: Panthera leo has a body mass of 175 kg."


@pytest.mark.asyncio
async def test_second_answer_without_a_tool_is_shown_once():
    from app.llm_agent import stream_response
    with patch("app.llm_agent.build_agent", side_effect=[_agent([_tokens("Hello!")]), _agent([_tokens("Hi there.")])]):
        assert await _collect(stream_response("hi")) == "Hi there."


@pytest.mark.asyncio
async def test_tool_called_but_no_text_is_not_retried():
    from app.llm_agent import stream_response
    with patch("app.llm_agent.build_agent", side_effect=[_agent(_TOOL)]) as build:
        assert await _collect(stream_response("how heavy is a lion")) == ""
    assert build.call_count == 1


@pytest.mark.asyncio
async def test_each_chunk_is_one_sse_event_after_holding():
    # chat_eval and other readers parse one event per chunk
    from app.llm_agent import stream_response
    events = [_tokens("Let me check. "), _tokens("One moment. ")] + _TOOL + [_tokens("Database: 175 kg.")]
    with patch("app.llm_agent.build_agent", side_effect=[_agent(events)]):
        chunks = [c async for c in stream_response("how heavy is a lion")]
    assert chunks and all(c.startswith("data: ") and c.count("data: ") == 1 for c in chunks)


# ── Increment 22 review fixes ─────────────────────────────────────────────────

def test_ranking_caveat_does_not_vouch_for_a_number():
    text = "Database: The Greenland shark has a maximum recorded or estimated lifespan of 400 years."
    assert _check(text, _BIRDS).startswith("From general knowledge:")


def test_ranking_coverage_count_needs_a_coverage_word():
    for text in ("Database: There are 1,469 species of birds.",
                 "Database: 1,469 bird species are endangered."):
        assert _check(text, _BIRDS).startswith("From general knowledge:"), text


def test_not_recorded_rule_rejects_held_fields_and_extra_claims():
    result = _LION_RESULT + "\n- Not recorded: body length, diet / trophic level"
    # body mass is recorded (175 kg); only "body length" is missing
    assert _check("Database: Its body mass is not recorded in the database.", result).startswith("From general")
    # a claim riding along with the not-recorded statement
    text = "Database: The database does not record its diet, but lions mainly hunt zebras."
    assert _check(text, result).startswith("From general knowledge:")
    # another result of the turn holds the diet
    other = "DATABASE RESULT: FOUND — Panthera tigris is in the database.\n- Trophic level: carnivore"
    from app.llm_agent import LabelChecker
    checker = LabelChecker()
    checker.add_tool_output(result)
    checker.add_tool_output(other)
    out = checker.feed("Database: The diet is not recorded in the database.") + checker.flush()
    assert out.startswith("From general knowledge:")


def test_trait_estimator_uses_the_chat_model_settings(monkeypatch):
    import langchain_ollama
    from app import trait_utils
    seen = {}

    class FakeOllama:
        def __init__(self, **kw):
            seen.update(kw)

        def invoke(self, prompt):
            return type("R", (), {"content": "{}"})()

    monkeypatch.setattr(langchain_ollama, "ChatOllama", FakeOllama)
    monkeypatch.setenv("AK_CHAT_MODEL", "qwen3.8:27b")
    assert trait_utils._call_estimator("text") == "{}"
    # same model and context as the chat: Ollama reloads a runner whose num_ctx changes,
    # and a second model next to a 17 GB one spills into RAM
    assert (seen["model"], seen["num_ctx"], seen["reasoning"], seen["format"]) == ("qwen3.8:27b", 16384, False, "json")


@pytest.mark.asyncio
async def test_second_attempt_streams_without_holding():
    # Its text is shown whatever happens: an error after it must not swallow it
    from app.llm_agent import stream_response

    async def tokens_then_error(*a, **k):
        yield _tokens("Hi there. ")
        raise Exception("connection dropped")

    second = MagicMock()
    second.astream_events = MagicMock(side_effect=tokens_then_error)
    with patch("app.llm_agent.build_agent", side_effect=[_agent([_tokens("Hello!")]), second]):
        chunks = [c async for c in stream_response("hi")]
    assert any("Hi there." in c for c in chunks)


# ── Increment 22: coverage note on "lowest" rankings ──────────────────────────

def test_lowest_ranking_with_low_coverage_carries_a_coverage_note(monkeypatch):
    from app import taxon_queries
    monkeypatch.setattr(taxon_queries, "species_count", lambda path: 1800133)
    out, _ = _rank(monkeypatch, ranked=(3612, _RANKED), order="lowest")
    assert ("- Coverage note: Only 3,612 of 1,800,133 species in Strigiformes have a recorded max lifespan, "
            "so shorter-lived species may exist.") in out


def test_coverage_note_only_for_lowest_rankings_with_low_coverage(monkeypatch):
    from app import taxon_queries
    monkeypatch.setattr(taxon_queries, "species_count", lambda path: 3)
    assert "Coverage note" not in _rank(monkeypatch, ranked=(2, _RANKED), order="lowest")[0]   # 2 of 3
    monkeypatch.setattr(taxon_queries, "species_count", lambda path: 1800133)
    assert "Coverage note" not in _rank(monkeypatch, ranked=(2, _RANKED))[0]                     # highest


_SMALLEST = "\n".join([
    "DATABASE RESULT: FOUND — bottom 1 by body mass among 3612 species in Animalia with a recorded body mass.",
    "- #1 Plethodon cinereus (Eastern red-backed salamander): 0.0005 kg",
    "- Coverage note: Only 3,612 of 1,800,133 species in Animalia have a recorded body mass, "
    "so lighter species may exist.",
    "END OF DATABASE RESULT."])
_NOTE = ("Database: Only 3,612 of 1,800,133 species in Animalia have a recorded body mass, "
         "so lighter species may exist.")


@pytest.mark.asyncio
async def test_coverage_note_is_added_to_the_answer():
    from app.llm_agent import stream_response
    events = [{"event": "on_tool_start", "name": "rank_species_by_trait", "data": {"input": {}}},
              {"event": "on_tool_end", "name": "rank_species_by_trait", "data": {"output": _SMALLEST}},
              _tokens("Database: The smallest animal is Plethodon cinereus, at 0.0005 kg.")]
    with patch("app.llm_agent.build_agent", side_effect=[_agent(events)]):
        text = await _collect(stream_response("what is the smallest animal"))
    assert text == "Database: The smallest animal is Plethodon cinereus, at 0.0005 kg.\n\n" + _NOTE


@pytest.mark.asyncio
async def test_coverage_note_not_repeated_when_the_answer_states_it():
    from app.llm_agent import stream_response
    answer = "Database: Of the 3,612 species with a recorded body mass, Plethodon cinereus is the lightest."
    events = [{"event": "on_tool_start", "name": "rank_species_by_trait", "data": {"input": {}}},
              {"event": "on_tool_end", "name": "rank_species_by_trait", "data": {"output": _SMALLEST}},
              _tokens(answer)]
    with patch("app.llm_agent.build_agent", side_effect=[_agent(events)]):
        assert await _collect(stream_response("what is the smallest animal")) == answer


# ── Increment 23: chat name links ─────────────────────────────────────────────

def _lion_rows(monkeypatch, seen=None):
    from app import taxon_links
    lion = {"scientific_name": "Panthera leo", "taxon_path": "Animalia|Panthera|Panthera leo",
            "taxon_rank": "species", "common_names": '["Lion"]'}
    def fake_rows(names):
        if seen is not None:
            seen.append(list(names))
        return [lion] if "Panthera leo" in names else []
    monkeypatch.setattr(taxon_links, "subject_rows", fake_rows)


def _types(chunks):
    return [json.loads(c[6:])["type"] for c in chunks]


@pytest.mark.asyncio
async def test_links_event_names_the_looked_up_species(monkeypatch):
    from app.llm_agent import stream_response
    _lion_rows(monkeypatch)
    events = _TOOL + [_tokens("Database: The Lion (Panthera leo) has a body mass of 175 kg.")]
    with patch("app.llm_agent.build_agent", side_effect=[_agent(events)]):
        chunks = [c async for c in stream_response("how heavy is a lion")]
    assert _types(chunks)[-2:] == ["links", "done"]
    links = json.loads(chunks[-2][6:])["links"]
    assert [l["text"] for l in links] == ["Lion", "Panthera leo"]
    assert links[0] == {"text": "Lion", "scientific_name": "Panthera leo",
                        "taxon_path": "Animalia|Panthera|Panthera leo", "taxon_rank": "species"}


@pytest.mark.asyncio
async def test_links_come_from_the_shown_attempt_only(monkeypatch):
    from app.llm_agent import stream_response
    seen = []
    _lion_rows(monkeypatch, seen)
    first = _agent([_tokens("Lions are big.")])
    second = _agent(_TOOL + [_tokens("Database: Panthera leo weighs 175 kg.")])
    with patch("app.llm_agent.build_agent", side_effect=[first, second]):
        chunks = [c async for c in stream_response("how heavy is a lion")]
    assert seen == [["Panthera leo"]]
    links = json.loads(next(c for c in chunks if '"type": "links"' in c)[6:])["links"]
    assert [l["text"] for l in links] == ["Panthera leo"]


@pytest.mark.asyncio
async def test_image_tool_has_no_subjects(monkeypatch):
    from app.llm_agent import stream_response
    seen = []
    _lion_rows(monkeypatch, seen)
    events = [{"event": "on_tool_start", "name": "get_species_image", "data": {"input": {}}},
              {"event": "on_tool_end", "name": "get_species_image",
               "data": {"output": '{"url": "http://x/lion.jpg", "attribution": "a"}'}},
              _tokens("Here is a Lion (Panthera leo).")]
    with patch("app.llm_agent.build_agent", side_effect=[_agent(events)]):
        chunks = [c async for c in stream_response("show a lion")]
    assert "links" not in _types(chunks) and seen in ([], [[]])


@pytest.mark.asyncio
async def test_no_links_event_without_a_lookup_or_after_an_error(monkeypatch):
    from app.llm_agent import stream_response
    _lion_rows(monkeypatch)
    with patch("app.llm_agent.build_agent",
               side_effect=[_agent([_tokens("Hello! Lions?")]), _agent([_tokens("Hi there, Lion fan.")])]):
        chunks = [c async for c in stream_response("hello")]
    assert _types(chunks)[-1] == "done" and "links" not in _types(chunks)

    async def failing(*args, **kwargs):
        for e in _TOOL + [_tokens("Database: The Lion ")]:
            yield e
        raise RuntimeError("model crashed")
    broken = MagicMock()
    broken.astream_events = failing
    with patch("app.llm_agent.build_agent", side_effect=[broken]):
        chunks = [c async for c in stream_response("how heavy is a lion")]
    types = _types(chunks)
    assert types[-1] == "error" and "links" not in types and "done" not in types


@pytest.mark.asyncio
async def test_a_database_error_while_linking_keeps_the_answer(monkeypatch):
    from app import taxon_links
    from app.llm_agent import stream_response
    def broken(names):
        raise RuntimeError("database is locked")
    monkeypatch.setattr(taxon_links, "subject_rows", broken)
    events = _TOOL + [_tokens("Database: The Lion weighs 175 kg.")]
    with patch("app.llm_agent.build_agent", side_effect=[_agent(events)]):
        chunks = [c async for c in stream_response("how heavy is a lion")]
    assert _types(chunks)[-1] == "done" and "links" not in _types(chunks)


@pytest.mark.asyncio
async def test_scientific_names_link_without_a_lookup(monkeypatch):
    from app import taxon_links
    from app.llm_agent import stream_response
    monkeypatch.setattr(taxon_links, "named_rows", lambda text: [
        {"scientific_name": "Pygoscelis adeliae", "taxon_path": "A|P", "taxon_rank": "species",
         "common_names": "[]"}] if "Pygoscelis adeliae" in text else [])
    events = [{"event": "on_tool_start", "name": "semantic_search_species", "data": {"input": {}}},
              {"event": "on_tool_end", "name": "semantic_search_species", "data": {"output": "- **X y** (z) [species]\n  a"}},
              _tokens("From general knowledge: the Adelie penguin (Pygoscelis adeliae).")]
    monkeypatch.setattr(taxon_links, "subject_rows", lambda names: [])
    with patch("app.llm_agent.build_agent", side_effect=[_agent(events)]):
        chunks = [c async for c in stream_response("which penguins live in antarctica")]
    links = json.loads(next(c for c in chunks if '"type": "links"' in c)[6:])["links"]
    assert [l["text"] for l in links] == ["Pygoscelis adeliae"]


# ── Increment 24: latitude-only ranges and wild record counts ─────────────────

def test_range_text_latitude_only():
    from app import llm_agent
    assert llm_agent._range_text({"lat_min": 51.6, "lat_max": 83.0, "records": 4892}) == \
        "lat 51.6–83.0, longitude not recorded (range crosses the 180° line) (4,892 wild records)"


def test_range_text_full_range_with_records():
    from app import llm_agent
    assert llm_agent._range_text({"lat_min": -38.51, "lat_max": -26.4, "lon_min": 138.6,
                                  "lon_max": 153.6, "records": 350798, "countries": 1}) == \
        "lat -38.51–-26.4, lon 138.6–153.6 (350,798 wild records)"


def test_range_text_old_row_unchanged():
    from app import llm_agent
    assert llm_agent._range_text({"lat_min": -35, "lat_max": 10, "lon_min": -18, "lon_max": 51}) == \
        "lat -35–10, lon -18–51"


def test_range_text_without_latitudes_is_none():
    from app import llm_agent
    assert llm_agent._range_text({"lat_min": 0}) is None


def test_lookup_species_latitude_only_range():
    from app.llm_agent import lookup_species
    row = _lion_row(geo_bounding_box='{"lat_min": 51.6, "lat_max": 83.0, "records": 4892}',
                    trait_sources='{"_sourced": "2026-11-03"}')
    with patch("app.llm_agent.database.get_species", return_value=row):
        result = lookup_species.invoke({"scientific_name": "Panthera leo"})
    assert "- Geographic range: lat 51.6–83.0, longitude not recorded (range crosses the 180° line)" in result
    assert "None" not in result.split("- Geographic range:")[1].splitlines()[0]


# ── Increment 24: rank by northern / southern range edge ──────────────────────

_PENGUIN = {"scientific_name": "Spheniscus mendiculus", "taxon_rank": "species",
            "common_names": '["Galápagos penguin"]', "rank_value": 0.1}


def _rank_range(monkeypatch, total=48, **args):
    from app import taxon_queries
    monkeypatch.setattr(taxon_queries, "species_count", lambda path, living_only=False: total)
    return _rank(monkeypatch, **args)


def test_fmt_lat():
    from app.llm_agent import _fmt_lat
    assert (_fmt_lat(0.1), _fmt_lat(-5.2), _fmt_lat(0), _fmt_lat(-77.5)) == ("0.1°N", "5.2°S", "0°", "77.5°S")


def test_rank_tool_northern_edge_output(monkeypatch):
    out, calls = _rank_range(monkeypatch, ranked=(20, [_PENGUIN]), trait="northernmost")
    assert calls[0][0] == "lat_max" and calls[0][2] is True
    assert "top 1 by northern range edge among 20 species in Strigiformes with a range from 1,000+ wild records" in out
    assert "- #1 Spheniscus mendiculus (Galápagos penguin): northern range edge 0.1°N" in out
    assert "leaving out the outer 0.5% of records" in out
    assert "maximum recorded or estimated" not in out
    assert out.rstrip().splitlines()[-1].startswith("END OF DATABASE RESULT.")


def test_rank_tool_southern_edge_converts_back(monkeypatch):
    out, calls = _rank_range(monkeypatch, ranked=(20, [dict(_PENGUIN, rank_value=77.5)]), trait="south")
    assert calls[0][0] == "lat_south"
    assert "southern range edge 77.5°S" in out and "by southern range edge" in out


def test_rank_tool_furthest_north_with_space(monkeypatch):
    _, calls = _rank_range(monkeypatch, ranked=(20, [_PENGUIN]), trait="furthest north")
    assert calls[0][0] == "lat_max"


def test_rank_tool_range_coverage_note_for_highest(monkeypatch):
    out, _ = _rank_range(monkeypatch, ranked=(20, [_PENGUIN]), trait="north")
    assert ("- Coverage note: Only 20 of 48 living species in Strigiformes have a range from 1,000+ wild records, "
            "so species further north may exist.") in out
    out, _ = _rank_range(monkeypatch, ranked=(20, [_PENGUIN]), trait="south")
    assert "so species further south may exist." in out


def test_rank_tool_range_no_note_when_most_have_a_range(monkeypatch):
    out, _ = _rank_range(monkeypatch, total=30, ranked=(20, [_PENGUIN]), trait="north")
    assert "Coverage note" not in out


def test_rank_tool_no_ranges_in_group(monkeypatch):
    out, _ = _rank_range(monkeypatch, ranked=(0, []), trait="north")
    assert "No species in Strigiformes has a range from 1,000+ wild records" in out


def test_rank_tool_unknown_trait_lists_north_and_south(monkeypatch):
    out, _ = _rank(monkeypatch, trait="diet")
    assert "north" in out and "south" in out


def test_label_checker_keeps_database_label_for_southern_latitude(monkeypatch):
    out, _ = _rank_range(monkeypatch, ranked=(20, [dict(_PENGUIN, scientific_name="Spheniscus humboldti",
                                                        common_names='["Humboldt penguin"]', rank_value=-5.2)]),
                         trait="north")
    assert "northern range edge 5.2°S" in out
    text = "Database: The Humboldt penguin reaches 5.2°S."
    assert _check(text, out) == text


def test_rank_tool_range_coverage_counts_living_species_only(monkeypatch):
    from app import taxon_queries
    seen = []
    monkeypatch.setattr(taxon_queries, "species_count",
                        lambda path, living_only=False: seen.append(living_only) or (20 if living_only else 58))
    out, _ = _rank(monkeypatch, ranked=(19, [_PENGUIN]), trait="north")
    assert seen == [True] and "Coverage note" not in out
    monkeypatch.setattr(taxon_queries, "species_count", lambda path, living_only=False: 48)
    out, _ = _rank(monkeypatch, ranked=(20, [_PENGUIN]), trait="north")
    assert "Only 20 of 48 living species in Strigiformes have a range from 1,000+ wild records" in out


# ── Increment 25: species named in a semantic query or a one-species group ────

_KOALA = {"scientific_name": "Phascolarctos cinereus", "taxon_rank": "species",
          "common_names": '["Koala"]',
          "taxon_path": "Animalia|Chordata|Mammalia|Diprotodontia|Phascolarctidae|Phascolarctos|"
                        "Phascolarctos cinereus"}
_KOALA_FAMILY = {"scientific_name": "Phascolarctidae", "taxon_rank": "family",
                 "common_names": '["Koalas"]',
                 "taxon_path": "Animalia|Chordata|Mammalia|Diprotodontia|Phascolarctidae"}
_FAKE_LOOKUP = ("DATABASE RESULT: FOUND — Phascolarctos cinereus is in the database.\n"
                "**Phascolarctos cinereus** (species rank)\n- Common names: Koala\n"
                "- Lineage: Animalia → Phascolarctos cinereus\n- Taxonomic status: ACCEPTED\n"
                "- IUCN status: VU\n- Geographic range: lat -38.5–-15.6\n"
                "END OF DATABASE RESULT. Report the facts.")
_SEMANTIC_HIT = [{"scientific_name": "Vombatus ursinus", "common_names": ["Wombat"],
                  "taxon_rank": "species", "distance": 0.3, "abstract_snippet": "A marsupial."}]


def _koala_named(monkeypatch):
    from app import llm_agent, taxon_queries
    monkeypatch.setattr(taxon_queries, "named_species", lambda text: _KOALA if "koala" in text else None)
    monkeypatch.setattr(llm_agent.lookup_species, "func",
                        lambda scientific_name: _FAKE_LOOKUP if scientific_name == "Phascolarctos cinereus"
                        else "DATABASE RESULT: No species found")


def test_semantic_search_leads_with_the_named_species(monkeypatch):
    from app.llm_agent import semantic_search_species
    _koala_named(monkeypatch)
    with patch("app.llm_agent.vector_db.semantic_search", return_value=_SEMANTIC_HIT):
        out = semantic_search_species.invoke({"query": "koalas diet"})
    assert out.startswith("DATABASE RESULT: FOUND — Phascolarctos cinereus is in the database.")
    assert "- IUCN status: VU" in out
    assert out.index("END OF DATABASE RESULT") < out.index("**Vombatus ursinus**")


def test_semantic_search_named_species_without_vector_hits(monkeypatch):
    from app.llm_agent import semantic_search_species
    _koala_named(monkeypatch)
    with patch("app.llm_agent.vector_db.semantic_search", return_value=[]):
        out = semantic_search_species.invoke({"query": "koalas diet"})
    assert out.startswith("DATABASE RESULT: FOUND — Phascolarctos cinereus")
    assert "No results from semantic search" not in out


def test_semantic_search_without_a_named_species_is_unchanged(monkeypatch):
    from app.llm_agent import semantic_search_species
    _koala_named(monkeypatch)
    with patch("app.llm_agent.vector_db.semantic_search", return_value=_SEMANTIC_HIT):
        out = semantic_search_species.invoke({"query": "a striped horse-like animal"})
    assert out.startswith("- **Vombatus ursinus** (Wombat) [species]")


def test_taxonomy_of_one_species_group_adds_its_facts(monkeypatch):
    from app import llm_agent, taxon_queries
    monkeypatch.setattr(taxon_queries, "sole_living_species",
                        lambda path: _KOALA if path == _KOALA_FAMILY["taxon_path"] else None)
    monkeypatch.setattr(llm_agent.lookup_species, "func", lambda scientific_name: _FAKE_LOOKUP)
    out, _ = _taxonomy(monkeypatch, _KOALA_FAMILY, (1, [_KOALA]), ranks={"genus": 1})
    lines = out.splitlines()
    assert "- Only living species: Phascolarctos cinereus (Koala)" in lines
    assert "- IUCN status: VU" in lines and "- Geographic range: lat -38.5–-15.6" in lines


def test_taxonomy_of_group_of_many_adds_no_facts(monkeypatch):
    out, _ = _taxonomy(monkeypatch, _STRIGIFORMES, (1, [_STRIGIDAE_ROW]))
    assert "Only living species" not in out


@pytest.mark.asyncio
async def test_named_species_in_semantic_search_is_evidence_and_linked(monkeypatch):
    from app import taxon_links
    from app.llm_agent import stream_response
    _koala_named(monkeypatch)
    seen = []
    monkeypatch.setattr(taxon_links, "subject_rows", lambda names: seen.append(list(names)) or [])
    with patch("app.llm_agent.vector_db.semantic_search", return_value=_SEMANTIC_HIT):
        from app.llm_agent import semantic_search_species
        out = semantic_search_species.invoke({"query": "koalas diet"})
    events = [{"event": "on_tool_start", "name": "semantic_search_species", "data": {"input": {}}},
              {"event": "on_tool_end", "name": "semantic_search_species", "data": {"output": out}},
              _tokens("Database: The koala is listed as VU. Database: The wombat is a marsupial.")]
    with patch("app.llm_agent.build_agent", side_effect=[_agent(events)]):
        text = await _collect(stream_response("what do koalas eat"))
    assert "Database: The koala is listed as VU." in text
    # Semantic hits stay outside the evidence, as before
    assert "Database: The wombat is a marsupial." not in text
    assert seen and seen[0][:2] == ["Phascolarctos cinereus", "Vombatus ursinus"]


# ── Increment 26: species in a place ──────────────────────────────────────────

class _Place:
    name, kind, bbox = "Netherlands", "country", [50.8, 53.5, 3.4, 7.2]
    label = "Netherlands (country)"


_SNAKE_ROWS = [
    {"scientific_name": "Natrix helvetica", "common_names": '["Banded Grass Snake"]', "records": 119476, "fit": 0.0559},
    {"scientific_name": "Vipera berus", "common_names": '["common adder"]', "records": 127461, "fit": 0.0081},
]


def _in_place(monkeypatch, place=_Place(), group=("snakes (snake families)", ["A|C"]),
              result=(4, 7, 241, _SNAKE_ROWS), total=3900, **args):
    from app import places, taxon_queries
    from app.llm_agent import species_in_place
    monkeypatch.setattr(places, "find_place", lambda name: place)
    monkeypatch.setattr(taxon_queries, "place_group", lambda name: group)
    monkeypatch.setattr(taxon_queries, "species_in_place", lambda paths, pl, limit: result)
    monkeypatch.setattr(taxon_queries, "living_species_count", lambda paths: total)
    return species_in_place.invoke({"place": "holland", "group": "snakes", **args})


def test_species_in_place_lists_the_overlapping_species(monkeypatch):
    out = _in_place(monkeypatch)
    lines = out.splitlines()
    assert lines[0] == ("DATABASE RESULT: FOUND — 4 species in snakes (snake families) have a recorded "
                        "range that overlaps Netherlands (country) and fits it closely; showing 2, closest fit first.")
    assert "- Wider ranges: 3 more species have a much wider range that also overlaps it." in lines
    assert "- Species: Natrix helvetica (Banded Grass Snake); Vipera berus (common adder)" in lines
    assert any(l.startswith("- Coverage note: Only 241 of 3,900 living species") for l in lines)
    assert lines[-1].startswith("END OF DATABASE RESULT.") and "may occur there" in lines[-1]


def test_species_in_place_unknown_place(monkeypatch):
    out = _in_place(monkeypatch, place=None)
    assert out.startswith("DATABASE RESULT: No place found for 'holland'")


def test_species_in_place_unknown_group(monkeypatch):
    out = _in_place(monkeypatch, group=None)
    assert out.startswith("DATABASE RESULT: No group found for 'snakes'")


def test_species_in_place_none_overlapping(monkeypatch):
    out = _in_place(monkeypatch, result=(0, 0, 241, []))
    assert out.startswith("DATABASE RESULT: No species in snakes (snake families) has a recorded range "
                          "overlapping Netherlands (country)")


def test_species_in_place_no_coverage_note_when_most_have_a_range(monkeypatch):
    assert "Coverage note" not in _in_place(monkeypatch, total=300)


def test_species_in_place_is_evidence_for_the_listed_names(monkeypatch):
    out = _in_place(monkeypatch)
    assert _check("Database: The common adder (Vipera berus) has a recorded range overlapping "
                  "the Netherlands.", out).startswith("Database:")


def test_species_in_place_is_a_chat_tool():
    from app import llm_agent
    assert "species_in_place" in llm_agent._EVIDENCE_TOOLS
    assert "species_in_place" in llm_agent._SYSTEM_PROMPT


def test_species_in_place_count_is_evidence(monkeypatch):
    out = _in_place(monkeypatch)
    assert _check("Database: 4 snake species have a recorded range that fits the Netherlands.", out) \
        .startswith("Database:")


# ── Increment 26: countries from GBIF country records ────────────────────────

class _CountryPlace(_Place):
    countries = ("NL",)


def _in_country(monkeypatch, result=(4, 2, _SNAKE_ROWS), has_records=True):
    from app import taxon_queries
    monkeypatch.setattr(taxon_queries, "has_country_records", lambda codes: has_records)
    monkeypatch.setattr(taxon_queries, "species_in_country", lambda paths, codes, limit, partial=(), place=None: result)
    return _in_place(monkeypatch, place=_CountryPlace())


def test_species_in_place_country_uses_gbif_country_records(monkeypatch):
    lines = _in_country(monkeypatch).splitlines()
    assert lines[0] == ("DATABASE RESULT: FOUND — 4 species in snakes (snake families) are commonly "
                        "recorded in the wild in Netherlands (country); showing 2, most recorded first.")
    assert "- Species: Natrix helvetica (Banded Grass Snake); Vipera berus (common adder)" in lines
    assert any(l.startswith("- Rarely recorded: 2 more species have far fewer records there") for l in lines)
    assert not any("Coverage note" in l or "Wider ranges" in l for l in lines)
    assert lines[-1].startswith("END OF DATABASE RESULT.") and "observed" in lines[-1]


def test_species_in_place_country_none_recorded(monkeypatch):
    out = _in_country(monkeypatch, result=(0, 1, []))
    assert out.startswith("DATABASE RESULT: No species in snakes (snake families) has 5 or more wild "
                          "GBIF records in Netherlands (country)")
    assert "From general knowledge" in out


def test_species_in_place_country_without_records_falls_back_to_boxes(monkeypatch):
    out = _in_country(monkeypatch, has_records=False)
    assert "have a recorded range that overlaps" in out.splitlines()[0]


def test_species_in_place_country_count_is_evidence(monkeypatch):
    out = _in_country(monkeypatch)
    assert _check("Database: 4 snake species have been recorded in the Netherlands.", out).startswith("Database:")
    assert _check("Database: The common adder (Vipera berus) is found in the Netherlands.", out) \
        .startswith("Database:")


def test_species_in_place_country_without_any_record_says_absent(monkeypatch):
    out = _in_country(monkeypatch, result=(0, 0, []))
    assert out.startswith("DATABASE RESULT: FOUND — no species in snakes (snake families) has any wild "
                          "GBIF record in Netherlands (country).")
    assert "no wild records of them there" in out
    assert _check("Database: There are no wild records of snakes in the Netherlands.", out).startswith("Database:")


def test_absence_backs_only_a_plain_denial(monkeypatch):
    out = _in_country(monkeypatch, result=(0, 0, []))
    assert _check("Database: Ireland has no snakes.", out).startswith("Database:")
    assert _check("Database: There are no snakes, but 3 lizards live there.", out).startswith("From general")
    assert _check("Database: The adder lives in Ireland.", out).startswith("From general")


# ── Increment 27: countries of one species ───────────────────────────────────

_TIGER_ROW = {"scientific_name": "Panthera tigris", "taxon_rank": "species", "common_names": '["Tiger"]',
              "taxon_path": "Animalia|Chordata|Mammalia|Carnivora|Felidae|Panthera|Panthera tigris",
              "taxonomic_status": "ACCEPTED",
              "geo_bounding_box": '{"lat_min":-2.35,"lat_max":49.1,"lon_min":75.64,"lon_max":136.88}'}


def _tiger(monkeypatch, inside, outside):
    from app import places, taxon_queries
    from app.llm_agent import lookup_species
    monkeypatch.setattr(taxon_queries, "countries_of", lambda name: [("XX", 1)])
    monkeypatch.setattr(places, "native_countries", lambda records: (inside, outside))
    with patch("app.llm_agent.database.get_species", return_value=dict(_TIGER_ROW)):
        return lookup_species.invoke({"scientific_name": "Panthera tigris"})


def test_lookup_lists_the_countries_inside_the_range(monkeypatch):
    out = _tiger(monkeypatch, [("India", 4802), ("Russia", 224), ("Nepal", 113)], 4)
    lines = out.splitlines()
    assert "- Countries with wild records (most first): India, Russia, Nepal" in lines
    assert ("- Records far from its range: 4 other countries (zoo animals, escapes or misplaced "
            "records), not listed") in lines
    assert "countries" not in next(l for l in lines if l.startswith("- Not recorded:"))


def test_lookup_caps_the_country_list(monkeypatch):
    many = [(f"Land {i}", 100 - i) for i in range(30)]
    out = _tiger(monkeypatch, many, 0)
    line = next(l for l in out.splitlines() if l.startswith("- Countries with wild records"))
    assert line.endswith("Land 19, and 10 more") and "Records far" not in out


def test_lookup_without_country_records(monkeypatch):
    out = _tiger(monkeypatch, [], 0)
    assert "Countries with wild records" not in out
    assert "countries" in next(l for l in out.splitlines() if l.startswith("- Not recorded:"))


def test_each_country_is_evidence(monkeypatch):
    out = _tiger(monkeypatch, [("India", 4802), ("Russia", 224), ("Nepal", 113)], 4)
    assert _check("Database: Tigers can be found in the wild in India and Nepal.", out).startswith("Database:")
    assert _check("Database: Tigers live in Brazil.", out).startswith("From general")


def test_taxonomy_of_a_species_carries_its_countries(monkeypatch):
    from app import taxon_queries
    from app.llm_agent import taxonomy_of
    monkeypatch.setattr(taxon_queries, "resolve_taxon", lambda name: dict(_TIGER_ROW))
    monkeypatch.setattr(taxon_queries, "lineage", lambda path: [{"name": "Panthera tigris", "common": "Tiger"}])
    monkeypatch.setattr(taxon_queries, "members", lambda path, n, rank=None: (1, [_TIGER_ROW]))
    _tiger(monkeypatch, [("India", 4802)], 0)       # sets the country stubs
    with patch("app.llm_agent.database.get_species", return_value=dict(_TIGER_ROW)):
        out = taxonomy_of.invoke({"name": "tiger"})
    assert "- Countries with wild records (most first): India" in out.splitlines()



# ── Increment 28: listed groups in the ranking and statistics tools ──────────

def test_rank_and_stats_use_listed_groups(monkeypatch):
    from app import taxon_queries
    from app.llm_agent import group_stats, rank_species_by_trait
    seen = []
    monkeypatch.setattr(taxon_queries, "group_paths",
                        lambda name: ("sharks", "sharks (shark orders)", ["A|C|E|L", "A|C|E|C"]))
    monkeypatch.setattr(taxon_queries, "rank_by_trait", lambda col, path, hi, limit: (
        seen.append(path) or (2, [{"scientific_name": "Carcharodon carcharias", "common_names": "[]",
                                   "rank_value": 70.0}])))
    out = rank_species_by_trait.invoke({"trait": "lifespan", "group": "sharks"})
    assert seen == [["A|C|E|L", "A|C|E|C"]]
    assert "among 2 species in sharks with a recorded max lifespan" in out.splitlines()[0]
    monkeypatch.setattr(taxon_queries, "group_summary", lambda path, examples=5: {
        "species": 500, "extinct": 3, "iucn": {}, "trends": {}, "threatened": []})
    out = group_stats.invoke({"group": "sharks"})
    assert out.splitlines()[0] == "DATABASE RESULT: FOUND — statistics for sharks (shark orders)."
