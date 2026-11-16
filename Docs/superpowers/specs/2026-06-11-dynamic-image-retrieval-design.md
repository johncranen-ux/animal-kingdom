# Dynamic Image Retrieval for Species Panel

**Date:** 2026-06-11  
**Status:** Approved

## Problem

The species panel hides the image section when `primary_image_url` is null, and silently hides it on `onerror` with no retry. Many species have no stored image despite being retrievable from public sources. When a stored URL goes stale, there is no recovery path.

## Solution

Add a dedicated backend endpoint that runs a 4-source image lookup chain and caches the result to the DB. The frontend calls this endpoint when `primary_image_url` is null or when an `<img>` `onerror` fires.

---

## Image Lookup Chain

Sources are tried in order; the first result wins:

1. **Wikipedia** — page summary thumbnail (`/api/rest_v1/page/summary/{name}`)
2. **iNaturalist** — taxa endpoint (`/v1/taxa?q={name}&rank=species`)
3. **Wikimedia Commons** — action API search + imageinfo (`commons.wikimedia.org/w/api.php`)
4. **DuckDuckGo** — `ddgs` package (`DDGS().images(name, max_results=5)`)

Attribution is stored as a best-effort plain string from whatever the source provides (private non-commercial project — no strict formatting required).

---

## Backend

### New module: `backend/app/image_utils.py`

Owns all image-fetching logic. Exposes:

```python
def fetch_image(scientific_name: str, common_names: list[str] | None = None) -> tuple[str, str] | None:
    """Run the 4-source chain. Returns (url, attribution) or None."""
```

Internal helpers (all return `(url, attribution) | None`):

- `_wikipedia_image(scientific_name)` — extracted from `llm_agent.py` (no change in logic)
- `_inaturalist_image(scientific_name)` — extracted from `llm_agent.py` (no change in logic)
- `_wikimedia_image(scientific_name)` — new; 2-step Commons API: search by name in file namespace, then `prop=imageinfo&iiprop=url|extmetadata` on first result
- `_duckduckgo_image(scientific_name, common_names)` — new; `DDGS().images(query, max_results=5)`, returns first result's `image` URL; catches `RatelimitException` and returns `None`

`fetch_image` also tries common names (first name in list) as a fallback query for DDG if scientific name returns nothing.

### `llm_agent.py` changes

`get_species_image` imports `_wikipedia_image` and `_inaturalist_image` from `image_utils` instead of defining them inline. No behaviour change.

### `database.py` changes

New helper:

```python
def update_species_image(scientific_name: str, url: str, attribution: str) -> None:
    """Write primary_image_url and image_attribution. Used for write-through cache."""
```

### New endpoint: `GET /api/species/{name}/image`

Query param: `force: bool = False`

**Logic:**

1. Read current `primary_image_url` from DB.
2. If `not force` and value is `"__none__"` → return 404 immediately (previously attempted, nothing found).
3. Call `fetch_image(name, common_names)`.
4. If result found → call `update_species_image`, return `{"url": ..., "attribution": ...}`.
5. If no result → write `"__none__"` to `primary_image_url` (only when `not force`), return 404.

The `"__none__"` sentinel in `primary_image_url` prevents repeated external calls for species with no findable image. It is consistent with other sentinel values used in this project (`__alpha__`, `__unclassified__`).

---

## Frontend (`app.js`)

### `_showSpeciesPanel` updated behaviour

| `primary_image_url` value | Action |
|---|---|
| `"__none__"` | Hide `imgWrap` immediately — no fetch |
| `null` | Show `"Finding image…"` label inside `imgWrap`, call `/api/species/{name}/image`; on success set `imgEl.src` and clear label; on 404 hide `imgWrap` |
| valid URL | Set `imgEl.src`; `onerror` → call `/api/species/{name}/image?force=true`; on success swap `imgEl.src`; on 404/error hide `imgWrap` |

Loading state: inline text `"Finding image…"` inside `imgWrap` — no new CSS dependencies.

---

## Tests

### Backend

- `test_fetch_image_returns_wikipedia_result` — mock `_wikipedia_image` to return a URL; assert `fetch_image` returns it without calling further sources.
- `test_fetch_image_falls_through_chain` — mock Wikipedia and iNat to return `None`, mock Commons to return a URL; assert result is the Commons URL.
- `test_fetch_image_returns_none_when_all_fail` — all four mocked to return `None`; assert `fetch_image` returns `None`.
- `test_image_endpoint_caches_result` — call `/api/species/{name}/image`; assert DB `primary_image_url` is updated.
- `test_image_endpoint_returns_404_for_none_sentinel` — seed DB with `primary_image_url = "__none__"`; assert endpoint returns 404 without calling `fetch_image`.
- `test_image_endpoint_force_bypasses_sentinel` — seed `"__none__"`, call with `?force=true`; assert `fetch_image` is called.

### Frontend

- `_showSpeciesPanel shows loading state then image on success` — mock fetch to return a URL; assert loading text appears then `imgEl.src` is set.
- `_showSpeciesPanel hides image on 404` — mock fetch to 404; assert `imgWrap` hidden.
- `onerror triggers force refetch` — set a URL that fires onerror; assert `/image?force=true` is called.

### Regression

All existing backend and frontend tests must continue to pass. `get_species_image` in `llm_agent.py` behaviour is unchanged.

---

## What Does Not Change

- `GET /api/species/{name}` — response shape unchanged; `primary_image_url` may now be `"__none__"` which the frontend handles.
- `llm_agent.py` chat agent flow — unchanged; `get_species_image` continues to work as before.
- Background enrichment scripts — unaffected.
- DB schema — no new columns; `"__none__"` is a valid TEXT value in `primary_image_url`.
