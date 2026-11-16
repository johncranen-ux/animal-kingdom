# Dynamic Trait Retrieval for Species Panel

**Date:** 2026-11-03
**Status:** Approved 2026-11-03
**Increment:** 12

## Problem

Most species-panel rows are empty because the data was never imported. Across ~2.5 M accepted species:

| Field | Filled | Field | Filled |
|---|---|---|---|
| `body_mass` | 0.1% (AnAge) | `habitat_type` | 0 |
| `max_lifespan` | 0.2% (AnAge) | `elevation_limits` | 0 |
| `geo_bounding_box` | 0.2% | `trophic_level` | 0 |
| `iucn_status` / `population_trend` | ~6% | `activity_period` | 0 |
| `wikipedia_abstract` | 0.3% | `reproduction_strategy` | 0 |
| `body_length` | 0 | `metabolic_rate` | <0.1% |

Pre-populating 2.5 M rows from online sources would take days to weeks. The panel hides empty rows, so users see a sparse record and can't tell missing data from a bug.

## Intent

Do for traits what Increment 10e did for images: **when a species is opened, look up its missing traits live, show them, and store them**, so every later open is instant and offline. The user's goal: **fill in as many traits as possible**.

## Decisions made by the user

1. **Lazy, on demand** — fetch when a species is queried, not by pre-populating the database.
2. **Maximise coverage** — use every reasonable source.
3. **Estimates are allowed:** a trait that only the local LLM can supply (by reading the description) is **shown and marked "estimated"**, not left empty.
4. **Chat labels estimated facts `Database (estimated):`**, distinct from `Database:` and `From general knowledge:`.
5. **Source on hover:** each trait row shows where its value came from (e.g. "IUCN Red List", "Wikidata", "Estimated from Wikipedia description") when hovered.
6. **Estimates come from the description only.** The LLM may not estimate from its own knowledge: no Wikipedia abstract → no estimate. Numbers (mass, length, lifespan) are estimated only when the description states them.
7. **Chat fetches sourced traits, not estimates.** `lookup_species` runs the online-source stage (~3 s, once per species) but never waits for the LLM estimate; estimates are filled when the species is opened in the panel.

## Builder's calls (made by Claude, not the user — check these)

- **Failure vs "no data":** only a source that *answered* counts as tried. Network errors, timeouts, HTTP 429/5xx, or Ollama being down leave the stage unmarked, so it is retried on the next open.
- **Two stage markers** instead of one sentinel: `_sourced` (online sources done) and `_estimated` (LLM stage done, or skipped because there is no abstract). Closing the panel before estimates finish doesn't lose them — the next open runs only the missing stage.
- **Replacing estimates:** a later sourced value may replace an *estimated* one. Sourced and imported values are never overwritten. `force=true` reruns both stages; it is API-only (no panel button) for maintenance and testing.
- **Eligibility:** only `taxon_rank` `species` and `subspecies` (any taxonomic status) trigger fetching — never genus or higher, so no estimated body mass for a whole genus. Sources are queried with the row's own scientific name; values are written to that row.

## Goals

- Fill every empty trait field the sources can supply, on first open of a species.
- Never fetch the same species twice unless forced (sentinel, like images).
- Record provenance per field (source + estimated flag) so the panel and chat can show it.
- Chat answers draw on the same enriched record, with correct three-way labels.

## Non-goals

- Bulk pre-population (existing `data/` scripts remain for that).
- Overwriting values that are already stored (AnAge weights, IUCN status from the sweep, etc.).
- `metabolic_rate` — no live source found; stays AnAge-only.
- Fixing GBIF common-name quality (e.g. *Theraphosa blondi* listed first as "Chilean rose-hair tarantula") — separate issue.

## Anti-goals (would make this a failure even if it works)

- An estimated value displayed or stated in chat as if it were a sourced fact.
- Wrong units silently stored (e.g. Wikidata's 6.2 **ounce** spider stored as 6.2 kg).
- The panel blocking: the stored record must render immediately; traits arrive afterwards.
- Hammering an API on every open of a species where nothing was found.

## Sources and field mapping

Tried per field in this order; the first source that yields a value wins. Results verified against live API responses on 2026-11-03.

| Field | 1st | 2nd | 3rd (estimated) |
|---|---|---|---|
| `habitat_type` | IUCN assessment `habitats` | GBIF `speciesProfiles` `habitat` | LLM |
| `elevation_limits` | IUCN `supplementary_info` elevation / depth limits | — | LLM |
| `body_mass` (kg) | Wikidata P2067 (mass) | — | LLM |
| `body_length` (m) | Wikidata P2043 (length) | — | LLM |
| `max_lifespan` (years) | Wikidata P2250 (life expectancy) | — | LLM |
| `trophic_level` | — | — | LLM (may use Wikidata P1034 "main food source" as input) |
| `activity_period` | — | — | LLM |
| `reproduction_strategy` | — | — | LLM |
| `iucn_status`, `population_trend` | IUCN (only if missing — e.g. species not matched by the bulk sweep) | — | never estimated |
| `geo_bounding_box` | GBIF occurrence search (logic as in `data/enrich_gbif_occurrences.py`) | — | never estimated |
| `wikipedia_abstract` | Wikipedia REST summary (logic as in `data/enrich_wikipedia.py`) | — | never estimated |

The abstract is fetched **before** the LLM step, since it is the LLM's input.

### Source details

- **IUCN API v4** (token from `.env`, TLS verification on). Assessment ID: from `E:\AnimalKingdomSystem\iucn_checkpoint.json` `matched` map if present, else look up by name via the taxa endpoint. One `GET /assessment/{id}` call yields habitats, elevation/depth, systems, trend. Trend codes: 0=Increasing, 1=Decreasing, 2=Stable, 3=Unknown; prefer `description.en`.
  - `habitat_type` text: the `description.en` of habitats with `majorImportance == "Yes"`; if none, those with `suitability == "Suitable"`; joined with "; ".
  - `elevation_limits` text: e.g. `"0–4,200 m"`; marine depth as `"depth 0–200 m"`; both if both.
- **GBIF:** `species/match` (confidence ≥ 90, as in the existing script) → `species/{key}/speciesProfiles` → first English `habitat` value (normalise e.g. "Terrestrial"); occurrence search for the bounding box.
- **Wikidata SPARQL** (`query.wikidata.org`, no key, send a User-Agent). Match item by P225 (taxon name). Read quantity **with unit** (`psv:` value node) and convert to kg / m / years. When several values exist (lion mass: 1.65, 126, 188 kg), take the **largest**. Drop values whose unit can't be converted.
- **LLM estimate:** local Ollama `llama3.1:8b`, one call per species, JSON output, temperature 0. Input: the Wikipedia abstract plus any already-known traits. **Skipped entirely when there is no abstract.** The prompt instructs the model to use only what the text says, not its own knowledge; numeric fields are filled only when the text states a figure (with unit, converted like Wikidata values). Only fills fields still empty after sources 1–2. Values must come from a closed vocabulary where one exists (e.g. activity: diurnal / nocturnal / crepuscular / cathemeral; trophic: herbivore / carnivore / omnivore / insectivore / piscivore / detritivore / filter feeder / …; reproduction: free text, short). The model returns `null` for anything it can't determine.

## Storage

- New TEXT column **`trait_sources`** on `species` (JSON, via `database.py` helpers like `common_names`): `{"habitat_type": {"source": "IUCN Red List", "estimated": false}, "activity_period": {"source": "Estimated from Wikipedia description", "estimated": true}, ..., "_sourced": "2026-11-03", "_estimated": "2026-11-03"}`. Added with `ALTER TABLE ... ADD COLUMN` (instant in SQLite) on startup if missing.
- **Stage markers:** `_sourced` / `_estimated` mean "this stage completed — don't rerun unless `force=true`". Set only when the stage ran without transport errors (see builder's calls). Fields not found simply stay NULL.
- Values go into the existing columns (`habitat_type`, `body_mass`, …) so all existing readers keep working.
- Existing non-NULL values are never overwritten, except an estimated value by a sourced one. Pre-existing values without a `trait_sources` entry are shown with their known bulk source (AnAge for mass/lifespan/metabolic rate, IUCN for status/trend, GBIF for range, Wikipedia for abstract).

## Backend

- New module **`backend/app/trait_utils.py`** — owns the source chain, unit conversion, and the LLM estimate. Exposes `fetch_traits(row: dict) -> dict` returning `{field: (value, source, estimated)}` for fields it filled. Network calls per source are independent and may run concurrently; each has a timeout.
- **`database.py`:** `update_species_traits(scientific_name, values: dict, sources: dict)` — fills only NULL columns and merges `trait_sources`; parse/serialize helpers for `trait_sources`.
- **`main.py`:** `GET /api/species/{scientific_name}/traits?force=false` → returns the full trait set with provenance. Must be registered **before** `/api/species/{scientific_name}` (same route-order rule as `/image`). Runs only the stages whose marker is missing; with both markers set and `force` false, it returns stored data without network calls. Non-eligible ranks return stored data only.
- `fetch_traits` is split into a **sourced** stage and an **estimate** stage so chat can run the first alone.
- **`/api/species/{name}`** response gains `trait_sources` so the first panel render can already show provenance for stored values.

## Frontend (species panel)

- Render the stored record immediately (as now). If either stage marker is absent (and the rank is eligible), call `/traits`, show a small "Looking up traits…" line, then re-render the rows when it returns.
- **Estimated** values get a visible marker after the value (e.g. a small "est." badge, styled muted).
- **Hover:** every trait row shows its source on hover (tooltip consistent with the existing tree tooltip style).
- Rows with no value stay hidden (unchanged).
- New rows render for fields the panel doesn't yet show, if any (check `elevation_limits`, `trophic_level`, `activity_period`, `reproduction_strategy` are all present — they already are in `app.js`).

## Chat

- `lookup_species` runs **only the sourced stage** when `_sourced` is absent (user decision 7), never the estimate stage, then formats the enriched record including any estimates already stored. This deliberately revises the Increment 2b decision against live fetches in the tool loop: the cost is ~3 s once per species. Lines for estimated values are tagged, e.g. `- Activity period: nocturnal (estimated)`.
- **Three labels:** `Database:`, `Database (estimated):`, `From general knowledge:`. Prompt updated with the third label and an example.
- **`LabelChecker`** tracks estimated values separately: a `Database:` sentence supported only by estimated values is relabelled `Database (estimated):`; a `Database (estimated):` sentence with no stored value is relabelled `From general knowledge:`.

## Performance

- Target: panel traits visible within ~3 s for source lookups; the LLM estimate may take longer (~5–10 s on the 8B model). The LLM call should not hold back the sourced values — return/display sourced traits first, estimated ones when ready.
- Second open of any species: no network calls.

## Testing

- Unit tests per source with mocked HTTP (IUCN habitats/elevation formatting, GBIF profile parsing, Wikidata unit conversion incl. ounce/pound/gram/cm/mm/days/months, largest-value rule, LLM JSON parsing and vocabulary validation).
- `database.update_species_traits`: fills NULLs only, never overwrites, merges sources.
- Endpoint: sentinel respected, `force=true` refetch, route order.
- `LabelChecker`: estimated-only support → `Database (estimated):`; three-label streams.
- Frontend: loading line, est. badge, hover text, re-render.
- Live spot checks: *Panthera leo*, *Ursus maritimus*, *Theraphosa blondi*, *Apis cerana* (record before/after).

## Left to the builder

- Concurrency mechanism (threads vs async) and exact timeouts.
- How the sourced-then-estimated two-stage response is delivered (two requests, or one request returning sourced values and a second for estimates).
- Exact closed vocabularies and the LLM prompt wording.
- Tooltip implementation details and badge styling.
- Whether to refactor `data/enrich_*` logic into shared helpers or reimplement minimal versions in `trait_utils.py`.
