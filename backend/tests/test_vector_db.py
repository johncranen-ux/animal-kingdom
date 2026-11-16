"""Tests for vector_db.py — uses in-memory ChromaDB to avoid disk I/O."""

import uuid
import pytest
import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

EMBED_MODEL = "all-MiniLM-L6-v2"


@pytest.fixture(scope="session")
def ef():
    """Load the embedding function once for the whole test session."""
    return SentenceTransformerEmbeddingFunction(model_name=EMBED_MODEL)


@pytest.fixture(autouse=True)
def isolated_chroma(monkeypatch, ef):
    """Fresh in-memory ChromaDB collection per test via unique collection name.

    EphemeralClient's in-memory backend is module-level (singleton), so we use
    a unique UUID name each time to guarantee zero bleed between tests.
    """
    import app.vector_db as vdb

    client = chromadb.EphemeralClient()
    col = client.create_collection(
        name=f"test_{uuid.uuid4().hex}",
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )

    monkeypatch.setattr(vdb, "_client", client)
    monkeypatch.setattr(vdb, "_collection", col)
    yield col


# ── embed_batch ───────────────────────────────────────────────────────────────

def test_embed_batch_inserts_records(isolated_chroma):
    import app.vector_db as vdb

    vdb.embed_batch([{
        "scientific_name": "Panthera leo",
        "wikipedia_abstract": "The lion is a large cat native to Africa.",
        "common_names": ["Lion", "African lion"],
        "taxon_rank": "species",
    }])
    assert isolated_chroma.count() == 1


def test_embed_batch_empty_is_noop(isolated_chroma):
    import app.vector_db as vdb

    vdb.embed_batch([])
    assert isolated_chroma.count() == 0


def test_embed_batch_upsert_does_not_duplicate(isolated_chroma):
    import app.vector_db as vdb

    record = {
        "scientific_name": "Panthera leo",
        "wikipedia_abstract": "The lion is a large cat native to Africa.",
        "common_names": ["Lion"],
        "taxon_rank": "species",
    }
    vdb.embed_batch([record])
    vdb.embed_batch([record])
    assert isolated_chroma.count() == 1


def test_embed_batch_multiple_records(isolated_chroma):
    import app.vector_db as vdb

    vdb.embed_batch([
        {
            "scientific_name": "Panthera leo",
            "wikipedia_abstract": "The lion is a large cat.",
            "common_names": ["Lion"],
            "taxon_rank": "species",
        },
        {
            "scientific_name": "Panthera tigris",
            "wikipedia_abstract": "The tiger is the largest living cat species.",
            "common_names": ["Tiger"],
            "taxon_rank": "species",
        },
        {
            "scientific_name": "Ursus arctos",
            "wikipedia_abstract": "The brown bear is a large bear native to Eurasia and North America.",
            "common_names": ["Brown bear"],
            "taxon_rank": "species",
        },
    ])
    assert isolated_chroma.count() == 3


def test_embed_batch_metadata_stored_correctly(isolated_chroma):
    import app.vector_db as vdb

    vdb.embed_batch([{
        "scientific_name": "Panthera leo",
        "wikipedia_abstract": "The lion is a large cat.",
        "common_names": ["Lion", "African lion"],
        "taxon_rank": "species",
    }])
    result = isolated_chroma.get(ids=["Panthera leo"], include=["metadatas"])
    meta = result["metadatas"][0]
    assert meta["scientific_name"] == "Panthera leo"
    assert "Lion" in meta["common_names"]
    assert meta["taxon_rank"] == "species"


# ── semantic_search ───────────────────────────────────────────────────────────

def test_semantic_search_empty_collection_returns_empty(isolated_chroma):
    import app.vector_db as vdb

    assert vdb.semantic_search("lion") == []


def test_semantic_search_returns_results(isolated_chroma):
    import app.vector_db as vdb

    vdb.embed_batch([
        {
            "scientific_name": "Panthera leo",
            "wikipedia_abstract": "The lion is a large cat native to Africa and India.",
            "common_names": ["Lion"],
            "taxon_rank": "species",
        },
        {
            "scientific_name": "Panthera tigris",
            "wikipedia_abstract": "The tiger is the largest living cat species in the world.",
            "common_names": ["Tiger"],
            "taxon_rank": "species",
        },
    ])
    results = vdb.semantic_search("large African feline predator", n_results=2)
    assert len(results) >= 1
    assert all("scientific_name" in r for r in results)
    assert all("distance" in r for r in results)


def test_semantic_search_top_result_is_most_relevant(isolated_chroma):
    import app.vector_db as vdb

    vdb.embed_batch([
        {
            "scientific_name": "Panthera leo",
            "wikipedia_abstract": "The lion lives in Africa and is known as the king of the jungle.",
            "common_names": ["Lion"],
            "taxon_rank": "species",
        },
        {
            "scientific_name": "Salmo salar",
            "wikipedia_abstract": "The Atlantic salmon is a species of fish in the family Salmonidae.",
            "common_names": ["Atlantic salmon"],
            "taxon_rank": "species",
        },
    ])
    results = vdb.semantic_search("king of the jungle Africa cat", n_results=2)
    assert results[0]["scientific_name"] == "Panthera leo"


def test_semantic_search_result_fields(isolated_chroma):
    import app.vector_db as vdb

    vdb.embed_batch([{
        "scientific_name": "Panthera leo",
        "wikipedia_abstract": "The lion is a large cat.",
        "common_names": ["Lion"],
        "taxon_rank": "species",
    }])
    r = vdb.semantic_search("lion", n_results=1)[0]
    assert "scientific_name" in r
    assert "common_names" in r
    assert "taxon_rank" in r
    assert "distance" in r
    assert "abstract_snippet" in r
    assert isinstance(r["common_names"], list)


def test_semantic_search_respects_n_results(isolated_chroma):
    import app.vector_db as vdb

    vdb.embed_batch([
        {
            "scientific_name": f"Species{i}",
            "wikipedia_abstract": f"This is a description of species number {i}.",
            "common_names": [],
            "taxon_rank": "species",
        }
        for i in range(5)
    ])
    assert len(vdb.semantic_search("species description", n_results=3)) == 3


def test_semantic_search_abstract_snippet_truncated(isolated_chroma):
    import app.vector_db as vdb

    vdb.embed_batch([{
        "scientific_name": "Longus abstractus",
        "wikipedia_abstract": "A" * 500,
        "common_names": [],
        "taxon_rank": "species",
    }])
    results = vdb.semantic_search("AAAA", n_results=1)
    assert len(results[0]["abstract_snippet"]) <= 300
