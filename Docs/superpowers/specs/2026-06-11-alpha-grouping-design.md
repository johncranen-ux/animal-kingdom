# Alpha Grouping for Large Taxonomy Nodes

**Date:** 2026-06-11  
**Status:** Approved

## Problem

When a taxonomy node has more than 200 children, the tree shows the first 200 and a `+N more — use Search to find species` sentinel. Users can find specific species via search, but cannot browse the remaining children.

## Solution

Replace the `+N more` sentinel with alphabetical letter-group nodes (`[A] (42)`, `[B] (8)`, …). Clicking a letter expands it in-place, showing all children whose name starts with that letter. Navigation via search (`expandToNode`) drills through the alpha layer automatically — fully transparent to the user.

---

## Trigger Condition

Alpha grouping activates when the child count exceeds `_CHILD_LIMIT = 200` (unchanged). It applies in **both** code paths of `taxonomy_zoom`:

- **Known-rank path** (`expected_all` branch): currently unbounded — if `len(nodes) > _CHILD_LIMIT` after `_build_tree`, emit alpha groups instead.
- **Unknown-rank fallback** (`else` branch): currently shows first 200 + `__more__` sentinel — replace that sentinel with alpha groups.

The same applies to `/api/taxonomy/unclassified` (orphan children), which also emits `__more__` sentinels today.

The `[Unclassified]` orphan-rank sentinel is a separate concept and is **not** affected.

---

## Node ID Format

```
node_id:  "__alpha__<parent_taxon_path>|<LETTER>"
name:     "[A] (42)"
rank:     "alpha"
```

- Only letters with ≥ 1 child produce a node (no empty buckets).
- The parent path is everything between the `__alpha__` prefix and the final `|LETTER` suffix — parseable without a DB lookup.
- Names starting with digits or punctuation are grouped under `[#]`; the DB helpers treat any non-letter first character as `#`.

---

## Backend

### `database.py` — two new helpers

**`get_children_letter_counts(parent_path: str, parent_depth: int) -> dict[str, int]`**

Single SQL query using `GROUP BY upper(substr(child_segment, 1, 1))` on the range-scanned children. Excludes SYNONYMs. Returns `{"A": 42, "B": 8, …}` ordered by letter. Uses the existing `idx_taxon_depth_path` composite index.

**`get_children_by_letter(parent_path: str, parent_depth: int, letter: str) -> list[dict]`**

Same range-scan as `get_children`, filtered to rows whose last path segment starts with `letter` (case-insensitive). No row limit — within one letter bucket the count is always manageable. Excludes SYNONYMs.

### `main.py` — one new endpoint + zoom changes

**`GET /api/taxonomy/alpha?node_id=X&letter=A`** → `list[TaxonNode]`

Calls `get_children_by_letter`. Applies the same structural-SYNONYM filter as `taxonomy_zoom` (retain SYNONYM genus/subgenus nodes that have ACCEPTED descendants). Returns children as normal `TaxonNode` objects — no further alpha grouping within a letter bucket.

**`taxonomy_zoom` changes**

In the known-rank path: after `_build_tree`, if `len(nodes) > _CHILD_LIMIT`, replace `nodes` with alpha-group sentinels derived from `get_children_letter_counts`.

In the unknown-rank fallback: replace the `__more__` sentinel with alpha-group sentinels.

Helper `_alpha_nodes(parent_path, letter_counts) -> list[TaxonNode]` builds the sentinel list from a `dict[str, int]`.

**`taxonomy_unclassified` changes**

Same pattern: replace the `__more__` sentinel at the end with alpha-group sentinels when `total > offset + _CHILD_LIMIT`.

---

## Frontend (`visualizer.js`)

### `loadNode(node)`

Add an `__alpha__` branch before the existing `__unclassified__` branch:

```js
if (node.node_id.startsWith("__alpha__")) {
  // parse parent_path and letter from node_id
  // fetch /api/taxonomy/alpha?node_id=<parent>&letter=<L>
}
```

### Node styling

Alpha nodes use the same gray filled circle as `_pathOnly` nodes (`fill: #888`, `r = 6`). Label is the node `name` verbatim (`[A]  (42)`). Tooltip: `"Children of <parent> starting with <letter>"`.

### Click behaviour

- Unloaded alpha node → `loadNode` (lazy-loads children, same as every other node).
- Loaded alpha node → normal collapse/expand toggle.
- `_pathOnly` flag is **not** set on alpha nodes — they behave as ordinary collapsible branches.

### `expandToNode(taxonPath)`

After loading a node's children, check whether all returned children are alpha nodes (`every c => c.node_id.startsWith("__alpha__")`). If so:

1. Derive the required letter from the first character of the next path segment.
2. Find the matching `[LETTER]` child node.
3. Call `loadNode` on it (await).
4. Continue walking the path as normal.

This is a single extra await step inserted transparently into the existing path-walk loop.

---

## Tests

### Backend (2 new)

- `test_zoom_returns_alpha_nodes_when_over_limit` — seed a parent with >200 children across multiple letters; assert `taxonomy_zoom` returns alpha sentinel nodes, not raw children.
- `test_alpha_endpoint_returns_correct_letter_children` — call `/api/taxonomy/alpha?node_id=X&letter=A`; assert only children starting with A are returned.

### Frontend (1 new)

- `expandToNode drills through alpha group automatically` — mock `loadNode` to return alpha nodes for the parent; assert `expandToNode` calls `loadNode` a second time with the matching alpha node and does not stop at the alpha layer.

### Regression

All 89 backend + 29 frontend tests must continue to pass. The `__more__` sentinel should no longer appear in any response.

---

## What Does Not Change

- `_CHILD_LIMIT = 200` — threshold unchanged.
- `[Unclassified]` sentinel — unaffected (different concept: wrong-rank children).
- `/api/taxonomy/node` — unaffected (single-node injection for `expandToNode` fallback).
- Search, chat, species panel — no changes needed.
- All existing node ID prefixes (`__unclassified__`, `__more__`) — `__more__` is retired; `__unclassified__` is unchanged.
