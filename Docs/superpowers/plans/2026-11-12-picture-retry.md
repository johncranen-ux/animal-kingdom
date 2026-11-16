# Picture Retry Button Implementation Plan (Increment 31)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the species panel ends up without a picture, show a "Search again" button that runs a wider search, including a source the normal lookup doesn't use, and stops recording "no picture" when a source was only offline.

**Architecture:** `image_utils.fetch_image` gets a `wide` mode and reports outages (`ImagesUnavailable`) instead of treating them as misses. `GET /api/species/{name}/image?retry=true` runs the wide mode. A small frontend module `frontend/js/images.js` renders the no-picture line and the button, and `app.js` wires it in where the image area is hidden today.

**Tech Stack:** FastAPI, SQLite (species.db), urllib, Vitest, Playwright.

**Spec:** Future Enhancements entry "Retry button for a missing picture" (noted 2026-11-11, `Docs/PLAN.md` on `tree-legend`): "when the species panel finds no image, show a button to search again, possibly from another source than the ones already tried (see the image chain in `image_utils.py`)". This plan adds the findings and decisions below.

## Findings (2026-11-12, live species.db and live APIs, read-only)

- 72 rows have `primary_image_url = '__none__'` (29 accepted species, 18 genera, 12 subspecies, 8 GBIF_ONLY, 3 synonyms, 3 higher ranks). Most other rows were never opened, so the button matters mainly in the moment a panel opens.
- Today the panel **hides** the image area in every no-picture case: stored `__none__`, a 404 from `/image`, or a picture that fails to load. You can't tell "no picture" from "still loading".
- **Bug:** `_http_get` returns `None` on any error, so a timeout or a 5xx from Wikipedia, iNaturalist or Commons counts as "no picture". The endpoint then writes `__none__`, and that species never gets a picture again.
- **Bug:** `_inaturalist_image` asks for `rank=species`, so subspecies and higher ranks never match. Without the rank filter, iNaturalist had a photo for all 6 tested subspecies (*Tyto furcata bondi*, *Sciurus niger avicennia*, ...), plus *Tanichthyidae* and *Chlorokybophyceae*: 9 of 25 sampled `__none__` rows.
- **New source, GBIF occurrence photos** (`api.gbif.org/v1/occurrence/search?scientificName=…&mediaType=StillImage`, no account): 12 of the 25 had one. For obscure taxa they are almost all **museum specimens** (`basisOfRecord = PRESERVED_SPECIMEN`: NHM London, MNHN Paris, CAS), with CC licences and a creator or rights holder. Living-animal photos come as `HUMAN_OBSERVATION`, mostly iNaturalist's.

## Decisions

The two user questions are answered at the end; everything else is my call.

1. **The button appears whenever the panel ends with no picture:** stored `__none__`, `/image` 404, or the picture still fails after the existing `force=true` reload. The image area stays visible with one grey line, "No picture found.", and a small **Search again** button. It is never shown while a lookup is running ("Finding image…" stays as it is).
2. **Search again = the wide search,** run only on the click, never on its own (it is slower: GBIF plus extra calls):
   1. the normal four sources (Wikipedia, iNaturalist, Commons, DuckDuckGo);
   2. for an old name, the same four for its current name (`database.current_name`, from Increment 30), attribution suffixed " (picture of *current name*)";
   3. GBIF occurrence photos (museum specimens allowed, the user's answer). Living-animal photos (`HUMAN_OBSERVATION`) come first; a specimen photo is used only when there is none, with attribution suffix " (museum specimen)".
3. **iNaturalist rank fix in both modes:** drop `rank=species` and accept a result only when its exact name matches **and** its `rank` equals the row's `taxon_rank` (default "species"). This keeps homonyms in other ranks out, and subspecies get pictures on the first open, with no button needed.
4. **Outages aren't misses:** `_http_get` returns `None` for HTTP 404 and raises `_SourceDown` for everything else (timeout, URLError, 429, 5xx, bad JSON). `fetch_image` keeps going past a source that is down. If it finds nothing and any of Wikipedia, iNaturalist, Commons or GBIF was down, it raises `ImagesUnavailable`. DuckDuckGo errors stay misses: it rate-limits often, and treating that as an outage would stop `__none__` from ever being written.
5. **Endpoint:** `/image?retry=true` implies `force` and `wide`.
   - Found: store and return it, as now.
   - Real miss: store `__none__` with `image_attribution = "searched again YYYY-MM-DD"` (no schema change), 404 `{"detail": {"message": "No image found", "searched_again": "YYYY-MM-DD"}}`.
   - `ImagesUnavailable`: 503 "A picture source didn't answer; try again later". Nothing is stored, in either mode, and a real URL is never overwritten.
6. **Panel text after a failed retry:** "Still no picture after a wider search." The button stays, because a later try may still find one. On 503: "A picture source didn't answer. Try again later." On a stored `__none__` whose attribution starts with "searched again": "No picture found (searched again on YYYY-MM-DD)."
7. **Chat unchanged:** `get_species_image` keeps the normal chain. It only maps `ImagesUnavailable` to its existing error JSON ("Picture sources are unavailable right now."), without writing `__none__`.

## Non-goals

- No bulk re-run over the 72 `__none__` rows. Each one gets the iNaturalist fix when its panel next opens with the button.
- No parent-species picture for a subspecies: the iNaturalist rank fix covered every subspecies tested.
- No picture picker or "wrong picture" report button.

## Global Constraints

- Branch `increment-31-picture-retry` off `master` (after the Increment 30 merge), in worktree `..\Animal Kingdom-wt25`. It needs the `current_name` from Increment 30.
- Image requests use the existing `_IMG_USER_AGENT`; no personal details go in any request.
- E2E runs on a private port (for example `AK_PORT=8035`), never 8010. Don't restart the user's backend.
- The frontend API base is the page origin; no hardcoded ports.
- Commit per task; merge to master only on the user's approval; check off PLAN.md only after approval.

## Review Focus

1. **A real stored picture is never replaced by `__none__`:** a retry from a panel whose picture failed to load and then misses must keep the old URL (the existing force rule). Test in Task 2.
2. **A slow source must not hang the button:** each request keeps its 10 s timeout. The wide search runs its sources one after another, so the worst case is about 70 s; the button shows "Searching more sources…" and is disabled until the response arrives. Test in Task 3 (disabled while pending).
3. **Panel switched mid-search:** the answer of a retry for animal A must not land in B's panel. Use the existing `panelShows(name)` check, as `_loadTraits` does. Test in Task 3.
4. **Homonym keys:** `Name [Parent]` must be stripped to `Name` before asking GBIF or iNaturalist, as Wikipedia already gets the plain name. Test in Task 1.
5. **GBIF returns synonyms:** GBIF matches *Barbodes sirang* to records labelled *Puntius sirang*. Accept them, since GBIF did the matching, but query only with `scientificName=`, never with free-text `q=`, which matches any record that mentions the name. Test in Task 1 (`test_gbif_image_uses_scientific_name_parameter`).

---

### Task 1: Wide image search and outage reporting (`image_utils.py`)

**Files:**
- Modify: `backend/app/image_utils.py`
- Test: `backend/tests/test_image_utils.py`

**Interfaces:**
- Produces:
  - `class ImagesUnavailable(Exception)`
  - `fetch_image(scientific_name: str, common_names: list[str] | None = None, taxon_path: str | None = None, *, rank: str | None = None, wide: bool = False, current_name: str | None = None) -> tuple[str, str] | None`. It raises `ImagesUnavailable` on a miss with an outage. The positional signature is unchanged for existing callers.
  - `_gbif_image(scientific_name: str) -> tuple[str, str] | None`
  - `_inaturalist_image(scientific_name: str, rank: str = "species")`

- [ ] **Step 1: Write the failing tests**

```python
def test_http_get_returns_none_on_404(monkeypatch): ...            # HTTPError 404 -> None
def test_http_get_raises_source_down_on_timeout(monkeypatch): ...  # -> image_utils._SourceDown
def test_fetch_image_raises_unavailable_when_a_source_was_down(monkeypatch):
    # wikipedia raises _SourceDown, the others return None
    with pytest.raises(image_utils.ImagesUnavailable): image_utils.fetch_image("Panthera leo")
def test_fetch_image_down_source_does_not_hide_a_later_hit(monkeypatch):
    # wikipedia down, inaturalist hits -> returns the iNaturalist tuple
def test_fetch_image_duckduckgo_error_is_a_miss(monkeypatch):      # returns None, no raise
def test_inaturalist_image_matches_subspecies_rank(monkeypatch):
    # results [{"name": "Tyto furcata bondi", "rank": "subspecies", "default_photo": {...}}]
    assert image_utils._inaturalist_image("Tyto furcata bondi", rank="subspecies")[0] == URL
def test_inaturalist_image_rejects_same_name_other_rank(monkeypatch):
    # name matches, rank "genus" vs requested "species" -> None
def test_gbif_image_prefers_a_living_animal_photo(monkeypatch):
    # results: PRESERVED_SPECIMEN first, HUMAN_OBSERVATION second -> the second, attribution
    # "© Anuar Acosta (CC BY-NC 4.0) via GBIF"
def test_gbif_image_falls_back_to_a_labelled_specimen(monkeypatch):
    # only PRESERVED_SPECIMEN, rightsHolder "The Trustees of the Natural History Museum, London",
    # license http://creativecommons.org/licenses/by/4.0/ ->
    # "© The Trustees of the Natural History Museum, London (CC BY 4.0) via GBIF (museum specimen)"
def test_gbif_image_skips_media_without_identifier_or_not_still_image(monkeypatch): ...
def test_gbif_image_uses_scientific_name_parameter(monkeypatch):  # URL has scientificName=, no q=
def test_gbif_image_strips_homonym_suffix(monkeypatch):
    # "Bacteria laesa [Phasmatidae]" -> request URL contains scientificName=Bacteria%20laesa
def test_fetch_image_wide_tries_current_name_then_gbif(monkeypatch):
    # normal chain misses for "Tapirus indicus"; for "Acrocodia indica" wikipedia hits ->
    # attribution ends " (picture of Acrocodia indica)"; gbif not called
def test_fetch_image_not_wide_never_calls_gbif(monkeypatch): ...
```

- [ ] **Step 2: Run them, expect failures** — `..\.venv\Scripts\python -m pytest tests/test_image_utils.py -v` → the new tests fail (no `_SourceDown`, `ImagesUnavailable`, `_gbif_image`, `rank`).

- [ ] **Step 3: Implement.**
  - `_http_get`: return `None` on `HTTPError` 404; raise `_SourceDown` on any other exception.
  - `fetch_image`: run each source through a helper that catches `_SourceDown` and records it. Wide order: the normal four for the name → (if `current_name`) the normal four for `current_name` → `_gbif_image(name)`.
  - Licence URL → short name: `creativecommons.org/licenses/<code>/<ver>` → `CC <CODE> <ver>`, `publicdomain/zero` → `CC0`, otherwise the raw value.
  - GBIF: `limit=20`, image types `StillImage` with an `image/*` format (or none given). Attribution `© {creator or rightsHolder or "GBIF contributors"} ({licence}) via GBIF`, plus ` (museum specimen)` unless `basisOfRecord == "HUMAN_OBSERVATION"`.
  - Update the existing `fetch_image` / `_inaturalist_image` tests that mock `_http_get` to the new `rank` behaviour.

- [ ] **Step 4: Run** `..\.venv\Scripts\python -m pytest tests/test_image_utils.py -v` → all pass.

- [ ] **Step 5: Commit** `feat: wide picture search with GBIF photos; outages are not misses (Increment 31)`

### Task 2: `/image?retry=true` and the chat tool

**Files:**
- Modify: `backend/app/main.py:487-514` (`species_image`), `backend/app/llm_agent.py` (`get_species_image`)
- Test: `backend/tests/test_taxonomy_api.py` (section `# --- GET /api/species/{name}/image ---`), `backend/tests/test_llm_agent.py` (or the file holding the `get_species_image` tests)

**Interfaces:**
- Consumes: `image_utils.fetch_image(..., rank=, wide=, current_name=)`, `image_utils.ImagesUnavailable`, `database.current_name(row)`
- Produces:
  - `GET /api/species/{name}/image?retry=true`: 200 `{url, attribution}`; 404 `{"detail": {"message": "No image found", "searched_again": "YYYY-MM-DD"}}`; 503 `{"detail": "A picture source didn't answer; try again later"}`.
  - The normal path also passes `rank=row["taxon_rank"]`.

- [ ] **Step 1: Write the failing tests**

```python
def test_image_retry_runs_wide_search_with_current_name(monkeypatch):
    # synonym row with accepted_name -> fetch_image called with wide=True, current_name="Acrocodia indica"
def test_image_retry_ignores_none_sentinel(monkeypatch):           # __none__ row, retry -> fetch runs
def test_image_retry_miss_records_date(monkeypatch):
    # __none__ row, miss -> 404, detail.searched_again == today; row image_attribution "searched again <today>"
def test_image_retry_miss_keeps_a_real_url(monkeypatch):
    # row with a real (broken) URL, retry misses -> URL unchanged
def test_image_outage_returns_503_and_stores_nothing(monkeypatch):
    # fetch_image raises ImagesUnavailable, retry=false, empty row -> 503; primary_image_url still NULL
def test_image_endpoint_passes_taxon_rank(monkeypatch): ...
def test_chat_image_tool_outage_is_not_cached(monkeypatch):
    # ImagesUnavailable -> error JSON "Picture sources are unavailable right now.", row unchanged
```

- [ ] **Step 2: Run them, expect failures.**
- [ ] **Step 3: Implement** `species_image(scientific_name: str, force: bool = False, retry: bool = False)` according to Decision 5. Date: `datetime.date.today().isoformat()`. Writing `__none__` stays limited to rows without a real URL: the empty or `__none__` case, as now.
- [ ] **Step 4: Run** the full backend suite `..\.venv\Scripts\python -m pytest tests/ -q` → all pass (788 + new).
- [ ] **Step 5: Commit** `feat: picture retry endpoint (Increment 31)`

### Task 3: Panel no-picture line and Search again button

**Files:**
- Create: `frontend/js/images.js`
- Modify: `frontend/js/app.js` (`_showSpeciesPanel` image block, `_fetchRemoteImage`), `frontend/index.html` (an empty `<div id="sp-no-image">` inside `#sp-image-wrap`), `frontend/css/style.css` only if Tailwind classes don't cover it
- Test: `frontend/tests/images.test.js`, `e2e/picture_retry.spec.ts`

**Interfaces:**
- Consumes: `/image?retry=true` from Task 2
- Produces (`images.js`):
  - `noPictureHtml(state: 'none' | 'searching' | 'still-none' | 'unavailable', searchedOn?: string) -> string`: the grey line plus `<button data-picture-retry>`. The button is disabled in 'searching'.
  - `retryPicture(name: string, {api, fetchFn = fetch}) -> Promise<{url, attribution} | {state: 'still-none' | 'unavailable'}>`

- [ ] **Step 1: Write the failing Vitest tests**

```js
it('none: says no picture found and offers Search again', ...)          // text "No picture found.", button enabled
it('none with a date: says when it was searched again', ...)            // "No picture found (searched again on 2026-11-12)."
it('searching: disables the button and says Searching more sources…', ...)
it('still-none: says Still no picture after a wider search.', ...)
it('unavailable: says a picture source did not answer', ...)            // "A picture source didn't answer. Try again later."
it('retryPicture calls /image?retry=true with the encoded name', ...)    // "Bacteria laesa [Phasmatidae]" encoded
it('retryPicture maps 404 to still-none and 503 to unavailable', ...)
it('escapes nothing user-supplied into HTML except the date', ...)       // date passed through escapeHtml
```

- [ ] **Step 2: Run** `npm run test -- images` → fails (no module).
- [ ] **Step 3: Implement** `images.js`, then wire it into `app.js`. Every place that now does `imgWrap.classList.add('hidden')` for a missing picture instead shows `noPictureHtml(...)` and hides the `<img>`/attribution. A delegated click on `[data-picture-retry]` sets 'searching', awaits `retryPicture`, and applies the result only if `panelShows(name)`. On success it sets `img.src`/attribution, as `_fetchRemoteImage` does.
- [ ] **Step 4: Write `e2e/picture_retry.spec.ts`** (route-mocked, like `old_names.spec.ts`):
  - `'a panel without a picture offers Search again and shows what it finds'`: species with `__none__` → button visible → `/image?retry=true` returns PIXEL → `#sp-image` src is PIXEL, line gone.
  - `'a retry that finds nothing says so and keeps the button'`: 404 → "Still no picture after a wider search."
  - `'a retry answer for another animal is ignored'`: retry pending with a delayed route, open another species, release → the second panel is unchanged.
- [ ] **Step 5: Run** `npm run test` (all Vitest) and `set AK_PORT=8035 && npx playwright test --grep-invert chat` → all pass.
- [ ] **Step 6: Commit** `feat: Search again button for a missing picture (Increment 31)`

### Task 4: Docs and live check

**Files:** `Docs/Manual.md` (species panel section), `Docs/PLAN.md` (new "Increment 31 — Picture Retry" section before "Data Source Reference", "Built …, awaiting approval"; GBIF occurrence API row's "Used For" adds pictures), `CLAUDE.md` (Key Data Flows: the image chain and its wide mode; `__none__` + "searched again" note)

- [ ] **Step 1:** Write the docs. The Future Enhancements entry lives only on `tree-legend`; strike it through there when master is merged into tree-legend.
- [ ] **Step 2: Live check, read-only on species.db** (DB writes stubbed out, as in Increment 30). Run `fetch_image(..., wide=True)` on the 25 sampled `__none__` rows and record the hits per source in PLAN.md. Expected roughly: iNaturalist 9 (rank fix), GBIF about 12 minus overlap.
- [ ] **Step 3: Commit** `docs: Increment 31 picture retry`

## Answers (2026-11-12)

1. Museum specimens: **yes**, when no living-animal photo exists, labelled "(museum specimen)".
2. iNaturalist rank fix in the normal lookup too: **yes**.
