# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

An offline-first app cataloguing ~1.8 million animal species, with taxonomy from Catalogue of Life Extended (COL26.10 XR). Core features: an interactive zoomable D3.js taxonomy tree and a local RAG chatbot backed by Ollama (`llama3.1:8b` by default, `AK_CHAT_MODEL` overrides; AMD GPU, Ollama 0.40.16).

**Data lives on a separate NVMe drive:** `E:\AnimalKingdomSystem\` — SQLite DB and ChromaDB vector store go there, not in the repo.

## Tech Stack

| Layer | Technology |
|---|---|
| Backend API | Python 3.12 (venv at `.venv/`) / FastAPI |
| LLM Engine | Ollama (local, AMD ROCm) |
| LLM Orchestration | LangChain / LangGraph |
| Structured DB | SQLite |
| Vector DB | ChromaDB |
| Frontend | HTML5, Tailwind CSS, ES6+ JS |
| Visualization | D3.js (collapsible/zoomable tree or sunburst) |

## Commands

All commands verified 2026-11-03. Ollama must be running for the app and the chat E2E specs.

```bash
# Run the app (from project root) — backend also serves the frontend
start.bat / stop.bat                       # default AK_PORT=8010 → http://localhost:8010
python manage.py start|stop|status         # AK_PORT env var, default 8000; output → backend.log

# Backend dev server (from backend/)
..\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8010

# Backend tests (from backend/)
..\.venv\Scripts\python -m pytest tests/ -v
..\.venv\Scripts\python -m pytest tests/test_database.py::test_search_respects_limit   # single test

# Frontend tests (from frontend/)
npm run test          # Vitest
npm run test:coverage

# E2E tests (from project root; reuses a running backend on AK_PORT, else starts one)
set AK_PORT=8010 && npx playwright test
npx playwright test e2e/taxonomy_tree.spec.ts   # single spec

# Data pipeline (from project root; one-off, resumable)
.venv\Scripts\python data\verify_col_levels.py         # blank orders/families vs independent sources, via Global Names; resumable
.venv\Scripts\python data\build_col_db.py [--target F] # ~6 min; COL trial DB + species_gbif_backup.db -> new species table; never overwrites. Then run the roll-up and fix_common_names on it (SPECIES_DB_PATH), and carry panel data written since the last build
.venv\Scripts\python data\build_embeddings.py          # ~45 s for ~7k abstracts
.venv\Scripts\python data\chat_eval.py [--chat] ["question" ...]  # live chat check with a tool trace; --chat = one conversation; needs Ollama, not the backend
.venv\Scripts\python data\chat_eval.py --suite --model M   # scored model comparison (tool choice, empty answers, label corrections, times); `ollama stop` other models first
.venv\Scripts\python data\enrich_iucn.py --missing-trends
.venv\Scripts\python data\backfill_extinct.py --rollup-only [--dry-run]  # ~20 s, after a COL build; the GBIF species pass needs the backbone, deleted 2026-11-10
.venv\Scripts\python data\batch_extinct_gbif.py [--sample N] # GBIF-era; needs the deleted GBIF backbone, not runnable now
.venv\Scripts\python data\fix_name_collisions.py [--dry-run] # GBIF-era one-off; COL builds use row_score and `Name [Parent]` keys instead
.venv\Scripts\python data\fix_common_names.py [--dry-run]    # seconds, reviewed tree labels for phyla/classes/orders; re-run after an import
.venv\Scripts\python data\build_places.py               # ~5 s; Natural Earth places (E:\AnimalKingdomSystem\natural_earth) -> backend/app/data/places.json for the chat's species_in_place
.venv\Scripts\python data\import_gbif_ranges.py [--dry-run]  # ~15 min; ranges from the GBIF SQL download in E:\AnimalKingdomSystem\gbif_ranges (re-run after a COL build); backup -> gbif_ranges_backup.jsonl
.venv\Scripts\python data\import_gbif_countries.py [--dry-run]  # ~15 s; wild GBIF records per species per country (E:\AnimalKingdomSystem\gbif_countries) -> species_countries table, swapped in
```

Port 8000 is often taken on this machine (a Postgres MCP server), hence the 8010 default in the `.bat` files.

## Architecture

### Directory Layout

```
D:\Claudecode\projects\Animal Kingdom\
├── README.md
├── manage.py                # Service manager behind start.bat / stop.bat
├── Docs/
│   ├── PLAN.md              # Incremental build plan with checkboxes
│   ├── Manual.md            # User manual
│   └── DB_SCHEMA.md
├── backend/
│   ├── app/
│   │   ├── __init__.py      # Sets HF offline flags before any third-party import
│   │   ├── main.py          # FastAPI entry point, route registration, static frontend
│   │   ├── database.py      # SQLite connection + query helpers
│   │   ├── vector_db.py     # ChromaDB embedding handlers
│   │   ├── image_utils.py   # 4-source image lookup chain; wide mode (current name + GBIF photos) for the panel's "Search again"
│   │   ├── trait_utils.py   # On-demand trait sources + sourced/estimate stages
│   │   ├── taxon_queries.py # Group queries for chat: name resolution, rankings, stats, lineage
│   │   ├── taxon_links.py   # Chat name links: subjects of the DB results, matched in the answer
│   │   ├── places.py        # Place names + 0.5° grid cells (data/places.json) for species_in_place
│   │   └── llm_agent.py     # LangChain tools, Ollama config, source-label checker
│   ├── tests/
│   └── requirements.txt
├── frontend/
│   ├── index.html
│   ├── css/style.css
│   ├── js/
│   │   ├── app.js           # Search, species panel, chat (SSE)
│   │   ├── traits.js        # Panel trait rows, est. badge, on-demand loading
│   │   └── visualizer.js    # D3.js tree rendering + zoom logic
│   └── tests/
├── e2e/                     # Playwright E2E tests
└── data/                    # Seed scripts, import utilities
```

### Key Data Flows

**Taxonomy zoom:** `GET /api/taxonomy/zoom?node_id=X` → SQLite children query → nested JSON → D3.js re-render.

**Chat:** user query → FastAPI `POST /api/chat` → LangGraph ReAct agent on Ollama → tools `lookup_species` (SQLite; includes the countries the species lives in, `places.native_countries` over `species_countries`), `find_species` (common → scientific name), `rank_species_by_trait` (lifespan / mass / length / northern or southern range edge), `group_stats` (counts, IUCN, trends), `taxonomy_of` (lineage, members, relatives), `species_in_place` (a country or continent: species with wild GBIF records there, table `species_countries`; continents list their countries in `places.json`; other places: species whose GBIF range overlaps the continent / island / region / sea, `places.py`; snakes / lizards / sharks / marsupials are fixed family or order lists, `taxon_queries.group_paths`, also used by the ranking and stats tools), `semantic_search_species` (ChromaDB), `get_species_image` (DB → 4-source fallback) → streamed SSE tokens + image payload + a `links` event before `done` (the subjects of the shown attempt's database results where the answer names them, plus exact scientific names of any species in the tree, `taxon_links.py`; the browser wraps them in `a.taxon-link`, opened via `openTaxon` like a search result). Memory: the browser sends the last 6 messages as `history` (`frontend/js/chat.js`); the server keeps no state. Group SQL lives in `taxon_queries.py`: accepted species in the tree only, descendants by a `taxon_path` range (not `LIKE`). Every "Database:" sentence is verified against the output of the database tools (`_EVIDENCE_TOOLS`) by `LabelChecker` and relabelled "From general knowledge:" if unsupported; a sentence denying what a ranking just showed ("no turtles over 100 years") is replaced with the ranked count ; an answer written without any tool call is dropped and asked once more with a nudge; a "lowest" ranking covering under half its group gets a coverage sentence appended ("Only 3,612 of 1,800,133 species … have a recorded body mass") — don't rely on the prompt alone for source labels.

**Traits (on demand):** panel opens species → `GET /api/species/{name}/traits?stage=sourced` (IUCN / GBIF / Wikidata / Wikipedia, concurrent, 8 s deadline) → then `stage=estimated` (local LLM reads the abstract; values must be grounded in the text) → write-through to SQLite with provenance in `trait_sources`. Chat's `lookup_species` runs the sourced stage only. Labels: `Database:`, `Database (estimated):`, `From general knowledge:`. Logic in `trait_utils.py` / `frontend/js/traits.js`.

### SQLite Schema (20 fields per species + `trait_sources`, `rejected_images`)

Primary key: `scientific_name` (TEXT). Fields grouped by concern:

- **Taxonomy/UI:** `taxon_path` (pipe-delimited lineage), `taxon_rank`, `common_names` (JSON), `taxonomic_status` (ACCEPTED|SYNONYM)
- **Physical:** `body_mass` (kg), `body_length` (m), `max_lifespan` (years), `metabolic_rate`, `reproduction_strategy`
- **Ecology:** `geo_bounding_box` (JSON lat/lon), `habitat_type`, `elevation_limits`, `trophic_level`, `activity_period`
- **Conservation/Media:** `iucn_status` (LC/VU/EN/CR/EW/EX), `extinct` (1/0/NULL; bulk 1s from `backfill_extinct.py` — PBDB-sourced species + all-extinct groups; per-species from GBIF profiles on first panel open; drives the tree's † and "Hide extinct"), `population_trend`, `primary_image_url` (`__none__` = all sources answered and none had a picture; a failed "Search again" stores `image_attribution` "searched again YYYY-MM-DD"; a source that didn't answer stores nothing, `/image` returns 503), `image_attribution`, `rejected_images` (JSON list of picture URLs the user replaced via "Other pictures"; `fetch_image` and `image_candidates` skip them; `GET /api/species/{name}/image/candidates`, `PUT /api/species/{name}/image`), `wikipedia_abstract`
- **Catalogue of Life:** `col_id`, `accepted_name` (synonyms; also set on an ACCEPTED row from Wikidata's "taxon synonym of", provenance in `trait_sources`; `database.current_name` follows the chain to the accepted taxon for the panel's "Current name" link), `gbif_taxon_path` (old path of rows COL lacks). `taxonomic_status` also has GBIF_ONLY: kept in the DB, searchable, `taxon_path` NULL, not in the tree. `taxon_path` may be NULL, so guard it. `scientific_name` is the row key: a homonym is `Name [Parent]`, and tree nodes expose it as `scientific_name` next to the plain `name`. Applied fixes are in the `taxon_fixes` table. The pre-switch DB is `species_gbif_backup.db`. IUCN status EX always sets `extinct` = 1.
- **Country records:** table `species_countries (country, scientific_name, records)`, wild GBIF records per ISO alpha-2 country (`import_gbif_countries.py`)
- **Trait provenance:** `trait_sources` (JSON `{field: {source, estimated}}` + `_sourced` / `_estimated` / `_names` stage-date markers; `_names` = the Wikidata old-name check, part of the sourced stage, run once on its own for rows sourced before it) — read/write only via `database.parse_trait_sources` / `update_species_traits`

## Project Workflow

1. Build increments tracked in `Docs/PLAN.md` — check off only after the increment is tested and user-approved.
2. After each approved increment: update `PLAN.md` with decisions made, then commit to Git.
3. Always verify the backend is running and reachable before marking a frontend-dependent task done.

## Testing Strategy

- **Backend:** pytest + FastAPI TestClient — store under `backend/tests/`
- **Frontend:** Vitest + Testing Library — store under `frontend/tests/`
- **E2E:** Playwright — store under `e2e/`
- Target 80% functional coverage per layer.

## Coding Standards

- Use the latest stable library versions; check PyPI/npm for version compatibility before pinning.
- Verify AMD ROCm compatibility for any ML/inference dependency before adopting it.
- `common_names` and `geo_bounding_box` are JSON strings stored in SQLite TEXT columns — always parse/serialize consistently via helper functions in `database.py`.
- LangChain tool definitions live in `llm_agent.py`; FastAPI routes stay thin and delegate to that layer for all LLM interactions.
- Frontend API base is the page origin — never hardcode a port in `frontend/js/`.
- Keep `HF_HUB_OFFLINE`/`TRANSFORMERS_OFFLINE` in `backend/app/__init__.py`: `langchain_core` imports `huggingface_hub`, which reads them once at import.
- IUCN API v4 `population_trend` codes: 0=Increasing, 1=Decreasing, 2=Stable, 3=Unknown. Prefer the response's `description.en` label. The API works with TLS verification on — don't use `--no-verify-ssl`.