# Dynamic Trait Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a species or subspecies is opened, fetch its missing traits live (IUCN → GBIF → Wikidata → Wikipedia, then an LLM estimate from the description), store them with per-field provenance, show them in the panel with source-on-hover and an "est." badge, and let chat use them with a `Database (estimated):` label.

**Architecture:** A new `backend/app/trait_utils.py` owns two stages: `run_sourced_stage` (concurrent online lookups) and `run_estimate_stage` (one Ollama JSON call over the abstract). `database.py` stores values in the existing columns plus a new `trait_sources` JSON column holding provenance and the `_sourced` / `_estimated` stage markers. A new `GET /api/species/{name}/traits?stage=` endpoint runs one stage; the panel calls it twice (sourced, then estimated). Chat's `lookup_species` runs only the sourced stage.

**Tech Stack:** Python 3.12, FastAPI, SQLite, urllib (stdlib HTTP, as in `image_utils.py`), `concurrent.futures`, `langchain_ollama.ChatOllama` (`format="json"`), Wikidata SPARQL, IUCN API v4, GBIF API v1, Vitest.

**Spec:** `Docs/superpowers/specs/2026-11-03-dynamic-trait-retrieval-design.md`

**Testing depth:** extended per user request. See **Risk Analysis** (R1–R15). Every risk maps to named tests in the owning task, marked *Risk tests*.

## Global Constraints

- Only `taxon_rank` in `{"species", "subspecies"}` ever triggers fetching.
- Never overwrite a non-NULL value, **except** an estimated value may be replaced by a sourced one.
- A stage marker (`_sourced` / `_estimated`, ISO date) is written only if every source in that stage *answered* (HTTP 200 or 404). Timeout, connection error, HTTP 429 or 5xx, or Ollama unreachable → no marker.
- No estimate without a `wikipedia_abstract`; the estimate stage then sets `_estimated` (skipped counts as done). Numeric estimates only when the figure appears in the abstract text.
- Exact source labels: `"IUCN Red List"`, `"GBIF"`, `"GBIF occurrences"`, `"Wikidata"`, `"Wikipedia"`, `"AnAge"`, `"Estimated from Wikipedia description"`.
- Imported values with no provenance entry: `body_mass`, `max_lifespan`, `metabolic_rate` → `"AnAge"`; `iucn_status`, `population_trend` → `"IUCN Red List"`; `geo_bounding_box` → `"GBIF occurrences"`; `wikipedia_abstract` → `"Wikipedia"`.
- Units stored: `body_mass` kg, `body_length` m, `max_lifespan` years. Multiple Wikidata values → keep the largest after conversion. Unconvertible units are dropped.
- IUCN: token from env `IUCN_API_TOKEN` or project-root `.env`; TLS verification ON; trend codes 0=Increasing, 1=Decreasing, 2=Stable, 3=Unknown, prefer `description.en`.
- Chat labels: `Database:`, `Database (estimated):`, `From general knowledge:`.
- `/traits` route registered **before** `/api/species/{scientific_name}` in `main.py`.
- Per-request network timeout 10 s; sourced stage wall-clock target ≤ ~3 s typical.
- Tests: `..\.venv\Scripts\python -m pytest tests/ -v` (from `backend/`), `npm run test` (from `frontend/`). No real network in unit tests.

## Review Focus

1. **Untrusted text in the panel** — Wikidata/IUCN/GBIF/LLM strings containing `<`, `"` or `&` must render as text, not HTML (Task 9: `escapeHtml` test with `<img onerror>`).
2. **Fast species switching** — a `/traits` response for species A arriving after the panel shows B must not render into B (Task 9: stale-response guard test).
3. **Offline / a source down** — no stage marker written, no error toast, stored record still shown; the next open retries (Task 5: `SourceUnavailable` → `complete=False`; Task 7: endpoint test with a failing source).
4. **Names needing URL encoding** — subspecies with spaces, hybrids with `×`, apostrophes (Task 2: `_get_json` called with encoded URL; Task 9: `encodeURIComponent` in fetch URL test).
5. **Two writers for one species** (panel + chat at the same time) — an estimate arriving after a sourced value must not overwrite it (Task 1: `update_species_traits` estimated-after-sourced test).

## Risk Analysis

Where this increment can realistically go wrong, ranked by **impact × likelihood**. Stored values persist and are reused by chat, so **a wrong value stored is worse than a missing one**. Each risk lists its mitigation and the tests (ID → task) that pin it.

| ID | Risk | Impact | Likelihood | Mitigation | Tests |
|---|---|---|---|---|---|
| R1 | **Wrong taxon matched.** The Wikidata P225 name belongs to a plant/fungus homonym, GBIF `match` falls back to the genus (`matchType: HIGHERRANK`) or another kingdom, or a Wikipedia title redirects to the genus or a different subject. Values for the wrong organism get stored. | High | Medium | Wikidata: require exactly one item with P225 = name and P105 (taxon rank) matching the row's rank, else skip. GBIF: require `matchType` `EXACT`, `rank` equal to the row's rank, `kingdom` equal to the row's kingdom. Wikipedia: accept only if the extract mentions the scientific name or a stored common name. | T2-r1, T4-r1..r3 |
| R2 | **Unit or magnitude errors.** A value is labelled kilogram but is really grams; pounds or tonnes are converted wrongly. Absurd values get stored. | High | Medium | Plausibility bounds after conversion (`PLAUSIBLE_RANGES`); reject values outside them. | T2-r2, T2-r3, T6-r2 |
| R3 | **LLM misreads the text.** A number from another context ("described in 1804") is taken as a trait; injection-like text in an abstract; placeholder answers ("unknown", "not stated"). | High | Medium | A number must appear in the abstract followed within 3 words by a unit word of the right dimension. Bounds as in R2. Free text ≤ `FREE_TEXT_MAX`; `PLACEHOLDER_VALUES` dropped. Fields already filled → ignored. | T6-r1..r5 |
| R4 | **The panel hangs or is slow.** IUCN (2 calls) and GBIF (3 calls) run sequentially inside one source, so worst case 10 s × 3 per source. | Medium | High | Overall `STAGE_DEADLINE_S` for the sourced stage; sources still running at the deadline are abandoned and the stage counts as incomplete. Estimate: `ESTIMATE_TIMEOUT_S`. Frontend: abort `/traits` after `TRAITS_FETCH_TIMEOUT_MS` and remove the loading line. | T5-r1, T6-r6, T9-r3 |
| R5 | **Retry storms or permanent gaps.** A misclassified error either retries forever (401 from a bad token, every open) or freezes a gap (a timeout marked as done). | Medium | Medium | 401/403 → `SourceUnavailable` (no marker), with a warning logged once per process. 404 and an empty result → answered. A stale checkpoint assessment ID (404) → fall back to the taxa lookup. | T2-r4, T3-r1, T3-r3 |
| R6 | **Concurrent writes** (panel + chat, or two tabs) read-modify-write the `trait_sources` JSON and lose provenance entries. | Medium | Low | `update_species_traits` uses `BEGIN IMMEDIATE`, then reads, merges and writes in one transaction. | T1-r1 |
| R7 | **Subspecies inherit species data.** IUCN or Wikidata return the parent species' record for a subspecies row. | Medium | Medium | IUCN taxa lookup for a subspecies must match `infra_name`; Wikidata rank check (R1). No fallback to the species. | T3-r2 |
| R8 | **Label parsing with the new label.** `Database (estimated):` is mis-parsed (prefix overlap with `Database`), casing/spacing variants slip through, or a number in both sourced and estimated lines is classified wrongly. | Medium | Medium | Match labels case-insensitively with optional whitespace: `^database\s*\(estimated\)\s*:` before `^database\s*:`. A value present in sourced evidence → sourced. | T8-r1..r3 |
| R9 | **Migration under load.** `ALTER TABLE` while the IUCN script holds the write lock; `_init_schema` runs on every connection. | Low | Medium | Idempotent check before ALTER (already the pattern). Run the backend once before starting long writers (Task 10). | T1-r2 |
| R10 | **Corrupt or legacy `trait_sources`** (hand-edited, partial JSON) crash the panel and chat. | Medium | Low | `parse_trait_sources` returns `{}` on bad JSON or a non-dict. | T1-r3, T7-r2 |
| R11 | **Display formatting.** Tiny masses shown as `1e-7`, long floats `0.17582…`, quotes in values breaking the `title` attribute. | Low | High | `formatTraitValue`: 3 significant figures, no exponent notation; escape attribute values. | T9-r1, T9-r2 |
| R12 | **The panel closes or switches mid-load** → writes into a removed or other species' DOM, or the loading line sticks. | Low | Medium | Guard every async step on the current species, and null-check panel elements. | T9-r4 (+ Review Focus 2) |
| R13 | **API shape drift.** IUCN, GBIF or Wikidata change response fields, mocks stay green, and production silently returns nothing. | Medium | Low | Opt-in live smoke tests (`pytest -m live`) for 4 known species, run in Task 10, skipped by default. | T10-r1 |
| R14 | **Regressions in existing behavior.** The panel row order and labels change; image loading breaks; chat/label tests regress. | Medium | Low | A snapshot of rendered rows for a stored-only record; the full suites; a route-mocked Playwright spec. | T9-r5, T10-r2 |
| R15 | **Tests accidentally hit the network** and become slow or flaky. | Low | Medium | An autouse fixture in `test_trait_utils.py` makes `urllib.request.urlopen` and the Ollama client raise if not patched. | T2-r5 |

New constants introduced by mitigations (implementers use these exact names and values):
- in `trait_utils.py`:
  - `PLAUSIBLE_RANGES = {"body_mass": (1e-9, 2e5), "body_length": (1e-5, 40.0), "max_lifespan": (0.01, 600.0)}`
  - `STAGE_DEADLINE_S = 8`
  - `ESTIMATE_TIMEOUT_S = 60`
  - `PLACEHOLDER_VALUES = {"unknown", "not stated", "not mentioned", "n/a", "none", ""}`
  - `FREE_TEXT_MAX = 120`
- in `traits.js`: `TRAITS_FETCH_TIMEOUT_MS = 30000`

---

## File Map

| File | Change |
|---|---|
| `backend/app/database.py` | **Modify** — `trait_sources` column, `TraitValue`, `parse/serialize_trait_sources`, `update_species_traits`, `trait_provenance` |
| `backend/app/trait_utils.py` | **Create** — HTTP helper, unit conversion, IUCN/GBIF/Wikidata/Wikipedia sources, two stages |
| `backend/app/main.py` | **Modify** — `SpeciesRecord` provenance fields, `TraitsResponse`, `/traits` endpoint |
| `backend/app/llm_agent.py` | **Modify** — `lookup_species` runs sourced stage and tags estimates; prompt; `LabelChecker` three labels |
| `frontend/js/traits.js` | **Create** — pure trait-row rendering, `escapeHtml`, `nextTraitStage` |
| `frontend/js/app.js` | **Modify** — use `traits.js`; load traits after first render |
| `backend/tests/test_database.py`, `test_trait_utils.py` (new), `test_taxonomy_api.py`, `test_llm_agent.py` | tests |
| `frontend/tests/traits.test.js` | **Create** |
| `Docs/PLAN.md`, `CLAUDE.md` | Increment 12 section; schema note |

---

### Task 1: Storage — `trait_sources` column and helpers

**Files:**
- Modify: `backend/app/database.py` (`_init_schema` ~line 64; helpers after `update_species_image` ~line 329)
- Test: `backend/tests/test_database.py`

**Interfaces:**
- Produces:
  - `class TraitValue(NamedTuple): value: float | str | dict; source: str; estimated: bool = False`
  - `TRAIT_FIELDS: tuple[str, ...] = ("habitat_type", "elevation_limits", "body_mass", "body_length", "max_lifespan", "trophic_level", "activity_period", "reproduction_strategy", "iucn_status", "population_trend", "geo_bounding_box", "wikipedia_abstract")`
  - `parse_trait_sources(json_str: str | None) -> dict` / `serialize_trait_sources(d: dict) -> str`
  - `update_species_traits(scientific_name: str, values: dict[str, TraitValue], stage: Literal["sourced", "estimated"], completed: bool) -> None`
  - `trait_provenance(row: dict) -> dict[str, dict]` — `{field: {"source": str, "estimated": bool}}` for every non-NULL trait/imported field, using the imported defaults from Global Constraints when no entry exists.

- [ ] **Step 1: Write failing tests** in `test_database.py`:
  - `test_schema_has_trait_sources_column` — `"trait_sources"` in `PRAGMA table_info(species)`.
  - `test_update_traits_fills_null_and_records_source` — insert row; `update_species_traits("X", {"habitat_type": TraitValue("Grassland", "IUCN Red List")}, "sourced", True)`; row `habitat_type == "Grassland"`; `parse_trait_sources(...)["habitat_type"] == {"source": "IUCN Red List", "estimated": False}`; `"_sourced"` key present.
  - `test_update_traits_never_overwrites_sourced` — row with `body_mass=3.9`; update with `TraitValue(5.0, "Wikidata")` → still `3.9`.
  - `test_estimate_never_overwrites_sourced_value` (Review Focus 5) — sourced `habitat_type` stored, then estimated stage writes `TraitValue("Forest", "Estimated from Wikipedia description", True)` → unchanged.
  - `test_sourced_replaces_estimated_value` — estimated `activity_period="nocturnal"` stored; sourced update `"diurnal"` → replaced, provenance `estimated False`.
  - `test_incomplete_stage_sets_no_marker` — `completed=False` → values written, no `_sourced` key.
  - `test_provenance_defaults_for_imported_values` — row with `body_mass=3.9, iucn_status="VU"`, no `trait_sources` → `{"body_mass": {"source": "AnAge", "estimated": False}, "iucn_status": {"source": "IUCN Red List", ...}}`.
  - *Risk tests:*
    - `test_concurrent_trait_updates_keep_all_provenance` (T1-r1, R6) — 8 threads each call `update_species_traits` with a different field on the same row → all 8 provenance keys present, all 8 values stored.
    - `test_init_schema_idempotent` (T1-r2, R9) — `get_connection()` twice on a DB that already has `trait_sources` → no error, column present once.
    - `test_parse_trait_sources_tolerates_garbage` (T1-r3, R10) — `"{not json"`, `"[1,2]"`, `None` → `{}`; `trait_provenance` on such a row still returns the imported defaults.

- [ ] **Step 2: Run** `..\.venv\Scripts\python -m pytest tests/test_database.py -v` — Expected: new tests FAIL.
- [ ] **Step 3: Implement.** Add `trait_sources` to `_init_schema` via the same `PRAGMA table_info` / `ALTER TABLE ADD COLUMN` pattern used for `taxon_depth` (no backfill). `update_species_traits` reads the row's current values + `trait_sources` in one transaction, writes a field only if NULL or currently `estimated` and the new value is not estimated, merges provenance, sets `"_" + stage` to `date.today().isoformat()` when `completed`. Serialize `geo_bounding_box` dicts with the existing `serialize_geo_bbox`.
- [ ] **Step 4: Run** the same command — Expected: all PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat: trait_sources column and update_species_traits write-through helper"`

---

### Task 2: `trait_utils` foundation — HTTP, units, Wikidata

**Files:**
- Create: `backend/app/trait_utils.py`
- Test: `backend/tests/test_trait_utils.py` (create)

**Interfaces:**
- Consumes: `database.TraitValue`
- Produces:
  - `class SourceUnavailable(Exception)` — raised for timeout, connection error, HTTP 429, HTTP ≥ 500.
  - `_get_json(url: str, headers: dict | None = None, params: dict | None = None) -> dict | None` — returns parsed JSON; `None` on HTTP 404; raises `SourceUnavailable` otherwise on failure. Encodes `params` with `urllib.parse.urlencode`. 10 s timeout, User-Agent `"AnimalKingdomApp/1.0 (educational offline project)"`.
  - `to_kg(amount: float, unit: str) -> float | None`, `to_m(...)`, `to_years(...)` — unit is an English label, case-insensitive: mass `kilogram, gram, milligram, tonne, pound, ounce`; length `metre, centimetre, millimetre, kilometre, inch, foot`; time `year, annum, month, week, day`. Unknown → `None`.
  - `wikidata_traits(name: str) -> dict[str, TraitValue]` — keys among `body_mass`, `body_length`, `max_lifespan`; source `"Wikidata"`.

- [ ] **Step 1: Write failing tests:**
  - `test_to_kg_converts_ounce` — `to_kg(6.2, "ounce") == pytest.approx(0.1758, rel=1e-3)`; `to_kg(1, "Gram") == 0.001`; `to_kg(1, "furlong") is None`.
  - `test_to_m_and_to_years` — `to_m(30, "centimetre") == 0.3`; `to_years(6, "month") == 0.5`; `to_years(730, "day") == pytest.approx(2.0, rel=1e-2)`.
  - `test_get_json_404_returns_none` / `test_get_json_429_raises` / `test_get_json_timeout_raises` — patch `urllib.request.urlopen`.
  - `test_get_json_encodes_params` (Review Focus 4) — `params={"q": "Apis cerana × mellifera"}` → requested URL contains `Apis+cerana+%C3%97+mellifera`.
  - `test_wikidata_takes_largest_converted_value` — patch `_get_json` to return SPARQL bindings for mass `(1.65, "kilogram"), (126, "kilogram"), (188, "kilogram")` → `{"body_mass": TraitValue(188.0, "Wikidata")}`.
  - `test_wikidata_drops_unconvertible_units` — mass `(5, "stone-age-unit")` only → `{}`.
  - *Risk tests:*
    - `test_wikidata_skips_ambiguous_or_wrong_rank_items` (T2-r1, R1) — two items for the name, or one item whose P105 is genus for a species row → `{}`.
    - `test_wikidata_rejects_implausible_values` (T2-r2, R2) — mass `(188000, "tonne")` and length `(500, "metre")` → no keys; a boundary value of exactly 2e5 kg is kept.
    - `test_unit_conversions_pound_tonne_inch_foot_week` (T2-r3, R2) — `to_kg(2, "pound") ≈ 0.907`, `to_kg(1.5, "tonne") == 1500`, `to_m(12, "inch") ≈ 0.3048`, `to_m(1, "foot") ≈ 0.3048`, `to_years(52, "week") ≈ 1.0`.
    - `test_get_json_401_raises_and_logs_once` (T2-r4, R5) — two 401s → `SourceUnavailable` both times, a single warning in `caplog`.
    - `test_sparql_name_is_escaped` (T2-r1) — a name containing `"` and `\` → both escaped in the query string, no unescaped quote.
    - Autouse fixture `_no_network` (T2-r5, R15) — patches `urllib.request.urlopen` to raise `AssertionError("network in unit test")`; tests that need it patch it explicitly.
- [ ] **Step 2: Run** `..\.venv\Scripts\python -m pytest tests/test_trait_utils.py -v` — Expected: FAIL (module missing).
- [ ] **Step 3: Implement.** Wikidata: one SPARQL `GET https://query.wikidata.org/sparql` with `Accept: application/sparql-results+json`, matching `?item wdt:P225 "<name>"` and, per property, `p:Pxxxx/psv:Pxxxx [wikibase:quantityAmount ?amt; wikibase:quantityUnit ?unit]` with English `?unitLabel` (properties: P2067 mass, P2043 length, P2250 life expectancy). Escape `"` and `\` in the name before embedding.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat: trait_utils HTTP helper, unit conversion, Wikidata source"`

---

### Task 3: IUCN source

**Files:**
- Modify: `backend/app/trait_utils.py`
- Test: `backend/tests/test_trait_utils.py`

**Interfaces:**
- Produces: `iucn_traits(name: str, row: dict) -> dict[str, TraitValue]` — keys among `habitat_type`, `elevation_limits`, and (only if NULL in `row`) `iucn_status`, `population_trend`; source `"IUCN Red List"`. Returns `{}` with no token or no assessment.

- [ ] **Step 1: Write failing tests** (patch `_get_json` and the assessment-ID lookup):
  - `test_iucn_habitat_prefers_major_importance` — habitats `[{"majorImportance": "Yes", "suitability": "Suitable", "description": {"en": "Grassland - Subtropical/Tropical Dry"}}, {"majorImportance": None, "suitability": "Marginal", "description": {"en": "Shrubland"}}]` → `habitat_type == "Grassland - Subtropical/Tropical Dry"`.
  - `test_iucn_habitat_falls_back_to_suitable` — no `"Yes"` → joins `suitability == "Suitable"` descriptions with `"; "`.
  - `test_iucn_elevation_and_depth_format` — `upper_elevation_limit 4200, lower 0` → `"0–4,200 m"`; depth `lower 200, upper 0`, no elevation → `"depth 0–200 m"`; both → `"0–4,200 m; depth 0–200 m"`.
  - `test_iucn_status_only_when_missing` — row with `iucn_status="VU"` → no `iucn_status` key; row with NULL → `iucn_status` from `red_list_category.code`, `population_trend` from `description.en`.
  - `test_iucn_without_token_returns_empty`.
  - *Risk tests:*
    - `test_iucn_stale_checkpoint_id_falls_back_to_taxa_lookup` (T3-r1, R5) — assessment ID from the checkpoint → 404; the taxa lookup gives a new ID → its habitats are used.
    - `test_iucn_subspecies_requires_infra_match` (T3-r2, R7) — subspecies row; the taxa response holds only the species-level assessment → `{}`.
    - `test_iucn_answered_without_data_is_not_an_error` (T3-r3, R5) — the taxa lookup returns no assessments → `{}`, no exception (so the stage can complete).
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement.** Assessment ID: from the `matched` map in `E:\AnimalKingdomSystem\iucn_checkpoint.json` (load once, cache module-level; path overridable via `IUCN_CHECKPOINT_PATH` env); else `GET https://api.iucnredlist.org/api/v4/taxa/scientific_name` with `genus_name`, `species_name` (and `infra_name` for subspecies), taking the assessment with `latest: true`. Verify that taxa-endpoint response shape with one live call before finalising the parser. Then `GET /api/v4/assessment/{id}` with header `Authorization: <token>`.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat: IUCN habitat, elevation and status trait source"`

---

### Task 4: GBIF and Wikipedia sources

**Files:**
- Modify: `backend/app/trait_utils.py`
- Test: `backend/tests/test_trait_utils.py`

**Interfaces:**
- Produces:
  - `gbif_traits(name: str, row: dict) -> dict[str, TraitValue]` — `habitat_type` (source `"GBIF"`) and, if NULL in `row`, `geo_bounding_box` (source `"GBIF occurrences"`, dict `{lat_min, lat_max, lon_min, lon_max}`).
  - `wikipedia_abstract(name: str) -> dict[str, TraitValue]` — `{"wikipedia_abstract": TraitValue(text, "Wikipedia")}` or `{}`.

- [ ] **Step 1: Write failing tests:**
  - `test_gbif_rejects_low_confidence_match` — `species/match` confidence 80 → `{}`.
  - `test_gbif_habitat_normalised` — profiles `[{"habitat": "TERRESTRE"}, {"habitat": "Terrestrial"}, {"habitat": "marine"}]` → `habitat_type == "Terrestrial, Marine"` (known English values `terrestrial, marine, freshwater, brackish`, title-cased, de-duplicated, first-seen order; non-English values ignored).
  - `test_gbif_bbox_from_occurrences` — occurrences with lat/lon → min/max dict.
  - `test_wikipedia_disambiguation_returns_empty` — `{"type": "disambiguation"}` → `{}`.
  - *Risk tests:*
    - `test_gbif_rejects_higher_rank_match` (T4-r1, R1) — `matchType: "HIGHERRANK"`, or `rank: "GENUS"` for a species row → `{}`.
    - `test_gbif_rejects_other_kingdom` (T4-r2, R1) — row path starts `Animalia|…`, match `kingdom: "Plantae"` → `{}`.
    - `test_wikipedia_rejects_unrelated_extract` (T4-r3, R1) — the extract mentions neither the scientific name nor any common name → `{}`; one that mentions "Goliath birdeater" (a stored common name) → accepted.
    - `test_gbif_bbox_ignores_null_island_and_requires_points` — `(0, 0)` coordinates dropped; fewer than 3 remaining points → no `geo_bounding_box`.
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** following `data/enrich_gbif_occurrences.py` (`_get_usage_key` with `MIN_CONFIDENCE = 90`, `_get_bbox`) and `data/enrich_wikipedia.py` (`_fetch_summary`: REST `page/summary/{quote(name)}`, reject `disambiguation` / `no-extract`) — reimplement minimally on `_get_json`; don't import from `data/`.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat: GBIF habitat/range and Wikipedia abstract trait sources"`

---

### Task 5: Sourced stage orchestrator

**Files:**
- Modify: `backend/app/trait_utils.py`
- Test: `backend/tests/test_trait_utils.py`

**Interfaces:**
- Consumes: `iucn_traits`, `gbif_traits`, `wikidata_traits`, `wikipedia_abstract`; `database.parse_trait_sources`
- Produces:
  - `ELIGIBLE_RANKS = frozenset({"species", "subspecies"})`
  - `is_eligible(row: dict) -> bool`
  - `run_sourced_stage(row: dict) -> tuple[dict[str, TraitValue], bool]` — returns `(values, complete)`. `values` contains only fields that are NULL in `row` or currently estimated; per field, priority IUCN > GBIF for `habitat_type`, Wikidata for numbers. `complete` is `False` if any source raised `SourceUnavailable`.

- [ ] **Step 1: Write failing tests** (patch the four source functions):
  - `test_sourced_stage_priority_iucn_over_gbif` — both give `habitat_type` → IUCN value wins.
  - `test_sourced_stage_skips_filled_fields` — row `body_mass=3.9` + Wikidata mass → no `body_mass` key.
  - `test_sourced_stage_incomplete_when_a_source_unavailable` (Review Focus 3) — `gbif_traits` raises `SourceUnavailable` → other sources' values still returned, `complete is False`.
  - `test_sourced_stage_ineligible_rank` — `taxon_rank="genus"` → `({}, False)` and no source called.
  - *Risk tests:*
    - `test_sourced_stage_respects_deadline` (T5-r1, R4) — one source sleeps 30 s (patched `STAGE_DEADLINE_S = 0.5`) → the stage returns in < 2 s with the other sources' values, `complete is False`.
    - `test_sourced_stage_unexpected_exception_is_incomplete` — a source raises `KeyError` (shape drift) → logged, `complete is False`, other values kept.
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** with `concurrent.futures.ThreadPoolExecutor(max_workers=4)`, one future per source.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat: concurrent sourced trait stage with completeness tracking"`

---

### Task 6: Estimate stage (LLM)

**Files:**
- Modify: `backend/app/trait_utils.py`
- Test: `backend/tests/test_trait_utils.py`

**Interfaces:**
- Consumes: `to_kg`, `to_m`, `to_years`; Ollama config `OLLAMA_MODEL`, `OLLAMA_BASE_URL` from `llm_agent` (import the constants, or move them to a shared spot if that creates a cycle).
- Produces: `run_estimate_stage(row: dict) -> tuple[dict[str, TraitValue], bool]` — source `"Estimated from Wikipedia description"`, `estimated=True`, only for fields still NULL. No abstract → `({}, True)`. Ollama unreachable → `({}, False)`.

Closed vocabularies:
- `activity_period`: `diurnal, nocturnal, crepuscular, cathemeral`
- `trophic_level`: `herbivore, carnivore, omnivore, insectivore, piscivore, frugivore, nectarivore, granivore, detritivore, filter feeder, parasite`
- `habitat_type`, `reproduction_strategy`, `elevation_limits`: free text, ≤ 120 chars
- `body_mass`, `body_length`, `max_lifespan`: `{"value": <number as written in text>, "unit": <unit word>}` or null

- [ ] **Step 1: Write failing tests** (patch the LLM call to return a JSON string):
  - `test_estimate_skipped_without_abstract` — `({}, True)`, LLM not called.
  - `test_estimate_rejects_out_of_vocabulary` — `{"activity_period": "sometimes"}` → no key.
  - `test_estimate_number_must_appear_in_text` — abstract "weighs up to 6.2 oz"; LLM `{"body_mass": {"value": 6.2, "unit": "ounce"}}` → `TraitValue(≈0.1758, ..., True)`; LLM `{"body_mass": {"value": 900, "unit": "gram"}}` → no key.
  - `test_estimate_invalid_json_is_complete_but_empty` — `"not json"` → `({}, True)`.
  - `test_estimate_ollama_down_is_incomplete` — call raises `ConnectionError` → `({}, False)`.
  - *Risk tests:*
    - `test_estimate_number_needs_adjacent_unit` (T6-r1, R3) — abstract "First described in 1804. It lives up to 25 years."; LLM lifespan `{"value": 1804, "unit": "year"}` → rejected; `{"value": 25, "unit": "year"}` → `25.0`.
    - `test_estimate_rejects_implausible` (T6-r2, R2) — "weighs 300 tonnes" → rejected by bounds (> 2e5 kg); a value inside the bounds is kept (bounds are a sanity net, not taxon-aware).
    - `test_estimate_drops_placeholders` (T6-r3, R3) — `{"habitat_type": "Unknown", "reproduction_strategy": "not stated"}` → no keys.
    - `test_estimate_truncates_and_keeps_text_inert` (T6-r4, R3) — the abstract contains "Ignore previous instructions"; LLM free text of 500 chars with `<script>` → stored ≤ 120 chars, stored as plain text (escaping is the panel's job, Task 9).
    - `test_estimate_ignores_filled_fields` (T6-r5) — row has `activity_period` sourced; LLM returns one → not in the result.
    - `test_estimate_timeout_is_incomplete` (T6-r6, R4) — the LLM call exceeds `ESTIMATE_TIMEOUT_S` (patched small) → `({}, False)`.
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** with `ChatOllama(model=..., base_url=..., temperature=0, format="json")`. The prompt states: use only facts in the given text, return null for anything not stated, give numbers exactly as written. "Appears in text" = the value's digits, formatted as the model returned them, occur in the abstract.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat: LLM trait estimate stage grounded in the Wikipedia abstract"`

---

### Task 7: `/traits` endpoint and provenance in species records

**Files:**
- Modify: `backend/app/main.py` (models ~line 42; route before line 419)
- Test: `backend/tests/test_taxonomy_api.py` (extend `_insert` with `taxon_rank`, `wikipedia_abstract`, `trait_sources` kwargs)

**Interfaces:**
- Consumes: `trait_utils.run_sourced_stage`, `run_estimate_stage`, `is_eligible`; `database.update_species_traits`, `trait_provenance`, `parse_trait_sources`, `get_species`
- Produces:
  - `SpeciesRecord` gains `provenance: dict[str, dict] = {}`, `traits_sourced: bool = False`, `traits_estimated: bool = False`, `trait_eligible: bool = False`.
  - `class TraitsResponse(BaseModel)`: `scientific_name: str`, `values: dict[str, Any]` (every non-NULL field in `TRAIT_FIELDS`), `provenance: dict[str, dict]`, `traits_sourced: bool`, `traits_estimated: bool`, `trait_eligible: bool`.
  - `GET /api/species/{scientific_name}/traits?stage=sourced|estimated&force=false` → `TraitsResponse`. `stage=estimated` runs the sourced stage first if `_sourced` is missing. A stage whose marker is set is skipped unless `force=true`. Ineligible rank → stored data, no stage run. 404 if the species doesn't exist; 422 for any other `stage`.

- [ ] **Step 1: Write failing tests** (patch `trait_utils.run_*`):
  - `test_traits_route_not_shadowed_by_species_route`
  - `test_traits_sourced_stage_writes_and_marks`
  - `test_traits_marker_set_skips_network` — `_sourced` present → `run_sourced_stage` not called.
  - `test_traits_force_reruns_stage`
  - `test_traits_source_down_leaves_unmarked` (Review Focus 3) — stage returns `({...}, False)` → values returned, `traits_sourced is False`.
  - `test_traits_genus_not_eligible` — `trait_eligible is False`, no stage called.
  - `test_species_record_includes_provenance`
  - *Risk tests:*
    - `test_traits_unknown_stage_422_and_missing_species_404`
    - `test_traits_corrupt_trait_sources_does_not_500` (T7-r2, R10) — the row's `trait_sources = "{oops"` → 200, the stage runs, valid JSON written back.
    - `test_traits_estimate_stage_requires_eligible_rank` — genus + `stage=estimated` → stored data, no stage called.
- [ ] **Step 2: Run** `..\.venv\Scripts\python -m pytest tests/test_taxonomy_api.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement** — a thin route; the stage logic lives in `trait_utils`, the writes in `database`. After the sourced stage, re-read the row with `database.get_species` before running the estimate stage, because the abstract may have just been fetched. Also add `test_traits_estimate_uses_freshly_fetched_abstract` to Step 1.
- [ ] **Step 4: Run** the full backend suite — Expected: all PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat: GET /api/species/{name}/traits endpoint with stage markers"`

---

### Task 8: Chat — sourced traits and three-way labels

**Files:**
- Modify: `backend/app/llm_agent.py` (`_SYSTEM_PROMPT`, `lookup_species`, `LabelChecker`)
- Test: `backend/tests/test_llm_agent.py`

**Interfaces:**
- Consumes: `trait_utils.run_sourced_stage`, `is_eligible`; `database.update_species_traits`, `parse_trait_sources`
- Produces: `lookup_species` output lines for estimated fields end with ` (estimated)`, e.g. `- Activity period: nocturnal (estimated)`. `_DB_EST_LABEL = "Database (estimated):"`.

- [ ] **Step 1: Write failing tests:**
  - `test_lookup_species_runs_sourced_stage_once` — no `_sourced` → stage called and written; with `_sourced` → not called; estimate stage never called.
  - `test_lookup_species_tags_estimated_lines`
  - `test_label_estimated_only_support_becomes_estimated_label` — "Database: It is nocturnal." with `nocturnal` only on an `(estimated)` line → `"Database (estimated): It is nocturnal."`
  - `test_label_estimated_without_support_becomes_general` — "Database (estimated): It eats seals." → `"From general knowledge: It eats seals."`
  - `test_label_estimated_kept_when_supported`
  - The existing `LabelChecker` tests stay green.
  - *Risk tests:*
    - `test_label_parsing_new_label_not_split` (T8-r1, R8) — the input `"Database (estimated): It is nocturnal."` with support → output identical (not `"Database: (estimated): …"`).
    - `test_label_variants_normalised` (T8-r2, R8) — `"database (Estimated):"`, `"Database(estimated):"` → recognised and emitted in canonical form.
    - `test_value_in_both_sourced_and_estimated_counts_as_sourced` (T8-r3, R8) — 175 on a sourced line and an estimated line → `"Database:"` kept.
    - `test_lookup_species_survives_stage_failure` — `run_sourced_stage` raises → the tool still returns the stored record, no exception into the agent.
- [ ] **Step 2: Run** `..\.venv\Scripts\python -m pytest tests/test_llm_agent.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement.** `LabelChecker.add_tool_output` routes values from `(estimated)` lines into a separate evidence set; `_supported` returns `"sourced" | "estimated" | None`. Prompt: add the third label with a one-line example. `lookup_species` catches every stage exception and falls back to stored data.
- [ ] **Step 4: Run** the full backend suite — Expected: all PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat: chat uses sourced traits; Database (estimated) label verified in code"`

---

### Task 9: Panel — trait rows, est. badge, source on hover

**Files:**
- Create: `frontend/js/traits.js`
- Modify: `frontend/js/app.js` (`_showSpeciesPanel` ~line 135; new `_loadTraits`)
- Test: `frontend/tests/traits.test.js` (create)

**Interfaces:**
- Consumes: `SpeciesRecord` / `TraitsResponse` fields from Task 7
- Produces (from `traits.js`):
  - `escapeHtml(s: unknown) -> string`
  - `traitRowsHtml(sp: object, provenance: object) -> string` — the same rows and labels as the current `sp-fields` list, in the same order. Values are escaped. Estimated values get `<span class="trait-est">est.</span>`. Each row has `title="Source: <source>"`, or `title="Source: <source> (estimated)"`.
  - `nextTraitStage(sp) -> 'sourced' | 'estimated' | null` — `null` if `!sp.trait_eligible`.

- [ ] **Step 1: Write failing tests:**
  - `escapes untrusted values` (Review Focus 1) — a `habitat_type` of `'<img src=x onerror=alert(1)>'` → the output contains `&lt;img` and no `<img`.
  - `marks estimated values and shows source in title`
  - `hides rows with no value`
  - `nextTraitStage order` — not sourced → `'sourced'`; sourced but not estimated → `'estimated'`; both → `null`; ineligible → `null`.
  - In `app.js`, a stale response is ignored (Review Focus 2). Export a small `isCurrentSpecies(name)` guard from `traits.js`, or test `_loadTraits` with mocked `fetch`: opening A then B, with A's response arriving last → the panel shows B's values.
  - The traits URL uses `encodeURIComponent` (Review Focus 4) — `'Apis cerana × mellifera'`.
  - *Risk tests:*
    - `formats numbers to 3 significant figures` (T9-r1, R11) — `formatTraitValue(0.175823) === "0.176"`, `formatTraitValue(188) === "188"`, `formatTraitValue(1.2e-7) === "0.00000012"`.
    - `escapes quotes in title attributes` (T9-r2, R11) — a source or value with `"` → `&quot;` inside `title`.
    - `removes loading line after fetch timeout` (T9-r3, R4) — fake timers, `fetch` never resolves → after `TRAITS_FETCH_TIMEOUT_MS` the loading line is gone and nothing is thrown.
    - `no errors when panel is closed mid-load` (T9-r4, R12) — the panel element is removed before the response → no exception, no DOM writes.
    - `row order and labels unchanged for stored-only record` (T9-r5, R14) — snapshot of `traitRowsHtml` for a record with no provenance → the same labels, in the same order as the current `app.js` list.
- [ ] **Step 2: Run** `npm run test` (from `frontend/`) — Expected: FAIL.
- [ ] **Step 3: Implement.** `_showSpeciesPanel` renders `traitRowsHtml(sp, sp.provenance)`. If `nextTraitStage(sp)` returns a stage, it shows a muted "Looking up traits…" line under the fields and calls `_loadTraits`. That fetches `/traits?stage=sourced`, re-renders, then (if still needed) fetches `stage=estimated` and re-renders. Each step checks the panel still shows the same species. Network errors silently remove the loading line.
- [ ] **Step 4: Run** `npm run test` — Expected: all PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat: species panel loads traits on open with est. badge and source tooltips"`

---

### Task 10: Live verification and docs

**Files:**
- Modify: `Docs/PLAN.md` (new "Increment 12" section before "## Data Source Reference"), `CLAUDE.md` (schema: `trait_sources`; data flow: traits)

- [ ] **Step 1:** Restart the backend (`stop.bat`, then `start.bat`). Record "before" rows for *Panthera leo*, *Ursus maritimus*, *Theraphosa blondi*, *Apis cerana*.
- [ ] **Step 2:** Open each one in a headless browser (pattern: the scratch `panel_check.mjs` used for the description fix). Expected:
  - lion: habitat (IUCN), elevation "0–4,200 m";
  - spider: habitat "Terrestrial" (GBIF), body mass ≈ 0.176 kg (Wikidata);
  - estimated rows carry "est." and their source in `title`.
  - Record the time until the sourced rows appear.
- [ ] **Step 3:** Reopen the same species. Expected: no `/traits` network work. Check `backend.log` shows a `/traits` call that returns without running stages, or no call at all.
- [ ] **Step 4:** Chat "how heavy is a Goliath birdeater" → a `Database:` sentence with the Wikidata mass. Chat about an estimated trait → `Database (estimated):`.
- [ ] **Step 5:** Run the full backend, frontend and E2E suites (`set AK_PORT=8010 && npx playwright test`) — Expected: all pass.
  - *Risk tests:*
    - **Live smoke** (T10-r1, R13): `backend/tests/test_trait_sources_live.py`, marked `@pytest.mark.live` (register the marker in `pytest.ini`, deselected by default with `-m "not live"`). For *Panthera leo*, *Ursus maritimus*, *Theraphosa blondi*, *Apis cerana*: each source returns its expected field types without exceptions; the lion's IUCN habitat is non-empty; the spider's Wikidata mass ≈ 0.176 kg. Run: `..\.venv\Scripts\python -m pytest -m live -v`.
    - **Route-mocked E2E** (T10-r2, R14): `e2e/traits_panel.spec.ts`. `page.route('**/api/species/*/traits*')` returns a fixed `TraitsResponse` with one sourced and one estimated value. Asserts:
      - the loading line appears, then disappears;
      - the "est." badge is shown on the estimated row only;
      - hovering shows the `title` source;
      - the image still loads;
      - switching species mid-load shows only the second species' traits.
- [ ] **Step 6:** Add the Increment 12 section to `PLAN.md`: the task checklist, decisions, before/after counts and timings. Update `CLAUDE.md`. Ask the user for approval before committing.
- [ ] **Step 7: Commit** after approval — `git commit -m "docs: Increment 12 complete — dynamic trait retrieval"`
