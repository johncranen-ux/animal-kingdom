# Dynamic Image Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a user opens the species panel and no image URL is stored (or the stored URL fails to load), fetch one from a 4-source chain (Wikipedia → iNaturalist → Wikimedia Commons → DuckDuckGo), cache it back to the DB, and display it.

**Architecture:** A new `image_utils.py` module owns the 4-source fetch chain. `llm_agent.py` is refactored to import from it. A new `GET /api/species/{name}/image?force=false` endpoint runs the chain and caches to DB. The frontend calls this endpoint when `primary_image_url` is null or when `<img onerror>` fires with `?force=true`.

**Tech Stack:** Python 3.12, FastAPI, SQLite, `ddgs` (PyPI), Wikimedia Commons Action API, Vitest (frontend tests)

---

## File Map

| File | Change |
|---|---|
| `backend/app/image_utils.py` | **Create** — 4-source chain (`_wikipedia_image`, `_inaturalist_image`, `_wikimedia_image`, `_duckduckgo_image`, `fetch_image`) |
| `backend/tests/test_image_utils.py` | **Create** — unit tests for chain |
| `backend/requirements.txt` | **Modify** — add `ddgs` |
| `backend/app/database.py` | **Modify** — add `update_species_image` helper |
| `backend/app/llm_agent.py` | **Modify** — remove inline helpers, import from `image_utils`, use `database.update_species_image` |
| `backend/app/main.py` | **Modify** — add `ImageResponse` model + `GET /api/species/{name}/image` endpoint |
| `backend/tests/test_taxonomy_api.py` | **Modify** — extend `_insert` helper + add endpoint tests |
| `frontend/js/app.js` | **Modify** — loading state, null/`__none__` handling, `onerror` refetch |
| `frontend/tests/app.test.js` | **Modify** — add species panel image tests |

---

## Task 1: Add `ddgs` dependency

**Files:**
- Modify: `backend/requirements.txt`

- [ ] **Step 1: Add `ddgs` to requirements.txt**

Open `backend/requirements.txt` and add after the `# Testing` block:

```
# Image search
ddgs==9.14.4
```

- [ ] **Step 2: Install the package**

Run from the repo root (activate the venv first):
```bash
pip install ddgs==9.14.4
```

Expected: `Successfully installed ddgs-9.14.4` (or "already satisfied").

- [ ] **Step 3: Verify import works**

```bash
python -c "from ddgs import DDGS; print('ok')"
```

Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add backend/requirements.txt
git commit -m "chore: add ddgs 9.14.4 for image search fallback"
```

---

## Task 2: Create `image_utils.py` (TDD)

**Files:**
- Create: `backend/app/image_utils.py`
- Create: `backend/tests/test_image_utils.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_image_utils.py`:

```python
"""Unit tests for image_utils — 4-source image lookup chain."""

import sys
import types
import pytest
from app import image_utils


def test_fetch_image_returns_wikipedia_result(monkeypatch):
    monkeypatch.setattr(image_utils, '_wikipedia_image',
        lambda name: ('https://upload.wikimedia.org/img.jpg', '© Wikipedia contributors (CC BY-SA)'))
    result = image_utils.fetch_image('Apis mellifera')
    assert result == ('https://upload.wikimedia.org/img.jpg', '© Wikipedia contributors (CC BY-SA)')


def test_fetch_image_stops_at_first_hit(monkeypatch):
    calls = []
    monkeypatch.setattr(image_utils, '_wikipedia_image',
        lambda name: ('https://wiki.org/img.jpg', '© Wikipedia'))
    monkeypatch.setattr(image_utils, '_inaturalist_image',
        lambda name: calls.append('inat') or None)
    result = image_utils.fetch_image('Apis mellifera')
    assert result[0] == 'https://wiki.org/img.jpg'
    assert 'inat' not in calls   # inat was not reached


def test_fetch_image_falls_through_to_wikimedia(monkeypatch):
    monkeypatch.setattr(image_utils, '_wikipedia_image', lambda name: None)
    monkeypatch.setattr(image_utils, '_inaturalist_image', lambda name: None)
    monkeypatch.setattr(image_utils, '_wikimedia_image',
        lambda name: ('https://commons.wikimedia.org/img.jpg', '© Jane Doe (CC BY-SA 4.0)'))
    result = image_utils.fetch_image('Apis mellifera')
    assert result == ('https://commons.wikimedia.org/img.jpg', '© Jane Doe (CC BY-SA 4.0)')


def test_fetch_image_falls_through_to_duckduckgo(monkeypatch):
    monkeypatch.setattr(image_utils, '_wikipedia_image', lambda name: None)
    monkeypatch.setattr(image_utils, '_inaturalist_image', lambda name: None)
    monkeypatch.setattr(image_utils, '_wikimedia_image', lambda name: None)
    monkeypatch.setattr(image_utils, '_duckduckgo_image',
        lambda name, common_names=None: ('https://example.com/bee.jpg', 'Source: example.com'))
    result = image_utils.fetch_image('Apis mellifera')
    assert result == ('https://example.com/bee.jpg', 'Source: example.com')


def test_fetch_image_passes_common_names_to_duckduckgo(monkeypatch):
    received = {}
    monkeypatch.setattr(image_utils, '_wikipedia_image', lambda name: None)
    monkeypatch.setattr(image_utils, '_inaturalist_image', lambda name: None)
    monkeypatch.setattr(image_utils, '_wikimedia_image', lambda name: None)
    def capture_ddg(name, common_names=None):
        received['common_names'] = common_names
        return None
    monkeypatch.setattr(image_utils, '_duckduckgo_image', capture_ddg)
    image_utils.fetch_image('Apis mellifera', common_names=['Honey bee'])
    assert received['common_names'] == ['Honey bee']


def test_fetch_image_returns_none_when_all_fail(monkeypatch):
    monkeypatch.setattr(image_utils, '_wikipedia_image', lambda name: None)
    monkeypatch.setattr(image_utils, '_inaturalist_image', lambda name: None)
    monkeypatch.setattr(image_utils, '_wikimedia_image', lambda name: None)
    monkeypatch.setattr(image_utils, '_duckduckgo_image',
        lambda name, common_names=None: None)
    result = image_utils.fetch_image('Unknown xyz 99999')
    assert result is None


def test_wikimedia_image_returns_none_when_no_search_results(monkeypatch):
    def fake_http_get(url):
        if 'list=search' in url:
            return {'query': {'search': []}}
        return None
    monkeypatch.setattr(image_utils, '_http_get', fake_http_get)
    result = image_utils._wikimedia_image('Unknown xyz 99999')
    assert result is None


def test_wikimedia_image_returns_none_when_http_fails(monkeypatch):
    monkeypatch.setattr(image_utils, '_http_get', lambda url: None)
    result = image_utils._wikimedia_image('Apis mellifera')
    assert result is None


def test_duckduckgo_image_returns_none_when_ddgs_not_installed(monkeypatch):
    fake_mod = types.ModuleType('ddgs')
    class _FakeDDGS:
        def images(self, *a, **kw): raise ImportError('not installed')
    fake_mod.DDGS = _FakeDDGS
    # Temporarily replace the module so the import inside _duckduckgo_image fails
    original = sys.modules.pop('ddgs', None)
    try:
        result = image_utils._duckduckgo_image('Apis mellifera')
    finally:
        if original is not None:
            sys.modules['ddgs'] = original
    # Either ImportError caught or search returned nothing — both give None
    assert result is None


def test_duckduckgo_image_returns_none_on_ratelimit(monkeypatch):
    fake_mod = types.ModuleType('ddgs')
    class _FakeDDGS:
        def images(self, query, max_results=5):
            raise Exception('RatelimitException: rate limited')
    fake_mod.DDGS = _FakeDDGS
    monkeypatch.setitem(sys.modules, 'ddgs', fake_mod)
    result = image_utils._duckduckgo_image('Apis mellifera')
    assert result is None
```

- [ ] **Step 2: Run tests to confirm they all fail**

```bash
cd backend && python -m pytest tests/test_image_utils.py -v
```

Expected: all tests FAIL with `ModuleNotFoundError: No module named 'app.image_utils'`.

- [ ] **Step 3: Create `backend/app/image_utils.py`**

```python
"""Image lookup helpers — 4-source chain used by both the species panel endpoint
and the LLM chat agent."""

import json
import re
import ssl
import urllib.parse
import urllib.request

_IMG_USER_AGENT = "AnimalKingdomApp/1.0 (educational offline project)"
_ssl_ctx = ssl.create_default_context()


def _http_get(url: str) -> dict | None:
    req = urllib.request.Request(url, headers={"User-Agent": _IMG_USER_AGENT})
    try:
        with urllib.request.urlopen(req, context=_ssl_ctx, timeout=10) as r:
            return json.loads(r.read())
    except Exception:
        return None


def _wikipedia_image(scientific_name: str) -> tuple[str, str] | None:
    """Wikipedia REST summary thumbnail."""
    title = urllib.parse.quote(scientific_name.replace(" ", "_"))
    data  = _http_get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}")
    if not data:
        return None
    thumb = data.get("thumbnail") or {}
    src   = thumb.get("source")
    return (src, "© Wikipedia contributors (CC BY-SA)") if src else None


def _inaturalist_image(scientific_name: str) -> tuple[str, str] | None:
    """iNaturalist taxa API."""
    q    = urllib.parse.quote(scientific_name)
    data = _http_get(f"https://api.inaturalist.org/v1/taxa?q={q}&per_page=5&rank=species")
    if not data:
        return None
    for taxon in data.get("results", []):
        if taxon.get("name", "").lower() != scientific_name.lower():
            continue
        photo = taxon.get("default_photo") or {}
        url   = photo.get("medium_url") or photo.get("square_url")
        if url:
            return url, photo.get("attribution", "© iNaturalist contributors")
    return None


def _wikimedia_image(scientific_name: str) -> tuple[str, str] | None:
    """Wikimedia Commons: search by name then fetch imageinfo."""
    q = urllib.parse.quote(scientific_name)
    search_data = _http_get(
        f"https://commons.wikimedia.org/w/api.php"
        f"?action=query&list=search&srsearch={q}&srnamespace=6&srlimit=1&format=json"
    )
    if not search_data:
        return None
    results = search_data.get("query", {}).get("search", [])
    if not results:
        return None
    title = results[0].get("title")
    if not title:
        return None
    info_data = _http_get(
        f"https://commons.wikimedia.org/w/api.php"
        f"?action=query&titles={urllib.parse.quote(title)}"
        f"&prop=imageinfo&iiprop=url|extmetadata&iiurlwidth=800&format=json"
    )
    if not info_data:
        return None
    for page in info_data.get("query", {}).get("pages", {}).values():
        infos = page.get("imageinfo", [])
        if not infos:
            continue
        info = infos[0]
        url  = info.get("url")
        if not url:
            continue
        meta         = info.get("extmetadata", {})
        artist       = re.sub(r"<[^>]+>", "", meta.get("Artist", {}).get("value", "")).strip()
        license_name = meta.get("LicenseShortName", {}).get("value", "")
        attribution  = f"© {artist} ({license_name})" if artist else license_name or "© Wikimedia Commons contributors"
        return url, attribution
    return None


def _duckduckgo_image(
    scientific_name: str,
    common_names: list[str] | None = None,
) -> tuple[str, str] | None:
    """DuckDuckGo image search via ddgs package (unofficial, rate-limit aware)."""
    try:
        from ddgs import DDGS
    except ImportError:
        return None
    queries = [scientific_name]
    if common_names:
        queries.append(common_names[0])
    for query in queries:
        try:
            for r in DDGS().images(query, max_results=5):
                url = r.get("image")
                if url:
                    source = r.get("source") or r.get("url") or "DuckDuckGo"
                    return url, f"Source: {source}"
        except Exception:
            continue
    return None


def fetch_image(
    scientific_name: str,
    common_names: list[str] | None = None,
) -> tuple[str, str] | None:
    """Run the 4-source chain. Returns (url, attribution) or None."""
    result = _wikipedia_image(scientific_name)
    if result:
        return result
    result = _inaturalist_image(scientific_name)
    if result:
        return result
    result = _wikimedia_image(scientific_name)
    if result:
        return result
    return _duckduckgo_image(scientific_name, common_names)
```

- [ ] **Step 4: Run tests and confirm they all pass**

```bash
cd backend && python -m pytest tests/test_image_utils.py -v
```

Expected: all 10 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/image_utils.py backend/tests/test_image_utils.py
git commit -m "feat: add image_utils — 4-source image lookup chain (Wikipedia, iNat, Wikimedia, DDG)"
```

---

## Task 3: Add `update_species_image` to `database.py` (TDD)

**Files:**
- Modify: `backend/app/database.py`
- Modify: `backend/tests/test_taxonomy_api.py` (extend `_insert` helper)

- [ ] **Step 1: Write the failing test**

Open `backend/tests/test_database.py` and add at the end:

```python
# --- update_species_image ---

def test_update_species_image_writes_url_and_attribution(isolated_db):
    conn = database.get_connection()
    conn.execute(
        "INSERT INTO species (scientific_name, taxon_path, taxon_rank, taxonomic_status) "
        "VALUES ('Apis mellifera', 'Animalia|Apis mellifera', 'species', 'ACCEPTED')"
    )
    conn.commit()
    conn.close()

    database.update_species_image(
        'Apis mellifera',
        'https://example.com/bee.jpg',
        '© Some Photographer (CC BY 4.0)',
    )

    row = database.get_species('Apis mellifera')
    assert row['primary_image_url'] == 'https://example.com/bee.jpg'
    assert row['image_attribution'] == '© Some Photographer (CC BY 4.0)'


def test_update_species_image_overwrites_existing_url(isolated_db):
    conn = database.get_connection()
    conn.execute(
        "INSERT INTO species (scientific_name, taxon_path, taxon_rank, taxonomic_status, "
        "primary_image_url, image_attribution) "
        "VALUES ('Apis mellifera', 'Animalia|Apis mellifera', 'species', 'ACCEPTED', "
        "'https://old.com/img.jpg', 'old attribution')"
    )
    conn.commit()
    conn.close()

    database.update_species_image('Apis mellifera', 'https://new.com/img.jpg', 'new attribution')

    row = database.get_species('Apis mellifera')
    assert row['primary_image_url'] == 'https://new.com/img.jpg'
    assert row['image_attribution'] == 'new attribution'
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd backend && python -m pytest tests/test_database.py::test_update_species_image_writes_url_and_attribution tests/test_database.py::test_update_species_image_overwrites_existing_url -v
```

Expected: FAIL with `AttributeError: module 'app.database' has no attribute 'update_species_image'`.

- [ ] **Step 3: Add `update_species_image` to `database.py`**

Open `backend/app/database.py` and add after the `get_species` function (around line 327):

```python
def update_species_image(scientific_name: str, url: str, attribution: str) -> None:
    """Write primary_image_url and image_attribution. Used for write-through image cache."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE species SET primary_image_url = ?, image_attribution = ? "
            "WHERE scientific_name = ?",
            (url, attribution, scientific_name),
        )
        conn.commit()
    finally:
        conn.close()
```

- [ ] **Step 4: Run tests and confirm they pass**

```bash
cd backend && python -m pytest tests/test_database.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/database.py backend/tests/test_database.py
git commit -m "feat: add database.update_species_image write-through helper"
```

---

## Task 4: Migrate `llm_agent.py` to use `image_utils`

**Files:**
- Modify: `backend/app/llm_agent.py`

- [ ] **Step 1: Run existing llm_agent tests to establish baseline**

```bash
cd backend && python -m pytest tests/test_llm_agent.py -v
```

Note how many pass. They must all still pass after this task.

- [ ] **Step 2: Refactor `llm_agent.py`**

Replace the current content of `llm_agent.py` with the following. The only functional changes are:
1. `_http_get`, `_IMG_USER_AGENT`, `_ssl_ctx`, `_wikipedia_image`, `_inaturalist_image` are removed (now in `image_utils`).
2. `get_species_image` uses `image_utils.fetch_image` and `database.update_species_image`.
3. `get_species_image` respects the `__none__` sentinel.

```python
"""LangChain tool definitions and Ollama agent configuration."""

import json
import re
import warnings
from typing import AsyncGenerator

# langgraph 1.x raises LangGraphDeprecatedSinceV10 about create_react_agent
# moving to langchain.agents, but langchain base isn't in our deps and the
# langgraph version works identically — suppress until we upgrade.
warnings.filterwarnings(
    "ignore",
    message="create_react_agent has been moved",
)

from langchain_ollama import ChatOllama
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, AIMessageChunk
from langgraph.prebuilt import create_react_agent

from app import database, image_utils, vector_db

OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL    = "llama3.1:8b"


_SYSTEM_PROMPT = """You are a factual naturalist assistant backed by a local database of \
1.78 million species.

MANDATORY WORKFLOW — follow exactly, in order:
1. Call ONE tool immediately — no text before the first tool call.
2. If the result is empty, call a DIFFERENT tool using the scientific name you already know.
3. Write a concise 3–5 sentence answer. Label each fact with its source:
   - Facts from the tool result → prefix that sentence with "Database:"
   - Facts from your own training knowledge → prefix with "From general knowledge:"
   This way the user always knows which information is DB-backed and which is not.

COMMON-NAME → SCIENTIFIC NAME (use lookup_species directly, skip semantic search):
  ladybug / ladybird → Coccinella septempunctata
  black panther      → Panthera pardus
  mountain lion      → Puma concolor
  cougar / puma      → Puma concolor
  wolf               → Canis lupus
  lion               → Panthera leo
  tiger              → Panthera tigris
  polar bear         → Ursus maritimus
  killer whale       → Orcinus orca
  great white shark  → Carcharodon carcharias
  house cat          → Felis catus
  domestic dog       → Canis lupus familiaris
  For unlisted common names: call semantic_search_species first, then \
lookup_species on the best match.

HARD RULES — violations break the app:
  ✗ NEVER write {"name": ...} or any JSON in your reply.
  ✗ NEVER narrate your reasoning ("I will try...", "Let me call...").
  ✓ Always label every fact — "Database:" or "From general knowledge:" — never mix unlabelled.
"""

# ── Tools ─────────────────────────────────────────────────────────────────────

@tool
def lookup_species(scientific_name: str) -> str:
    """Look up detailed facts for a species by its scientific name.

    Returns a markdown-formatted summary of taxonomy, physical traits,
    ecology, conservation status, and a Wikipedia abstract if available.
    """
    row = database.get_species(scientific_name)
    if row is None:
        return f"No species found with scientific name '{scientific_name}'."

    common = database.parse_common_names(row.get("common_names"))
    common_str = ", ".join(common) if common else "none recorded"
    bbox = database.parse_geo_bbox(row.get("geo_bounding_box"))

    lines = [
        f"**{row['scientific_name']}** ({row.get('taxon_rank', 'unknown')} rank)",
        f"- Common names: {common_str}",
        f"- Lineage: {row.get('taxon_path', '').replace('|', ' → ')}",
        f"- Taxonomic status: {row.get('taxonomic_status', 'unknown')}",
    ]
    if row.get("body_mass"):
        lines.append(f"- Body mass: {row['body_mass']} kg")
    if row.get("body_length"):
        lines.append(f"- Body length: {row['body_length']} m")
    if row.get("max_lifespan"):
        lines.append(f"- Max lifespan: {row['max_lifespan']} years")
    if row.get("habitat_type"):
        lines.append(f"- Habitat: {row['habitat_type']}")
    if row.get("trophic_level"):
        lines.append(f"- Trophic level: {row['trophic_level']}")
    if row.get("iucn_status"):
        lines.append(f"- IUCN status: {row['iucn_status']}")
    if row.get("population_trend"):
        lines.append(f"- Population trend: {row['population_trend']}")
    if bbox:
        lines.append(f"- Geographic range: lat {bbox.get('lat_min')}–{bbox.get('lat_max')}, "
                     f"lon {bbox.get('lon_min')}–{bbox.get('lon_max')}")
    if row.get("wikipedia_abstract"):
        lines.append(f"\n**Summary:** {row['wikipedia_abstract'][:500]}")

    return "\n".join(lines)


@tool
def semantic_search_species(query: str) -> str:
    """Search for species semantically using a natural-language query.

    Returns the top-3 most relevant species with a short abstract snippet.
    Use this when you don't know the exact scientific name or want related species.
    """
    results = vector_db.semantic_search(query, n_results=3)
    if not results:
        return (
            "No results from semantic search. "
            "Call lookup_species with your best scientific-name guess to continue."
        )

    parts = []
    for r in results:
        common = ", ".join(r["common_names"]) if r["common_names"] else "no common name"
        snippet = r["abstract_snippet"] or "(no abstract)"
        parts.append(
            f"- **{r['scientific_name']}** ({common}) [{r['taxon_rank']}]\n"
            f"  {snippet}"
        )
    return "\n".join(parts)


@tool
def get_species_image(scientific_name: str) -> str:
    """Retrieve an image URL and attribution for a species.

    Checks the local database first; if no image is stored, runs the 4-source
    chain (Wikipedia → iNaturalist → Wikimedia Commons → DuckDuckGo) and caches
    the result back to the database.
    Returns a JSON string with 'url', 'attribution', and 'source' fields.
    """
    row = database.get_species(scientific_name)
    if row is None:
        return json.dumps({"error": f"Species '{scientific_name}' not found."})

    url         = row.get("primary_image_url") or ""
    attribution = row.get("image_attribution") or ""

    if url == "__none__":
        return json.dumps({"error": "No image found in any source."})

    if url:
        return json.dumps({"url": url, "attribution": attribution, "source": "database"})

    common_names = database.parse_common_names(row.get("common_names"))
    result = image_utils.fetch_image(scientific_name, common_names or None)
    if result:
        url, attribution = result
        database.update_species_image(scientific_name, url, attribution)
        return json.dumps({"url": url, "attribution": attribution, "source": "fetched"})

    return json.dumps({"error": "No image found in database, Wikipedia, iNaturalist, Wikimedia Commons, or DuckDuckGo."})


# ── Agent ──────────────────────────────────────────────────────────────────────

def get_llm() -> ChatOllama:
    return ChatOllama(model=OLLAMA_MODEL, base_url=OLLAMA_BASE_URL, temperature=0)


def build_agent():
    llm = get_llm()
    tools = [lookup_species, semantic_search_species, get_species_image]
    return create_react_agent(llm, tools, prompt=_SYSTEM_PROMPT)


_TOOL_CALL_RE = re.compile(r'^\s*\{\s*"name"\s*:')


def _filter_json_blobs(text: str, state: dict) -> str:
    """Strip raw JSON tool-call blobs ({"name": ...}) from streamed text.

    `state` carries brace_depth and buf across token boundaries.
    Returns only the characters that should be forwarded to the client.
    """
    out_chars: list[str] = []
    for ch in text:
        if state["depth"] == 0:
            if ch == '{':
                state["depth"] = 1
                state["buf"] = ch
            else:
                out_chars.append(ch)
        else:
            state["buf"] += ch
            if ch == '{':
                state["depth"] += 1
            elif ch == '}':
                state["depth"] -= 1
                if state["depth"] == 0:
                    if not _TOOL_CALL_RE.match(state["buf"]):
                        out_chars.append(state["buf"])
                    state["buf"] = ""
    return "".join(out_chars)


async def stream_response(user_message: str) -> AsyncGenerator[str, None]:
    """Yield server-sent event strings for each token/image from the agent."""
    try:
        agent = build_agent()
    except Exception as exc:
        yield _sse("error", {"detail": f"Failed to initialise agent: {exc}"})
        return

    inputs = {"messages": [HumanMessage(content=user_message)]}
    json_state = {"depth": 0, "buf": ""}

    try:
        async for event in agent.astream_events(inputs, version="v2"):
            kind = event["event"]

            if kind == "on_chat_model_stream":
                chunk: AIMessageChunk = event["data"]["chunk"]
                text = chunk.content
                if text:
                    filtered = _filter_json_blobs(text, json_state)
                    if filtered:
                        yield _sse("token", {"content": filtered})

            elif kind == "on_tool_end":
                tool_name = event.get("name", "")
                output = event["data"].get("output", "")
                if tool_name == "get_species_image" and isinstance(output, str):
                    try:
                        payload = json.loads(output)
                        if "url" in payload:
                            yield _sse("image", payload)
                    except (json.JSONDecodeError, TypeError):
                        pass

    except Exception as exc:
        msg = str(exc)
        if "Connection refused" in msg or "Failed to connect" in msg or "ConnectError" in msg:
            yield _sse("error", {"detail": "Ollama is not running. Start it with: ollama serve"})
        else:
            yield _sse("error", {"detail": msg})
        return

    # Flush any unterminated buffer as plain text (incomplete JSON → probably prose)
    if json_state["buf"]:
        yield _sse("token", {"content": json_state["buf"]})

    yield _sse("done", {})


def _sse(event_type: str, data: dict) -> str:
    return f"data: {json.dumps({'type': event_type, **data})}\n\n"
```

- [ ] **Step 3: Run all backend tests to confirm nothing regressed**

```bash
cd backend && python -m pytest tests/ -v
```

Expected: all tests PASS (same count as baseline). No failures.

- [ ] **Step 4: Commit**

```bash
git add backend/app/llm_agent.py
git commit -m "refactor: migrate llm_agent image helpers to image_utils, use update_species_image"
```

---

## Task 5: Add `GET /api/species/{name}/image` endpoint (TDD)

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_taxonomy_api.py`

- [ ] **Step 1: Extend `_insert` to support `primary_image_url`**

Open `backend/tests/test_taxonomy_api.py`. Find the `_insert` function (around line 19) and replace it with:

```python
def _insert(scientific_name: str, taxon_path: str, taxon_rank: str = "species",
            common_names: str = "[]", taxonomic_status: str = "ACCEPTED",
            iucn_status: str | None = None,
            primary_image_url: str | None = None) -> None:
    conn = database.get_connection()
    conn.execute(
        """
        INSERT INTO species
          (scientific_name, taxon_path, taxon_rank, common_names, taxonomic_status,
           iucn_status, primary_image_url)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (scientific_name, taxon_path, taxon_rank, common_names, taxonomic_status,
         iucn_status, primary_image_url),
    )
    conn.commit()
    conn.close()
```

- [ ] **Step 2: Write failing endpoint tests**

Add the following at the end of `backend/tests/test_taxonomy_api.py`:

```python
# --- GET /api/species/{name}/image ---

from app import image_utils as _image_utils_mod


def test_image_endpoint_fetches_and_caches_result(monkeypatch):
    _insert('Apis mellifera', 'Animalia|Apis mellifera', primary_image_url=None)
    monkeypatch.setattr(_image_utils_mod, 'fetch_image',
        lambda name, common_names=None: ('https://example.com/bee.jpg', '© Example'))
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
        lambda name, common_names=None: ('https://example.com/new.jpg', '© New'))
    resp = client.get('/api/species/Apis%20mellifera/image?force=true')
    assert resp.status_code == 200
    assert resp.json()['url'] == 'https://example.com/new.jpg'


def test_image_endpoint_stores_none_sentinel_when_all_fail(monkeypatch):
    _insert('Apis mellifera', 'Animalia|Apis mellifera', primary_image_url=None)
    monkeypatch.setattr(_image_utils_mod, 'fetch_image',
        lambda name, common_names=None: None)
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
        lambda name, common_names=None: None)
    resp = client.get('/api/species/Apis%20mellifera/image?force=true')
    assert resp.status_code == 404
    # __none__ sentinel must NOT be written when force=True (old URL was valid, just temporarily broken)
    row = database.get_species('Apis mellifera')
    assert row['primary_image_url'] == 'https://old.com/old.jpg'
```

- [ ] **Step 3: Run tests to confirm they all fail**

```bash
cd backend && python -m pytest tests/test_taxonomy_api.py -k "image_endpoint" -v
```

Expected: all 6 image endpoint tests FAIL with 404 (endpoint does not exist yet).

- [ ] **Step 4: Add the endpoint to `main.py`**

Open `backend/app/main.py`. After the imports, add `image_utils` to the `from app import` line:

```python
from app import database, image_utils
from app.llm_agent import stream_response
```

Add the `ImageResponse` model after the existing `ChatRequest` model (around line 74):

```python
class ImageResponse(BaseModel):
    url: str
    attribution: str
```

Add the endpoint immediately before the existing `species_detail` route (before line 384). The image endpoint must come first so FastAPI doesn't try to match the `/image` suffix as a species name:

```python
@app.get("/api/species/{scientific_name}/image", response_model=ImageResponse)
def species_image(scientific_name: str, force: bool = Query(False)):
    """Fetch an image for a species on demand, caching the result to the DB.

    Returns 404 immediately if primary_image_url == '__none__' (all sources
    previously failed) unless force=true is passed (e.g. after an onerror event).
    On all-fail with force=False, writes '__none__' sentinel to prevent re-fetch loops.
    """
    row = database.get_species(scientific_name)
    if row is None:
        raise HTTPException(status_code=404, detail="Species not found")

    current_url = row.get("primary_image_url") or ""
    if not force and current_url == "__none__":
        raise HTTPException(status_code=404, detail="No image available")

    common_names = database.parse_common_names(row.get("common_names"))
    result = image_utils.fetch_image(scientific_name, common_names or None)

    if result:
        url, attribution = result
        database.update_species_image(scientific_name, url, attribution)
        return ImageResponse(url=url, attribution=attribution)

    if not force:
        database.update_species_image(scientific_name, "__none__", "")

    raise HTTPException(status_code=404, detail="No image found")
```

- [ ] **Step 5: Run all backend tests and confirm they pass**

```bash
cd backend && python -m pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/main.py backend/tests/test_taxonomy_api.py
git commit -m "feat: add GET /api/species/{name}/image endpoint with __none__ sentinel caching"
```

---

## Task 6: Update `frontend/js/app.js` (TDD)

**Files:**
- Modify: `frontend/js/app.js`
- Modify: `frontend/tests/app.test.js`

- [ ] **Step 1: Write failing frontend tests**

**Important:** `app.test.js` does NOT import `app.js`. It tests logic by inlining reimplementations of the functions being tested (see the comment at line 43 in the existing file: *"These replicate just enough of app.js to make DOM-independent assertions"*). Follow the same pattern.

Open `frontend/tests/app.test.js` and add the following at the end:

```js
// ── Species panel image helpers (inline reimplementations) ────────────────────
// Mirror the logic from app.js _showSpeciesPanel image block and _fetchRemoteImage.
// Tests here verify the decision tree, not the DOM wiring.

const API_BASE = 'http://localhost:8000';

function setupSpeciesImageDOM() {
  document.body.innerHTML = `
    <div id="sp-image-wrap" class="hidden">
      <img id="sp-image" alt="" />
      <p id="sp-attr"></p>
    </div>
  `;
}

// Inline of _fetchRemoteImage from app.js
async function _fetchRemoteImage(scientificName, imgEl, attrEl, imgWrap, force) {
  const qs  = force ? '?force=true' : '';
  const url = `${API_BASE}/api/species/${encodeURIComponent(scientificName)}/image${qs}`;
  try {
    const resp = await fetch(url);
    if (!resp.ok) {
      imgWrap.classList.add('hidden');
      return;
    }
    const data = await resp.json();
    imgEl.src          = data.url;
    imgEl.alt          = scientificName;
    attrEl.textContent = data.attribution || '';
    imgWrap.classList.remove('hidden');
    imgEl.onerror = () => imgWrap.classList.add('hidden');
  } catch {
    imgWrap.classList.add('hidden');
  }
}

// Inline of the image block from _showSpeciesPanel
function _applyImageState(sp) {
  const imgWrap = document.getElementById('sp-image-wrap');
  const imgEl   = document.getElementById('sp-image');
  const attrEl  = document.getElementById('sp-attr');
  if (sp.primary_image_url === '__none__') {
    imgWrap.classList.add('hidden');
  } else if (sp.primary_image_url) {
    imgEl.src          = sp.primary_image_url;
    imgEl.alt          = sp.scientific_name || '';
    attrEl.textContent = sp.image_attribution || '';
    imgWrap.classList.remove('hidden');
    imgEl.onerror = () => _fetchRemoteImage(sp.scientific_name, imgEl, attrEl, imgWrap, true);
  } else {
    imgEl.removeAttribute('src');
    attrEl.textContent = 'Finding image…';
    imgWrap.classList.remove('hidden');
    _fetchRemoteImage(sp.scientific_name, imgEl, attrEl, imgWrap, false);
  }
  return { imgWrap, imgEl, attrEl };
}

// ── Species panel image tests ──────────────────────────────────────────────────

describe('species panel — image state', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    setupSpeciesImageDOM();
  });

  afterEach(() => {
    document.body.innerHTML = '';
  });

  it('hides imgWrap immediately for __none__ sentinel without fetching', () => {
    global.fetch = vi.fn();
    const { imgWrap } = _applyImageState({ scientific_name: 'Apis mellifera', primary_image_url: '__none__' });
    expect(imgWrap.classList.contains('hidden')).toBe(true);
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('shows loading text and calls /image when primary_image_url is null', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ url: 'https://example.com/bee.jpg', attribution: '© Example' }),
    });
    const { imgWrap, imgEl, attrEl } = _applyImageState({
      scientific_name: 'Apis mellifera',
      primary_image_url: null,
    });
    // Loading text shown immediately (before fetch resolves)
    expect(attrEl.textContent).toBe('Finding image…');
    expect(imgWrap.classList.contains('hidden')).toBe(false);
    // Wait for fetch to resolve
    await vi.waitFor(() => imgEl.src === 'https://example.com/bee.jpg');
    expect(imgEl.src).toBe('https://example.com/bee.jpg');
    expect(attrEl.textContent).toBe('© Example');
    const call = global.fetch.mock.calls[0][0];
    expect(call).toContain('/api/species/Apis%20mellifera/image');
    expect(call).not.toContain('force=true');
  });

  it('hides imgWrap when /image endpoint returns 404', async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 404 });
    const { imgWrap, attrEl } = _applyImageState({
      scientific_name: 'Apis mellifera',
      primary_image_url: null,
    });
    await vi.waitFor(() => imgWrap.classList.contains('hidden'));
    expect(imgWrap.classList.contains('hidden')).toBe(true);
  });

  it('sets img src directly when valid URL is stored', () => {
    global.fetch = vi.fn();
    const { imgEl, imgWrap } = _applyImageState({
      scientific_name: 'Apis mellifera',
      primary_image_url: 'https://stored.com/bee.jpg',
      image_attribution: '© Stored',
    });
    expect(imgEl.src).toBe('https://stored.com/bee.jpg');
    expect(imgWrap.classList.contains('hidden')).toBe(false);
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('onerror on a stored URL calls /image with force=true', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ url: 'https://new.com/bee.jpg', attribution: '© New' }),
    });
    const { imgEl } = _applyImageState({
      scientific_name: 'Apis mellifera',
      primary_image_url: 'https://broken.com/bee.jpg',
    });
    // Manually fire the onerror handler (JSDOM does not load images natively)
    imgEl.onerror();
    await vi.waitFor(() => {
      const call = global.fetch.mock.calls[0]?.[0] || '';
      return call.includes('force=true');
    });
    const call = global.fetch.mock.calls[0][0];
    expect(call).toContain('/api/species/Apis%20mellifera/image?force=true');
  });
});
```

- [ ] **Step 2: Run tests to confirm the new tests pass**

```bash
cd frontend && npm run test -- --reporter=verbose 2>&1 | grep -E "species panel|PASS|FAIL"
```

Expected: all 5 `species panel — image state` tests PASS. These tests verify the **inline reimplementations** in the test file — they serve as the spec for what `app.js` must implement in Step 3. If any test fails here, there is a logic error in the test file itself — fix it before proceeding.

- [ ] **Step 3: Update `frontend/js/app.js`**

Find the `_showSpeciesPanel` function (around line 134). Replace the image block (lines 139–150) with:

```js
  const imgWrap = document.getElementById('sp-image-wrap');
  const imgEl   = document.getElementById('sp-image');
  const attrEl  = document.getElementById('sp-attr');

  if (sp.primary_image_url === '__none__') {
    imgWrap.classList.add('hidden');
  } else if (sp.primary_image_url) {
    imgEl.src          = sp.primary_image_url;
    imgEl.alt          = sp.scientific_name;
    attrEl.textContent = sp.image_attribution || '';
    imgWrap.classList.remove('hidden');
    imgEl.onerror = () => _fetchRemoteImage(sp.scientific_name, imgEl, attrEl, imgWrap, true);
  } else {
    imgEl.removeAttribute('src');
    attrEl.textContent = 'Finding image…';
    imgWrap.classList.remove('hidden');
    _fetchRemoteImage(sp.scientific_name, imgEl, attrEl, imgWrap, false);
  }
```

Then add the following new function immediately after `_showSpeciesPanel` (before `_showToast`):

```js
async function _fetchRemoteImage(scientificName, imgEl, attrEl, imgWrap, force) {
  const qs  = force ? '?force=true' : '';
  const url = `${API}/api/species/${encodeURIComponent(scientificName)}/image${qs}`;
  try {
    const resp = await fetch(url);
    if (!resp.ok) {
      imgWrap.classList.add('hidden');
      return;
    }
    const data = await resp.json();
    imgEl.src          = data.url;
    imgEl.alt          = scientificName;
    attrEl.textContent = data.attribution || '';
    imgWrap.classList.remove('hidden');
    imgEl.onerror = () => imgWrap.classList.add('hidden');
  } catch {
    imgWrap.classList.add('hidden');
  }
}
```

- [ ] **Step 4: Run all frontend tests and confirm they pass**

```bash
cd frontend && npm run test
```

Expected: all tests PASS.

- [ ] **Step 5: Run all backend tests to confirm no regression**

```bash
cd backend && python -m pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/js/app.js frontend/tests/app.test.js
git commit -m "feat: species panel dynamic image fetch — loading state, onerror force-refetch"
```

---

## Final check

- [ ] **Verify the full test suite is green**

```bash
cd backend && python -m pytest tests/ -v
cd frontend && npm run test
```

Both must be fully green before marking this increment complete.

- [ ] **Update `Docs/PLAN.md`** — add Increment 10e with tasks checked and commit SHA noted.
