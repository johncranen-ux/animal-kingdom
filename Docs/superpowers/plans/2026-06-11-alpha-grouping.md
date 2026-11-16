# Alpha Grouping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `+N more — use Search` sentinel with A–Z letter-group nodes for any taxonomy node with >200 children, enabling tree browsing without search.

**Architecture:** Two new DB helpers count/fetch children by first letter; a new `/api/taxonomy/alpha` endpoint serves a letter bucket; `taxonomy_zoom` and `taxonomy_unclassified` emit `__alpha__` sentinel nodes instead of `__more__` when child count exceeds 200; `loadNode` routes `__alpha__` prefixes to the correct endpoint; `expandToNode` drills through alpha layers automatically via a `_drillAlpha` helper.

**Tech Stack:** Python/FastAPI (backend), SQLite (range-scan queries), D3.js/ES6 (frontend), Vitest (frontend tests), pytest/FastAPI TestClient (backend tests).

---

## File Map

| File | Change |
|---|---|
| `backend/app/database.py` | Add `get_children_letter_counts`, `get_children_by_letter`, `get_orphan_letter_counts`, `get_orphan_children_by_letter` |
| `backend/app/main.py` | Add `_alpha_sentinels`, `GET /api/taxonomy/alpha`; modify `taxonomy_zoom` and `taxonomy_unclassified` |
| `backend/tests/test_taxonomy_api.py` | Add 2 new tests |
| `frontend/js/visualizer.js` | Modify `loadNode`, `_render`, `_onClick`; add `_drillAlpha`; modify `expandToNode` |
| `frontend/tests/visualizer.test.js` | Add 1 new test |

---

## Task 1: `get_children_letter_counts` DB helper

**Files:**
- Modify: `backend/app/database.py` (append after `count_children`)
- Test: `backend/tests/test_database.py`

- [ ] **Step 1: Write the failing test**

```python
# In backend/tests/test_database.py, add after existing tests:

def test_get_children_letter_counts_groups_by_first_letter(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    conn = database.get_connection()
    for name, path, rank in [
        ("Fabaceae",  "Fabaceae",         "family"),
        ("Acacia",    "Fabaceae|Acacia",   "genus"),
        ("Albizia",   "Fabaceae|Albizia",  "genus"),
        ("Bauhinia",  "Fabaceae|Bauhinia", "genus"),
    ]:
        conn.execute(
            "INSERT INTO species (scientific_name, taxon_path, taxon_rank, taxonomic_status) VALUES (?,?,?,'ACCEPTED')",
            (name, path, rank),
        )
    conn.commit()
    conn.close()

    counts = database.get_children_letter_counts("Fabaceae")
    assert counts == {"A": 2, "B": 1}


def test_get_children_letter_counts_excludes_synonyms(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    conn = database.get_connection()
    for name, path, status in [
        ("Fabaceae",  "Fabaceae",        "ACCEPTED"),
        ("Acacia",    "Fabaceae|Acacia",  "ACCEPTED"),
        ("Albizia",   "Fabaceae|Albizia", "SYNONYM"),
    ]:
        conn.execute(
            "INSERT INTO species (scientific_name, taxon_path, taxon_rank, taxonomic_status) VALUES (?,?,?,'ACCEPTED')",
            (name, path, "genus"),
        )
        conn.execute(
            "UPDATE species SET taxonomic_status=? WHERE scientific_name=?", (status, name)
        )
    conn.commit()
    conn.close()

    counts = database.get_children_letter_counts("Fabaceae")
    assert counts == {"A": 1}   # Albizia excluded as SYNONYM
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd backend && pytest tests/test_database.py::test_get_children_letter_counts_groups_by_first_letter tests/test_database.py::test_get_children_letter_counts_excludes_synonyms -v
```
Expected: FAIL with `AttributeError: module 'app.database' has no attribute 'get_children_letter_counts'`

- [ ] **Step 3: Implement `get_children_letter_counts` in `database.py`**

Add after `count_children` (around line 169):

```python
def get_children_letter_counts(parent_path: str) -> dict[str, int]:
    """Return a {letter: count} map for non-SYNONYM direct children.

    Uses the (taxon_depth, taxon_path) index for a fast range-scan.
    Names that do not start with A–Z are grouped under '#'.
    """
    conn = get_connection()
    try:
        child_depth = parent_path.count("|") + 1
        offset      = len(parent_path) + 2   # 1-indexed; skip "parent_path|"
        lo          = parent_path + "|"
        hi          = parent_path + chr(ord("|") + 1)
        rows = conn.execute(
            """
            SELECT upper(substr(taxon_path, ?, 1)) AS letter, count(*) AS cnt
            FROM   species
            WHERE  taxon_depth = ?
              AND  taxon_path  >= ?
              AND  taxon_path  <  ?
              AND  taxonomic_status != 'SYNONYM'
            GROUP  BY letter
            ORDER  BY letter
            """,
            (offset, child_depth, lo, hi),
        ).fetchall()
        result: dict[str, int] = {}
        for letter, cnt in rows:
            key = letter if (letter and letter.isalpha()) else "#"
            result[key] = result.get(key, 0) + cnt
        return dict(sorted(result.items()))
    finally:
        conn.close()
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd backend && pytest tests/test_database.py::test_get_children_letter_counts_groups_by_first_letter tests/test_database.py::test_get_children_letter_counts_excludes_synonyms -v
```
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/database.py backend/tests/test_database.py
git commit -m "feat: add get_children_letter_counts DB helper"
```

---

## Task 2: `get_children_by_letter` DB helper

**Files:**
- Modify: `backend/app/database.py`
- Test: `backend/tests/test_database.py`

- [ ] **Step 1: Write the failing test**

```python
# In backend/tests/test_database.py, append:

def test_get_children_by_letter_returns_matching_children(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    conn = database.get_connection()
    for name, path in [
        ("Fabaceae",  "Fabaceae"),
        ("Acacia",    "Fabaceae|Acacia"),
        ("Albizia",   "Fabaceae|Albizia"),
        ("Bauhinia",  "Fabaceae|Bauhinia"),
    ]:
        conn.execute(
            "INSERT INTO species (scientific_name, taxon_path, taxon_rank, taxonomic_status) VALUES (?,?,'genus','ACCEPTED')",
            (name, path),
        )
    conn.commit()
    conn.close()

    rows = database.get_children_by_letter("Fabaceae", "A")
    names = {r["scientific_name"] for r in rows}
    assert names == {"Acacia", "Albizia"}

    rows = database.get_children_by_letter("Fabaceae", "B")
    assert {r["scientific_name"] for r in rows} == {"Bauhinia"}

    rows = database.get_children_by_letter("Fabaceae", "Z")
    assert rows == []
```

- [ ] **Step 2: Run test to verify it fails**

```
cd backend && pytest tests/test_database.py::test_get_children_by_letter_returns_matching_children -v
```
Expected: FAIL with `AttributeError`

- [ ] **Step 3: Implement `get_children_by_letter`**

Add immediately after `get_children_letter_counts`:

```python
def get_children_by_letter(parent_path: str, letter: str) -> list[dict]:
    """Return non-SYNONYM direct children whose name starts with `letter`.

    Pass letter='#' to get children whose first character is not A–Z.
    """
    conn = get_connection()
    try:
        child_depth = parent_path.count("|") + 1
        offset      = len(parent_path) + 2
        lo          = parent_path + "|"
        hi          = parent_path + chr(ord("|") + 1)
        letter_up   = letter.upper()
        if letter_up == "#":
            sql = """
                SELECT * FROM species
                WHERE  taxon_depth = ?
                  AND  taxon_path  >= ?
                  AND  taxon_path  <  ?
                  AND  (upper(substr(taxon_path, ?, 1)) < 'A'
                        OR upper(substr(taxon_path, ?, 1)) > 'Z')
                  AND  taxonomic_status != 'SYNONYM'
            """
            params: list = [child_depth, lo, hi, offset, offset]
        else:
            sql = """
                SELECT * FROM species
                WHERE  taxon_depth = ?
                  AND  taxon_path  >= ?
                  AND  taxon_path  <  ?
                  AND  upper(substr(taxon_path, ?, 1)) = ?
                  AND  taxonomic_status != 'SYNONYM'
            """
            params = [child_depth, lo, hi, offset, letter_up]
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()
```

- [ ] **Step 4: Run test to verify it passes**

```
cd backend && pytest tests/test_database.py::test_get_children_by_letter_returns_matching_children -v
```
Expected: 1 passed

- [ ] **Step 5: Run full backend test suite to check for regressions**

```
cd backend && pytest tests/ -v
```
Expected: all existing tests pass + 3 new ones

- [ ] **Step 6: Commit**

```bash
git add backend/app/database.py backend/tests/test_database.py
git commit -m "feat: add get_children_by_letter DB helper"
```

---

## Task 3: Orphan letter-count helpers (for `taxonomy_unclassified`)

**Files:**
- Modify: `backend/app/database.py`
- Test: `backend/tests/test_database.py`

- [ ] **Step 1: Write the failing tests**

```python
# In backend/tests/test_database.py, append:

def _insert_species(conn, name, path, rank="genus", status="ACCEPTED"):
    conn.execute(
        "INSERT INTO species (scientific_name, taxon_path, taxon_rank, taxonomic_status) VALUES (?,?,?,?)",
        (name, path, rank, status),
    )


def test_get_orphan_letter_counts(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    conn = database.get_connection()
    _insert_species(conn, "Viruses", "Viruses", "kingdom")
    # expected rank for kingdom children is "phylum"; these are orphans (rank "family")
    _insert_species(conn, "Adenoviridae",  "Viruses|Adenoviridae",  "family")
    _insert_species(conn, "Astroviridae",  "Viruses|Astroviridae",  "family")
    _insert_species(conn, "Bunyaviridae",  "Viruses|Bunyaviridae",  "family")
    conn.commit()
    conn.close()

    expected = frozenset({"phylum"})
    counts = database.get_orphan_letter_counts("Viruses", expected)
    assert counts == {"A": 2, "B": 1}


def test_get_orphan_children_by_letter(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    conn = database.get_connection()
    _insert_species(conn, "Viruses", "Viruses", "kingdom")
    _insert_species(conn, "Adenoviridae", "Viruses|Adenoviridae", "family")
    _insert_species(conn, "Bunyaviridae", "Viruses|Bunyaviridae", "family")
    conn.commit()
    conn.close()

    expected = frozenset({"phylum"})
    rows = database.get_orphan_children_by_letter("Viruses", expected, "A")
    assert {r["scientific_name"] for r in rows} == {"Adenoviridae"}

    rows = database.get_orphan_children_by_letter("Viruses", expected, "B")
    assert {r["scientific_name"] for r in rows} == {"Bunyaviridae"}
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd backend && pytest tests/test_database.py::test_get_orphan_letter_counts tests/test_database.py::test_get_orphan_children_by_letter -v
```
Expected: FAIL with `AttributeError`

- [ ] **Step 3: Implement both helpers in `database.py`**

Add after `get_children_by_letter`:

```python
def get_orphan_letter_counts(
    parent_path: str,
    expected_ranks: frozenset[str],
) -> dict[str, int]:
    """Return a {letter: count} map for orphan (non-expected-rank) direct children."""
    conn = get_connection()
    try:
        child_depth = parent_path.count("|") + 1
        offset      = len(parent_path) + 2
        lo          = parent_path + "|"
        hi          = parent_path + chr(ord("|") + 1)
        ranks_list  = sorted(expected_ranks)
        ph          = ",".join("?" * len(ranks_list))
        rows = conn.execute(
            f"""
            SELECT upper(substr(taxon_path, ?, 1)) AS letter, count(*) AS cnt
            FROM   species
            WHERE  taxon_depth = ?
              AND  taxon_path  >= ?
              AND  taxon_path  <  ?
              AND  (taxon_rank NOT IN ({ph}) OR taxon_rank IS NULL)
              AND  taxonomic_status != 'SYNONYM'
            GROUP  BY letter
            ORDER  BY letter
            """,
            [offset, child_depth, lo, hi] + ranks_list,
        ).fetchall()
        result: dict[str, int] = {}
        for letter, cnt in rows:
            key = letter if (letter and letter.isalpha()) else "#"
            result[key] = result.get(key, 0) + cnt
        return dict(sorted(result.items()))
    finally:
        conn.close()


def get_orphan_children_by_letter(
    parent_path: str,
    expected_ranks: frozenset[str],
    letter: str,
    depth: int = 1,
) -> list[dict]:
    """Return orphan direct children whose name starts with `letter`."""
    conn = get_connection()
    try:
        child_depth = parent_path.count("|") + 1
        offset      = len(parent_path) + 2
        lo          = parent_path + "|"
        hi          = parent_path + chr(ord("|") + 1)
        ranks_list  = sorted(expected_ranks)
        ph          = ",".join("?" * len(ranks_list))
        letter_up   = letter.upper()
        if letter_up == "#":
            letter_filter = f"AND (upper(substr(taxon_path, ?, 1)) < 'A' OR upper(substr(taxon_path, ?, 1)) > 'Z')"
            letter_params: list = [offset, offset]
        else:
            letter_filter = "AND upper(substr(taxon_path, ?, 1)) = ?"
            letter_params = [offset, letter_up]
        sql = f"""
            SELECT * FROM species
            WHERE  taxon_depth = ?
              AND  taxon_path  >= ?
              AND  taxon_path  <  ?
              AND  (taxon_rank NOT IN ({ph}) OR taxon_rank IS NULL)
              AND  taxonomic_status != 'SYNONYM'
              {letter_filter}
        """
        params: list = [child_depth, lo, hi] + ranks_list + letter_params
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd backend && pytest tests/test_database.py::test_get_orphan_letter_counts tests/test_database.py::test_get_orphan_children_by_letter -v
```
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/database.py backend/tests/test_database.py
git commit -m "feat: add orphan letter-count and letter-filter DB helpers"
```

---

## Task 4: `_alpha_sentinels` helper + `/api/taxonomy/alpha` endpoint + modify `taxonomy_zoom`

**Files:**
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_taxonomy_api.py`

- [ ] **Step 1: Write the failing tests**

```python
# In backend/tests/test_taxonomy_api.py, append:

def _insert_many_genera(parent_path, count, taxon_rank_parent="family"):
    """Insert a parent node + `count` genus children under it."""
    parent_name = parent_path.rsplit("|", 1)[-1] if "|" in parent_path else parent_path
    _insert(parent_name, parent_path, taxon_rank=taxon_rank_parent)
    for i in range(count):
        name = f"Genus{i:03d}"
        _insert(name, f"{parent_path}|{name}", taxon_rank="genus")


def test_zoom_returns_alpha_nodes_when_over_limit():
    _insert_many_genera("Fabaceae", 201)

    resp = client.get("/api/taxonomy/zoom?node_id=Fabaceae&depth=1")
    assert resp.status_code == 200
    nodes = resp.json()
    ranks = {n["rank"] for n in nodes}
    assert "alpha" in ranks
    assert "genus" not in ranks
    alpha_nodes = [n for n in nodes if n["rank"] == "alpha"]
    assert all(n["node_id"].startswith("__alpha__Fabaceae|") for n in alpha_nodes)
    assert all(n["name"].startswith("[") for n in alpha_nodes)


def test_zoom_shows_all_children_when_under_limit():
    _insert_many_genera("Rosaceae", 5)

    resp = client.get("/api/taxonomy/zoom?node_id=Rosaceae&depth=1")
    assert resp.status_code == 200
    nodes = resp.json()
    assert all(n["rank"] == "genus" for n in nodes)
    assert len(nodes) == 5


def test_alpha_endpoint_returns_children_for_letter():
    _insert("Fabaceae", "Fabaceae", taxon_rank="family")
    _insert("Acacia",   "Fabaceae|Acacia",   taxon_rank="genus")
    _insert("Albizia",  "Fabaceae|Albizia",  taxon_rank="genus")
    _insert("Bauhinia", "Fabaceae|Bauhinia", taxon_rank="genus")

    resp = client.get("/api/taxonomy/alpha?node_id=Fabaceae&letter=A")
    assert resp.status_code == 200
    names = {n["name"] for n in resp.json()}
    assert names == {"Acacia", "Albizia"}

    resp = client.get("/api/taxonomy/alpha?node_id=Fabaceae&letter=Z")
    assert resp.status_code == 200
    assert resp.json() == []
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd backend && pytest tests/test_taxonomy_api.py::test_zoom_returns_alpha_nodes_when_over_limit tests/test_taxonomy_api.py::test_alpha_endpoint_returns_children_for_letter -v
```
Expected: FAIL (404 on `/api/taxonomy/alpha`, no `alpha` rank in zoom)

- [ ] **Step 3: Add `_alpha_sentinels` helper and `GET /api/taxonomy/alpha` endpoint to `main.py`**

Add `_alpha_sentinels` after `_CHILD_LIMIT = 200` (around line 223):

```python
def _alpha_sentinels(parent_path: str, letter_counts: dict[str, int]) -> list[TaxonNode]:
    """Build alpha-group sentinel nodes from a {letter: count} map."""
    return [
        TaxonNode(
            node_id=f"__alpha__{parent_path}|{letter}",
            name=f"[{letter}] ({count:,})",
            rank="alpha",
        )
        for letter, count in sorted(letter_counts.items())
    ]
```

Add the new endpoint after `taxonomy_unclassified` (after line ~309):

```python
@app.get("/api/taxonomy/alpha", response_model=list[TaxonNode])
def taxonomy_alpha(
    node_id: str = Query(..., description="taxon_path of the parent node"),
    letter: str  = Query(..., min_length=1, max_length=1),
):
    """Return children of node_id whose name starts with `letter`.

    Applies the same structural-SYNONYM filter as taxonomy_zoom so that
    SYNONYM genus nodes with ACCEPTED descendants are included.
    """
    rows = database.get_children_by_letter(node_id, letter)
    non_synonym = [r for r in rows if r.get("taxonomic_status") != "SYNONYM"]
    synonym_genera = [
        r for r in rows
        if r.get("taxonomic_status") == "SYNONYM"
        and r.get("taxon_rank") in ("genus", "subgenus")
    ]
    if synonym_genera:
        active = database.paths_with_accepted_descendants(
            [r["taxon_path"] for r in synonym_genera if r.get("taxon_path")]
        )
        non_synonym += [r for r in synonym_genera if r.get("taxon_path") in active]
    return _build_tree(non_synonym, node_id)
```

- [ ] **Step 4: Modify `taxonomy_zoom` to emit alpha sentinels**

In `taxonomy_zoom`, in the `if expected_all:` branch, add the alpha-group check **immediately after** `nodes = _build_tree(rows, node_id)` (before the `if expected_d1:` block):

```python
        nodes = _build_tree(rows, node_id)

        # Alpha-group when depth=1 result exceeds the child limit
        if depth == 1 and len(nodes) > _CHILD_LIMIT:
            alpha = _alpha_sentinels(node_id, database.get_children_letter_counts(node_id))
            if expected_d1:
                orphan_count = database.count_orphan_children(node_id, expected_d1, depth=1)
                if orphan_count > 0:
                    alpha.append(TaxonNode(
                        node_id=f"__unclassified__{node_id}",
                        name=f"[Unclassified] ({orphan_count:,})",
                        rank="unclassified",
                    ))
            return alpha

        if expected_d1:   # ← existing line, unchanged
```

In the `else:` branch, replace the `__more__` sentinel block:

```python
    else:
        total = database.count_children(node_id, depth=1)
        if total > _CHILD_LIMIT:
            return _alpha_sentinels(node_id, database.get_children_letter_counts(node_id))
        rows  = database.get_children(node_id, depth=depth, limit=_CHILD_LIMIT)
        rows  = [r for r in rows if r.get("taxonomic_status") != "SYNONYM"]
        nodes = _build_tree(rows, node_id)
    return nodes
```

(The old `if total > _CHILD_LIMIT: nodes.append(TaxonNode(node_id="__more__..."))` block is deleted.)

- [ ] **Step 5: Run tests**

```
cd backend && pytest tests/test_taxonomy_api.py -v
```
Expected: all existing tests pass + 3 new tests pass

- [ ] **Step 6: Run full backend suite**

```
cd backend && pytest tests/ -v
```
Expected: all tests pass

- [ ] **Step 7: Commit**

```bash
git add backend/app/main.py backend/tests/test_taxonomy_api.py
git commit -m "feat: alpha sentinels in taxonomy_zoom + /api/taxonomy/alpha endpoint"
```

---

## Task 5: Modify `taxonomy_unclassified` to emit alpha sentinels

**Files:**
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_taxonomy_api.py`

- [ ] **Step 1: Write the failing test**

```python
# In backend/tests/test_taxonomy_api.py, append:

def test_unclassified_returns_alpha_when_over_limit():
    # Viruses kingdom: expected child rank = "phylum"; insert 201 "family" orphans
    _insert("Viruses", "Viruses", taxon_rank="kingdom")
    for i in range(201):
        name = f"Viridae{i:03d}"
        _insert(name, f"Viruses|{name}", taxon_rank="family")

    resp = client.get("/api/taxonomy/unclassified?node_id=Viruses")
    assert resp.status_code == 200
    nodes = resp.json()
    ranks = {n["rank"] for n in nodes}
    assert "alpha" in ranks
    assert "family" not in ranks
    assert all(n["node_id"].startswith("__alpha____unclassified__Viruses|") for n in nodes if n["rank"] == "alpha")


def test_unclassified_letter_param_filters_children():
    _insert("Viruses", "Viruses", taxon_rank="kingdom")
    _insert("Adenoviridae", "Viruses|Adenoviridae", taxon_rank="family")
    _insert("Bunyaviridae", "Viruses|Bunyaviridae", taxon_rank="family")

    resp = client.get("/api/taxonomy/unclassified?node_id=Viruses&letter=A")
    assert resp.status_code == 200
    names = {n["name"] for n in resp.json()}
    assert names == {"Adenoviridae"}
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd backend && pytest tests/test_taxonomy_api.py::test_unclassified_returns_alpha_when_over_limit tests/test_taxonomy_api.py::test_unclassified_letter_param_filters_children -v
```
Expected: FAIL

- [ ] **Step 3: Modify `taxonomy_unclassified` in `main.py`**

Replace the entire `taxonomy_unclassified` function with:

```python
@app.get("/api/taxonomy/unclassified", response_model=list[TaxonNode])
def taxonomy_unclassified(
    node_id: str = Query(..., description="taxon_path of the parent node"),
    offset: int  = Query(0, ge=0),
    letter: str | None = Query(None, min_length=1, max_length=1),
):
    """Return orphaned (non-expected-rank) children of a node.

    When `letter` is provided, return only children starting with that letter.
    When total orphan count exceeds _CHILD_LIMIT, return alpha-group sentinels
    instead of raw children (unless `letter` is provided).
    """
    parent_row  = database.get_taxon_by_path(node_id)
    parent_rank = (parent_row.get("taxon_rank") or "") if parent_row else ""
    expected    = _EXPECTED_CHILD_RANKS.get(parent_rank)
    if not expected:
        return []

    if letter:
        rows = database.get_orphan_children_by_letter(node_id, expected, letter, depth=1)
        return _build_tree(rows, node_id)

    total = database.count_orphan_children(node_id, expected, depth=1)
    if total > _CHILD_LIMIT:
        return _alpha_sentinels(
            f"__unclassified__{node_id}",
            database.get_orphan_letter_counts(node_id, expected),
        )

    rows  = database.get_orphan_children(node_id, expected, depth=1,
                                         limit=_CHILD_LIMIT, offset=offset)
    return _build_tree(rows, node_id)
```

- [ ] **Step 4: Run tests**

```
cd backend && pytest tests/test_taxonomy_api.py -v
```
Expected: all tests pass

- [ ] **Step 5: Run full backend suite**

```
cd backend && pytest tests/ -v
```
Expected: all tests pass (89+ passing)

- [ ] **Step 6: Commit**

```bash
git add backend/app/main.py backend/tests/test_taxonomy_api.py
git commit -m "feat: alpha sentinels in taxonomy_unclassified + letter filter param"
```

---

## Task 6: Frontend — `loadNode` routing + `_render`/`_onClick` alpha styling

**Files:**
- Modify: `frontend/js/visualizer.js`
- Test: `frontend/tests/visualizer.test.js`

- [ ] **Step 1: Write the failing test**

```js
// In frontend/tests/visualizer.test.js, add inside describe('loadNode', ...) :

it('routes __alpha__ node to /api/taxonomy/alpha with parent and letter', async () => {
  global.fetch = mockFetch([]);
  await loadNode('__alpha__Animalia|Arthropoda|Insecta|Hymenoptera|Apidae|A');
  const url = global.fetch.mock.calls[0][0];
  expect(url).toContain('/api/taxonomy/alpha');
  expect(url).toContain('node_id=');
  expect(url).toContain('Apidae');
  expect(url).toContain('letter=A');
});

it('routes __alpha____unclassified__ node to /api/taxonomy/unclassified with letter', async () => {
  global.fetch = mockFetch([]);
  await loadNode('__alpha____unclassified__Viruses|A');
  const url = global.fetch.mock.calls[0][0];
  expect(url).toContain('/api/taxonomy/unclassified');
  expect(url).toContain('node_id=Viruses');
  expect(url).toContain('letter=A');
});
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd frontend && npm test -- --reporter=verbose 2>&1 | grep -A3 "routes __alpha"
```
Expected: FAIL

- [ ] **Step 3: Modify `loadNode` in `visualizer.js`**

Replace the current `loadNode` function body (lines 394–411) with:

```js
export async function loadNode(taxonPath) {
  let url;
  if (!taxonPath) {
    url = `${API}/api/taxonomy/root`;
  } else if (taxonPath.startsWith('__alpha__')) {
    const inner    = taxonPath.slice('__alpha__'.length);
    const lastPipe = inner.lastIndexOf('|');
    const parent   = inner.slice(0, lastPipe);
    const letter   = inner.slice(lastPipe + 1);
    if (parent.startsWith('__unclassified__')) {
      const actualPath = parent.slice('__unclassified__'.length);
      url = `${API}/api/taxonomy/unclassified?node_id=${encodeURIComponent(actualPath)}&letter=${encodeURIComponent(letter)}`;
    } else {
      url = `${API}/api/taxonomy/alpha?node_id=${encodeURIComponent(parent)}&letter=${encodeURIComponent(letter)}`;
    }
  } else if (taxonPath.startsWith('__unclassified__')) {
    const parentPath = taxonPath.slice('__unclassified__'.length);
    url = `${API}/api/taxonomy/unclassified?node_id=${encodeURIComponent(parentPath)}`;
  } else {
    url = `${API}/api/taxonomy/zoom?node_id=${encodeURIComponent(taxonPath)}&depth=1`;
  }
  try {
    const res = await fetch(url);
    if (!res.ok) return [];
    return res.json();
  } catch {
    return [];
  }
}
```

- [ ] **Step 4: Update `_render` and `_onClick` for alpha nodes**

In `_render` (around line 683), add `isAlpha` alongside `isSentinel` and `isUnclassified`:

```js
  const isSentinel      = d => d.data.rank === 'more';
  const isUnclassified  = d => d.data.rank === 'unclassified';
  const isAlpha         = d => d.data.rank === 'alpha';
```

Update the three places that use `isSentinel`/`isUnclassified` to also include `isAlpha`:

```js
// circle fill (line ~722):
  .attr('fill', d => {
    if (isSentinel(d) || isUnclassified(d) || isAlpha(d)) return '#374151';
    if (d.data.node_id === _selectedNodeId) return '#f59e0b';
    return (d.data._children || d.data._pathOnly) ? '#6b7280' : (RANK_COLOR[d.data.rank] || '#9ca3af');
  })

// text fill (line ~731):
  .attr('fill', d => (isSentinel(d) || isUnclassified(d) || isAlpha(d)) ? '#6b7280' : '#e5e7eb')
  .attr('font-style', d => (isSentinel(d) || isUnclassified(d) || isAlpha(d)) ? 'italic' : 'normal')
```

In `_onClick` (line 738), add `alpha` to the early-return guard:

```js
  if (data.rank === 'root' || data.rank === 'more') return;
```
becomes:
```js
  if (data.rank === 'root' || data.rank === 'more') return;
```
(No change here — alpha nodes should expand/collapse normally via the existing lazy-load logic.)

Find the "Confirmed leaf" section (line ~775) and update the synthetic-node guard:

```js
    // No children → confirmed leaf: show detail panel (skip synthetic nodes)
    if (data.rank === 'unclassified') return;
```
becomes:
```js
    if (data.rank === 'unclassified' || data.rank === 'alpha') return;
```

- [ ] **Step 5: Run frontend tests**

```
cd frontend && npm test
```
Expected: 29 existing + 2 new = 31 passed

- [ ] **Step 6: Commit**

```bash
git add frontend/js/visualizer.js frontend/tests/visualizer.test.js
git commit -m "feat: loadNode alpha routing + alpha node styling in _render/_onClick"
```

---

## Task 7: Frontend — `expandToNode` alpha drilling

**Files:**
- Modify: `frontend/js/visualizer.js`
- Test: `frontend/tests/visualizer.test.js`

- [ ] **Step 1: Write the failing test**

```js
// In frontend/tests/visualizer.test.js, add inside describe('expandToNode', ...):

it('drills through alpha group automatically when navigating to a species', async () => {
  const kingdoms = [{ node_id: 'K', name: 'K', rank: 'kingdom', common_names: [], children: [] }];
  const kAlpha   = [{ node_id: '__alpha__K|A', name: '[A] (2)', rank: 'alpha', common_names: [], children: [] }];
  const alphaA   = [{ node_id: 'K|Apis', name: 'Apis', rank: 'genus', common_names: [], children: [] }];
  const apisKids = [
    { node_id: 'K|Apis|Apis cerana',    name: 'Apis cerana',    rank: 'species', common_names: [], children: [] },
    { node_id: 'K|Apis|Apis mellifera', name: 'Apis mellifera', rank: 'species', common_names: [], children: [] },
  ];

  global.fetch = vi.fn().mockImplementation((url) => {
    if (url.includes('root'))
      return Promise.resolve({ ok: true, json: async () => kingdoms });
    if (url.includes('zoom') && url.includes('node_id=K&'))
      return Promise.resolve({ ok: true, json: async () => kAlpha });
    if (url.includes('alpha') && url.includes('letter=A'))
      return Promise.resolve({ ok: true, json: async () => alphaA });
    if (url.includes('zoom') && url.includes('K%7CApis'))
      return Promise.resolve({ ok: true, json: async () => apisKids });
    // node injection fallback
    return Promise.resolve({ ok: true, json: async () => apisKids[0] });
  });

  document.body.innerHTML = '<div id="alpha-drill" style="width:800px;height:600px"></div>';
  await initTree('alpha-drill');

  await expandToNode('K|Apis|Apis cerana');

  // /api/taxonomy/alpha must have been called for letter A
  const alphaCalls = global.fetch.mock.calls.filter(([url]) => url.includes('/api/taxonomy/alpha'));
  expect(alphaCalls.length).toBeGreaterThanOrEqual(1);
  expect(alphaCalls[0][0]).toContain('letter=A');

  // zoom for direct parent Apis must have been called once
  const parentCalls = global.fetch.mock.calls.filter(
    ([url]) => url.includes('zoom') && url.includes('K%7CApis') && !url.includes('K%7CApis%7C')
  );
  expect(parentCalls).toHaveLength(1);
});
```

- [ ] **Step 2: Run test to verify it fails**

```
cd frontend && npm test -- --reporter=verbose 2>&1 | grep -A5 "drills through alpha"
```
Expected: FAIL (alpha endpoint not called)

- [ ] **Step 3: Add `_drillAlpha` internal function to `visualizer.js`**

Add this new function immediately before `_freshNode` (around line 602):

```js
/**
 * If `current`'s loaded children are all alpha-group nodes, find the one
 * matching the first letter of the last segment of `partialPath`, load its
 * children, and return the child node whose node_id equals `partialPath`.
 * Returns null if current has no alpha children or no match is found.
 */
async function _drillAlpha(current, partialPath) {
  const allKids = [...(current.children || []), ...(current._children || [])];
  if (!allKids.length || !allKids.every(c => c.node_id.startsWith('__alpha__'))) return null;

  const lastSeg  = partialPath.split('|').pop();
  const ch       = lastSeg?.[0]?.toUpperCase() ?? '';
  const letter   = /^[A-Z]$/.test(ch) ? ch : '#';
  const alphaId  = `__alpha__${current.node_id}|${letter}`;
  let   alphaNode = allKids.find(c => c.node_id === alphaId);
  if (!alphaNode) return null;

  // Ensure alpha node is in visible (non-collapsed) children
  if (!current.children) current.children = [];
  if (!current.children.includes(alphaNode)) {
    current._children = (current._children || []).filter(c => c !== alphaNode);
    if (!current._children.length) current._children = null;
    current.children.push(alphaNode);
  }

  // Load alpha bucket on demand
  if (!alphaNode._loaded) {
    const loaded      = await loadNode(alphaNode.node_id);
    alphaNode._loaded = true;
    alphaNode.children = loaded.length ? loaded.map(_freshNode) : null;
  } else if (alphaNode._children && !alphaNode.children) {
    alphaNode.children  = alphaNode._children;
    alphaNode._children = null;
  }

  return (alphaNode.children || []).find(c => c.node_id === partialPath) ?? null;
}
```

- [ ] **Step 4: Wire `_drillAlpha` into `expandToNode`**

In `expandToNode`, there are **two** places where `target` may be null after a search. Add the drill call in both.

**First location** — after the initial `allKids.find` (line ~467):

```js
    let target = allKids.find(c => c.node_id === partialPath);

    if (!target) {
      // Try alpha drilling before attempting a stale-refresh or injection
      target = await _drillAlpha(current, partialPath);
    }

    if (!target) {
      // Not in the tree yet — if parent was stale-loaded, re-fetch it first
      if (current._loaded && current.node_id !== '__root__') {
```

**Second location** — after the stale-refresh lookup (line ~478, inside the stale-refresh block):

```js
          target = current.children.find(c => c.node_id === partialPath);
          if (!target) {
            target = await _drillAlpha(current, partialPath);
          }
```

- [ ] **Step 5: Run frontend tests**

```
cd frontend && npm test
```
Expected: 31 existing + 1 new = 32 passed

- [ ] **Step 6: Run full test suite**

```
cd backend && pytest tests/ -v
```
Expected: all backend tests still pass (no regressions)

- [ ] **Step 7: Commit**

```bash
git add frontend/js/visualizer.js frontend/tests/visualizer.test.js
git commit -m "feat: expandToNode drills through alpha groups automatically"
```

---

## Task 8: Final verification

- [ ] **Step 1: Run the complete test suite one final time**

```
cd backend && pytest tests/ -v
cd frontend && npm test
```
Expected: all backend tests pass (91+), all frontend tests pass (32+)

- [ ] **Step 2: Verify `__more__` sentinel is gone from the codebase**

```
grep -rn "__more__" backend/app/ frontend/js/
```
Expected: zero matches (the sentinel is fully retired)

- [ ] **Step 3: Start the backend and do a manual smoke test**

```
cd backend && uvicorn app.main:app --reload --port 8000
```

Open `http://localhost:8000` in a browser. Navigate to a large family (e.g. search "Apidae", expand it). Confirm:
- Alpha letter nodes `[A] (N)` appear instead of `+N more`
- Clicking `[A]` expands it and shows genera beginning with A
- Searching "Apis cerana" and clicking the result navigates through the alpha layer automatically
- Clicking a `_pathOnly` intermediate node (gray circle) loads all siblings

- [ ] **Step 4: Commit final state with plan check-off note**

```bash
git add .
git commit -m "feat: complete alpha-grouping — A-Z letter nodes replace +N more sentinel"
```
