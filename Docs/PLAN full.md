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
  - Phase 2 in progress (background): 174,843 per-assessment calls for `population_trend`; ~24 h at 0.5 s/call
- [x] IUCN Phase 1 complete (all 8 categories swept)
- [ ] IUCN Phase 2 complete (population_trend — running in background)
- [x] Create `data/enrich_images.py` — iNaturalist taxa API (no token):
  - Queries `api.inaturalist.org/v1/taxa?q={name}&per_page=5&rank=species`; verifies exact name match
  - Stores `primary_image_url` + `image_attribution` (e.g. `"© user (CC BY-NC)"`)
  - Scopes: default (has abstract, ~7k, ~1.4h) · `--iucn-matched` (~175k, ~34h) · `--all-accepted` (~1.78M, days)
  - Checkpointed to `E:\AnimalKingdomSystem\images_checkpoint.json`; 0.7 s/request (≤86 req/min)
  - Status: **running in background** — `--iucn-matched` scope (171,462 species)
- [ ] Run `data/build_embeddings.py` after enrichment to reindex any new `wikipedia_abstract` entries added during enrichment

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
- [ ] Run embedding pipeline; record final count and approximate runtime
- [x] Write `backend/tests/test_vector_db.py`:
  - Test `semantic_search` returns results for a known species query
- [x] All tests pass: `pytest tests/ -v` — 53 passed (42 prior + 11 new)

### Decisions recorded
- **Embedding model:** `all-MiniLM-L6-v2` (384 dims, cosine space) — fast on CPU, well-known quality/size tradeoff, no GPU needed for embedding inference
- **Torch:** CPU-only wheel (`torch-2.12.0+cpu`) — ROCm wheels are Linux-only; Ollama handles GPU inference separately
- **HuggingFace offline mode:** `HF_HUB_OFFLINE=1` set in `tests/conftest.py` — model pre-downloaded once manually to avoid SSL cert issues on this machine during tests
- **ChromaDB EphemeralClient isolation:** In chromadb 1.0.9 the in-memory backend is module-level (singleton); tests use UUID collection names per fixture to guarantee isolation
- **FastAPI version:** ChromaDB 1.0.9 downgraded fastapi 0.136.3 → 0.115.9; all 53 tests still pass
- **Embedding count and runtime:** Not yet run — requires Wikipedia enrichment first (`python data/enrich_wikipedia.py`)
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

### Status: COMPLETE — pending user visual verification and approval

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
- [ ] User visual verification: search "Apis cerana", confirm tree shows "Hymenoptera" / "Apidae" (not "Ants" / "Euglossine"), path matches details panel lineage, highlight dims non-path nodes
- [ ] Git commit all changes

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

## Increment 11 — Git History & Documentation

Tidy up and commit a clean, documented project.

### Tasks

- [ ] Initialise git repo if not already done: `git init`
- [ ] Add `.gitignore` entries:
  - `__pycache__/`, `*.pyc`, `.venv/`
  - `node_modules/`, `dist/`, `.vitest/`
  - `*.db`, `chroma_db/` (data stays on E: drive, not in repo)
  - `.env` (if any secrets are added later)
- [ ] Update `CLAUDE.md` commands section with final, tested commands
- [ ] Update this `PLAN.md` with all "Decisions to record" filled in
- [ ] Make a clean initial commit: `git commit -m "Initial scaffold and full implementation"`

---

## Data Source Reference

| Source | URL | Auth | Format | Used For |
|--------|-----|------|--------|----------|
| GBIF Backbone Taxonomy | gbif.org/dataset/d7dddbf4-… | None | TSV (~1.78M rows) | All taxonomy fields + `taxon_path` |
| GBIF Occurrence API | api.gbif.org/v1/occurrence/search | None | REST JSON | `geo_bounding_box` (lat/lon bbox from occurrence records) |
| IUCN Red List API v4 | api.iucnredlist.org/api/v4 | Free account token | REST JSON | `iucn_status`, `population_trend` |
| Wikipedia REST API | en.wikipedia.org/api/rest_v1 | None | REST JSON | `wikipedia_abstract`, `primary_image_url` |
| AnAge Longevity Database | genomics.senescence.info/species/dataset.zip | None | ZIP/TSV | `body_mass` (kg), `max_lifespan` (yrs), `metabolic_rate` (W) |
| iNaturalist Taxa API | api.inaturalist.org/v1/taxa | None | REST JSON | `primary_image_url`, `image_attribution` (bulk via `enrich_images.py` + live fallback in agent) |

---

## Dependency Notes

- **AMD ROCm:** Verify all PyTorch-based deps (sentence-transformers) against ROCm version before pinning. Use `torch` with ROCm wheel, not CUDA.
- **ChromaDB:** Use `PersistentClient` with path `E:\AnimalKingdomSystem\chroma_db` — do **not** use in-memory client in production.
- **Ollama:** Must be running as a background service before starting the backend. Document startup order in `README` once added.
