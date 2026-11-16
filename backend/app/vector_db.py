"""ChromaDB embedding handlers for semantic species search."""

import os
import ssl

# HF offline flags are set in app/__init__.py so they apply before any import.
# SSL cert chain is broken on this machine — disable verification for the process.
ssl._create_default_https_context = ssl._create_unverified_context  # noqa: SIM117

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

from app.paths import data_path

CHROMA_PATH = os.environ.get("CHROMA_DB_PATH") or str(data_path("chroma_db"))
COLLECTION_NAME = "species_abstracts"
EMBED_MODEL = "all-MiniLM-L6-v2"

_client = None
_collection = None


def _embedding_fn() -> SentenceTransformerEmbeddingFunction:
    return SentenceTransformerEmbeddingFunction(model_name=EMBED_MODEL)


def get_collection() -> chromadb.Collection:
    global _client, _collection
    if _collection is not None:
        return _collection
    _client = chromadb.PersistentClient(path=CHROMA_PATH)
    _collection = _client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=_embedding_fn(),
        metadata={"hnsw:space": "cosine"},
    )
    return _collection


def embed_batch(records: list[dict]) -> None:
    """Embed a batch of species records and upsert into ChromaDB.

    Each record must have 'scientific_name' and 'wikipedia_abstract'.
    Optional: 'common_names' (list[str]), 'taxon_rank'.
    """
    if not records:
        return
    col = get_collection()
    ids = [r["scientific_name"] for r in records]
    documents = [r["wikipedia_abstract"] or "" for r in records]
    metadatas = [
        {
            "scientific_name": r["scientific_name"],
            "common_names": ",".join(r.get("common_names") or []),
            "taxon_rank": r.get("taxon_rank") or "",
        }
        for r in records
    ]
    col.upsert(ids=ids, documents=documents, metadatas=metadatas)


def semantic_search(query: str, n_results: int = 5) -> list[dict]:
    """Return top-N species whose abstracts are semantically closest to query."""
    col = get_collection()
    count = col.count()
    if count == 0:
        return []
    n = min(n_results, count)
    results = col.query(query_texts=[query], n_results=n)
    output = []
    ids = results["ids"][0]
    distances = results["distances"][0]
    metadatas = results["metadatas"][0]
    documents = results["documents"][0]
    for i, sid in enumerate(ids):
        meta = metadatas[i]
        output.append(
            {
                "scientific_name": sid,
                "common_names": [n for n in meta["common_names"].split(",") if n],
                "taxon_rank": meta["taxon_rank"],
                "distance": distances[i],
                "abstract_snippet": documents[i][:300] if documents[i] else "",
            }
        )
    return output


def reset_collection() -> None:
    """Drop and recreate the collection. Used in tests."""
    global _client, _collection
    if _client is None:
        _client = chromadb.PersistentClient(path=CHROMA_PATH)
    try:
        _client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    _collection = _client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=_embedding_fn(),
        metadata={"hnsw:space": "cosine"},
    )
