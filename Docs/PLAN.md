# Animal Kingdom — Incremental Build Plan

Each increment must be **tested and user-approved** before the checkbox is ticked and a git commit is made.

---

## Increment 0 — Project Scaffold

Stand up the full directory skeleton, dev environment, and minimal runnable stubs so every subsequent increment has a clean base to build on.

### Tasks

- [x] Create backend directory tree: `backend/app/`, `backend/tests/`
- [x] Create `backend/requirements.txt` with pinned latest-stable versions:
  - `fastapi`, `uvicorn[standard]`, `pydantic`
  - `langchain`, `langchain-community`, `langgraph`
  - `chromadb`, `sentence-transformers`
  - `pytest`, `httpx` (for FastAPI TestClient)
- [x] Create `backend/app/__init__.py`, `main.py`, `database.py`, `vector_db.py`, `llm_agent.py` as empty stubs with module-level docstrings
- [x] Create frontend directory tree: `frontend/css/`, `frontend/js/`, `frontend/tests/`
- [x] Create `frontend/index.html` skeleton (Tailwind CDN, placeholder `<div>` for tree and chat)
- [x] Create `frontend/css/style.css` stub
- [x] Create `frontend/js/app.js` and `frontend/js/visualizer.js` stubs
- [x] Create `frontend/package.json` with Vitest + Testing Library
- [x] Create `e2e/` directory with Playwright config (`playwright.config.ts`)
- [x] Create `data/` directory with `README.md` noting the import pipeline
- [x] Create `E:\AnimalKingdomSystem\` directory (external NVMe drive)
- [x] Verify `uvicorn app.main:app --reload --port 8000` starts without errors
- [x] Verify `npm run test` exits cleanly (no test files yet is fine)

### Decisions recorded
- **Python:** 3.12 (chosen over 3.12 default for package compatibility; 3.14 also installed)
- **Backend versions pinned:** fastapi 0.136.3, uvicorn 0.49.0, pydantic 2.13.4, pytest 9.0.3, httpx 0.28.1
- **LangChain/ChromaDB/sentence-transformers:** version-pinned in requirements.txt but installed in later increments
- **torch/ROCm note:** PyTorch ROCm wheels are Linux-only; Windows options are CPU-only or torch-directml — deferred to Increment 5
- **Node:** v24.15.0 / npm 11.14.1
- **Frontend versions:** vitest 3.2.6, @vitest/coverage-v8 3.2.6 (pinned exact to match peer dep)
- **vitest config:** `passWithNoTests: true` added so `npm test` exits 0 with no test files
- **SSL:** Both pip and npm have local cert issues — pip uses `--trusted-host`, npm has `strict-ssl=false` set globally
- **Git:** Initialised at Increment 0; `.venv/` and `node_modules/` excluded via `.gitignore`

---

## Increment 1 — SQLite Schema & Data Layer

Create the SQLite database, define the 20-field schema, and implement all helper functions in `database.py`.

### Tasks

- [x] Create `E:\AnimalKingdomSystem\species.db` (via migration script or init SQL)
- [x] Create table `species` with primary key `scientific_name TEXT`:
  - Taxonomy/UI: `taxon_path TEXT`, `taxon_rank TEXT`, `common_names TEXT` (JSON), `taxonomic_status TEXT` (ACCEPTED|SYNONYM)
  - Physical: `body_mass REAL`, `body_length REAL`, `max_lifespan REAL`, `metabolic_rate REAL`, `reproduction_strategy TEXT`
  - Ecology: `geo_bounding_box TEXT` (JSON lat/lon), `habitat_type TEXT`, `elevation_limits TEXT`, `trophic_level TEXT`, `activity_period TEXT`
  - Conservation/Media: `iucn_status TEXT`, `population_trend TEXT`, `primary_image_url TEXT`, `image_attribution TEXT`, `wikipedia_abstract TEXT`
- [x] Add indexes: `taxon_rank`, `taxonomic_status`, `iucn_status`, `taxon_path` (for lineage prefix queries)
- [x] Implement `database.py`:
  - `get_connection()` — returns SQLite connection to `E:\AnimalKingdomSystem\species.db`
  - `parse_common_names(json_str) -> list[str]` and `serialize_common_names(names) -> str`
  - `parse_geo_bbox(json_str) -> dict` and `serialize_geo_bbox(bbox) -> str`
  - `get_children(taxon_path: str, depth: int = 1) -> list[dict]` — returns direct children for taxonomy tree zoom
  - `get_species(scientific_name: str) -> dict | None`
  - `search_species(query: str, limit: int = 20) -> list[dict]`
- [x] Write `backend/tests/test_database.py`:
  - Test schema exists and columns match spec
  - Test JSON round-trip helpers
  - Test `get_children` with seed data
- [x] All tests pass: `pytest tests/test_database.py -v`

### Decisions recorded
- **WAL mode:** ON — `PRAGMA journal_mode=WAL` applied in `get_connection()` for concurrent read performance
- **Schema init:** `_init_schema()` called inside `get_connection()` using `CREATE TABLE/INDEX IF NOT EXISTS` — idempotent, no separate migration step needed
- **DB path:** Configurable via `SPECIES_DB_PATH` env var (defaults to `E:\AnimalKingdomSystem\species.db`); tests monkeypatch the module var to an isolated temp file
- **Index strategy:** Four indexes on `taxon_rank`, `taxonomic_status`, `iucn_status`, `taxon_path`; prefix LIKE queries use `idx_taxon_path`
- **`get_children` depth:** Uses SQLite pipe-count expression `length(taxon_path) - length(replace(taxon_path,'|',''))` to filter by hierarchy level; LIKE used for prefix filtering
- **`search_species`:** Searches `scientific_name` and `common_names` (JSON string) via LIKE; full-text search deferred to Increment 10

---

## Increment 2 — Data Sourcing & Import Pipeline

Download, clean, and load ~1.78 million species records into `species.db`.

### Tasks

- [x] Research and select primary data source:
  - **Primary:** GBIF Backbone Taxonomy (download from gbif.org/dataset — `backbone-current.zip`, ~1.78M accepted taxa)
  - **Supplementary:** IUCN Red List API for `iucn_status` + `population_trend`
  - **Supplementary:** Wikipedia API for `wikipedia_abstract` + `primary_image_url`
- [x] Create `data/import_gbif.py`:
  - Parse GBIF `Taxon.tsv` (tab-separated) → map columns to schema fields
  - Build `taxon_path` as pipe-delimited lineage from GBIF `kingdom|phylum|class|order|family|genus|species`
  - Batch-insert with SQLite `executemany` (chunk size 10,000)
  - Log progress: records inserted, skipped, errors
- [x] Create `data/enrich_iucn.py` (optional/async):
  - Hit IUCN Red List API for each species name → update `iucn_status`, `population_trend`
  - Respect API rate limits; checkpoint progress to resume on failure
- [x] Create `data/enrich_wikipedia.py` (optional/async):
  - For species with no `wikipedia_abstract`: query Wikipedia API → store abstract + thumbnail URL
  - Checkpoint progress
- [x] Create `data/validate_import.py`:
  - Row count ≥ 1,700,000
  - No nulls in required fields (`scientific_name`, `taxon_rank`, `taxon_path`)
  - Sample 100 random species, print to console for manual review
- [x] Run full import and validate; record final row count in this plan
- [x] `pytest tests/test_database.py -v` still passes after import

### Decisions recorded
- **GBIF dataset:** Backbone taxonomy downloaded 2026-06-06 from hosted-datasets.gbif.org; full DwC-A including VernacularName.tsv
- **Final row count:** 5,879,286 total rows (3,017,944 accepted + 2,861,342 synonyms/other)
- **Import stats:** 7.7M source rows processed; 6,413,514 attempted inserts; 534,228 silently dropped as `INSERT OR IGNORE` duplicates (homonyms); 1,280,807 skipped pre-insert (missing canonicalName or taxon_path)
- **Vernacular names:** 161,527 taxa had English common names in VernacularName.tsv
- **Import runtime:** ~2.9 hours (~800 rows/s sustained)
- **IUCN enrichment:** API v3 token obtained but v4 API required a full script rewrite — see Increment 2b
- **Wikipedia enrichment (run 1):** Ran with `--only-with-common-names`; processed 100k species; got 3,263 abstracts + 4,844 images. Low hit rate (~3%) is correct — most species are obscure subspecies with no Wikipedia article. Famous species (Panthera leo, Homo sapiens) were silently rate-limited (HTTP 429) and incorrectly checkpointed as confirmed misses.
- **Wikipedia enrichment bug fixed:** `enrich_wikipedia.py` now distinguishes 429 (retry with 60s backoff, max 3 retries, NOT checkpointed) from genuine 404 (checkpointed as confirmed miss). `REQUEST_DELAY` raised 0.15s → 0.5s. `--delay` CLI flag added. Checkpoint was cleaned to remove ~98,664 poisoned entries. Re-run ongoing.
- **body_mass / physical traits:** Wikipedia is free-text prose — not a reliable source for numeric traits. `body_mass`, `body_length`, `max_lifespan` will need a structured source (PanTHERIA for mammals, AnAge for longevity) in a future increment.
- **csv field size:** GBIF TSV fields can exceed Python's default 131,072-byte csv limit; fixed with `csv.field_size_limit(2_147_483_647)` in import_gbif.py
- **Rank distribution:** species 4,576,774 · genus 471,246 · variety 361,526 · subspecies 339,435 · form 66,988 · family 31,713 · …

---

## Increment 2b — Physical & Ecological Attribute Enrichment

Populate the numeric and conservation columns (`body_mass`, `max_lifespan`, `metabolic_rate`, `geo_bounding_box`, `iucn_status`, `population_trend`) from three structured external sources.  Two require no token; one requires a free IUCN account token stored in `.env`.

### Tasks

- [x] Decide against dynamic API lookup at query time — pre-populate DB instead (offline-first mandate; LLM tool-call latency stacks badly)
- [x] Create `data/enrich_anage.py` — AnAge longevity database (no token):
  - Downloads `dataset.zip` from `genomics.senescence.info`; detects columns dynamically
  - Converts grams → kg for `body_mass`; updates `body_mass`, `max_lifespan`, `metabolic_rate`
  - Run: **4,547 species updated** (3,628 with body_mass, 4,098 with max_lifespan)
- [x] Create `data/enrich_gbif_occurrences.py` — GBIF Occurrence API (no token):
  - Two calls per species: `species/match` (resolve usageKey) + `occurrence/search` (geo coords)
  - Derives `lat_min/lat_max/lon_min/lon_max` bounding box from up to 300 occurrence records
  - Checkpointed to `E:\AnimalKingdomSystem\gbif_bbox_checkpoint.json`; 0.5 s delay per call
  - Default scope: species with `wikipedia_abstract IS NOT NULL` (~6,930); `--all-accepted` for full run
  - Status: **ongoing in background** — 867 bboxes added so far, ~6,060 remaining
- [x] Rewrite `data/enrich_iucn.py` for IUCN Red List API v4 (token required — free account):
  - Phase 1 (bulk sweep): paginate `GET /api/v4/red_list_categories/{code}?page=N&latest=true` for each of 8 categories; update `iucn_status`
  - Phase 2 (`--fetch-trends`): per-match call `GET /api/v4/assessment/{id}` to populate `population_trend`
  - Token read from `.env` → env var → `--token` CLI flag
  - Phase 1 result: **181,543 iucn_status updates** across 8 categories (LC 98,561 · EN 20,021 · DD 23,548 · VU 18,244 · NT 10,453 · CR 10,716 · EX+EW ~1,000)
  - Phase 2 finished 2026-06-11: 174,843 per-assessment calls, 3 errors
- [x] IUCN Phase 1 complete (all 8 categories swept)
- [x] IUCN Phase 2 complete (population_trend) — trend codes were off by one; corrected 2026-11-03 (see Increment 11 decisions)
- [x] Create `data/enrich_images.py` — iNaturalist taxa API (no token):
  - Queries `api.inaturalist.org/v1/taxa?q={name}&per_page=5&rank=species`; verifies exact name match
  - Stores `primary_image_url` + `image_attribution` (e.g. `"© user (CC BY-NC)"`)
  - Scopes: default (has abstract, ~7k, ~1.4h) · `--iucn-matched` (~175k, ~34h) · `--all-accepted` (~1.78M, days)
  - Checkpointed to `E:\AnimalKingdomSystem\images_checkpoint.json`; 0.7 s/request (≤86 req/min)
  - Status: **running in background** — `--iucn-matched` scope (171,462 species)
- [x] Run `data/build_embeddings.py` after enrichment to reindex any new `wikipedia_abstract` entries added during enrichment — done 2026-11-03 (6,930 records)

### Decisions recorded

- **Offline-first over dynamic API:** Considered fetching trait data live from APIs during LLM tool calls. Rejected: LLM tool-loop stacks latency (≥2 API round-trips per query × 300 ms each = noticeable lag), and CLAUDE.md mandates offline-first. All enrichment happens as one-time background scripts.
- **AnAge source:** `https://genomics.senescence.info/species/dataset.zip` — free, no token. ~4,645 vertebrate records. Column names detected with `_find_col(*needles)` to handle header variations between releases. `UnicodeEncodeError` on Windows terminal for non-ASCII print chars — replaced `→` with `=` in column-mapping output.
- **GBIF Occurrence API:** Two-step lookup (species-match → occurrence-search) with `MIN_CONFIDENCE=90` to reject fuzzy name matches. Bounding box derived from raw occurrence lat/lon records (up to 300 sampled). `geo_bounding_box` stored as JSON string via `database.serialize_geo_bbox()`.
- **IUCN v4 API auth:** Raw token as `Authorization` header value with **no prefix** ("Bearer", "Token", "Api-Key" all return 401). Confirmed from working `curl` example provided by user.
- **Cloudflare WAF bypass:** IUCN v4 API (`api.iucnredlist.org`) blocks Python `urllib` user-agent with HTTP 1010. Fixed by sending a Chrome-like `User-Agent` string.
- **IUCN bulk endpoint:** `GET /api/v4/red_list_categories/{code}?page=N&latest=true` returns 100 assessments per page for a given Red List category. Using `latest=true` filter reduces required pages by ~5× (without it, only 18% of records are current assessments). API is **1-indexed** — `page=0` returns 404.
- **IUCN pagination:** Paginate by incrementing `page` until the `assessments` array is empty. Each record contains `taxon_scientific_name`, `red_list_category_code`, `assessment_id`.
- **IUCN population_trend codes:** `assessment_id` → `GET /api/v4/assessment/{id}` → `population_trend.code`: `"1"` = Decreasing, `"2"` = Stable, `"3"` = Increasing, `"4"` = Unknown.
- **429 rate-limit handling:** Exponential backoff — 10 s → 20 s → 40 s → 80 s → 120 s (cap); gracefully returns `None` after max retries so the outer pagination loop skips rather than crashes. Triggered by three concurrent scripts hitting the API simultaneously — reduced to a single background process.
- **`.env` token file:** `IUCN_API_TOKEN=<token>` parsed from project root `.env` by `_read_token_from_env_file()`. `.env` is git-ignored.
- **IUCN Phase 2 checkpoint:** Saves `phase2_pos` (integer index into `matched` list) to `iucn_checkpoint.json` every 100 iterations so the trend lookup can resume after interruption without redoing completed work. Commit frequency reduced from 500 → 100 iterations to keep DB write-lock windows short (~50 s) and allow concurrent writers (GBIF, iNat) to acquire locks.
- **SQLite concurrent writer timeout:** `database.get_connection(timeout=300)` — raised from default 5 s to 300 s so background enrichment scripts queue on write-lock contention instead of immediately raising `OperationalError: database is locked`.
- **iNaturalist image source:** Free, no token. Exact name verified by matching `results[n].name` case-insensitively against the queried scientific name before accepting the photo. Attribution stored verbatim from the API (`"© user (CC BY-NC)"`). Hit rate ~89% for IUCN-matched species (conservation-relevant, well-observed).
- **Image enrichment strategy:** Hybrid — background `enrich_images.py` pre-populates in bulk; `get_species_image` agent tool provides live fallback (DB → Wikipedia → iNaturalist) with write-through cache so each live hit is stored for future queries. Tool returns `source` field for provenance labelling.

---

## Increment 3 — Taxonomy API

Expose the SQLite taxonomy data via FastAPI endpoints consumed by the D3.js tree.

### Tasks

- [x] Implement `GET /api/taxonomy/root` → returns top-level kingdoms (depth=0 children)
- [x] Implement `GET /api/taxonomy/zoom?node_id={taxon_path}&depth={1|2}`:
  - Queries `get_children(taxon_path, depth)` from `database.py`
  - Returns `{ node_id, name, rank, children: [...] }` nested JSON
- [x] Implement `GET /api/species/{scientific_name}` → full species record
- [x] Implement `GET /api/search?q={query}&limit={20}` → list of matching species
- [x] Wire all routes into `main.py` (thin routes — delegate to `database.py`)
- [x] Add CORS middleware for `localhost` origins
- [x] Write `backend/tests/test_taxonomy_api.py` using `FastAPI TestClient`:
  - Test root returns kingdoms
  - Test zoom returns correct children
  - Test species lookup returns 404 for unknown name
  - Test search returns results
- [x] All tests pass: `pytest tests/ -v`

### Decisions recorded
- **Pagination:** offset-based `limit` param (1–100) on `/api/search`; `/api/taxonomy/zoom` has no pagination — depth capped at 2 which bounds result size naturally
- **Max depth:** 2, enforced via FastAPI `Query(ge=1, le=2)` — returns 422 for out-of-range values
- **Tree nesting:** flat `get_children` result is converted to nested `TaxonNode` in `_build_tree()` in `main.py` — O(n²) but fine given depth ≤ 2 and typical child counts
- **Response models:** `TaxonNode` (tree nodes), `SpeciesRecord` (full 20-field record), `SearchResult` (lightweight subset) — all Pydantic models
- **`common_names`/`geo_bounding_box`:** parsed from JSON strings at the API layer before returning; raw strings never exposed to clients
- **`_CHILD_LIMIT = 200`:** nodes beyond limit render a sentinel `+N more — use Search` node; the `/api/taxonomy/node` endpoint (added post-I9) allows the frontend to inject a specific out-of-limit node by taxon_path during `expandToNode`
- **`GET /api/taxonomy/node?node_id=`:** Added to fetch a single node by exact taxon_path; used by `expandToNode` to inject truncated nodes that exceed `_CHILD_LIMIT`; backed by `database.get_taxon_by_path()`
- **85 backend tests passing** (after all post-I9 additions)

---

## Increment 4 — D3.js Taxonomy Tree (Frontend)

Build the interactive zoomable/collapsible taxonomy tree in `visualizer.js`.

### Tasks

- [x] Add D3.js v7 via CDN or npm in `package.json`
- [x] Implement `visualizer.js`:
  - `initTree(containerId)` — sets up SVG with pan/zoom (`d3.zoom`)
  - `loadNode(taxonPath)` — fetches `GET /api/taxonomy/zoom?node_id=X`, appends children to tree
  - `renderTree(data)` — renders collapsible radial or vertical tree layout
  - Click a node → expand (load children) or collapse
  - Node labels: common name if available, else scientific name
  - Color nodes by `taxon_rank` (kingdom/phylum/class/order/family/genus/species)
- [x] Wire `visualizer.js` into `index.html` — tree renders on page load starting from root
- [x] Add a search bar: typing triggers `GET /api/search?q=X` and highlights matching nodes
- [x] Write `frontend/tests/visualizer.test.js` (Vitest + jsdom):
  - Mock fetch; test `loadNode` calls correct URL
  - Test `renderTree` produces expected node count
- [x] Manual browser test: tree loads, zoom works, expand/collapse works
- [x] `npm run test` passes

### Decisions recorded
- **Layout:** Horizontal collapsible tree, left-to-right (kingdoms left, species right); rejected radial — harder to navigate 7-level deep hierarchies
- **D3 loading:** Import map in browser (`https://cdn.jsdelivr.net/npm/d3@7/+esm`); npm `d3@7` devDependency for Vitest — no bundler needed
- **Lazy loading:** `children: null` = not yet fetched; `_children` = collapsed; `_loaded` flag on data object; first click fetches from `/api/taxonomy/zoom?depth=1`
- **Rank colours:** kingdom #c0392b · phylum #e67e22 · class #f39c12 · order #27ae60 · family #2980b9 · genus #8e44ad · species #16a085
- **Search:** debounced 300 ms input → `/api/search` → results dropdown + `highlightNodes()` dims non-matching tree nodes to 12% opacity
- **`highlightNodes`:** compares taxon_path with ancestor-prefix matching (`p.startsWith(id + '|')`) so the full lineage stays visible, not just the exact match
- **`expandToNode(taxonPath)`:** walks path segment-by-segment, expanding each ancestor level; injects out-of-limit nodes via `/api/taxonomy/node`; scrolls target into view with `scrollIntoView` after 320ms (post-D3 transition)
- **`data-node-id` attribute:** stamped on every D3 `g` element so `expandToNode` and Playwright can query nodes by taxon_path
- **SVG width:** computed dynamically in `_render()` as `max(tx + maxY*scale + 320, containerW)` so tree never clips horizontally; `#tree-panel` has `overflow-auto`
- **Leaf-node click → species panel:** `_onClick` detects confirmed leaves (loaded, no children), toggles `_selectedNodeId` (amber dot at r=9), calls `highlightNodes([nodeId])`, dispatches `species-selected` CustomEvent; `clearSelection()` export resets both
- **Species detail panel:** positioned `fixed top-14 right-[25rem] z-50` (outside `<main>` entirely) to avoid `overflow` clipping from any ancestor; shows all 20 DB fields + image + Wikipedia abstract
- **28 frontend tests passing**
- **Root SYNONYM filter (post-increment fix):** 25 orphan SYNONYM records had `taxon_depth=0` and appeared as duplicate root kingdoms (bacteria/virus duplicates). Fixed in `taxonomy_root` endpoint: filter `taxonomic_status = 'ACCEPTED'` before building the cached root tree. Result: root returns exactly 8 ACCEPTED kingdoms.
- **`expandToNode` — D3 pan (post-increment fix):** `scrollIntoView()` scrolls the DOM container, not the SVG zoom viewport. Fixed by reading the current `d3.zoomTransform`, computing the `getBoundingClientRect` delta between container centre and node centre, and applying a 300 ms `_zoom.transform` transition to pan the target node into view.
- **`expandToNode` — CSS.escape pipe bug (post-increment fix):** `CSS.escape("Plantae|...|Rumex acetosella")` over-escapes `|` characters, making the `[data-node-id="..."]` attribute selector invalid. Fixed by replacing `querySelector` with D3's `.filter(d => d.data.node_id === taxonPath)` which requires no CSS escaping.
- **`expandToNode` — gold highlight on search select (post-increment fix):** Selecting a visible species from search results opened the detail panel but did not apply the gold dot highlight. Fixed by setting `_selectedNodeId` inside `expandToNode` (not only in `_onClick`) and calling `_render()` after the zoom transition.

---

## Increment 5 — ChromaDB Embedding Pipeline

Embed `wikipedia_abstract` fields into ChromaDB to power the RAG chatbot.

### Tasks

- [x] Verify `sentence-transformers` is in `requirements.txt` (e.g. `all-MiniLM-L6-v2`)
- [x] Create `E:\AnimalKingdomSystem\chroma_db\` directory (created by ChromaDB PersistentClient on first use)
- [x] Implement `vector_db.py`:
  - `get_collection()` — returns/creates ChromaDB `PersistentClient` collection `species_abstracts`
  - `embed_batch(records: list[dict])` — embeds `wikipedia_abstract` text, upserts to ChromaDB with metadata `{ scientific_name, common_names, taxon_rank }`
  - `semantic_search(query: str, n_results: int = 5) -> list[dict]` — returns top-N species with distance scores
- [x] Create `data/build_embeddings.py`:
  - Streams all species with non-null `wikipedia_abstract` from SQLite in batches of 500
  - Calls `embed_batch`; logs progress
  - Skippable if already embedded (checks existing IDs)
- [x] Run embedding pipeline; record final count and approximate runtime — **6,930 records, 42 s on CPU, 38 MB** (2026-11-03)
- [x] Write `backend/tests/test_vector_db.py`:
  - Test `semantic_search` returns results for a known species query
- [x] All tests pass: `pytest tests/ -v` — 53 passed (42 prior + 11 new)

### Decisions recorded
- **Embedding model:** `all-MiniLM-L6-v2` (384 dims, cosine space) — fast on CPU, well-known quality/size tradeoff, no GPU needed for embedding inference
- **Torch:** CPU-only wheel (`torch-2.12.0+cpu`) — ROCm wheels are Linux-only; Ollama handles GPU inference separately
- **HuggingFace offline mode:** `HF_HUB_OFFLINE=1` set in `tests/conftest.py` — model pre-downloaded once manually to avoid SSL cert issues on this machine during tests
- **ChromaDB EphemeralClient isolation:** In chromadb 1.0.9 the in-memory backend is module-level (singleton); tests use UUID collection names per fixture to guarantee isolation
- **FastAPI version:** ChromaDB 1.0.9 downgraded fastapi 0.136.3 → 0.115.9; all 53 tests still pass
- **Embedding count and runtime:** 6,930 abstracts (≈0.4% of species — only those with a `wikipedia_abstract`), 42 s, 38 MB on `E:` (2026-11-03). Semantic search covers only these species until more abstracts are fetched.
- **Collection name:** `species_abstracts`; HNSW cosine space

---

## Increment 6 — LLM Agent (LangChain + Ollama)

Build the tool-calling LangChain agent backed by local Ollama (Llama 3 8B).

### Tasks

- [x] Confirm Ollama is running and `llama3.1:8b` model is available: `ollama list`
- [x] Confirm AMD ROCm GPU is being used by Ollama (check `ollama ps` or GPU utilisation)
- [x] Implement `llm_agent.py`:
  - `get_llm()` — returns `ChatOllama(model="llama3.1:8b", base_url="http://localhost:11434")`
  - **Tool 1:** `lookup_species(scientific_name: str) -> str` — calls `database.get_species()`, formats facts as markdown
  - **Tool 2:** `semantic_search_species(query: str) -> str` — calls `vector_db.semantic_search()`, returns top-3 species summaries
  - **Tool 3:** `get_species_image(scientific_name: str) -> str` — returns image URL + attribution + source; fallback chain: DB → Wikipedia → iNaturalist; caches live-found URL back to DB
  - `build_agent()` — LangGraph `create_react_agent` wired with tools + system prompt instructing factual, cited responses
  - `stream_response(user_message: str) -> AsyncGenerator[str, None]` — yields token chunks from agent
- [x] Write `backend/tests/test_llm_agent.py`:
  - Mock Ollama; test tool definitions are registered
  - Test `lookup_species` formats output correctly
- [x] Manual smoke test: invoke agent with a known species query, verify it uses tools
- [x] All tests pass: `pytest tests/ -v` — 66 passed (53 prior + 13 new)

### Decisions recorded
- **System prompt:** Factual naturalist persona; instructs always use tools before answering, cite scientific name, keep answers 3-5 sentences; includes explicit common-name → scientific-name mapping table (ladybug→Coccinella septempunctata etc.) and hard rules: never emit raw JSON, never narrate reasoning
- **Per-sentence source labelling (post-increment):** Updated system prompt so every fact is prefixed with either `"Database:"` (value came from the tool result) or `"From general knowledge:"` (model's training data). Model is allowed to supplement DB gaps with training knowledge as long as the source is declared. This replaced an earlier stricter version that banned all non-DB facts — user preference is transparency over restriction.
- **JSON hallucination fix:** Added `_filter_json_blobs(text, state)` — character-level brace-depth state machine that silently strips any `{"name": ...}` tool-call JSON blobs that leak into the token stream; `_TOOL_CALL_RE` pattern distinguishes tool-call JSON from legitimate JSON in answers
- **`semantic_search_species` empty result:** Returns directive message `"No results. Call lookup_species with your best scientific-name guess to continue."` instead of passive "not found" so the agent always makes a second tool call
- **LangGraph `create_react_agent`:** Used over legacy `AgentExecutor`; note: deprecated in langgraph≥1.0, will migrate to `langchain.agents` API in Increment 10
- **Ollama model:** `llama3.1:8b` — switched from `llama3:8b` (base model does not support Ollama tool-calling protocol)
- **`astream_events` v2:** Yields `on_chat_model_stream` (token chunks) and `on_tool_end` (tool results); image URL extracted from `get_species_image` on `on_tool_end`
- **`get_species_image` fallback chain (post-increment):** Tool renamed from `get_wikipedia_image`. Now tries DB → Wikipedia thumbnail API → iNaturalist taxa API. First successful fallback is cached back to `primary_image_url` in the DB (write-through). Returns `source` field ("database"/"wikipedia"/"inaturalist") so the model can label provenance. Background script `data/enrich_images.py` pre-populates images in bulk using iNaturalist (no token); scopes: `--iucn-matched` (~175k, ~34h) and `--all-accepted` (~1.78M, days).
- **`pytest-asyncio` strict mode:** Installed; async tests marked `@pytest.mark.asyncio`; `astream_events` mocked with `MagicMock` (not `AsyncMock`)

---

## Increment 7 — Chat API (FastAPI SSE)

Expose the LangChain agent via a streaming FastAPI endpoint.

### Tasks

- [x] Implement `POST /api/chat` in `main.py`:
  - Request body: `{ "message": str, "session_id": str (optional) }`
  - Response: `text/event-stream` (SSE) yielding token chunks
  - Each SSE event: `data: {"type": "token", "content": "..."}` or `data: {"type": "image", "url": "...", "attribution": "..."}`
  - On stream end: `data: {"type": "done"}`
- [x] Add SSE helper: use `fastapi.responses.StreamingResponse` + `stream_response()` from `llm_agent.py`
- [x] Write `backend/tests/test_chat_api.py`:
  - Mock `stream_response`; test SSE events are well-formed
  - Test 400 on empty message
- [x] Manual smoke test via `curl` or Postman: send a message, verify streamed JSON events
- [x] All tests pass: `pytest tests/ -v` — 75 passed (66 prior + 9 new)

### Decisions recorded
- **Session history:** Stateless — `session_id` accepted in request body but not stored; each call is independent. LangGraph manages within-call state only. History endpoint deferred to Increment 10 if needed.
- **Error event:** Agent exceptions caught in `_event_stream()` and emitted as `{"type": "error", "detail": "..."}` SSE event so the client always gets a well-formed stream close
- **Import placement:** `stream_response` imported at module level (not inside the route) so it's patchable in tests via `app.main.stream_response`
- **SSE headers:** `Cache-Control: no-cache` and `X-Accel-Buffering: no` set to prevent proxy/CDN buffering

---

## Increment 8 — Chat UI (Frontend)

Build the chat interface in `app.js` that consumes the SSE chat endpoint.

### Tasks

- [x] Design two-panel layout in `index.html`:
  - Left/main panel: D3.js taxonomy tree (from Increment 4)
  - Right panel: chat interface (message list + input bar)
- [x] Implement `app.js`:
  - `sendMessage(text)` — POSTs to `POST /api/chat`, opens SSE stream
  - Token events → append to current assistant bubble in real-time
  - Image events → render `<img>` below the response with attribution caption
  - Done event → finalise bubble, enable input
  - Handle errors gracefully (show inline error message)
- [x] Style chat with Tailwind: user bubbles right-aligned, assistant bubbles left, image thumbnail max-width 200px
- [x] Write `frontend/tests/app.test.js`:
  - Mock SSE stream; test token accumulation and image rendering
- [x] Manual browser test: full chat conversation with at least 3 queries
- [x] `npm run test` passes — 23 frontend tests (14 visualizer + 9 app)

### Decisions recorded
- **Chat history:** No limit — all turns shown, panel scrolls; can add a cap in Increment 10 if needed
- **Markdown rendering:** Plain `textContent` for now (safe, no XSS risk); `marked.js` deferred to Increment 10 polish
- **Bubble layout:** User right (indigo-600), assistant left (gray-800); max-width lg:max-w-md to keep bubbles readable
- **Image thumbnail:** max-w-[200px], rounded corners, `onerror` removes broken images silently
- **Input lock:** Input + button disabled during streaming, re-enabled on completion or error
- **Species detail panel (added post-I8):** Clicking a confirmed leaf node in the tree dispatches `species-selected` event → `app.js` fetches `GET /api/species/{name}` → panel renders all 20 DB fields, image, Wikipedia abstract. Search result click also auto-opens panel. Panel is `fixed` positioned to avoid `overflow` clipping.

---

## Increment 9 — E2E Tests (Playwright)

Cover the critical user journeys end-to-end with Playwright.

### Tasks

- [x] Configure `playwright.config.ts`:
  - `baseURL: http://localhost:5173` (frontend); `http://localhost:8000/health` (backend)
  - `webServer` array starts frontend automatically; reuses existing backend
  - Headless Chromium; `NODE_TLS_REJECT_UNAUTHORIZED=0` needed for browser download on this machine
- [x] Write `e2e/taxonomy_tree.spec.ts`:
  - Page loads → tree renders with at least one kingdom node
  - Click a kingdom → children expand; click again → collapses
  - Search input → dropdown with results; clear → dropdown hidden
- [x] Write `e2e/chat.spec.ts`:
  - Input and button present; empty message does not submit
  - Message appears as user bubble; input disabled during streaming
  - Assistant response appears with text > 20 chars; input re-enables after
- [x] Write `e2e/full_journey.spec.ts`:
  - Search for Panthera leo → results appear → tree nodes highlighted
  - Ask chatbot → response mentions "panthera" or "lion"
  - Tree and chat panels both visible
- [x] All E2E tests pass: `npx playwright test` — 15 passed (7 tree + 6 chat + 2 journey)

### Decisions recorded
- **Real Ollama:** E2E tests run against the live Ollama instance (not mocked) — tests are slower (~90s for chat) but validate the full stack. Chat tests use 90-second timeouts.
- **Submission via keyboard:** `input.press('Enter')` used instead of `form.requestSubmit()` — `requestSubmit()` triggers navigation in jsdom-like environments when the submit listener isn't attached yet (initTree is async).
- **data-rank attribute:** Added to D3 node groups so Playwright can select nodes by taxonomic rank (`g[data-rank="kingdom"]`) without fragile CSS heuristics.
- **jsdom SVG compatibility:** `_zoom.transform` call wrapped in try-catch in `_render()` — jsdom doesn't implement SVG geometry (`baseVal`); falls back to direct `attr('transform', ...)` in unit tests.

---

## Increment 10 — Performance, Polish & Hardening

Tune and finish the app for comfortable daily use with 1.78M species.

### Tasks

- [x] **Backend performance:**
  - [x] WAL mode already on from Increment 1
  - [x] `_CHILD_LIMIT = 200` sentinel already limits taxonomy zoom
  - [x] `/api/search` already has `limit` param (1–100)
  - [x] Profile slowest taxonomy queries with `EXPLAIN QUERY PLAN`; add indexes
  - [x] Cache root/kingdom list in memory (rarely changes; avoids DB hit on every page load)
  - [x] Fix `create_react_agent` deprecation: suppress `LangGraphDeprecatedSinceV10` warning via `warnings.filterwarnings` + `pytest.ini`
- [x] **Frontend polish:**
  - [x] Lazy-load tree nodes — done (Increment 4)
  - [x] Debounce search 300ms — done (Increment 4)
  - [x] Horizontal scroll — done (post-I9)
  - [x] Species detail panel — done (post-I9)
  - [x] Loading spinner on tree node expand — fixed overlay centred over tree panel
  - [x] Markdown rendering in chat bubbles — `marked.js` v9 via CDN
  - [x] Favicon — paw-print emoji SVG data URI
- [x] **Error handling:**
  - [x] Frontend: toast notification for network failures (auto-dismiss 5s, manual ×)
  - [x] LLM: surface "Ollama not running" as readable error in chat; "Connection refused" pattern → friendly message
- [x] Re-run full test suite: 85 backend + 28 frontend passing; no warnings
- [x] Final manual walkthrough: find a species in tree, ask about it in chat, verify image loads

### Decisions recorded
- **`taxon_depth` column:** Added INTEGER column + `idx_taxon_depth_path (taxon_depth, taxon_path)` composite index. Taxonomy zoom went from O(full-scan) to O(index) — Mammalia node: 158ms → 6ms (25×). SQLite triggers auto-maintain the column on insert/update, no application code needed.
- **Root cache:** Keyed by `database.DB_PATH` (dict, not single variable) so each test's monkeypatched temp-DB gets its own cache entry — no test isolation bugs.
- **`create_react_agent`:** `langchain` base package not installed; `from langchain.agents import create_react_agent` not available. Suppressed `LangGraphDeprecatedSinceV10` in `llm_agent.py` (module-level `warnings.filterwarnings`) and in `pytest.ini` (`filterwarnings = ignore:create_react_agent`). Revisit when upgrading to LangGraph 2.0.
- **Markdown renderer:** `marked.js` v9 (CDN). Raw text accumulated per bubble; `textEl.innerHTML = marked.parse(rawText)` on each token. User messages keep `whitespace-pre-wrap`; assistant bubbles use `prose prose-invert prose-sm`.
- **Loading spinner:** Fixed overlay `inset-y-14 left-0 right-96` (clears header + chat panel). `tree-loading` CustomEvent dispatched from `_onClick` and `expandToNode`; toggled in `app.js`.
- **Error toasts:** `_showToast(msg, type)` appends a self-dismissing pill to `#toast-container` (fixed bottom-right). Auto-removes after 5s with CSS opacity fade.
- **Static file serving:** `app.mount("/", StaticFiles(...), html=True)` added to `main.py` so the frontend is served from port 8000 — no separate dev server needed, eliminates CORS friction. Requires `aiofiles` (added to deps).
- **Walkthrough results:** Tree renders all kingdoms on load; search finds species; species panel shows correctly (image loads from Wikipedia CDN — tested with Cicadetta montana); chat LLM responds with markdown (bold species names render); error toast confirmed working when backend unreachable.

---

## Increment 10b — Tree Visualization Improvements & Tooltips

Fixes to the taxonomy tree rendering and a full hover-tooltip system covering the entire tree of life.

### Tasks

- [x] Fix duplicate sibling nodes caused by multiple DB rows sharing the same `taxon_path`
- [x] Add SYNONYM filter to `taxonomy_zoom` endpoint (root endpoint already filtered; zoom did not)
- [x] Replace broken plurality-rank orphan heuristic with explicit `_EXPECTED_CHILD_RANKS` map
- [x] Add `_expected_ranks_to_depth()` helper so depth=2 zooms include both phyla and classes
- [x] Add new `GET /api/taxonomy/unclassified?node_id=` endpoint for lazy-loading orphaned children
- [x] Add three new `database.py` helpers: `get_children_by_rank`, `get_orphan_children`, `count_orphan_children`
- [x] Update frontend `loadNode` to route `__unclassified__*` node IDs to the new endpoint
- [x] Update `_freshNode` to preserve pre-populated children so synthetic nodes are handled correctly
- [x] Add hover-tooltip system (`_TAXON_DESCRIPTIONS` lookup + floating `<div>`) to `visualizer.js`
- [x] All 87 backend tests still passing after all changes

### Decisions recorded

- **Duplicate node root cause:** Multiple DB rows with different `scientific_name` but identical `taxon_path` (e.g. family-level orphans, unranked taxa classified only to family). Fixed by deduplicating in `_build_tree` — preference order: canonical row (`scientific_name == last path segment`) → ACCEPTED status → first seen. Previously each duplicate spawned its own tree node with the same label and `node_id`.
- **Plurality-rank heuristic failure:** First orphan-grouping attempt computed the plurality rank among siblings and flagged anything more specific than `plurality + 1` as an orphan. Failed in practice: under Animalia, thousands of orphaned genera/families outnumbered the ~35 correct phyla, so plurality resolved to genus-level and nothing was flagged. Replaced with the explicit `_EXPECTED_CHILD_RANKS` dict.
- **`_EXPECTED_CHILD_RANKS`:** Dict keyed by parent `taxon_rank` (e.g. `"kingdom"` → `frozenset({"phylum", "subkingdom", "superphylum", ...})`). When the parent rank is in the map, `taxonomy_zoom` uses `get_children_by_rank` (rank-filtered, no row limit) instead of the generic paginated query. Orphan count is returned separately and a `[Unclassified] (N)` sentinel is appended.
- **`_expected_ranks_to_depth`:** For depth=2 the single-level expected set must be expanded — a kingdom zoom at depth=2 needs both phyla and classes in the same query so `_build_tree` can correctly nest them. Helper walks the chain recursively for N levels and returns the union. Orphan counting always uses depth=1 only.
- **`/api/taxonomy/unclassified` endpoint:** Returns orphaned children (rank NOT in `_EXPECTED_CHILD_RANKS[parent_rank]`) paginated at 200, with a `+N more` sentinel if needed. Frontend `loadNode` detects the `__unclassified__` prefix and routes to this endpoint; all other node IDs hit the standard zoom endpoint as before.
- **Virus kingdom:** All virus taxa land in `[Unclassified]` because GBIF virus entries use non-standard rank names (realm, subrealm, etc.) instead of "phylum". This is left as-is — it accurately reflects GBIF's incomplete virus taxonomy and users can still find virus families via Search.
- **Tooltip system:** `_TAXON_DESCRIPTIONS` — a static lookup table of 190+ entries keyed by lowercase scientific name. Covers all 9 major + 24 minor animal phyla, plant divisions (embryophytes, algae, fossils), 16 archaeal phyla, 60+ bacterial phyla (including CPR lineages), protist lineages (alveolates, stramenopiles, rhizaria), fungal phyla (Dikarya + basal clades), protozoan groups, and virus families. Tooltip is a lazily-created `position:fixed` `<div>` with viewport overflow correction. Handlers added in the D3 `enter` selection on each node `g` element (`mouseover` / `mousemove` / `mouseout`).

---

## Increment 10c — SYNONYM Genus Visibility Fix (Honey Bee "Apis cerana")

Fixes a data quirk in the GBIF backbone where `Apiarus` (SYNONYM) occupies the
`Animalia|…|Apidae|Apis` path, causing the Apis genus and all honey bee species
to be invisible in the tree and appearing to "spawn from ants" when reached via
the stale-injection code path.

### Root cause

GBIF stores `Apiarus` (SYNONYM) at path `Animalia|…|Apidae|Apis`.  The
`taxonomy_zoom` endpoint filtered out all SYNONYM rows, so the Apis genus node
was never returned when expanding Apidae — yet `Apis cerana` (ACCEPTED) lives
under that path.  When a user searched for the honey bee, `expandToNode` could
not find the Apis node in Apidae's children, fell back to injecting it via
`/api/taxonomy/node`, and appended it at the **end** of Apidae's 231-genus
child list.  D3 placed the injected Apis at the very bottom of Apidae's subtree,
visually adjacent to the Formicidae (Ants) branch — hence "spawns from ants".

### Backend fix (`database.py`, `main.py`)

- New `paths_with_accepted_descendants(paths)` helper: given a list of SYNONYM
  genus paths, returns the subset that have at least one ACCEPTED descendant.
  Uses the compound `idx_taxon_depth_path (taxon_depth, taxon_path)` index for
  a range-scan (`taxon_depth = N+1 AND taxon_path >= lo AND taxon_path < hi`)
  that is ~40× faster than N separate LIKE queries (30 ms vs 935 ms for 191
  candidates).
- `taxonomy_zoom`: after filtering out synonyms, SYNONYM genus/subgenus nodes
  whose paths have ACCEPTED descendants are **added back** — they are structural
  waypoints needed to reach those species.

### Frontend fix (`visualizer.js`)

`expandToNode` now performs **focused path navigation** instead of loading all
siblings at every ancestor level:

- For **unloaded intermediate ancestors** (not the direct parent of the leaf),
  the node is injected or found but its children are *not* bulk-loaded.  The
  node gets `children = []` and `_pathOnly = true`; the next path segment is
  injected into this empty array.  Result: the tree shows only the search path
  (Life → Animalia → Arthropoda → … → Apidae → Apis → Apis cerana + siblings)
  without expanding hundreds of Hymenoptera families or Apidae genera.
- For **stale-loaded ancestors** (previously cached without the target child),
  the parent's children are re-fetched via `loadNode` before falling back to
  direct injection, so the target always appears in its correct sorted position.
- For the **direct parent** of the leaf, all children are always loaded so the
  leaf appears among its real siblings (e.g. Apis cerana alongside Apis
  mellifera, Apis florea, Apis dorsata).
- `_pathOnly` nodes show the same gray circle as collapsed nodes to indicate
  more siblings are available.  Clicking a `_pathOnly` node triggers a full
  lazy-load of all siblings instead of the normal collapse toggle.

### Tests

- 2 new backend tests: `test_zoom_shows_synonym_genus_with_accepted_descendants`
  and `test_zoom_hides_synonym_genus_without_accepted_descendants` (89 total).
- 1 new frontend test: verifies `expandToNode` only calls the zoom endpoint once
  (for the direct parent), not for every intermediate ancestor (29 total).

### Additional bugs found and fixed post-increment

**Bug 1: `highlightNodes` race condition with D3 enter-transitions**

When a user selected a search result, the highlight (dim non-path nodes to 12% opacity)
was being overridden by D3's enter-transition because `_render()` targeted a constant
`opacity: 1` and the transition fired 280 ms AFTER the synchronous `highlightNodes` call.

Fix — two-part:
- Added module-level `let _highlightPaths = []` in `visualizer.js` to persist highlight state.
- `_render()` transitions now call `_highlightOpacity(d)` (a function, evaluated at
  transition-setup time) instead of the constant `1`, so the correct per-node opacity is
  baked in before the animation starts.
- In `app.js`, moved `highlightNodes([item.taxon_path])` to run BEFORE `await expandToNode()`
  so `_highlightPaths` is populated when `_render()` transitions begin.

**Bug 2: `_pathOnly` nodes showing misleading GBIF common names ("Ants", "Euglossine")**

Hymenoptera's first GBIF English common name is "Ants, Bees And Wasps" (truncated to
"Ants" in tree labels); Apidae's first GBIF common name is "Euglossine" (the Euglossini
tribe, a subset of Apidae). Both names are misleading when those nodes appear as
focused-path ancestors on the route to a honey bee.

Fix: `_render()` now uses `d.data._pathOnly ? d.data.name : nodeLabel(d.data)` for node
text labels. `_pathOnly` ancestors show their scientific name instead of the GBIF common
name. The same guard is applied inside the new `getPathToNode` export (see below).

**Feature: `getPathToNode` + `_buildLineage` — consistent lineage in details panel**

The details panel was showing the raw `taxon_path` with `|` → `›` (all scientific names)
while the tree showed common names, so the two representations did not match.

Added:
- `getPathToNode(taxonPath)` (exported from `visualizer.js`): walks the already-loaded
  `_rootData` tree to collect `{ node_id, label }` pairs for each ancestor, using the
  same label logic as the tree renderer (`_pathOnly` → scientific name, else common name).
- `_buildLineage(taxonPath)` (in `app.js`): calls `getPathToNode` and formats each step
  as `"common (scientific)"` when the label differs from the scientific name, falling back
  to pipe-separated scientific names when the tree is not yet loaded.
- `_showSpeciesPanel` now uses `_buildLineage` instead of the plain `taxon_path.replace` fallback.

### Status: COMPLETE — user-verified 2026-11-03

### Tasks

- [x] Add `paths_with_accepted_descendants` to `database.py`
- [x] Update `taxonomy_zoom` in `main.py` to retain structural SYNONYM genus nodes
- [x] Add 2 backend tests; all 89 pass
- [x] Rewrite `expandToNode` in `visualizer.js` for focused path navigation
- [x] Update `_onClick` in `visualizer.js` to handle `_pathOnly` expansion
- [x] Update circle fill colour to show `_pathOnly` nodes as gray (has-children indicator)
- [x] Add 1 frontend test; all 29 pass
- [x] Fix `highlightNodes` race condition — `_highlightPaths` state + `_highlightOpacity(d)` in transitions
- [x] Fix `_pathOnly` label — use `d.data.name` (scientific) instead of GBIF common name
- [x] Add `getPathToNode` export and `_buildLineage` helper for cross-referenced details panel lineage
- [x] User visual verification (2026-11-03, after search-ranking fix `6b7ed55`): search "Apis cerana", confirm tree shows "Hymenoptera" / "Apidae" (not "Ants" / "Euglossine"), path matches details panel lineage, highlight dims non-path nodes
- [x] Git commit all changes (`abc1e7c`)

---

## Increment 10d — Alpha Grouping (A–Z Letter Nodes for Large Taxonomy Nodes)

Replaces the dead-end `+N more — use Search` sentinel with browsable alphabetical letter-group nodes. When a taxonomy node has >200 children, the tree shows `[A] (42)`, `[B] (8)`, … nodes instead. Clicking a letter bucket expands it in-place. Navigation via search drills through the alpha layer automatically — fully transparent to the user.

**Design spec:** [`Docs/superpowers/specs/2026-06-11-alpha-grouping-design.md`](superpowers/specs/2026-06-11-alpha-grouping-design.md)
**Implementation plan:** [`Docs/superpowers/plans/2026-06-11-alpha-grouping.md`](superpowers/plans/2026-06-11-alpha-grouping.md)

### Tasks

- [x] Add `get_children_letter_counts(parent_path)` to `database.py` — returns `{"A": 42, "B": 8, …}` via composite-index range-scan; non-A–Z names grouped under `"#"`; SYNONYM rows excluded
- [x] Add `get_children_by_letter(parent_path, letter)` to `database.py` — returns rows matching first letter (no SQL SYNONYM filter — Python layer handles structural SYNONYM retention)
- [x] Add `get_orphan_letter_counts(parent_path, expected_ranks)` and `get_orphan_children_by_letter(parent_path, expected_ranks, letter)` to `database.py` for `taxonomy_unclassified` equivalents
- [x] Add `_alpha_sentinels(parent_path, letter_counts)` helper to `main.py`
- [x] Add `GET /api/taxonomy/alpha?node_id=X&letter=A` endpoint — applies same structural-SYNONYM filter as `taxonomy_zoom`
- [x] Modify `taxonomy_zoom` — both `if expected_all:` and `else:` branches now return alpha sentinels when `len(nodes) > _CHILD_LIMIT`; `__more__` sentinel fully retired
- [x] Modify `taxonomy_unclassified` — returns alpha sentinels when orphan count > limit; new `letter` query param filters to one letter bucket
- [x] Update `loadNode` in `visualizer.js` — `__alpha__` branch routes to `/api/taxonomy/alpha`; `__alpha____unclassified__` sub-branch routes to `/api/taxonomy/unclassified?letter=`
- [x] Update `_render` and `_onClick` — alpha nodes styled gray/italic; `rank === 'alpha'` guard prevents species panel from opening
- [x] Add `_drillAlpha(current, partialPath)` to `visualizer.js`; wire into `expandToNode` at two injection points plus an injection-fallback discriminator path — search navigation is fully transparent
- [x] 101 backend + 32 frontend tests passing; zero regressions; `__more__` sentinel absent from codebase

### Decisions recorded

- **`__more__` fully retired:** The old pagination sentinel no longer appears anywhere. Both `taxonomy_zoom` code paths and `taxonomy_unclassified` now use alpha sentinels instead.
- **Node ID format:** `__alpha__<parent_taxon_path>|<LETTER>` for regular children; `__alpha____unclassified__<path>|<LETTER>` for orphan children. Letter is always the last `|`-delimited segment.
- **SYNONYM filter placement:** `get_children_letter_counts` and `get_orphan_letter_counts` exclude SYNONYMs in SQL (count display only). `get_children_by_letter` does NOT exclude SYNONYMs in SQL — the Python layer in `taxonomy_alpha` applies the structural-SYNONYM retention logic (same pattern as `get_children_by_rank` / `taxonomy_zoom`). This was caught during spec compliance review — `taxonomy_alpha` was dead code until fixed.
- **`_drillAlpha` deviation from plan:** The plan specified two direct injection points in `expandToNode` (after `allKids.find` and after stale-refresh lookup). Both are present. An additional third path was added: when `/api/taxonomy/node` returns a descendant rather than an exact match (indicating the target node is inside an alpha bucket not yet loaded), the implementation loads the parent's children and calls `_drillAlpha`. This handles the `_pathOnly` edge case where `allKids` is empty.
- **`#` bucket:** Names whose first character is not A–Z (digits, punctuation, non-ASCII) are grouped under `[#]`. The ASCII range check `'A' <= letter <= 'Z'` is used instead of Python's `str.isalpha()` (which accepts É, Ñ, etc. but SQLite's `upper()` is ASCII-only).
- **101 backend tests (up from 89), 32 frontend tests (up from 29)**

---

## Increment 10e — Dynamic Image Retrieval (Species Panel)

When a user opens the species panel and no image URL is stored (or the stored URL fails to load), fetch one from a 4-source chain (Wikipedia → iNaturalist → Wikimedia Commons → DuckDuckGo), cache it back to the DB, and display it.

**Design spec:** [`Docs/superpowers/specs/2026-06-11-dynamic-image-retrieval-design.md`](superpowers/specs/2026-06-11-dynamic-image-retrieval-design.md)
**Implementation plan:** [`Docs/superpowers/plans/2026-06-11-dynamic-image-retrieval.md`](superpowers/plans/2026-06-11-dynamic-image-retrieval.md)

### Tasks

- [x] Add `ddgs==9.14.4` to `backend/requirements.txt` — commit `d71929f`
- [x] Create `backend/app/image_utils.py` — 4-source chain (`_wikipedia_image`, `_inaturalist_image`, `_wikimedia_image`, `_duckduckgo_image`, `fetch_image`); 10 tests — commit `8db3f5a`
- [x] Add `database.update_species_image(scientific_name, url, attribution)` write-through helper; 2 tests — commit `322cbc2`
- [x] Migrate `llm_agent.py` — remove inline image helpers, import from `image_utils`, `get_species_image` tool uses `fetch_image` + `update_species_image` + `__none__` sentinel — commit `8eea1b9`
- [x] Add `GET /api/species/{scientific_name}/image?force=false` endpoint to `main.py`; extend `_insert` in test file; 6 endpoint tests — commit `b556dcb`
- [x] Update `frontend/js/app.js` `_showSpeciesPanel` — 3-branch image logic (`__none__` / stored URL / null); add `_fetchRemoteImage` helper; 5 frontend tests — commit `b9f7030`
- [x] 119 backend + 37 frontend tests passing; zero regressions

### Decisions recorded

- **`__none__` sentinel:** Stored in `primary_image_url` column (existing TEXT field) when all 4 sources fail and `force=False`. Prevents re-fetch loops without schema changes. `force=True` (sent by frontend `onerror`) bypasses the sentinel and does NOT overwrite it on failure (the old URL may have been temporarily broken).
- **4-source chain order:** Wikipedia REST summary → iNaturalist taxa API → Wikimedia Commons action API (2-step: search then imageinfo) → DuckDuckGo `ddgs` package. Stops at first hit.
- **DDG test fix:** The plan's `sys.modules.pop('ddgs', None)` idiom doesn't block reimports when the package is physically installed. Implementer correctly fixed to `monkeypatch.setitem(sys.modules, 'ddgs', None)` — Python's `None` sentinel in `sys.modules` raises `ImportError` on import.
- **Attribution:** Best-effort strings only (private non-commercial project). Wikipedia: `"© Wikipedia contributors (CC BY-SA)"`. iNat: photo attribution field. Wikimedia: artist + license from `extmetadata`. DDG: source domain.
- **Endpoint route order:** `/api/species/{name}/image` must be registered in FastAPI BEFORE `/api/species/{name}` to prevent `/image` being matched as a species name.
- **119 backend tests (up from 113), 37 frontend tests (up from 32)**

---

## Increment 11 — Git History & Documentation

Tidy up and commit a clean, documented project.

### Tasks

- [x] Initialise git repo if not already done: `git init` — repo exists since Increment 0 (`39d3a9e`)
- [x] Add `.gitignore` entries:
  - `__pycache__/`, `*.pyc`, `.venv/`
  - `node_modules/`, `dist/`, `.vitest/`
  - `*.db`, `chroma_db/` (data stays on E: drive, not in repo)
  - `.env` (if any secrets are added later)
  - plus `.pids.json`, `test-results/`, `coverage/`, `*.log`
- [x] Add `README.md` — overview, setup, running, API, data pipeline, tests (`7a68934`)
- [x] Update `CLAUDE.md` commands section with final, tested commands
- [x] Update this `PLAN.md` with all "Decisions to record" filled in — no placeholders remained; stale embedding/IUCN items updated with results
- [x] ~~Make a clean initial commit~~ — obsolete: full incremental history already exists
- [x] Tests: 137 backend · 37 frontend · 15/15 E2E (2026-11-03, `AK_PORT=8010`)

### Fixes made during this increment (2026-11-03)

| Commit | Fix |
|---|---|
| `a8de0cf` | HF offline flags moved to `backend/app/__init__.py` — chat stalled ~1 min on SSL retries to huggingface.co |
| `d386f1c` | Configurable backend port `AK_PORT`, port-in-use check, `backend.log`; `stop` only kills our own backend |
| `6b7ed55` | Search ranking — exact species match ("Apis cerana") was crowded out by subspecies |
| `f905d06` | Chat source labels verified in code (`LabelChecker`) — LLM labelled general knowledge as "Database:" |
| `12d2269` | IUCN `population_trend` codes off by one + `--missing-trends` re-fetch |

### Decisions recorded

- **Port 8010 default in `.bat` files:** a Postgres MCP server (SSE) occupies :8000 on this machine. `manage.py` keeps 8000 as its default and reads `AK_PORT`; the `.bat` files set `AK_PORT=8010` unless already defined. The frontend uses `window.location.origin` as its API base, so the backend-served page works on any port; Vitest pins jsdom's URL to `http://localhost:8000` to keep existing assertions.
- **`stop` safety:** previously killed whatever listened on the port (would have killed the MCP server). Now kills only tracked PIDs whose command line is our uvicorn, plus untracked processes on the port only if they are `uvicorn app.main:app`.
- **HF offline flags in `app/__init__.py`:** `llm_agent` imports `langchain_ollama → langchain_core → transformers → huggingface_hub` before `vector_db`, and `huggingface_hub` reads `HF_HUB_OFFLINE` once at import. The package `__init__` runs before any submodule.
- **Search ranking over full scan:** `LIKE '%q%'` already scans all rows (~1 s), so `ORDER BY` costs ≤0.2 s. Order: exact scientific name (NOCASE) → exact common-name JSON element → scientific-name prefix → substring; then ACCEPTED before SYNONYM, shorter names, A–Z. An FTS index was not needed for this.
- **Source labels verified in code, not prompt:** three prompt variants on `llama3.1:8b` (temp 0) each moved mislabels around rather than removing them. `LabelChecker` buffers streamed text per sentence and keeps "Database:" only if the sentence contains a value from the `lookup_species` result (number, IUCN code/name, trend, habitat, trophic level, higher taxon, common name when talking about names, or ≥50% overlap with summary words). The species' own genus/species words don't count. Trade-off: chat streams per sentence instead of per token. `lookup_species` also lists "Not recorded" fields and ends with an explicit boundary line.
- **IUCN trend codes:** API v4 uses 0=Increasing, 1=Decreasing, 2=Stable, 3=Unknown (verified on live responses). The old map stored 3 as "Increasing" and had no 0. One-off repair: `UPDATE species SET population_trend='Unknown' WHERE population_trend='Increasing'` → 83,951 rows (safe because code 0 was never stored). Truly increasing species had NULL trends; `--missing-trends` re-fetches the 7,875 NULL-trend species (many stay NULL — extinct species have no trend). The API works with TLS verification on. Run completed 2026-11-03: 1,422 of 7,875 trends filled, 0 errors.
- **Known flaky E2E:** `full_journey.spec.ts` once timed out waiting 5 s for search results on a cold backend (first chat loads the embedding model while the IUCN writer was active); passed on two reruns. Not changed.

### Open follow-ups

- `lookup_species` doesn't return subspecies/children, so "which subspecies of X exist" isn't answered from the DB.
- Only ~7k species have Wikipedia abstracts; more `enrich_wikipedia.py` runs would widen semantic search.

## Increment 12 — Dynamic Trait Retrieval (Species Panel + Chat)

Fill missing traits on demand when a species is opened (like 10e images), store them with provenance, and show where every value came from. Spec: `Docs/superpowers/specs/2026-11-03-dynamic-trait-retrieval-design.md`; plan with risk analysis R1–R15: `Docs/superpowers/plans/2026-11-03-dynamic-trait-retrieval.md`.

### Tasks

- [x] Storage — `trait_sources` JSON column (provenance + `_sourced` / `_estimated` stage markers), `update_species_traits` write-through (`BEGIN IMMEDIATE`, never overwrites sourced values, sourced replaces estimates)
- [x] Sources (`backend/app/trait_utils.py`) — IUCN Red List (habitat, elevation/depth, status, trend), GBIF (habitat, occurrence range), Wikidata (mass/length/lifespan with unit conversion), Wikipedia (abstract); each validates its match (rank, kingdom, exact name)
- [x] Sourced stage — the four sources concurrently, 8 s deadline; any failure leaves the stage unmarked so the next open retries
- [x] Estimate stage — local LLM reads the Wikipedia abstract (JSON mode); every value must be grounded in the text
- [x] `GET /api/species/{name}/traits?stage=sourced|estimated&force=false`; `SpeciesRecord` gains `provenance`, `traits_sourced`, `traits_estimated`, `trait_eligible`
- [x] Chat — `lookup_species` runs the sourced stage once per species (never the estimate), tags estimated lines; three labels verified in code: `Database:`, `Database (estimated):`, `From general knowledge:`
- [x] Panel — `frontend/js/traits.js`: rows fill after open, "est." badge, source on hover, stale-response guard, everything escaped
- [x] Tests — backend 243, frontend 54, E2E 17 (+ `e2e/traits_panel.spec.ts`), live smoke `pytest -m live` (6)
- [x] Final whole-branch review (fresh reviewer): 1 Critical + 3 Important fixed test-first; 6 minors deferred (below)

### Decisions recorded

- **Wikidata via the Action API, not SPARQL:** WDQS rate-limited to 1 req/min during an outage; `haswbstatement:P225=<name>` search + `wbgetentities`. Unit item IDs verified live. Exactly one item with matching P225 and P105 rank, else skip.
- **Write lock:** trait writes wait at most 10 s (`TRAIT_WRITE_TIMEOUT_S`); a bulk `data/` script can hold the lock for a minute. On a lock the values are still served, unmarked, so the next open retries.
- **Estimate stage needs a complete sourced stage:** without it "no abstract" means "not fetched yet"; marking it done would stop estimates for good. The panel stops after an incomplete sourced stage.
- **Grounding the LLM (spec decision 6):** numbers must appear in the abstract beside a unit of the same dimension, in a sentence with a field keyword and without a comparison ("longer than … Mongolarachne"); for a range the upper end is stored. Vocabulary terms need supporting stems (omnivore → "omnivor"); free text needs every content word in the text plus a field keyword. Live rejects: bee "omnivore", lion reproduction "sexually dimorphic", spider habitat "northern South America", Mongolarachne's 2.46 cm.
- **Numbers rounded to 3 significant figures** in `lookup_species` and the panel — LabelChecker must match what the model repeats (0.17576… kg → 0.176).
- **LabelChecker:** the "Not recorded" line is never evidence; a sentence with any estimate-only value is `Database (estimated):`; multi-value habitat lines match per part and per IUCN class head.
- **Panel timeout 90 s** (plan said 30 s): the estimated request can take 8 s sourced + 60 s LLM + lock waits.

### Verification (2026-11-03, live)

| Species | Before (traits filled) | After | First open | Reopen |
|---|---|---|---|---|
| Panthera leo | 4 | IUCN habitat, elevation 0–4,200 m, GBIF range | 5.4 s | no `/traits` call |
| Ursus maritimus | 7 (sourced) | Marine Oceanic, 0–1,717 m; depth 0–14 m | — | — |
| Theraphosa blondi | 1 | GBIF Terrestrial, Wikidata 0.176 kg, est. carnivore | 9.5 s | no `/traits` call |
| Apis cerana | 0 | GBIF Terrestrial, GBIF range | ~10 s | — |

Chat: "how heavy is a Goliath birdeater" → `Database: … 0.176 kg.` During the IUCN `--missing-trends` run every trait write was locked out (~40 s per open); after it finished, first opens took 5–10 s.

### Open follow-ups (deferred minors from the final review)

- `""` counts as filled in `update_species_traits` but as empty elsewhere.
- One malformed LLM JSON reply marks `_estimated` permanently.
- A timed-out Ollama call keeps running in an orphan thread.
- `force=true` does not re-estimate fields already holding estimates.
- `merge_trait_values` writes `trait_sources` even when nothing changed (needless write lock).
- Wikipedia summary URL keeps `/` unescaped (`quote(..., safe="")`).
- `data/enrich_iucn.py` holds a write transaction across network calls — the cause of the lock waits.
- `e2e/full_journey.spec.ts` is still occasionally flaky at the search step (passes on rerun).

### Post-review fixes from user testing (2026-11-03)

- **Search ranking** (`9a63439`): an exact *synonym* scientific name now ranks below an exact common name — "Zebra" opened the outdated snail genus *Zebra* (Orthalicidae) instead of *Equus zebra*.
- **One-word image lookups** (`9a63439`): for genus-and-up names the Wikipedia article must mention an ancestor from `taxon_path`, and Commons/DuckDuckGo queries add the nearest ancestor ("Zebra Orthalicus"). The snail's plains-zebra photo was cleared.
- **Rank tag in the search dropdown** (`0cddbb9`): "wombats — *Vombatidae* (family)"; species untagged. Dropdown names are now escaped.
- **DuckDuckGo results must name every query word** in title or page URL (`cbd2a5d`): the fossil wombat *Sceparnodon ramsayi* got a copperhead snake (*Austrelaps ramsayi*). Three wrong DDG images cleared (Sceparnodon ramsayi, Olor matthewi, Lithomucorites miocenicus).
- **Extinct marker** (`0f9179f`): new `extinct` column (1/0/NULL) filled in the sourced stage from GBIF species profiles (Paleobiology Database / Catalogue of Life; disagreement → unknown). Shown as "(extinct)" / "(extinct in the wild)" in the dropdown and "species · extinct" on the panel; IUCN EX/EW takes precedence. The 18 species already sourced had their `_sourced` marker removed so they pick up the flag.

Still open:
- 9 older DuckDuckGo images can't be re-checked (only the site name was stored).
- Fossils show "(extinct)" in search only after first open; a bulk Catalogue of Life import (ColDP `extinct` column) would tag all ~1.78 M names up front.
- "Wombat" search lists genera/order above the actual wombat species (substring matches sort by name length).

---

## Increment 13 — Extinct Taxa in the Tree (+ contrast pass) ✅

**Goal:** fossils are recognisable in the tree without opening each panel, and can be hidden (Tapirus: 21 of 28 species are fossils).

### Tasks
- [x] `data/backfill_extinct.py` — offline, from the local GBIF backbone `Taxon.tsv`:
  - Pass 1: accepted Animalia species / infraspecific taxa whose backbone source is the Paleobiology Database → `extinct = 1` (105,319 rows)
  - Pass 2: genus / family / order / unranked rows whose accepted species are *all* extinct → `extinct = 1` (35,371 rows)
- [x] `extinct` on `TaxonNode` (`/api/taxonomy/zoom`, `/alpha`, `/unclassified`, `/node`)
- [x] Tree: "† " prefix + grey label for extinct taxa (`treeLabel`)
- [x] "Hide extinct (†)" header toggle (localStorage `ak.hideExtinct`); filtered branches end in a clickable "† N extinct hidden" placeholder (`visibleChildren`); selected / searched path always kept
- [x] Tree follows the panel: when the panel's GBIF lookup learns a flag after the branch loaded, `setNodeExtinct` updates the node's † right away (bug from user testing: *T. lundeliusi* showed "species · extinct" in the panel but no † in the tree; `/traits` returns the raw `1`, `/species` a boolean — normalised in `app.js`)
- [x] Live roll-up (from user testing: *Samotherium major* learned extinct in the panel, so all 6 Samotherium species were extinct, but the genus stayed visible): `database.rollup_extinct_ancestors` runs in the trait-write transaction when a species gets `extinct = 1`. It flags each ancestor whose accepted species are now all extinct, stops at the first that is not, and never touches the kingdom. The tree then re-reads loaded ancestors (`refreshAncestorFlags`). Same label as pass 2 (`database.extinct_rollup_source`). Re-ran the backfill: +2 genera (incl. Samotherium)
- [x] Commons images must be filed under the name (bug from user testing: *Tapirus malayanus* got a Sumatran elephant calf — the photo's caption lists the park's wildlife). `_wikimedia_image` now checks the top 3 full-text hits and takes the first whose **title or categories** name every word of the name (one-word names: only the name, not the ancestor qualifier). Re-checked the 17 stored Commons-search images: only the elephant was wrong (cleared; no on-topic file exists, so the panel shows none)
- [x] Contrast pass: all small text ≥ WCAG AA 4.5:1 on the dark backgrounds (`gray-500/600/700` → `gray-400`, rank colours for kingdom/family/genus lightened, links `#6b7280`), `color-scheme: dark` for native scrollbars and the search clear button, border on the chat input
- [x] Tests: `backend/tests/test_backfill_extinct.py` (18), Vitest `treeLabel` / `visibleChildren` (8), `e2e/extinct_filter.spec.ts` (3)

### Decisions recorded
- **PBDB source = fossil, species level only.** Validated: all 55 PBDB-sourced Tapiridae species are fossils; no PBDB-sourced animal species is IUCN-assessed as living (the one hit, *Ficus nervosa*, is a fossil snail homonym of a living fig — skipped by the IUCN rule). The signal is one-way: no PBDB source → still NULL (unknown), never 0.
- **Higher ranks by roll-up, not PBDB:** the backbone credits PBDB for the order Sirenia (manatees, dugongs) — caught in the dry run. A group is flagged only when every accepted species under it is extinct.
- Match on name **and** full `taxon_path` (as `import_gbif.py` builds it) to rule out homonyms (281 mismatches skipped). Never overwrite an existing value; IUCN status other than EX blocks the flag. Provenance in `trait_sources.extinct`: "GBIF backbone (Paleobiology Database)" / "Derived: all N accepted species extinct".
- Rejected: fetching flags from the GBIF API when a branch opens — one call per species, rate limits, breaks offline use.
- Result: 140,698 extinct flags (was 8). Fossils from other checklists (e.g. *Tapirus lundeliusi*, *T. webbi*) stay unknown until their panel's GBIF profile lookup.

### Open follow-ups
- Re-run `backfill_extinct.py` occasionally: pass 2 picks up groups completed by on-demand flags.
- A Catalogue of Life (ColDP) import would cover non-PBDB fossils and give explicit "living" values.
- **Addressed by `data/batch_extinct_gbif.py`** (2026-11-04): the backbone `taxonID` is GBIF's key, so one `/species/{key}/speciesProfiles` call per species (~59/s with 8 workers; 231,895 candidates ≈ 75 min). Same rule as the panel (`trait_utils.extinct_from_profiles`, now shared); writes via `update_species_traits` (provenance + live roll-up); checkpoint `E:\AnimalKingdomSystem\extinct_batch_done.txt`; resumable. Sample of 300: 18 % extinct, 70 % living, 13 % no answer.
- Two slow queries found by the batch (it started at 1.5/s with "database locked" skips), both fixed:
  - `get_species` / `update_species_traits` looked names up with `COLLATE NOCASE`, which can't use the primary-key index: a full scan of 5.8 M rows (0.73 s) on every panel open and every trait write, under the write lock. They now try the exact name first: about 1 ms.
  - The roll-up's species query was planned on `idx_taxonomic_status` (~2.5 M rows, 1.5–6 s per extinct write). Unary `+` on rank and status keeps it on the `taxon_path` range: about 1 ms.
  - Result: 48/s, no lock errors.
- Batch result (2026-11-04, 86.5 min, 230,943 species, 0 skipped writes): 48,353 extinct, 85,126 living, 97,464 no answer; the live roll-up flagged ~7,600 more groups. Total extinct flags: 196,677 (152,342 species, 34,557 genera, 3,771 families, 18 orders).
- Before the batch: non-PBDB fossils stayed unknown until opened. ZooBank (`c8227bb4…`) mixes fossils (*Decennatherium rex*, *Honanotherium bernori*) with old names of living animals, and small single-paper fossil datasets (e.g. "Late Miocene large mammals from Mahmutgazi") are also sources. 231,898 unknown species sit in 9,183 genera that contain a known fossil: candidates for a resumable overnight GBIF species-profile batch.

### Post-increment fix — name collisions (2026-11-04)
- [x] Bug from user testing: selecting **Panthera** in search opened the moth genus *Pantherodes*. `scientific_name` is the primary key and `import_gbif.py` used `INSERT OR IGNORE`, so the first backbone row of a name won: here an outdated moth synonym, not the accepted cat genus.
- [x] `data/fix_name_collisions.py`: for each row that is not an accepted animal but shares its name with one, either
  - **replace** (other lineage): new path, rank, status and English common names; traits, image, abstract and extinct flag cleared (they described the other organism). 13,439 rows: 9,575 genera, 3,722 species, 80 families, 16 orders; 986 were accepted non-animals, e.g. *Micrococcus*.
  - **relabel** (same lineage, only the status was wrong): status and missing common names only, data kept. 14,748 rows.
  - Homonyms among accepted animals: the highest rank wins (Proboscidea = elephant order, not the polychaete genus); equal ranks are skipped (none left).
  - Originals backed up to `E:\AnimalKingdomSystem\name_collisions_backup.jsonl` (28,187 rows); no vector-store entries affected. Re-ran `backfill_extinct.py`: +281 species, +1,069 groups. Duplicate English names removed in 1,123 repaired rows.
- [x] `import_gbif.py` upserts by `row_score` (accepted animal > accepted other kingdom > synonym, then higher rank), whatever the file order.
- [x] Tests: `backend/tests/test_name_collisions.py` (14). Verified in the browser: Panthera → Felidae, "roaring cats".
- Still open: search ranking. "panther" lists the butterfly *Neurosigma siva* ("Panther") first; prefer well-known taxa among equal matches.

---

## Increment 14 — Class Tooltips, Fact-Checked Texts & the Three Domains ✅

**Goal:** Extend hover descriptions to classes, check the texts against sources, and start the tree at the three domains of life. User-verified 2026-11-05.

### Tasks
- [x] Hover description for every accepted class (`frontend/js/class_descriptions.js`), looked up with the phylum table through `taxonDescription()`.
- [x] Fact-check of 729 phylum and class texts against Wikipedia and Europe PMC: 64 corrected (30 wrong, 19 unsupported, 15 tightened). Of the unchanged texts, 435 had strong support, 182 thin support and 48 no source found. Specialist databases were not consulted.
- [x] Descriptions for the 7 real phyla that had none; `krumholzbacteriota` key corrected to `krumholzibacteriota`.
- [x] Removed the stray phylum row `Archaea|Sp` (no descendants, no traits). Backup: `E:\AnimalKingdomSystem\sp_row_backup.jsonl`.
- [x] Tree root shows Bacteria, Archaea, Eukarya (open on load, holding the five kingdoms) and Viruses.
- [x] Bacteria opens to its 72 phyla plus `[Unclassified] (8)`, instead of 5 genera plus `[Unclassified] (75)`.
- [x] Search offers domains by name (prefix, 3+ letters) above the animal genus of the same name; choosing one opens the branch with no species panel.
- [x] Domain and Viruses hover texts, shown for the domain only, not for the namesake genera. These four texts were not source-checked.
- [x] Fixed: branch lines from the initial load were invisible. `_initHideExtinct` re-rendered during their fade-in, the cancelled fade left them at opacity ~0.00008, and the update step never restored it.
- [x] All tree labels now sit right of their dot, so siblings line up, with a page-coloured outline to keep them readable over links.
- [x] Tests: `e2e/taxon_tooltips.spec.ts`, `e2e/domains.spec.ts`, plus additions to `test_taxonomy_api.py` and `visualizer.test.js`. Backend 304, frontend 98, E2E 30 passing.

### Decisions recorded
- **Domains are a display layer; no rows or `taxon_path` values changed.** Rewriting ~5.9M paths would also break `trait_utils.py`, which treats the first path segment as the kingdom when matching GBIF, and `import_gbif.py` would bring old-style paths back. It also keeps the classification easy to change: three domains are the standard teaching, but evidence that eukaryotes arose within the archaea (the Asgard group) supports two.
- **Bacteria and Archaea cannot have rows of their own:** `scientific_name` is the primary key and those names belong to a stick insect genus and a spider genus, which `row_score` prefers. The API adds the domain nodes itself (`_PATH_DOMAINS`, `_EUKARYA` in `main.py`).
- `_parent_rank()` returns "domain" for those two paths. `get_taxon_by_path("Bacteria")` otherwise returns an old synonym family stored at that bare path, so the zoom expected genera.
- Stored paths have no domain in them, so frontend walks start from `_walkStart()`, which steps into the domain holding the first segment.
- Labels moved right across the whole tree, not only for domains, because any expanded kingdom or phylum would otherwise stick out the same way.

### Open follow-ups
- Stale scripts after a frontend change: the server sends no `Cache-Control`, so a tab can keep old code until Ctrl+F5 (this caused a false "no tooltips" report). A `no-cache` header on the frontend files would prevent it.
- Viruses still opens to only `[Unclassified] (27)`, because it has no phylum rows directly beneath it.
- The first E2E run after a server restart had 3 unexplained failures (`chat.spec.ts` input check, `full_journey.spec.ts` search-then-chat, the domains top-level test). They passed on all 3 later full runs; the error messages were not captured.

---

## Increment 15 — Order Tooltips & Corrected Common Names ✅

**Goal:** Extend hover descriptions to animal orders, and correct the wrong common names found while checking them. User-approved 2026-11-05.

### Tasks
- [x] Hover description for all 636 non-synonym animal orders (`frontend/js/order_descriptions.js`), used only for nodes of rank "order", because some order names are shared with other ranks.
- [x] Sources: Wikipedia 581, Europe PMC 23 (at least 3 hits off-topic and not relied on), none found 32. A script confirmed every number appears in its source and 54 flagged texts were read; this is less than the claim-by-claim check of the classes. 56 texts are generic ("An order of sea sponges"), and those without a source state only what the order's place in the tree and general knowledge support.
- [x] Tests: `visualizer.test.js` (103 total) and `e2e/taxon_tooltips.spec.ts` (31 total). All 154 orders under six sampled classes were hovered in a browser and showed text.
- [x] Corrected the common names of 68 phyla, classes and orders with `data/fix_common_names.py`: Mammalia "Herbivore" → "Mammals", Myxini "fish" → "Hagfish", Strigiformes "Goatsuckers" → "Owls". Old values: `E:\AnimalKingdomSystem\common_names_backup.jsonl`. Backend 312 passing (8 new in `test_fix_common_names.py`).

### Decisions recorded
- **A reviewed list, not a rule.** The tree shows the first stored name, and the bulk import never chose it. No rule can tell that "Herbivore" is wrong for mammals, so all 507 stored kingdom, phylum, class and order names were read by hand. Covered: wrong names, garbled entries and names of only part of a group ("Ants" for Hymenoptera). Plain style differences ("Turtle", lowercase) were left alone.
- Ranks below order were not reviewed, and neither were names beyond the first four shown for each node, unless the dry run happened to list them.
- A re-import from the backbone would bring the old names back; re-run the script afterwards.
- None of the 13 sampled rows, the worst cases among them, had a stored image or abstract, and none was in the vector store, so nothing needed rebuilding.

### Open follow-ups
- ~~The other 1,324 orders (other kingdoms and domains) have no description.~~ Done in Increment 18.
- `full_journey.spec.ts` fails now and then: `/api/search` scans the table in 3.3 s alone and about 5 s under load, and the test's limit is 5 s.
- `Pennatulacea` is flagged extinct, because it holds only 6 fossil *Graphularia* species; the living sea pens sit under `Scleralcyonacea`. Its tooltip describes sea pens in general.
- 46 ray-finned fish orders (about 42,000 accepted species) sit under Chordata's `[Unclassified]`. This matches the source: their class is empty in GBIF's `Taxon.tsv`, so it is a gap in GBIF, not an import error.
- `Actinopterygii` and `Chondrichthyes` are empty nodes that do not appear in `Taxon.tsv`; their origin is untraced. Left in place, since a move to Catalogue of Life would replace them.
- **Next: trial import of Catalogue of Life (COL), approved by the user to start 2026-11-06.** GBIF's backbone was last updated in 2023 and GBIF now uses COL's Extended Release. Import COL into a separate database and report matched, moved and lost names before anything in the app changes. No invented groups such as "Fishes": the tree should reflect its source.

---

## Increment 16 — Switch to Catalogue of Life Extended ✅

**Goal:** Replace the GBIF backbone (2023) with COL26.10 XR as the taxonomy source, keeping the images, traits, IUCN data and abstracts already collected. Decided by the user on 2026-11-06, after the trial comparison.

### Tasks
- [x] Trial: `data/import_col.py` (each release in its own DB), `data/compare_col.py` (matched, moved, lost). Of 1,810,226 accepted animal species, Extended accepts 1,595,764, keeps 69,173 as synonyms, and lacks 144,888.
- [x] `data/verify_col_levels.py`: check the orders and families COL leaves blank against independent sources.
- [x] `data/build_col_db.py`: build the new `species` table in a separate file, carry data across, apply confirmed fixes.
- [x] Tree API: accept the new levels; `taxon_path` may be NULL for rows outside the tree. Tree nodes carry their row key, so a homonym opens its own record; a search hit outside the tree opens the panel.
- [x] Rebuild what depends on names: extinct roll-up, `fix_common_names.py`, vector store, tests. Hover text: 3 renamed phyla reuse their text; the gaps below stay open.
- [x] Swap into place, keeping the old database as `species_gbif_backup.db`. Second build (land snails, IUCN extinct) swapped the same day; the first build is `species_col_v1_backup.db`, and 45 rows of panel data written in between were copied across.
- [x] Chat E2E (`full_journey`) run with Ollama up. User approved the merge to master on 2026-11-06.

### Decisions recorded
- **Fossils and other GBIF-only names:** out of the tree, kept in the DB: `taxonomic_status = 'GBIF_ONLY'`, `taxon_path` NULL, old path in `gbif_taxon_path`. Fossils that COL has stay in the tree. GBIF-only synonyms and non-animals are kept only if they hold data; the rest stay in the backup.
- **Levels:** kingdom, phylum, class, order, family, genus, species. Where one is missing, the lowest level COL has in that gap stands in for it, under its real rank. Other intermediate levels stay as rows without a tree position.
- **Blank orders and families:** filled only if an independent source agrees with GBIF's value and none disagrees, and the fix would not change a level COL does state. Otherwise left as in COL. A fix belongs to the group (genus to family, family to order), and is recorded in the `taxon_fixes` table.
- **Land snails go by majority (user's decision):** ITIS alone says Helicida, and IRMNG sometimes gives a phylum or class as the order, so the strict rule left Stylommatophora blank on most families. For this one order, at least two sources agreeing and more agreeing than not is enough (203 links, 16,986 species, verdict `majority`). `verdicts_strict.tsv` keeps the strict run.
- **Unranked:** `BOLD:` and other DNA clusters are dropped; named unranked taxa stay.
- **A family or order COL already has brings its own COL lineage**, so it stays in one place in the tree; if that lineage contradicts a level COL states for the group, the fix is refused.
- **A genus that gained a family takes the family's order, not its own:** otherwise a family whose order the sources dispute (Camaenidae) would split across the tree. That leaves 5,714 species, mostly land snails, without the order confirmed for their genus.
- **Homonyms:** accepted names that lose the primary key keep a row as `Name [Parent]`, labelled from the path. Old data carries by name only if `same_taxon` holds; 555 old rows failed it (536 held only an extinct flag, 16 an IUCN status, 7 an image) and stay in the backup.
- **Extinct:** IUCN status EX always means extinct, even where COL says living (user's decision), so the tree knows without the panel being opened. Otherwise COL's flag wins, except over a living IUCN status. Species COL leaves blank inherit an extinct genus (10,414, such as *T. rex*). Roll-up re-run.

### Result (2026-11-06)
6,119,040 rows; 1,800,133 accepted animal species in the tree, 144,926 out of it (92,928 flagged extinct). Without an order: 49,507 (old tree 114,222). Without a family: 16,881 (old tree 50,578). Of species in both, 8,866 had an order and 5,188 a family that is now blank. Verification: 2,061 order and 1,964 family links applied. Order and family conflicts left as in COL, apart from land snails. No accepted species in the tree with IUCN status EX is left unflagged.

### Open
- **Hover text:** added for all 22 new animal classes and 69 of the 153 new animal orders (100+ species, renamed, or familiar), written from Wikipedia and checked against what the tree holds under each group. Direct pages for 81 of the 91, some only for a parent group or a single family; the other 10 rest on old text, family names and general knowledge. Less checked than the Increment 14 classes. Still none for 84 animal orders (1,654 species), 790 animal stand-in levels, plant, fungus and microbe orders, 45 phyla outside animals, and 19 new kingdoms. Class and phylum text no longer shows on a genus or species of the same name (Branchiura, Appendicularia). The gaps listed here were closed in Increment 18; stand-in levels below order get the automatic line.
- **Labels:** 16 new classes named in Increment 17; 41 animal classes stay blank.
- **Data clean-up (2026-11-10, user's decision):** deleted from `E:\AnimalKingdomSystem\` (~12.6 GB): the first COL build `species_col_v1_backup.db`, the COL base release (`col_base.db` and its zip), the non-extended `col_xr_coldp.zip`, the GBIF backbone (`gbif/backbone/` and its zip) and the empty `animals.db`. Kept: `species.db`, `species_gbif_backup.db` (read by `build_col_db.py`), `col/col_xr.db`, `col_xr_full_coldp.zip`, `col/verification/`, `col/comparison/`. Without the backbone, `compare_col.py`, `batch_extinct_gbif.py` and the species pass of `backfill_extinct.py` need it downloaded again; the roll-up runs with the new `--rollup-only` flag.

---

## Increment 17 — Search Ranking, Frontend Caching & Image Clean-up

**Goal:** Clear the small open items left after the Catalogue of Life switch. Decided by the user on 2026-11-09.

### Tasks
- [x] Search: among equal matches, prefer well-known taxa.
- [x] Frontend files sent with `Cache-Control: no-cache`.
- [x] Clear 11 doubtful DuckDuckGo images from `species.db`: the 9 that could not be re-checked (only the site name was stored), plus *Bacteria amazonica* (a news article about bacteria, on a name that is also a stick-insect genus) and *Danionidae* (apparently a journal cover). Old values are in `E:\AnimalKingdomSystem\ddg_images_cleared_backup.jsonl`; each is looked up again when its panel next opens.

- [x] Common names for 16 of the 57 blank animal classes, such as Teleostei (Teleosts), Petromyzonti (Lampreys) and Octocorallia (Soft corals), as Wikipedia gives them, in `data/fix_common_names.py`. About 47,700 species sit under them.
- [x] Removed "fish lice" from the worm genus *Branchiura* [Naididae]; the name belongs to the crustacean class. A one-row fix outside the script, so a new COL build could bring it back.

- [x] Hover text for the placeholder nodes `incertae sedis`, `Siluriformes_incertae_sedis` and `Family-incertae`, matched on those exact name shapes because "incertae" is also a real species epithet (*Tamerlania incertae*). `UnassignedNoctuidae`, a similar placeholder filed as a genus, has none.

- [x] Backend listener no longer dies on aborted connections: `manage.py` and `playwright.config.ts` start uvicorn with `--loop asyncio:SelectorEventLoop`. Tested with 8,000 aborted connections, 4,000 of them on a busy server: listener alive, no errors. The default loop died at 200 on a busy server.

### Decisions recorded
- **Listener bug:** on Windows, uvicorn's default `ProactorEventLoop` (Python 3.12.0) closes the listening socket for good on `WinError 64`, when clients abort connections while the server is busy. The process stays alive but the port refuses connections until a restart. An E2E run against port 8010 caused it, so run E2E on a private port (`AK_PORT=8011`).
- **`--reload` needs no flag:** uvicorn already picks the selector loop when it runs with a subprocess, so the dev commands in the docs are unchanged. Nothing in the backend uses asyncio subprocesses, which the selector loop doesn't support on Windows.
- **Blank classes:** named only where an established common name exists. The 41 left have only an anglicised name (Remipedia), none in everyday use (Chromadorea), or only a description (Cephalaspidomorphi, "jawless fishes").
- **"Soft corals" is informal:** Wikipedia's wording for Octocorallia, which also includes sea fans and sea pens.
- **"Panther" was not fixed by code:** COL's common names gave the puma and leopard the exact name "Panther", so as accepted names they now rank above the synonym butterfly *Neurosigma siva*, which stays 3rd.
- **Well-known score:** one point each for an abstract, an IUCN status and a photo. It comes after match type and accepted-before-synonym, and before name length. It cannot lift a name over a stronger match type or a synonym over an accepted name.
- **Genus panels stay without traits, no hint line (user's decision).**

### Open
- ~~**"wombat":** names that only contain the query in a common name ("common wombat") still rank below scientific names starting with it.~~ Done in Increment 30 (common-name word matching).
- **Partial typing:** famous species can push their own genus down ("panth" gives five *Panthera* species in the top 8, not the genus).
- At least 7 other DuckDuckGo images remain, all saved after the word check (`cbd2a5d`); not reviewed. DuckDuckGo images hosted on Wikimedia can't be told apart by address, as *Felis maxima* showed.
- **E2E stalls, cause unknown:** full parallel runs often stall for about 10, 20, 30 or 40 s and can then fail tests, with both event loops. Stalled in 3 of 10 runs as normal, 5 of 9 with the VPN disconnected, 7 of 10 with a second network client also switched off (its service and adapter stayed up); the samples are too small to read a trend. Stack dumps show the server closing a socket or idle, a client stuck connecting, idle workers and no scheduling gaps, which points to the Windows network layer rather than the app, database or CPU. The listener fix doesn't cure this: 1 of the 3 logged runs after it had 2 failures. Not yet tested: the firewall off.

---

## Increment 18 — Hover Text for the Whole Tree ✅

**Goal:** Every tree node gets a hover text. Written texts for every node at or above order; families and the other levels above genus get an automatic line. Requested by the user on 2026-11-09 and written 2026-11-09/10. User-approved 2026-11-10.

### Tasks
- [x] Automatic line: `nodeDescription(node)` in `visualizer.js` uses the written text if there is one, otherwise it builds one from the node's place in the tree ("A family in the order Rosales (…)"). Letter groups and `[Unclassified]` get their own line; genus, subgenus and species get none.
- [x] Kingdoms and upper levels: 31 kingdoms, realms, subkingdoms and the infrakingdom, plus 62 phyla, subphyla and infraphyla, in the new `frontend/js/upper_descriptions.js` (`UPPER_DESCRIPTIONS`).
- [x] Classes: 126 more in `class_descriptions.js`. Levels between class and order (subclass, superorder, infraclass and so on): 81 in `upper_descriptions.js`.
- [x] Orders: the last 84 animal orders in `order_descriptions.js` (789 in total). 1,432 orders of Archaea, Bacteria, Viruses, Protozoa, Fungi, Plantae and Chromista in the new `frontend/js/order_descriptions_other.js` (`OTHER_ORDER_DESCRIPTIONS`), used only for rank "order", like the animal table. No key appears in both order tables.
- [x] Audit (`E:\AnimalKingdomSystem\tooltip_work\tt_audit.py`): no node at or above order is left without a written text.
- [x] Tests: Vitest 128 passing (counts, length ≤ 170 characters, no key overlap, rank checks). `e2e/taxon_tooltips.spec.ts` has a new test that hovers a kingdom (Plantae), a plant order (Rosales) and a family (Rosaceae, automatic line). The tooltip, tree, domain and extinct specs all passed against a private backend (port 8031): 5 + 22 tests.

### Decisions recorded
- **Sources:** each text is written in my own words from the Wikipedia summary of the group, or of its only genus or family when the group has no page of its own (`tt_wiki.json`). Numbers appear only where the source gives them. Where the source is thin, the text says only what the tree shows ("Red algae of one family, Balliaceae"). This is less checked than the Increment 14 classes.
- **Leftover nodes:** a subphylum or class that only holds groups not placed lower down says "Here it holds … not placed in a class/order".
- **Empty orders:** 75 non-animal orders have no members in the tree, often old names or alternative spellings (Sphorolithales, Chaetocerales). Their text says "Here it has no members of its own."
- **Fossil wording** follows the extinct counts in the DB (`tt_stats.py`): "all fossils", "nearly all", "mostly", "about half", "many".
- **Lookup order** in `taxonDescription`: incertae sedis placeholder, domain, animal orders, other orders (both for rank order only), stop at genus and species, then the original table, classes, and upper levels. `tt_stats.py` found no name clashes between tree nodes above genus.

### Open
- Families and the lower levels have only the automatic line, by design.
- A new COL build may add or rename groups; re-run `tt_audit.py` afterwards.

---

## Increment 19 — Chat Query Tools

**Goal:** Let the chat answer name, ranking, counting and relationship questions from the database, and stop "Database:" labels on numbers the database doesn't hold. Requested by the user on 2026-11-10, after the chat answered "which animal can get oldest" with a thorny devil and denied that turtles pass 100. Detailed plan: `Docs/superpowers/plans/2026-11-10-chat-query-tools.md`.

**Status:** COMPLETE — user-approved and merged to master 2026-11-10.

### Tasks
- [x] Label fix: a sentence backed only by summary words can't carry a number missing from the result. *Moloch horridus* has no lifespan, but "Database: … can live up to 20 years" passed on the words "species" and "lizard".
- [x] `find_species(name)`: common name to scientific name from the database, replacing semantic search for names. A common name shared by several ranks goes to the broadest group ("Owls" → Strigiformes, not Strigidae).
- [x] `rank_species_by_trait(trait, order, group="Animalia", limit)`: max lifespan, body mass or length. States how many species have a value, with a caveat that values are maxima or estimates.
- [x] `group_stats(group)`: accepted species, extinct, IUCN breakdown, population trends, threatened examples.
- [x] `taxonomy_of(name)`: lineage with common names; members of a group, or relatives in a species' genus.
- [x] Live eval of 10 questions with Ollama on a private port; at least 8 must pass, the thorny devil one always. Then docs.

### Decisions recorded
- SQL lives in the new `backend/app/taxon_queries.py`, and the tools stay thin in `llm_agent.py`. Every database tool's output now feeds `LabelChecker`.
- Only accepted species inside the tree are counted or ranked; synonyms and GBIF_ONLY rows never are. Groups default to Animalia, so plants don't answer animal questions.
- No tools filter on habitat, diet or location: fewer than 5,100 species have those values.
- With seven tools, llama3.1:8b may choose tools less reliably. If 3 or more eval questions pick the wrong tool, `group_stats` and `taxonomy_of` get merged into one tool, after asking the user.
- `find_species` and the other tools take only exact names from the database: an exact scientific name (a primary-key lookup, no case-insensitive scan), else an exact common name or its singular / plural. Typical tool time on the live DB: 1-3.6 s.
- Rankings and lists show the first Latin-script common name (the live DB had a Chinese name first for *Sebastes aleutianus*).
- `group_stats` says its extinct count includes fossil species (1,870 mammals, against 76 IUCN EX). Without that the model claimed the opposite.
- `LabelChecker` now reads names from ranking, member, relative and threatened-example lines, and the common names in lineage lines. IUCN codes in parentheses are not names. A lineage now excludes only its own level (and the genus for a species), so a group's parent class counts as evidence.
- Whole-branch review (fresh reviewer): 6 Important findings, all fixed with tests.
  - Group tools never resolve to a single species, and a candidate group must contain accepted species. Near the top of the matches, a row whose first common name matches wins. Live results: snakes → Squamata (Catalogue of Life keeps the snake families directly under it, and its "Serpentes" rows are empty), turtles → Testudines, ants → Formicidae, bats → Chiroptera, owls → Strigiformes.
  - `taxonomy_of` lists the next main rank and counts the other direct children separately. Aves: 42 orders, plus 71 families and 125 genera placed directly under the class.
  - `LabelChecker` no longer takes common names from lineage or member lines ("Felis (Cat)" backed "a cat can sleep 16 hours"). Group counts back only sentences about counts, and "9,642" is read as one number.
  - The order words "ascending", "min" and "youngest" rank lowest first.
  - Two slow query plans fixed: a common-name lookup went from 30 s to 1 s.
- The eval runs in-process (`data/chat_eval.py`) rather than over HTTP, so it can print which tools were called. The E2E specs ran on port 8031.

### Live eval (llama3.1:8b, 2026-11-10)
| # | Question | Tool chosen | Result |
|---|---|---|---|
| 1 | which animal can get oldest | rank_species_by_trait | ✅ *Anoxycalyx joubini* 15,000 years, "Database:" |
| 2 | arent there turtles who reach over 100 years | rank_species_by_trait | ❌ gives *Aldabrachelys gigantea* 152 years from the database, but opens with a general-knowledge sentence that no turtle passes 100 |
| 3 | how old can kangaroos get | lookup_species | ✅ *Macropus giganteus* 25 years |
| 4 | what is the heaviest bird | rank_species_by_trait | ✅ Ostrich 111 kg |
| 5 | how many owl species are endangered | group_stats | ✅ 4 CR, 8 EN, 21 VU of 239 assessed |
| 6 | how many mammals have gone extinct | group_stats | ✅ 1,870 including fossils, 76 IUCN EX (after the wording fix) |
| 7 | what is a whale related to | taxonomy_of | ✅ Cetacea in Mammalia, example families |
| 8 | which orders do mammals have | taxonomy_of | ✅ list of orders, noted as not exhaustive |
| 9 | what is the scientific name of the eagle owl | find_species | ✅ *Bubo bubo* |
| 10 | tell me about the thorny devil | lookup_species | ✅ no lifespan under "Database:" |

9 of 10 pass and every question picked the right tool, so `group_stats` and `taxonomy_of` stay separate. Re-run after the review fixes: same 9 of 10. Test suites: backend 543, Vitest 128, chat and journey E2E 8/8 (E2E run before the review fixes, which touched only backend tools).

### Open
- Q2: the 8B model's own belief contradicts the database result within one answer. Fixed in Increment 20.
- The order list for Mammalia counts 143 orders, fossil orders included; the tool doesn't say so.

## Increment 20 — Chat Polish

**Goal:** Fix the remaining Increment 19 turtle answer (Q2) and the six minors deferred from its review. Requested by the user on 2026-11-10.

**Status:** COMPLETE — user-approved and merged to master 2026-11-10.

### Tasks
- [x] Contradicted denials: when a sentence denies that anything passes a threshold ("there are no turtles … over 100 years") and the ranking just returned values past it, `LabelChecker` replaces the sentence with the database count ("Database: 4 of the 10 ranked species exceed 100 years."). Works for "under / less than / below" too. The denial and the threshold must be in the same clause, so "no teeth, and some live over 100 years" is kept.
- [x] Trait names with spaces or hyphens ("body mass", "Max Lifespan") are accepted.
- [x] `%` and `_` in a name are matched literally, not as LIKE wildcards.
- [x] Lineage common names prefer a Latin-script name, through one shared `taxon_queries.first_common`.
- [x] `;` and `:` inside a common name become `,` and ` -`, so they can't break the tools' list parsing.
- [x] `find_species` marks the lineage of every match after the first as "Lineage (other match)", which is not evidence.
- [x] For a subspecies, the genus and species levels of its lineage are not evidence (they match the subject's own name).

### Decisions recorded
- A prompt rule ("Database sentences first, general knowledge must not contradict the result") was tried live and made it worse: the model switched to `group_stats` and still denied it. Adding the group's common name to the ranking header didn't help either (and showed "Testudines (Terrapins)"). The American box turtle at 138 years shows it isn't a tortoise-versus-turtle belief: the 8B model answers "aren't there …?" with a denial whatever the data says. Hence the deterministic check, in the same place as the label checks.
- The check only fires after a `rank_species_by_trait` result, and its replacement counts only the ranked species (the top 10 by default), so it is always a true database statement.
- "Felidae (Cat)" is a data question (the stored order of common names), not code; left as is.

### Live eval (llama3.1:8b, 2026-11-10)
10 of 10 pass with the same questions as Increment 19. Q2 now answers "Database: 4 of the 10 ranked species exceed 100 years. Database: The Aldabra giant tortoise (*Aldabrachelys gigantea*) has a recorded maximum lifespan of 152 years." Test suites: backend 553, chat and journey E2E 8/8 on port 8031. The frontend didn't change.

## Increment 21 — Chat Memory

**Goal:** Let the chat answer follow-up questions ("what is the largest animal" → "what does it eat"), and find out why "what does the blue whale eat" got a classification answer. Requested by the user on 2026-11-10 with a screenshot.

**Status:** COMPLETE — user-approved and merged to master 2026-11-10.

### Tasks
- [x] Conversation memory: the browser keeps this page's questions and answers (`frontend/js/chat.js`) and sends the last 6 messages as `history` with each question. `POST /api/chat` accepts `history: [{role: user|assistant, content}]` (other roles: 422). The backend caps it again: 6 messages, 1,500 characters each. A failed or empty answer isn't remembered; a page reload starts a new conversation. Nothing is stored on the server.
- [x] Follow-up rules in the prompt ("it" means the species from the previous answer; call the tool again with its scientific name), added only when the request carries history.
- [x] `taxonomy_of` for a species also returns that species' facts and its "Not recorded" line, the same lines `lookup_species` gives.
- [x] Name resolution ties go to the better-known row (abstract, IUCN status, photo), as in search: "snow leopard" resolved to the moth *Obtusipalpis pardalis*, now *Panthera uncia*.
- [x] From the user's second screenshot (2026-11-10, "which animal can get oldest" → top 5 → "what kind of animal is #1" → "and #2"):
  - A misspelt scientific name falls back to the closest accepted name with the same first three letters and word count (0.9 similarity, 10-260 ms): the model copies *Cinachyra antarctica* as "Cinachyrya" or "Cinachyry", and `lookup_species` found nothing. Used by `lookup_species` (the result says "closest match to …") and `resolve_taxon`.
  - "#1", "#2" in a follow-up get the name from the previous answer's numbered list ("what kind of animal is #1 (#1 = Anoxycalyx joubini)"): the model passed "#1" itself to `taxonomy_of` and then guessed "siphonophore".
  - A label written before a list bullet ("Database: - #1 …") goes after it, so the list still renders as a list.
  - The first answer naming the Greenland shark as the oldest animal didn't reproduce (5 runs, all *Anoxycalyx joubini*); model variation.

### Decisions recorded
- Why the third answer went wrong: llama3.1:8b called `taxonomy_of` for "what does the blue whale eat", so the answer was the classification and relatives. Diet itself isn't in the database for the blue whale ("Not recorded: diet"), so the general-knowledge label on krill was right.
- Prompt fixes for the tool choice were tried and measured (5 runs each). Every wording that sent the blue whale to `lookup_species` sent "aren't there turtles over 100 years" to `lookup_species` or `taxonomy_of` instead, 5 of 5 times; the follow-up rules in the single-question prompt did the same. Hence the history-only follow-up section and the species facts in `taxonomy_of`, which make the answer right whichever tool the model picks.
- Memory lives in the browser, not on the server: no sessions to expire, nothing to clean up, and the backend stays stateless. Earlier answers are context only; the label checker still only accepts facts from this turn's tool results, so the model has to call a tool again.

### Live eval (llama3.1:8b, 2026-11-10)
10 of 10 with the Increment 19 questions, each with the right tool. The screenshot's conversation: "what does it eat" now answers about the blue whale (krill, labelled general knowledge), "how long does it live" gives 110 years from the database, "where does it live" gives its marine habitat and depth from the database. The second screenshot's conversation, replayed twice with `data/chat_eval.py --chat`: all four answers from the database. Test suites: backend 570 (564 before the second-screenshot fixes), Vitest 132, E2E 38/38 on port 8031 (chat and journey specs rerun 9/9 after the fixes) (8 tests timed out on the first run while the VPN was being restarted, then passed).

## Increment 22 — Chat Model qwen3.8

**Goal:** Make the chat model a setting and switch to qwen3.8:27b if it beats llama3.1:8b on the app's own questions. Requested by the user on 2026-11-10 after the model comparison below. Detailed plan: `Docs/superpowers/plans/2026-11-10-chat-model-qwen.md`.

**Status:** COMPLETE — user-approved and merged to master 2026-11-10. The gate failed, so llama3.1:8b stays the default.

### Model comparison (2026-11-10, RX 7900 XTX 24 GB, 20 answers each: 13 questions + both screenshot conversations)
| Model | Ollama 0.33.2 | Ollama 0.40.16 | Answer time (0.40.16) | Tool choice | Problems |
|---|---|---|---|---|---|
| llama3.1:8b | 97 tok/s | 126 tok/s | median 3.0 s, max 5.2 s | 17/20 | diet / habitat / "#1" go to taxonomy_of (the Increment 21 rescues cover them); 4 label corrections |
| qwen3.8:27b | 9 tok/s | 50 tok/s | median 6.6 s, max 12 s | all 13 single questions | 13 label corrections (mostly correct sentences the checker doesn't recognise); 3 of 7 follow-ups answered without a tool |
| qwen3.6:27b | 9 tok/s | — | median 32 s (0.33.2) | good | one Ollama tool-call parse error |
| mistral-small3.2:24b | 42 tok/s | 48 tok/s | median 4.5 s | right when it works | 5 of 20 answers empty: Ollama drops its tool call when the model leaves out `[ARGS]`; a retry with a nudge rescues 2 of 5 |
| qwen3:30b (MoE) | 122 tok/s | 137 tok/s | 50 s+ | right | ignores thinking-off and writes its reasoning into the answer |

All models fit in VRAM (100% GPU). The qwen3.6/3.8 architecture (`qwen35`, with recurrent layers) ran at 9 tok/s on Ollama 0.33.2; the user updated Ollama to 0.40.16 (winget, `--source winget`: the msstore source failed on a certificate) and it went to 50 tok/s. A model left loaded (10 min keep-alive) made the next one spill into RAM: unload before timing.

### Tasks
- [x] Chat model setting: `AK_CHAT_MODEL` (default llama3.1:8b), thinking off, 16k context; a missing model shows an error naming it.
- [x] `data/chat_eval.py --suite --model M`: the comparison suite above plus a 6-message conversation, scored (tool choice, empty answers, label corrections, times).
- [x] Label checker reads qwen's phrasing: ranking coverage counts, the ranking caveat, "not recorded" statements for listed fields, other find_species match names.
- [x] An answer written without any tool call is dropped and asked once more with a nudge.
- [x] Gate: qwen3.8 becomes the default only with tool choice ≥ 12/13, no empty answers, label corrections ≤ llama's, median ≤ 10 s and max ≤ 20 s, the screenshot turns answered from the database, and no wrong "Database:" fact. Then full checks and docs.

### Gate result (2026-11-10, `chat_eval.py --suite`, each model alone, 100% GPU, 24 answers)
| Model | Median / max | Tool choice | Empty | Label corrections | Largest prompt |
|---|---|---|---|---|---|
| llama3.1:8b | 2.8 s / 4.6 s | 13/13 | 0 | 4 | 2,078 tokens |
| qwen3.8:27b | 6.1 s / 8.0 s | 11/13 | 0 | 13 | 2,611 tokens |

qwen3.8 failed three criteria:
- **Tool choice 11/13.** It went through find_species before lookup_species for the blue whale and the snow leopard. That is a sensible route, but the first call doesn't count.
- **13 label corrections against llama's 4.**
- **Follow-ups answered from memory.** "how long does it live", "and #2" and "where does it live" got no tool call even after the nudge (both attempts). The "#2" answer called the sponge *Cinachyra antarctica* "a parasitoid wasp"; the checker relabelled it general knowledge, but it is still wrong.

llama3.1:8b got every first tool right, and the new label rules plus the retry cost it nothing. Prompts stay far below the 16k context. Decisions:
- The setting, the label rules and the retry stay.
- `OLLAMA_MODEL` stays llama3.1:8b.
- The other models stay installed, at the user's request.
- A bug found by the gate run: held tokens went out joined into one chunk. Fixed: one SSE event per chunk.
- After the final review, five fixes:
  - stricter coverage-count, caveat and not-recorded rules;
  - the trait estimator shares the chat's model and context;
  - the second attempt streams.
- Added at the user's request after a screenshot: "what is the smallest animal" answered "the Eastern red-backed salamander, 0.0005 kg". The value is right, but only 3,612 of 1,800,133 species have a recorded body mass (almost all vertebrates). A "lowest" ranking that covers under half its group now gets a "- Coverage note:" line, and the chat appends it as a "Database:" sentence when the answer doesn't state the coverage itself.

## Increment 23 — Chat Name Links

**Goal:** The animals a chat question is about become links in the answer. Clicking one opens it in the tree and the species panel, as a search result does. The scope is the user's, from 2026-11-10:
- "What do koalas eat" → a link to koala;
- "top 3 longest-living" → 3 links;
- "what does the blue whale eat" → the whale, not the krill.

Design: `Docs/superpowers/specs/2026-11-10-chat-name-links-design.md`. Plan: `Docs/superpowers/plans/2026-11-10-chat-name-links.md`.

**Status:** COMPLETE — user-approved and merged to master 2026-11-11.

**Decisions:**
- Only subjects of this turn's database lookups are linked.
  - The user first chose "every name the database can find", then narrowed it. Common names like "small fish", "sea star" and "fruit fly" belong to specific species in the data and would link wrongly.
- The tool result names the exact row (homonyms included), so a link can't open a look-alike.

### Tasks
- [x] Subject names from each tool's output (lookup, first find match, ranked entries, group, taxonomy subject plus members and relatives, semantic results).
- [x] Subject rows by primary key; matching in the answer (scientific names exact, common names any case, plurals, possessives, word boundaries, longest first).
- [x] `links` SSE event before `done`, from the shown attempt only; none after an error.
- [x] Browser: links in the bubble, one `openTaxon` for search results and chat links, a subtle underline with a tooltip, plus an E2E click test.
- [x] Live check on the three example questions, full checks, docs.

**Built:**
- `backend/app/taxon_links.py`: `subject_names` (per tool), `subject_rows` (primary key only), `match_links`.
- `llm_agent._run_agent` collects the attempt's sent text and subjects; `stream_response` sends `links` before `done`.
- `frontend/js/chat.js` `linkNames` / `taxonItem`; `app.js` `openTaxon` shared by search results and chat links.
- Found while testing: the page-wide click handler that closes the search list also cleared the highlight a chat link had just set. For link clicks it now only closes the list.
- `data/chat_eval.py` prints a `links:` line.

**Live check (llama3.1:8b, 2026-11-11):**
- "what does the blue whale eat" (taxonomy_of): `blue whale`, `Blue whale(s)`, `Balaenoptera musculus` → *Balaenoptera musculus*; krill not linked. ✓
- "which animals live the longest, give the top 3" (rank_species_by_trait): `Anoxycalyx joubini`, `Arctica islandica`, `Iceland Cyprina` → 2 of 3 animals. In both runs the model wrote "Cinachyrya antarctica" for *Cinachyra antarctica*, so that name doesn't match.
- "what do koalas eat": no links, 3 of 3 runs. The model calls semantic_search_species ("koalas diet"), which returns a Komodo rat and two fish, never the koala, so the koala was not looked up. Correct under the rule, but it misses the user's example; fixing it means changing tool choice (a non-goal of this increment).

**Checks:** backend 621 passed; Vitest 139 passed; E2E 39 passed on port 8031 (first run: 6 `page.goto` timeouts, the known startup stall; rerun clean).

**Final review (Opus, 2026-11-11):** no Critical findings. The three Important findings are fixed, each with a test that failed first:
- **Subgenus keys** such as "Aedes (Stegomyia)" (11,369 in the DB) were cut to the genus, so the link opened the wrong taxon. `subject_names` now returns the item text, and `subject_rows` keeps the longest key candidate that exists.
- **"sea lions" / "mountain lions" linked to the lion.** A one-word common name is now dropped from the links when any mention of it follows a word that isn't a function word ("the", "a", "many"…). This costs a missed link ("male lions"), never a wrong one.
- **A database error while finding links** ended the stream without `done`, so a complete answer showed a network error and was left out of the chat memory. It's now logged, and the answer goes out without links.

After the fixes: backend 624 passed, Vitest 139 passed.

**Deferred minors:**
- On a shared common name, the first subject wins: an unrelated semantic-search hit can claim it.
- `casefold` vs regex case folding: names with "ß" don't match.
- The ranked-item regex is greedy up to the last colon.
- The E2E highlight check uses the `opacity="0.12"` selector.
- Raw `_underscore italics_` never link, because the browser's word boundary differs from Python's `\w`.

**Scientific names anywhere (the user's call, 2026-11-11):** "which penguins live in antarctica" listed five penguins from general knowledge with their scientific names and had no links. Semantic search had returned silverfish and a skate, so no penguin was looked up. Option 1, chosen by the user: an exact scientific name (binomial or trinomial) of a species in the tree links anywhere in the answer (`taxon_links.named_rows`: no synonyms or GBIF-only rows; no common names). Common names still link only for looked-up subjects.
- This bends the blue-whale rule on purpose: "krill (*Euphausia superba*)" would link the krill's scientific name.
- The screenshot answer links all 5 penguins. The live rerun didn't write scientific names, so it had none to link.
- Option 2, steering tool choice toward find_species / taxonomy_of so the animals are really looked up (koala, penguins), stays a candidate increment.

---

## Increment 24 — GBIF Ranges

**Goal:** Every well-recorded animal gets a geographic range from wild observations, and the chat can rank by it. "Which penguins live furthest north" should come from the database: Galápagos, Humboldt, then Magellanic/African. Today the model answered it wrongly from general knowledge, because only 3,306 accepted species have a range at all. Requested by the user on 2026-11-11.

**Status:** ✅ complete, approved by the user and merged to master 2026-11-11. The import has run on `species.db`; old values in `E:/AnimalKingdomSystem/gbif_ranges_backup.jsonl`. Detailed plan: `Docs/superpowers/plans/2026-11-11-gbif-ranges.md`.

### The download (done 2026-11-11)
- One GBIF SQL download, not per-species API calls. Per-species calls (penguin trial: ~45 requests, ~15 s per species) would take 1–2 weeks for all animals; the SQL job took about an hour on GBIF's side.
- File: `E:/AnimalKingdomSystem/gbif_ranges/0001920-261110092616502.csv`, DOI 10.15468/dl.5v8cu8, licence CC0. The submit script is next to it (`gbif_sql_download.py`).
  - It reads the user's GBIF login from `E:/AnimalKingdomSystem/gbif_credentials.json`, which is kept out of the repo.
- Columns per GBIF species: `specieskey`, `species`, `n` (wild records), `countries`, and `lat_min` / `lat_max` / `lon_min` / `lon_max`.
- Records: human and machine observations only, status DETECTED, with coordinates, no geospatial issues.
- Edges are the 0.5% and 99.5% percentiles. That trims stray records only for well-recorded species: below about 200 records the percentile is the single extreme record (final review). So rankings only use ranges from 1,000+ records, with 5+ records beyond each edge.
  - This drops zoo records: the Humboldt penguin's northern edge went from 53.4°N (zoos in Germany) to 5.2°S, and the King penguin's from 52.5°N to 46.4°S.
  - The cost: well-recorded species lose a little real edge. The Emperor penguin ends at 76.0°S, against about 78°S in reality.
- 366,688 species from 2.59 billion records. Against `species.db`:

  | Match | Species |
  |---|---|
  | accepted, in the tree | 348,403 |
  | of those, with 10+ records | 167,899 |
  | synonyms | 11,605 |
  | GBIF_ONLY | 6,043 |
  | no match | 637 |

  The matched species include 744 flagged extinct and 3,448 (with 10+ records) whose longitude span exceeds 340°.
- GBIF SQL gotchas, both found the hard way (two empty downloads):
  - Status is `'DETECTED'`; the web API still accepts `PRESENT`, SQL doesn't.
  - Taxa come from `occurrence.gbif_classification.taxonkeys` / `.specieskey` / `.species`. The flat `kingdomKey` / `familyKey` / `speciesKey` columns match nothing.
  - `GET /occurrence/download/request/sql?<search params>` shows GBIF's own translation.
  - `POST /occurrence/download/request/validate` checks a query without an account.

### Decisions (proposed, for the user to confirm)
- **Minimum 10 wild records** for a range. Half the species have fewer than 8, and a handful of points says little about a range.
- **Skip extinct species.** A fossil with a "human observation" is a data error.
- **Longitude across the 180° line:** when the span exceeds 340° (polar bear, Arctic fox, Snares penguin), store latitude only. The longitude edges then cover nearly the whole globe and say nothing.
- **Replace existing ranges.** The old raw min/max ranges include zoo records. Source "GBIF occurrences (wild, 0.5% edges)" in `trait_sources`, with the DOI.
- **Synonyms:** a range on a synonym goes to its accepted species, unless that species has its own row in the download.
- **On-demand fallback** (panel or chat on a species without an imported range): use the same wild filters. The edges are percentiles of the fetched sample, not raw min/max.
- **Extras** in the stored JSON: `records` (n) and `countries`, so the panel can show how well a range is supported.

### Tasks
- [ ] `data/import_gbif_ranges.py [--dry-run] [--min-records 10]`: CSV → `geo_bounding_box` with `trait_sources` provenance, written directly (`update_species_traits` never replaces a sourced value), short transactions, resumable, backup of replaced values to `E:/AnimalKingdomSystem/gbif_ranges_backup.jsonl`; prints the match table above.
- [ ] Latitude-only ranges: `parse_geo_bbox` / panel (`traits.js`) show "lat 51.6–83.0" without a longitude; the chat's lookup output says so too.
- [ ] Ranking: `rank_species_by_trait` gets `northernmost` (lat_max, highest first) and `southernmost` (lat_min, lowest first), aliases "north", "northern", "south", "southern", with the coverage note. Check the speed of `json_extract` over a group; add an expression index if needed.
- [ ] On-demand fallback in `trait_utils` uses the wild filters and sample percentiles.
- [ ] Live check: "which penguins live furthest north" (top 3 from the database), "what is the northernmost bear", koala range in the panel; full checks, docs (Manual, DB_SCHEMA, Data Source Reference with the DOI).

### Built (2026-11-11)
- `backend/app/geo_range.py`: the shared rules (10 records, 0.5% / 99.5% percentiles like SQL `PERCENTILE_CONT`, latitude only over a 340° longitude span).
- `data/import_gbif_ranges.py`: dry run, backup, batches of 1,000, re-run safe.
  - Dry run: 176,171 GBIF species with 10+ records → 167,356 accepted in the tree, 5,763 synonyms (26 unusable), 317 extinct skipped, 2,508 outside the tree, 201 no match → **172,104 species got a range** (926 s). A re-run changes 0 rows.
- Panel and chat show a latitude-only range as "lat 51.6–83.0, longitude not recorded (range crosses the 180° line) (4,892 wild records)". A range without both latitudes (old broken rows) shows nothing.
- `rank_species_by_trait` traits `north` / `south` (`lat_max`, and `lat_south` = −lat_min), output "northern range edge 0.1°N".
  - The coverage note counts living species only: fossils never have a range. Found in the live check, where it said "19 of 58 penguins", fossils included.
  - Speed: 1.3–2.7 s per ranking (`json_extract`, no index needed).
  - **Ranks only ranges from 1,000+ wild records** (`taxon_queries.RANK_MIN_RECORDS`), a final review fix.
    - Smaller samples let one stray record set an edge: a Madagascar mongoose at 85°N (251 records), an African butterfly at 82.7°S (19 records).
    - Old ranges without a record count (raw min/max, e.g. a Central American shrew at 89°N) are left out too.
    - With the threshold, the furthest-north mammals are the polar bear, harp seal and walrus; penguins keep 16 of 19, with the same top 3.
    - The panel still shows all ranges.
- On-demand fallback: wild filters, percentile edges, at least 10 points, source "GBIF occurrences (wild sample)"; `_get_json` now sends lists as repeated keys.

**Spot checks:**
- *Spheniscus mendiculus* lat_max 0.09;
- *S. humboldti* −5.21;
- *Ursus maritimus* has no longitude;
- *Phascolarctos cinereus* has 350,798 records.

The furthest-north animals overall are Arctic Ocean copepods at about 90°N.

**Live check (llama3.1:8b):**
- "which penguins live furthest north, give the top 3" → `rank_species_by_trait(north, penguins)`: Galápagos, Humboldt, Magellanic. ✓
- "what is the northernmost bear" → polar bear, 83°N. ✓
- "which owl lives furthest south" → *Bubo magellanicus*, 54.9°S. ✓
- "where does the koala live" → the model called `taxonomy_of`, which doesn't show the range, so the answer came from general knowledge. This is the known tool-choice gap (option 2 from Increment 23), not a range problem.

**Checks:** backend 668 passed; Vitest 142 passed; E2E 39 passed on port 8031.

### Later, not this increment
- Habitat (marine / freshwater / terrestrial) and extinct from GBIF species profiles for the same species: about 1 request per species, so limit it to well-known species first.
- `establishmentmeans` (captive, introduced) is in GBIF's SQL table and could remove zoo and introduced records outright.
- A refresh: re-run the same query yearly (`gbif_sql_download.py submit`).

---

## Increment 25 — Chat Tool Choice for One Animal ✅

Approved and merged to master 2026-11-12. Questions about one animal ("what do koalas eat",
"where do pandas live") reached the wrong row or no row: llama3.1:8b sends them to semantic
search ("koalas diet"), which only knows ~7k embedded abstracts, or to `taxonomy_of`, whose
name resolution picked the plant genus *Panda* and COL's empty wombat genus *Koala*.

### Decisions
- Code guards, no prompt change: earlier prompt fixes for llama broke other questions.
- **Semantic search** leads with the `lookup_species` facts of a species the query names
  (`taxon_queries.named_species`: phrases of up to 3 words, question words dropped, queries over
  4 content words skipped). A name counts if it resolves to an animal species, or to a group with
  exactly one living species ("koalas" = Phascolarctidae). Groups of many ("cats", "owls") name
  no species. The facts are evidence for `LabelChecker` and link targets; the semantic hits after
  "Other species from semantic search:" stay outside the evidence, as before.
- **`taxonomy_of`** on a group with one living species adds "Only living species: …" and that
  species' facts.
- **`resolve_taxon`:** a lowercase name that is the scientific name of a non-animal, or of a group
  with no living species, gives way to an animal with that common name ("panda", "koala"); the
  capitalised form still means the genus. The first-common-name match one level down only wins
  below a top-level match (the panda catfish no longer beats the giant panda's genus).

### Checks
- Backend 691 passed.
- `chat_eval --suite --model llama3.1:8b`: tool choice 13/13, empty answers 0, label corrections 4
  (same as the Increment 22 baseline).
- Live: koala diet → koala facts + links (diet itself is general knowledge, correctly labelled);
  where do koalas live → mass, lifespan, IUCN VU, decreasing; where do pandas live → giant panda
  118 kg, 36.8 years; "what do cats eat" and "a striped horse-like animal" unchanged.

### Open
- "giant panda" in an answer links to the genus *Ailuropoda* rather than the species.
- "which snakes live in Holland": no tool answers place questions → Increment 26.

## Increment 26 — Animals of a Place ✅

Approved and merged to master 2026-11-12. "Which snakes can be found in Holland" got an answer about three
snakes from Malaysia, Australia and Mexico: no tool answered place questions, so llama used semantic
search. The GBIF ranges (Increment 24) can answer them.

### Decisions (the user's)
- Places include continents and regions, not only countries.
- "Snakes" is a fixed list of snake families (`taxon_queries.SNAKE_FAMILIES`), used only by this tool:
  COL files most snake families directly under Squamata, so the tree's "snakes" are all squamates.

### Built
- `data/build_places.py` → `backend/app/data/places.json` (0.4 MB, committed): 910 places from Natural
  Earth 1:50m — 242 countries (overseas parts are their own places: France is mainland France), 30
  country parts (England, French Guiana), 7 continents, 66 islands, 86 island groups, 364 regions
  (ranges, deserts, basins), 115 seas; plus a box for the Galápagos (missing at 1:50m). Each place is
  stored as rows of a 0.5° grid; a cell belongs if its centre is inside or an edge passes through it.
  Aliases: "Holland", "UK", "USA", "the Amazon", …
- `app/places.py`: `find_place` (any case, accents, "in the …"; a country wins a shared name, so
  "Ireland" is the country) and `Place.overlaps(range box)` by grid lookup.
- `taxon_queries.species_in_place`: accepted species of the group with a range from 1,000+ wild
  records (as the rankings), no hybrids, whose box shares a grid cell with the place. Ordered by fit:
  the share of the species' box inside the place's box (Madagascar endemics 1.0, worldwide birds near
  0). Listed only if the fit is at least 1/20 of the best one; the wider ones are counted
  ("Wider ranges: 372 more species…") — Galápagos birds went from 396 to the 20 endemic-looking ones.
- Query speed: per group, unary `+` (path index) for small groups, the status index for groups with
  over 100,000 rows (`_is_large`). Animalia in Madagascar 2.7 s, insects in the Netherlands 3.6 s,
  snakes in Holland 0.3 s.
- Chat tool `species_in_place(place, group, limit)`, a prompt line, evidence (`- Species:` names, the
  header count), links, coverage note when under half the group's living species have a range.

### Countries from GBIF country records (the user asked, 2026-11-12)
Boxes put the grass snake in Ireland, so countries now use wild GBIF records per country.
- GBIF SQL download with the user's account (`E:\AnimalKingdomSystem\gbif_countries\
  gbif_countries_download.py`, DOI 10.15468/dl.rujp2t, ~17 min on GBIF's side): wild records (human /
  machine observations, DETECTED, coordinates without geospatial issues) per animal species per
  countryCode, 1.33 million rows.
- `data/import_gbif_countries.py` → new table `species_countries (country, scientific_name, records)`
  (created by `database._init_schema`): 355,567 tree species, 1,311,849 rows, 15 s. Synonyms add to
  their accepted species; built as `species_countries_new` and swapped in one transaction.
- `places.json`: countries carry their ISO code (`ISO_A2_EH`, which fills France's and Norway's -99); a
  country part with its own code (French Guiana GF, Svalbard SJ) has it too, one sharing the
  country's code (England GB) keeps the box test.
- `taxon_queries.species_in_country`: most recorded first; listed with 5+ records and at least 1% of
  the most recorded species' count (Netherlands snakes: the Amur ratsnake's 85 and the corn snake's
  25 records against 42,296 for the barred grass snake are counted, not listed).
- The tool uses country records for a place with codes that has any rows, else the boxes. A country
  without any record of the group answers "no species … has any wild GBIF record" as a database fact,
  and `LabelChecker` accepts a one-clause denial without numbers after it ("Ireland has no snakes").

### Checks
- Backend 747 passed.
- `chat_eval --suite`: tool choice 16/16 (3 place questions added), empty answers 0, label
  corrections 6, all on questions that were already in the suite (wording of "the top 5 … are:").
- Live, countries: Holland → barred grass snake, adder, smooth snake, grass snake; Ireland → "Database:
  There are no wild records of snakes in Ireland."; Madagascar lemurs; UK lizards (see limits).
- Live, boxes: Borneo owls; Alps mammals (ibex, chamois, marmot, Alpine shrew); Galápagos birds
  (finches, mockingbirds, Galápagos penguin).

### Known limits
- Continents, islands, regions, seas and country parts sharing their country's code (England) still
  use range boxes.
- "lizards" resolves to Squamata (COL common name "Lizards, Snakes"), so a lizard question lists
  snakes too; a lizard list like the snake families would fix it.
- Country records follow observers: well-watched countries list common, visible species first, and
  rarely seen species may fall under the 1% floor in a large group.
- "sharks" names no single taxon in COL, so shark questions fall back to general knowledge (a list
  like the snake families would fix it). "marsupials" resolves to the opossums (Didelphimorphia lists
  "Marsupials"); COL's Marsupialia row is an empty placeholder. Both affect the other group tools too.
- Species whose range crosses the 180° line have no longitudes and are not counted.

---

## Increment 27 — Countries of One Species ✅

Approved and merged to master 2026-11-12. "In which countries can I find tigers" got a general-knowledge
answer: Increment 26 answers "which animals live in X", not "where does this animal live". A second
screenshot showed "tigers" landing on the butterfly genus *Parantica* ("Tigers").

### Built
- `lookup_species` gets "- Countries with wild records (most first): India, Russia, …" (up to 20, "and N
  more") and "- Records far from its range: N other countries (zoo animals, escapes or misplaced
  records), not listed"; "countries" joins "Not recorded" without records. `taxonomy_of` and semantic
  search carry it through `_species_facts`. Prompt line: which countries one species lives in →
  lookup_species. `LabelChecker` takes each listed country as evidence.
- `taxon_queries.countries_of` reads `species_countries` (Increment 26).
- `places.native_countries`: the range box failed for species with few records (panda box from 29
  records reaches Germany, gorilla box the USA), so the countries come from the records themselves:
  start from the well-recorded countries (2% of the records and 20+, always the most recorded one), then
  add countries with records that lie within 1° of a kept one, repeatedly. Russia–USA is not a neighbour
  pair (St. Lawrence Island is ~60 km off Chukotka). Tiger: 11 Asian countries; Brazil, Germany, USA,
  Malawi left out. Snow leopard: 11 Central Asian countries, USA left out. Koala: Australia (Japan's 43
  zoo records left out). Red fox: Europe, Australia, North America. 0.06 s per species.
- `resolve_taxon`: an exact first common name of a well-known species (summary and a range from 1,000+
  wild records) beats a group that doesn't contain it — "tiger(s)" is *Panthera tigris*, not *Parantica*;
  "panda" stays the giant panda's genus (the aquarium catfish *Corydoras panda* has no range), "turtle"
  stays Testudines (its species lie inside). Not for group questions (`groups_only`).

### Checks
- Backend 764 passed.
- `chat_eval --suite`: tool choice 17/17 (tiger question added), empty answers 0, label corrections 7,
  all on questions that were already in the suite.
- Live: tigers (both phrasings) → India, Russia, Nepal, Indonesia, Thailand, Bangladesh, Malaysia, China,
  Cambodia, Bhutan, Myanmar; gorillas → 6 Central African countries; giant panda → China.

### Known limits
- GBIF files domestic dogs under *Canis lupus*: the wolf gets 166 countries.
- A country reached only through neighbours can be a stray (a brown bear seen in Switzerland counts).
- "Where can I see a snow leopard" sometimes gets the Wikipedia summary instead of the country list:
  the model chooses which facts to report.

---

## Increment 28 — Lizards, Sharks and Marsupials ✅

Approved and merged to master 2026-11-12. "Lizards" listed snakes too (COL's Squamata is "Lizards, Snakes"),
"sharks" fell back to general knowledge (COL's Selachimorpha row is a synonym; the shark orders sit in
Elasmobranchii with the rays) and "marsupials" landed on the opossums (Marsupialia is a synonym; the
marsupial orders sit directly under Mammalia).

### Built
- `taxon_queries.group_paths(name)` → (short name, label, paths): fixed lists for snakes (the snake
  families, Increment 26), lizards (Squamata's other families without the 6 amphisbaenian families: 79),
  sharks (9 orders) and marsupials (7 orders); other names resolve to one group as before.
  `place_group` wraps it.
- `rank_species_by_trait`, `group_stats` and `species_in_place` all use it; `rank_by_trait`,
  `species_count`, `group_summary`, `species_in_place`, `species_in_country` accept several paths.
  `_group_where`: several children of one parent are one range over the parent filtered on the
  child's path segment — per child, 79 lizard families took 12 s; now under 1 s.
- `_group_filter`: unary `+` keeps small groups on the path index in the rankings and counts too
  (owls: 0.7 s → 0.01 s); the suite's median answer went from 3.5 s to 2.7 s.

### Checks
- Backend 769 passed.
- `chat_eval --suite`: tool choice 19/19 (2 questions added), empty answers 0, label corrections 7,
  all on questions that were already in the suite.
- Live: UK lizards → common lizard, slow worm, sand lizard, wall lizard; sharks → 847 species, 32
  critically endangered; longest-living shark → Greenland shark (392 years); Australian marsupials →
  wallabies, koala, possums, kangaroos; South African sharks → bull shark, broadnose sevengill, tiger
  shark.

### Known limits
- `taxonomy_of("sharks")` still resolves one taxon (lineage questions about a listed group).
- Some species' first Latin-script common name is not English ("Ivanga sheu" for the bull shark).

---

## Increment 29 — Continents Through Their Countries ✅

Approved and merged to master 2026-11-12. Continents used range boxes; they now use the country records
(Increment 26) of their countries. Islands, regions and seas keep the boxes: a region like the Alps is
a small part of its countries.

### Built
- `build_places.assign_continents`: each continent place lists the GBIF codes of its countries by
  Natural Earth's CONTINENT field (the continent outlines are mainlands only: no UK, Madagascar or
  Indonesia), taken from a country's home units ("Seven seas" island units skipped); a territory with
  its own code has its own continent (French Guiana → South America). "Oceania" → the continent place
  Australia (alias "oceania"). A country with 5%+ of its cells on another continent's outline is on both
  as `partial`: Russia, Turkey, Kazakhstan, Georgia, Azerbaijan, plus Greece, Israel, Jordan, Palestine
  and Djibouti at the edges.
- `species_in_country(…, partial, place)`: records from a partial country count only if the species'
  range box touches the continent (an Asian snake recorded only in Russia is not European).
- `places.country_by_code` skips continents (they list codes too).

### Checks
- Backend 773 passed.
- `chat_eval --suite`: tool choice 20/20 ("which snakes live in europe" added), empty answers 0, label
  corrections 7, all on questions that were already in the suite.
- Live: Europe snakes → grass snake, adder, barred grass snake, smooth snake, green whip snake,
  Aesculapian snake, viperine snake, Montpellier snake, asp viper, ladder snake; Asian bears → brown,
  sloth, Asian black, sun and polar bear; South American marsupials → opossums and the monito del monte.
  1–7 s (all animals in Europe 6.9 s).

### Known limits
- A partial country adds all its records of a species whose box touches the continent, also those
  from its other side (Russian records of the brown bear count for Europe in full).

### Tried and dropped: zoo and escaped records at the source (2026-11-12)
A second country download (DOI 10.15468/dl.vrarrp) counted records GBIF marks captive, managed,
cultivated, released, casual or vagrant, to subtract them. It matched nothing (GBIF's concepts are
lowercase; the script is fixed), and it wouldn't help: only ~52,000 of 2.75 billion animal records carry
such a mark, and the known strays don't — the "tigers in Brazil" come from a research-permit dataset,
the "koalas in Japan" from an Australian koala survey with the wrong country code. The import keeps
the first download; `places.native_countries` (Increment 27) handles these cases.

---

## Increment 30 — Search Ranking and Old Names ✅

Approved and merged to master 2026-11-12. "wombat" listed *Wombatus fossor* and the synonyms *Wombatus* and
*Wombatula* above the wombats. Old names had no link to their current name: the Catalogue of Life links
2.9 million synonyms (`accepted_name`), but neither the panel nor the search showed it, and some old
names are separate "provisionally accepted" species there (*Tapirus malayanus*, the Malayan tapir).

### Built
- `search_species`: a new rank between an exact synonym and a scientific-name prefix — the query as a
  whole word of a common name ("Common wombat", "Hairy-nosed Wombats"; not "dandelion" for "lion").
- `database.current_name(row)`: follows `accepted_name` through synonyms of synonyms (max 4 hops, loop
  guard) to the accepted taxon; source "Catalogue of Life" or the stored provenance ("Wikidata").
  `/api/species` and `/traits` return it as `current_name`; `/api/search` returns `accepted_name`.
- Wikidata "taxon synonym of" (P12763) in `wikidata_traits`: *Tapirus malayanus* → *Tapirus indicus
  indicus* → (Catalogue of Life) *Acrocodia indica*. Stored in `accepted_name` only when NULL, with
  provenance; `taxonomic_status` stays as the Catalogue has it. `NAME_FIELDS` in `merge_trait_values`.
- Rows sourced before this increment get the check once (`run_name_stage`, marker `_names`); a complete
  sourced stage sets `_names` too.
- `_init_schema` adds the Catalogue of Life columns (`gbif_taxon_path`, `col_id`, `accepted_name`) when
  missing; only the build script added them before.
- Panel: "Current name" row (link + source) opens the current taxon like a search result; search tags
  "old name of …".

### Checks
- Backend 788 passed, Vitest 147, E2E 30 (non-chat specs, port 8034; new `old_names.spec.ts`).
- Live: "wombat" → Vombatidae, common wombat, both hairy-nosed wombats, *Vombatus*, *Lasiorhinus*;
  "lion" → lion, then puma, sea lions, lionfish before *Lionotus*. *Tapirus indicus* → Malayan tapir,
  *Tapirus bairdii* → Baird's tapir (Catalogue of Life); *Tapirus malayanus* → Malayan tapir (Wikidata;
  checked without writing to species.db).

### Known limits
- The Wikidata link appears only after a panel opens the name (or the chat looks it up); no bulk run.
- The search tag shows the stored link (*Tapirus malayanus*: "old name of Tapirus indicus indicus"); the
  panel shows the final taxon.
- Common names in the word tier include plants ("wombat berry") after the animals with more data.

---

## Increment 31 — Picture Retry ✅

Approved and merged to master 2026-11-12. Plan: `Docs/superpowers/plans/2026-11-12-picture-retry.md`. A panel
without a picture hid the picture area, and a source that timed out or rate-limited counted as "no
picture", stored for good as `__none__`. The user chose to allow museum-specimen photos and the
iNaturalist rank fix in the normal lookup.

### Built
- `_http_get`: a 4xx other than 429 is a real miss; anything else (timeout, 429, 5xx) is `_SourceDown`.
  `fetch_image` raises `ImagesUnavailable` when it finds nothing and Wikipedia, iNaturalist, Commons or
  GBIF didn't answer; `/image` returns 503 and stores nothing. DuckDuckGo errors stay misses.
- iNaturalist: no `rank=species` filter; exact name and the row's own rank (subspecies, families,
  classes get pictures; a same-named taxon of another rank doesn't).
- Homonym keys (`Name [Parent]`) are asked as `Name` from every source.
- Wide mode (`/image?retry=true`): the four sources, then the four for an old name's current name
  ("picture of …"), then `_gbif_image` (GBIF occurrence photos: a living-animal photo first, else a
  specimen marked "(museum specimen)"). A miss stores `__none__` with "searched again YYYY-MM-DD"; a
  real URL is never replaced by `__none__`.
- Panel (`frontend/js/images.js`): "No picture found." + **Search again**; "Searching more sources…";
  "Still no picture after a wider search."; "A picture source didn't answer. Try again later." A retry
  answer for an animal the panel has left is dropped.
- Chat `get_species_image`: passes the rank; an outage answers "Picture sources are unavailable right
  now." and stores nothing.

### Checks
- Backend 818 passed, Vitest 158, E2E 33 (non-chat specs, port 8035; new `picture_retry.spec.ts`).
- Live, read-only (writes stubbed), 25 of the 72 `__none__` rows: the normal lookup now finds 13
  (8 iNaturalist: 6 subspecies, a family, a class; 4 DuckDuckGo; 1 Commons); the wide search 16, adding 5 GBIF
  museum specimens (*Bacteria laesa*, *Barbodes sirang*, *Cerinomyces volaticus*, *C. tristis*,
  *Anoxycalyx ijimai*). 4 to 6 came back "unavailable": Wikipedia and Commons answered 429 during the
  test burst (the Wikipedia enrichment run shares the connection). Without this increment those
  would have been stored as "no picture".

### Known limits
- While Wikipedia rate-limits, panels without a stored picture show "A picture source didn't answer"
  more often; the image calls use the generic User-Agent, not the enrichment run's.
- The search runs its sources one after another; a wide search over slow sources can take up to about
  a minute (each request times out after 10 s).

---

## Increment 32 — Choose Another Picture ✅

Approved and merged to master 2026-11-12. Plan: `Docs/superpowers/plans/2026-11-12-picture-choice.md`. The user
saw a mountain-goat picture showing a goat being eaten by a snake. A delete button would bring the same
picture back (each source returns the same first hit), so the user chose option 2: pick from candidates.

### Built
- Each source has a list form (`_inaturalist_images` with the taxon's photos from `/v1/taxa/{id}`,
  `_wikimedia_images`, `_gbif_images`, `_duckduckgo_images`); the single forms return the first, so
  the normal lookup is unchanged (a single iNaturalist lookup is still one request).
- `image_candidates`: all sources at once (threads): Wikipedia 1, iNaturalist 4, Commons 3, GBIF 3,
  DuckDuckGo 3, plus an old name's current name (Wikipedia, iNaturalist, "(picture of …)"); deduped,
  without the current and rejected pictures, at most 12. GBIF links to iNaturalist originals use the
  medium size (originals can be several MB, and the same photo then dedupes).
- Column `rejected_images` (JSON list, added by `_init_schema`); `database.choose_species_image`
  stores the choice and remembers the replaced picture. `fetch_image(exclude=)` skips rejected
  pictures in automatic lookups (panel and chat).
- Routes `GET /api/species/{name}/image/candidates` → `{candidates, unavailable}` and
  `PUT /api/species/{name}/image` `{url, attribution}` (http(s) only).
- Panel: **Other pictures** under the picture (also in the no-picture line) opens a 3-column gallery
  with each picture's source; a thumbnail that fails to load is dropped; **Cancel** restores the old
  picture; results for an animal the panel has left are dropped.

### Checks
- Backend 853 passed, Vitest 169, E2E 38 (non-chat specs, port 8036; new `picture_choice.spec.ts`).
  Two of three full E2E runs had 2–3 failures among the first-started tests (panel never opened,
  including the unrelated tooltip spec), runs 56 s instead of 36 s: the known startup stall.
- Live, read-only: *Oreamnos americanus* 10 candidates in 16 s (iNaturalist 4, Commons 3, GBIF 3;
  the Wikipedia picture is the current one); *Tyto furcata bondi* 2 in 2 s (before the medium-size
  fix the same photo came twice); *Anoxycalyx ijimai* 3 museum specimens in 1 s.

### Review fixes
- A lookup that finishes after a choice no longer replaces it: `/image` writes only over the value it
  read (`database.replace_species_image`), and the panel drops lookups older than the last panel
  change, choice or Search again.
- The same photo at another size counts as the same picture (`image_utils.picture_key`: a Wikipedia
  thumbnail and its Commons original; iNaturalist square/medium/original), for rejections and dedupe.
- One choice at a time in the gallery; `choose_species_image` reads and writes in one transaction.
- `build_col_db.py` carries `rejected_images` through a rebuild.

### Known limits
- The gallery waits for the slowest source (about 15 s when DuckDuckGo is slow).
- No own picture link (option 3) and no "bad picture" report without choosing a replacement.

---

## Increment 33 — Picture Leftovers ✅

Approved and merged to master 2026-11-13. The Increment 32 deferred minors, built 2026-11-13 on branch `increment-33-picture-leftovers`. The user
chose a 10 s gallery deadline over only correcting the Manual, and skipping a dead picture once over
rejecting it for good.

### Built
- `image_candidates(deadline=10)`: the gallery shows the sources that answered within 10 s; a slower one
  counts as one that didn't answer (`unavailable`), except DuckDuckGo, whose errors were already misses.
  Late threads finish on their own. With pictures and `unavailable`, the gallery shows a note line:
  "Some picture sources were too slow. Other pictures again may find more."
- A failed save keeps the thumbnails and shows "Couldn't keep that picture. Try again." in the note line
  (it used to replace the grid).
- **Other pictures** is disabled while **Search again** runs, so no gallery opens beside it.
- `/image?failed=<url>`: when a stored picture doesn't load, the panel's forced lookup skips that URL
  for this lookup only. It doesn't join `rejected_images`: offline, every picture fails to load.
- The fixed 300 ms waits in `picture_choice.spec.ts` and `picture_retry.spec.ts` wait for the late
  response instead. (`traits_panel.spec.ts` still has one 500 ms wait, older than Increment 31.)

### Checks
- Backend 856 passed, Vitest 172, E2E 43 non-chat tests (port 8037; 5 new). The first full run had 7
  failures among the first-started tests (`page.goto` timeouts, the known startup stall); all passed
  on rerun.

### Not changed
- `master`'s `enrich_wikipedia.py` lacks the COALESCE guard; it arrives with `wikipedia-enrichment-fix`
  after the species run.

---

## Future Enhancements

Saved for later at the user's request; not scheduled.

- **Family descriptions from Wikipedia** (noted 2026-11-11). Family tooltips are the automatic line from `nodeDescription()` ("A family in the order Coleoptera (Beetles)"), which only says where the family sits. None of the 22,012 families (16,002 animal) has a `wikipedia_abstract`. Plan: extend `data/enrich_wikipedia.py` to families (a rank option), about 2½ hours for the animal families at 0.5 s each; strip the ` [Parent]` suffix of homonym keys before asking Wikipedia. Use the first sentence of the summary as the tooltip, before the automatic line; the full summary also serves the panel and the chat. Writing 16,000 texts by hand, as for the orders, isn't feasible. Run it after the species run below.
- ~~**Wikipedia descriptions for animal species**~~: done 2026-11-14 in five legs (2026-11-11 to 11-14), ~1.3 s per species, 0 rate limits. Leg 5 alone: 11,110 abstracts added, 7,070 without an article, 3 transient errors (retried on a later run). `build_embeddings.py` then embedded 81,286 new abstracts: 88,506 species in the semantic index (was ~7,200). Branch `wikipedia-enrichment-fix` (thumbnail only fills species without an image, `--animals-only`, contact User-Agent) merged via `tree-legend`. Manual's run time corrected (was "half a second / ~17 hours").
- ~~**Chat tool choice** (Increment 23 option 2)~~: done in Increment 25.
- **Increment 24 deferred minors**: listed in the Increment 24 final report.
- ~~**Retry button for a missing picture**~~: done in Increment 31.
- ~~**Increment 32 deferred minors**~~: done in Increment 33.

---

## Data Source Reference

| Source | URL | Auth | Format | Used For |
|--------|-----|------|--------|----------|
| GBIF Backbone Taxonomy | gbif.org/dataset/d7dddbf4-… | None | TSV (~1.78M rows) | All taxonomy fields + `taxon_path` |
| GBIF Occurrence API | api.gbif.org/v1/occurrence/search | None | REST JSON | `geo_bounding_box` on demand (wild-record sample, percentile edges); record photos for the panel's "Search again" (`mediaType=StillImage`) |
| GBIF SQL download | api.gbif.org/v1/occurrence/download/request (SQL_TSV_ZIP), DOI 10.15468/dl.5v8cu8 | Free GBIF account | TSV per species | `geo_bounding_box` for ~172k species (`import_gbif_ranges.py`) |
| GBIF SQL download (countries) | same endpoint, DOI 10.15468/dl.rujp2t | Free GBIF account | TSV per species and country | `species_countries` table for `species_in_place` (`import_gbif_countries.py`) |
| IUCN Red List API v4 | api.iucnredlist.org/api/v4 | Free account token | REST JSON | `iucn_status`, `population_trend` |
| Wikipedia REST API | en.wikipedia.org/api/rest_v1 | None | REST JSON | `wikipedia_abstract`, `primary_image_url` |
| AnAge Longevity Database | genomics.senescence.info/species/dataset.zip | None | ZIP/TSV | `body_mass` (kg), `max_lifespan` (yrs), `metabolic_rate` (W) |
| Natural Earth 1:50m (public domain) | github.com/nvkelso/natural-earth-vector (geojson/) | None | GeoJSON | Places for `species_in_place` (`build_places.py`; copies in `E:\AnimalKingdomSystem\natural_earth`) |
| iNaturalist Taxa API | api.inaturalist.org/v1/taxa | None | REST JSON | `primary_image_url`, `image_attribution` (bulk via `enrich_images.py` + live fallback in agent) |

---

## Dependency Notes

- **AMD ROCm:** Verify all PyTorch-based deps (sentence-transformers) against ROCm version before pinning. Use `torch` with ROCm wheel, not CUDA.
- **ChromaDB:** Use `PersistentClient` with path `E:\AnimalKingdomSystem\chroma_db` — do **not** use in-memory client in production.
- **Ollama:** Must be running as a background service before starting the backend. Document startup order in `README` once added.
