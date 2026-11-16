# Choose Another Picture Implementation Plan (Increment 32)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the panel's picture is wrong (a mountain goat being eaten by a snake), the user opens **Other pictures**, sees 6–12 candidates from all sources with their source, and clicks one to keep it. The replaced picture is remembered so no lookup brings it back.

**Architecture:** Each image source gets a list form (`_x_images(..., limit)`); the single-picture functions return the first of that list, so the normal chain is unchanged. `image_utils.image_candidates(...)` asks all sources at once (threads) and merges, dedupes and filters them. Two routes: `GET /api/species/{name}/image/candidates` and `PUT /api/species/{name}/image`. New column `rejected_images` (JSON list). Frontend helpers in `frontend/js/images.js`, wired into `app.js`.

**Tech Stack:** FastAPI, SQLite, urllib + ThreadPoolExecutor, Vitest, Playwright.

**Spec:** the user's choice on 2026-11-12, option 2: "Choose another picture: a strip of about 6 to 8 candidates from all sources, each with its source; click one and it's kept; the rejected picture is remembered so the automatic lookup never brings it back."

## Decisions (my calls)

1. **Candidates and their order:**
   - Wikipedia's lead picture (1), iNaturalist taxon photos (up to 4, from `/v1/taxa/{id}`), Commons (up to 3), GBIF (up to 3, living animals before specimens), DuckDuckGo (up to 3). That's at most 14, capped at 12.
   - Deduped by URL, leaving out the current picture and any rejected one.
   - For an old name, the current name's Wikipedia and iNaturalist pictures are added, labelled "(picture of …)".
2. **Sources run in parallel.** The wait is about one source's timeout (10 s), not the sum. A source that is down is skipped. An empty result with a source down is reported as `unavailable`.
3. **Choosing:** `PUT {url, attribution}` stores the picture. The previous real URL (not `__none__`/empty, and different from the new one) is appended to `rejected_images`. Only `http(s)://` URLs are accepted (400 otherwise). The route doesn't check that the URL came from the candidates list: this is a local, single-user app.
4. **Rejected pictures stay out of automatic lookups too.** `fetch_image(..., exclude=set)` treats a hit on a rejected URL as that source's miss and moves on. The endpoint and the chat tool pass the row's rejected list.
5. **Panel:**
   - A small **Other pictures** button sits under the picture (next to the attribution) and also in the no-picture line.
   - The gallery replaces the picture area: "Looking for pictures…", then a 3-column grid of thumbnails, each with its source as a tooltip and a short source label, plus **Cancel**.
   - A thumbnail that fails to load is removed.
   - Empty: "No other pictures found." Outage: "A picture source didn't answer. Try again later."
   - A result for an animal the panel has left is dropped.
6. **Schema:** `_init_schema` adds `rejected_images TEXT` when missing (instant ALTER in SQLite); column count 26 → 27.

## Non-goals
- Pasting your own picture link (option 3); uploading files.
- A "bad picture" report without choosing a replacement.
- Stricter DuckDuckGo/Commons checks against "X eating Y" photos.

## Global Constraints
- Branch `increment-32-picture-choice` off `master` (fddea4a), worktree `..\Animal Kingdom-wt25`.
- E2E on a private port (8036), never 8010; don't restart the user's backend.
- Commit per task; merge only on approval.

## Review Focus
1. A choice for animal A must not be stored on, or shown in, B's panel after a switch (test: E2E).
2. The current picture and rejected pictures never appear as candidates (test: backend).
3. Choosing the same URL that is already stored doesn't add it to `rejected_images` (test: backend).
4. A homonym key (`Name [Parent]`) works in the candidate search and in the PUT route (test: backend).
5. HTML injection: attribution and URL from outside sources go into `innerHTML` escaped (test: Vitest).

---

### Task 1: Source lists and `image_candidates` (`image_utils.py`)
**Produces:**
- `_inaturalist_images(name, rank="species", limit=4)`
- `_wikimedia_images(name, must_name=None, limit=3)`
- `_gbif_images(name, limit=3)`
- `_duckduckgo_images(query, common_names=None, limit=3)`
- The single forms return `[0]` or None.
- `image_candidates(name, common_names=None, taxon_path=None, *, rank=None, current_name=None, current_path=None, current_rank=None, exclude=frozenset(), limit=12) -> tuple[list[dict], bool]`, where each dict is `{url, attribution, source}` and the bool means "a source was down".
- `fetch_image(..., exclude=frozenset())`.

**Tests:**
- `test_inaturalist_images_lists_taxon_photos`
- `test_wikimedia_images_returns_several_on_topic_hits`
- `test_gbif_images_living_first_then_specimens`
- `test_duckduckgo_images_several`
- `test_image_candidates_merges_in_source_order_and_dedupes`
- `test_image_candidates_leaves_out_excluded_urls`
- `test_image_candidates_adds_current_name_pictures`
- `test_image_candidates_reports_a_down_source`
- `test_image_candidates_caps_at_limit`
- `test_fetch_image_skips_an_excluded_hit`
- The existing single-source tests must keep passing.

### Task 2: Column, helpers and routes
**Produces:**
- `database.parse_rejected_images(raw) -> list[str]`
- `database.choose_species_image(name, url, attribution) -> None`: stores the picture and appends the old real URL to `rejected_images`.
- `GET /api/species/{name}/image/candidates` → `{"candidates": [...], "unavailable": bool}`
- `PUT /api/species/{name}/image` with body `{url, attribution}` → `{url, attribution}`
- `/image` and the chat tool pass `exclude`.

**Tests:**
- Column tests updated (27 columns).
- `test_choose_species_image_remembers_the_replaced_picture`
- `test_choose_same_picture_rejects_nothing`
- `test_choose_after_no_picture_rejects_nothing`
- `test_candidates_route_excludes_current_and_rejected`
- `test_candidates_route_homonym_key`
- `test_choose_route_stores_and_rejects`
- `test_choose_route_rejects_non_http_url`
- `test_image_route_passes_rejected_as_exclude`
- `test_chat_image_tool_passes_rejected_as_exclude`

### Task 3: Panel gallery
**Produces** (`images.js`):
- `otherPicturesButtonHtml()`
- `candidatesHtml(list)` (escaped, `data-candidate=i`)
- `galleryMessageHtml(state)` for the states 'loading', 'empty' and 'unavailable'
- `fetchCandidates(name, {api, fetchFn}) -> {candidates, unavailable}` (an error counts as unavailable)
- `choosePicture(name, cand, {api, fetchFn}) -> {url, attribution} | null`

**Tests:**
- Vitest: rendering, escaping, the request URLs and the PUT body.
- E2E `e2e/picture_choice.spec.ts`:
  - `'Other pictures shows candidates and keeps the one clicked'`
  - `'no candidates says so'`
  - `'a choice made after switching animals is not shown'`

### Task 4: Docs and live check
- Manual (Pictures), PLAN.md section "Increment 32 — Choose Another Picture", CLAUDE.md (column, routes).
- Read-only live check of `image_candidates` for *Oreamnos americanus* and two `__none__`-era animals: count per source and the time taken.
