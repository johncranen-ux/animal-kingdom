# GBIF Ranges Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import wild-record geographic ranges for ~168k animal species from the finished GBIF SQL download, and let the chat rank species by how far north or south they reach.

**Architecture:** A small shared module (`geo_range.py`) holds the range rules: minimum records, percentile edges, and dropping longitude across the 180° line. A one-off data script reads the download CSV and writes `geo_bounding_box` plus provenance in short transactions, with a backup. The ranking query gains two JSON-derived "traits" (`lat_max`, `lat_south`). The panel and the chat show latitude-only ranges cleanly. The on-demand GBIF fallback uses the same wild filters and percentile rule.

**Tech Stack:** Python 3.12, SQLite (`json_extract`), FastAPI/LangChain tools, vanilla JS + Vitest.

**Spec:** `Docs/PLAN.md`, section "Increment 24 — GBIF Ranges". The user accepted its proposed decisions on 2026-11-11 by asking for this plan.

## Global Constraints

- Download file: `E:/AnimalKingdomSystem/gbif_ranges/0001920-261110092616502.csv`, tab-separated, columns `specieskey species n countries lat_min lat_max lon_min lon_max`. DOI `10.15468/dl.5v8cu8`.
- Minimum wild records for a range: **10** (`geo_range.MIN_RECORDS`).
- Longitude span over **340°** → store latitude only (`geo_range.WRAP_SPAN`).
- Edges are the **0.5% / 99.5%** percentiles (`geo_range.Q_LOW = 0.005`, `geo_range.Q_HIGH = 0.995`), with linear interpolation like SQL `PERCENTILE_CONT`.
- Stored JSON keys: `lat_min`, `lat_max`, optionally `lon_min`/`lon_max`, `records`, optionally `countries`. Values are rounded to 2 decimals.
- Import provenance: `trait_sources["geo_bounding_box"] = {"source": "GBIF occurrences (wild records, 0.5% edges, doi:10.15468/dl.5v8cu8)", "estimated": false}`.
- Fallback provenance: `"GBIF occurrences (wild sample)"`.
- Skip extinct species (`extinct = 1`) and rows outside the tree (`taxon_path IS NULL`, GBIF_ONLY).
- A synonym's range goes to its `accepted_name` row, unless that species has its own range in the file. Among several synonyms, the one with the most records wins.
- Replace existing ranges. Back up every replaced row to `E:/AnimalKingdomSystem/gbif_ranges_backup.jsonl` as `{"scientific_name", "geo_bounding_box", "trait_sources"}`.
- Bulk writes in short transactions (batches of 1,000), never one long transaction: the user's backend may be running.
- E2E runs only on port 8031, never 8010. Don't restart the user's backend.
- Wild filter for the on-demand fallback (REST API): `basisOfRecord=HUMAN_OBSERVATION&basisOfRecord=MACHINE_OBSERVATION`, `occurrenceStatus=PRESENT`, `hasCoordinate=true`, `hasGeospatialIssue=false`. The REST API accepts PRESENT; only the SQL table needs DETECTED.

## Review Focus

1. **Latitude-only ranges** (polar bear, Snares penguin) must never show "undefined", "None" or an empty longitude in the panel or the chat. Tests in Task 3.
2. **Malformed ranges:** rows whose `geo_bounding_box` is `'{}'` or has no `lat_max` (the old fallback wrote such rows) must not rank, and must not count as having a range. Test in Task 4: filter on the extracted value, not on the column being non-NULL.
3. **A chat answer quoting "5.2°S"** for a ranked species must keep its "Database:" label. LabelChecker compares numbers without sign, so the tool output must contain 5.2. Test in Task 4.
4. **Rerunning the import** after a partial run must skip rows that already hold the new range, so the backup doesn't record imported values as "old". Test in Task 2.
5. **Homonym keys** `Name [Parent]` and names that exist only as GBIF_ONLY rows must never receive a range meant for another row. A GBIF name matches only an exact `scientific_name`. Test in Task 2.

---

### Task 1: Shared range rules — `geo_range.py`

**Files:**
- Create: `backend/app/geo_range.py`
- Test: `backend/tests/test_geo_range.py`

**Interfaces:**
- Produces:
  - `MIN_RECORDS = 10`, `WRAP_SPAN = 340.0`, `Q_LOW = 0.005`, `Q_HIGH = 0.995`;
  - `percentile(values: Sequence[float], q: float) -> float`;
  - `make_range(lat_min: float, lat_max: float, lon_min: float, lon_max: float, records: int, countries: int | None = None) -> dict`.

- [ ] **Step 1: Write the failing tests**

```python
from app import geo_range

def test_percentile_interpolates_like_percentile_cont():
    assert geo_range.percentile([1, 2, 3, 4, 5], 0.5) == 3
    assert geo_range.percentile([0, 10], 0.25) == 2.5
    assert geo_range.percentile([7], 0.995) == 7

def test_percentile_ignores_input_order():
    assert geo_range.percentile([5, 1, 3], 0.0) == 1

def test_make_range_rounds_and_keeps_counts():
    assert geo_range.make_range(-38.512, -26.4049, 138.6, 153.6, 350798, 1) == {
        "lat_min": -38.51, "lat_max": -26.4, "lon_min": 138.6, "lon_max": 153.6,
        "records": 350798, "countries": 1}

def test_make_range_drops_longitude_across_the_180_line():
    r = geo_range.make_range(51.6, 83.0, -179.7, 179.4, 4892)
    assert r == {"lat_min": 51.6, "lat_max": 83.0, "records": 4892}

def test_make_range_keeps_a_340_degree_span():
    assert "lon_min" in geo_range.make_range(0, 1, -170, 170, 10)
```

- [ ] **Step 2: Run them, expect failures**

Run: `..\.venv\Scripts\python -m pytest tests/test_geo_range.py -v` (from `backend/`)
Expected: FAIL, `ImportError: cannot import name 'geo_range'`.

- [ ] **Step 3: Implement `geo_range.py`**

- `percentile`: sort the values; position `q * (n - 1)`; interpolate linearly between its neighbours.
- `make_range`: omit `countries` when it is None; drop the lon keys when `lon_max - lon_min > WRAP_SPAN`.

- [ ] **Step 4: Run them, expect PASS**

- [ ] **Step 5: Commit**

```bash
git add backend/app/geo_range.py backend/tests/test_geo_range.py
git commit -m "feat: shared range rules (percentile edges, 180-degree line, minimum records)"
```

---

### Task 2: Import script — `data/import_gbif_ranges.py`

**Files:**
- Create: `data/import_gbif_ranges.py`
- Test: `backend/tests/test_import_gbif_ranges.py`. Use the pattern of `test_fix_common_names.py`: `sys.path` to `data/`, an autouse fixture setting `database.DB_PATH` to `tmp_path`, and an `_add(...)` helper inserting rows as in `test_taxon_queries.py`.

**Interfaces:**
- Consumes: `geo_range.make_range`, `geo_range.MIN_RECORDS`; `database.get_connection`, `database.parse_geo_bbox`, `database.serialize_geo_bbox`, `database.parse_trait_sources`, `database.serialize_trait_sources`.
- Produces:
  - `read_ranges(csv_path: Path, min_records: int = MIN_RECORDS) -> dict[str, dict]`: species name → range dict (from `make_range`; `records` holds n). Rows with n below the minimum or any empty edge are skipped. Of two rows with the same name, the one with more records wins.
  - `match_ranges(conn, ranges: dict[str, dict]) -> tuple[dict[str, dict], Counter]`: target `scientific_name` → range. The Counter keys are `accepted`, `synonym`, `extinct`, `outside_tree`, `no_match`, `synonym_unusable`.
  - `apply_ranges(updates: dict[str, dict], source: str, backup_path: Path, batch: int = 1000) -> int`: rows changed.
  - `main(argv: list[str] | None = None) -> int`, with options `--csv`, `--min-records`, `--doi` (default `10.15468/dl.5v8cu8`), `--backup`, `--dry-run`.

- [ ] **Step 1: Write the failing tests** (CSV written to `tmp_path` with the header from the Global Constraints)

```python
def test_read_ranges_applies_minimum_and_skips_empty_edges(tmp_path):
    # rows: "A a" n=10, "B b" n=9, "C c" n=50 with empty lon_max
    assert list(imp.read_ranges(csv)) == ["A a"]

def test_read_ranges_keeps_the_better_recorded_duplicate(tmp_path):
    # "A a" twice: n=12 lat_max=1, n=40 lat_max=2
    assert imp.read_ranges(csv)["A a"]["lat_max"] == 2

def test_match_accepted_species_in_tree():
    _add("Spheniscus mendiculus", "Animalia|...|Spheniscus mendiculus")
    updates, counts = imp.match_ranges(conn, {"Spheniscus mendiculus": R})
    assert updates == {"Spheniscus mendiculus": R} and counts["accepted"] == 1

def test_match_skips_extinct_and_outside_tree_and_homonym_keys():
    _add("Fossilis x", PATH, extinct=1); _add("Orphan y", None, status="GBIF_ONLY")
    _add("Homonym z [Aves]", PATH)
    updates, counts = imp.match_ranges(conn, {"Fossilis x": R, "Orphan y": R, "Homonym z": R})
    assert updates == {} and counts["extinct"] == 1 and counts["outside_tree"] == 1 and counts["no_match"] == 1

def test_synonym_range_goes_to_accepted_unless_it_has_its_own():
    _add("Old name", PATH, status="SYNONYM", accepted_name="New name"); _add("New name", PATH2)
    updates, _ = imp.match_ranges(conn, {"Old name": R_small})
    assert updates == {"New name": R_small}
    updates, _ = imp.match_ranges(conn, {"Old name": R_small, "New name": R_own})
    assert updates == {"New name": R_own}

def test_of_two_synonyms_the_better_recorded_wins():
    # "Old a" (records 20) and "Old b" (records 90) -> "New name" gets "Old b"'s range

def test_apply_replaces_range_writes_provenance_and_backs_up(tmp_path):
    _add("A a", PATH, geo_bounding_box='{"lat_min": 1, "lat_max": 60}',
         trait_sources='{"habitat_type": {"source": "GBIF", "estimated": false}}')
    assert imp.apply_ranges({"A a": R}, "SRC", tmp_path / "b.jsonl") == 1
    row = _row("A a")
    assert json.loads(row["geo_bounding_box"]) == R
    src = json.loads(row["trait_sources"])
    assert src["geo_bounding_box"] == {"source": "SRC", "estimated": False} and "habitat_type" in src
    assert json.loads((tmp_path / "b.jsonl").read_text().splitlines()[0])["geo_bounding_box"] == '{"lat_min": 1, "lat_max": 60}'

def test_apply_rerun_skips_rows_already_holding_the_range(tmp_path):
    imp.apply_ranges({"A a": R}, "SRC", b)
    assert imp.apply_ranges({"A a": R}, "SRC", b) == 0
    assert len(b.read_text().splitlines()) == 1

def test_dry_run_writes_nothing(tmp_path, capsys):
    assert imp.main(["--csv", str(csv), "--backup", str(b), "--dry-run"]) == 0
    assert _row("A a")["geo_bounding_box"] is None and not b.exists()
    assert "accepted" in capsys.readouterr().out
```

- [ ] **Step 2: Run them, expect failures**

Run: `..\.venv\Scripts\python -m pytest tests/test_import_gbif_ranges.py -v`
Expected: FAIL, `ModuleNotFoundError: import_gbif_ranges`.

- [ ] **Step 3: Implement the script**

- Header docstring with usage and runtime; `sys.path` to `backend/` like the other data scripts.
- `match_ranges` looks up each name by primary key: `SELECT scientific_name, taxonomic_status, taxon_path, extinct, accepted_name FROM species WHERE scientific_name = ?`.
  - Direct ACCEPTED matches go first.
  - Synonyms are resolved second, and only fill targets with no direct range. The target must be ACCEPTED, have a `taxon_path` and not be extinct; otherwise count it as `synonym_unusable`.
- `apply_ranges` works in batches of `batch` names, each a `BEGIN IMMEDIATE` … `commit`:
  - read the current `geo_bounding_box` and `trait_sources`;
  - skip a row when `parse_geo_bbox(current) == new`;
  - otherwise append the backup line, then `UPDATE` both columns, keeping the other `trait_sources` keys.
- `main` prints:
  - the counts table;
  - rows to change (and in a real run, rows changed);
  - elapsed time.
  - With `--dry-run` it opens nothing for writing.
- Source string: `f"GBIF occurrences (wild records, 0.5% edges, doi:{doi})"`.

- [ ] **Step 4: Run them, expect PASS**

- [ ] **Step 5: Commit**

```bash
git add data/import_gbif_ranges.py backend/tests/test_import_gbif_ranges.py
git commit -m "feat: import GBIF wild-record ranges from the SQL download"
```

---

### Task 3: Latitude-only ranges and record counts in the panel and the chat

**Files:**
- Modify: `frontend/js/traits.js` (`_displayValue`, ~line 66)
- Modify: `backend/app/llm_agent.py:165-167` (lookup's "Geographic range" line)
- Test: `frontend/tests/traits.test.js`, `backend/tests/test_llm_agent.py`

**Interfaces:**
- Consumes: the stored JSON keys from the Global Constraints.
- Produces: `llm_agent._range_text(bbox: dict) -> str`, also used by Task 4.

Display format (both places, same text):
- Full: `lat -38.51–-26.4, lon 138.6–153.6 (350,798 wild records)`.
- Latitude only: `lat 51.6–83.0, longitude not recorded (range crosses the 180° line) (4,892 wild records)`.
- Without `records` (old rows): as today, `lat -35–10, lon -18–51`.

- [ ] **Step 1: Write the failing tests**

```js
it('shows a latitude-only range without longitude', () => {
  const text = rowsDom({ geo_bounding_box: { lat_min: 51.6, lat_max: 83, records: 4892 } }).textContent;
  expect(text).toContain('lat 51.6–83, longitude not recorded (range crosses the 180° line) (4,892 wild records)');
  expect(text).not.toMatch(/undefined|null/);
});
it('adds the wild record count to a full range', () => {
  expect(rowsDom({ geo_bounding_box: { lat_min: 1, lat_max: 2, lon_min: 3, lon_max: 4, records: 12 } })
    .textContent).toContain('lat 1–2, lon 3–4 (12 wild records)');
});
```

```python
def test_range_text_latitude_only():
    assert llm_agent._range_text({"lat_min": 51.6, "lat_max": 83.0, "records": 4892}) == \
        "lat 51.6–83.0, longitude not recorded (range crosses the 180° line) (4,892 wild records)"

def test_range_text_old_row_unchanged():
    assert llm_agent._range_text({"lat_min": -35, "lat_max": 10, "lon_min": -18, "lon_max": 51}) == \
        "lat -35–10, lon -18–51"
```

Plus one lookup-output test: a row with a latitude-only range gives `- Geographic range: lat 51.6–83.0, longitude not recorded …` and no "None".

- [ ] **Step 2: Run them, expect failures** (`npm run test` in `frontend/`; pytest `-k range_text` in `backend/`)

- [ ] **Step 3: Implement**

Format the thousands separator with a regex (`/\B(?=(\d{3})+(?!\d))/g`) in JS, not `toLocaleString`, so the output doesn't depend on the locale; in Python use `f"{n:,}"`.

- [ ] **Step 4: Run both suites, expect PASS** (the existing `'lat -35–10, lon -18–51'` test still passes)

- [ ] **Step 5: Commit** `feat: latitude-only ranges and wild record counts in panel and chat`

---

### Task 4: Rank by northern / southern range edge

**Files:**
- Modify: `backend/app/taxon_queries.py:133-160` (`TRAITS`, `rank_by_trait`)
- Modify: `backend/app/llm_agent.py:267-306` (`rank_species_by_trait`)
- Test: `backend/tests/test_taxon_queries.py`, `backend/tests/test_llm_agent.py`

**Interfaces:**
- Consumes: the stored JSON from Task 2.
- Produces:
  - `TRAITS` aliases:
    - `north`, `northern`, `northernmost`, `furthest_north`, `lat_max` → `("lat_max", "°")`;
    - `south`, `southern`, `southernmost`, `furthest_south`, `lat_south` → `("lat_south", "°")`.
  - `RANGE_COLUMNS = frozenset({"lat_max", "lat_south"})`.
  - `rank_by_trait` returns rows that each carry `rank_value: float`, for every trait (existing ones too).
    - `lat_max` is `json_extract(geo_bounding_box, '$.lat_max')`.
    - `lat_south` is `-json_extract(geo_bounding_box, '$.lat_min')`, so "highest" means furthest south.
    - The WHERE clause filters `<expr> IS NOT NULL`.
  - `llm_agent._fmt_lat(lat: float) -> str`: `0.1 → "0.1°N"`, `-5.2 → "5.2°S"`, `0 → "0°"`.

Tool output for a range trait:
- Header: `DATABASE RESULT: FOUND — top 3 by northern range edge among 20 species in Spheniscidae with a recorded range.` Use "southern range edge" for `lat_south`.
- Lines: `- #1 Spheniscus mendiculus (Galápagos penguin): northern range edge 0.1°N`. A `lat_south` value is converted back with `_fmt_lat(-rank_value)`.
- Coverage note, for any order, when n is under half the group's species: `- Coverage note: Only 20 of 48 species in Spheniscidae have a recorded range, so species further north may exist.` Use "further south" for `lat_south`.
- Footer: `END OF DATABASE RESULT. Range edges come from wild GBIF observations, leaving out the outer 0.5% of records, so the true range can reach slightly further. Label these facts "Database:". Species without a recorded range are not ranked — say so if it matters.`
- Docstring: add "how far north or south their range reaches", with traits `'north'` / `'south'` and the use "most northern / furthest south". The "Cannot rank" message lists `lifespan, mass, length, north, south`.

- [ ] **Step 1: Write the failing tests**

```python
# test_taxon_queries.py (seed: Bubo bubo bbox lat -5..70, Tyto alba lat -40..60, Strix perdita '{}')
def test_rank_by_northern_edge(seed_ranges):
    n, rows = taxon_queries.rank_by_trait("lat_max", _OWLS, True, 10)
    assert n == 2 and [r["scientific_name"] for r in rows] == ["Bubo bubo", "Tyto alba"]
    assert rows[0]["rank_value"] == 70

def test_rank_by_southern_edge_highest_is_furthest_south(seed_ranges):
    _, rows = taxon_queries.rank_by_trait("lat_south", _OWLS, True, 10)
    assert rows[0]["scientific_name"] == "Tyto alba" and rows[0]["rank_value"] == 40

def test_rank_by_trait_existing_column_has_rank_value(seed):
    _, rows = taxon_queries.rank_by_trait("max_lifespan", _OWLS, True, 1)
    assert rows[0]["rank_value"] == 68
```

```python
# test_llm_agent.py — via the existing _rank helper; _RANKED rows gain "rank_value"
def test_rank_tool_northern_edge_output(monkeypatch):
    out, calls = _rank(monkeypatch, ranked=(20, [{"scientific_name": "Spheniscus mendiculus",
        "common_names": '["Galápagos penguin"]', "rank_value": 0.1}]), trait="northernmost")
    assert calls[0][0] == "lat_max"
    assert "- #1 Spheniscus mendiculus (Galápagos penguin): northern range edge 0.1°N" in out
    assert "leaving out the outer 0.5% of records" in out

def test_rank_tool_southern_edge_converts_back(monkeypatch):
    # rank_value 77.5 for trait "south" -> "southern range edge 77.5°S"

def test_rank_tool_range_coverage_note_for_highest(monkeypatch):
    # species_count -> 48, n=20 -> "Only 20 of 48 species in Strigiformes have a recorded range, so species further north may exist."

def test_label_checker_keeps_database_label_for_southern_latitude():
    # feed the tool output with "northern range edge 5.2°S" through LabelChecker (as the existing
    # ranking label tests do); the answer "Database: The Humboldt penguin reaches 5.2°S." stays labelled
```

- [ ] **Step 2: Run them, expect failures**

- [ ] **Step 3: Implement**

- Keep `_TRAIT_COLUMNS` validation: the SQL expression comes from a fixed dict `_RANK_EXPR` keyed by column, never from input.
- Existing columns map to themselves.
- Update `_RANKED` in `test_llm_agent.py` to carry `rank_value`.

- [ ] **Step 4: Measure speed on the real DB** (read-only, after Task 6's import or against the current DB)

Run from `backend/`:
`..\.venv\Scripts\python -c "import time;from app import taxon_queries as t;s=time.time();print(t.rank_by_trait('lat_max','Animalia',True,10)[0], time.time()-s)"`

Expected: under 5 s. If slower, add an expression index `CREATE INDEX IF NOT EXISTS idx_species_lat_max ON species(json_extract(geo_bounding_box, '$.lat_max'))` (and the same for `lat_min`) to the import script. Ledger it as a Ruling.

- [ ] **Step 5: Run the backend suite, expect PASS; commit** `feat: rank species by northern or southern range edge`

---

### Task 5: On-demand fallback uses wild records and percentile edges

**Files:**
- Modify: `backend/app/trait_utils.py:320-331` (`gbif_traits`, the range part)
- Test: `backend/tests/test_trait_utils.py`. Replace `test_gbif_bbox_from_occurrences` and `test_gbif_bbox_ignores_null_island_and_requires_points`, which assert the old raw min/max and the 3-point minimum.

**Interfaces:**
- Consumes: `geo_range.percentile`, `make_range`, `MIN_RECORDS`, `Q_LOW`, `Q_HIGH`.
- Produces: `TraitValue(make_range(...), "GBIF occurrences (wild sample)")`.

- [ ] **Step 1: Write the failing tests**

```python
def test_gbif_range_requests_wild_records_only(monkeypatch):
    # capture params of the occurrence/search call
    assert params["basisOfRecord"] == ["HUMAN_OBSERVATION", "MACHINE_OBSERVATION"]
    assert params["occurrenceStatus"] == "PRESENT" and params["hasGeospatialIssue"] == "false"

def test_gbif_range_uses_percentile_edges_and_counts(monkeypatch):
    pts = [(float(i), float(i)) for i in range(1, 11)] + [(53.4, 10.0)]   # 10 wild + 1 outlier
    value = trait_utils.gbif_traits("Panthera leo", _animal_row())["geo_bounding_box"]
    assert value.source == "GBIF occurrences (wild sample)"
    assert value.value["lat_max"] == round(geo_range.percentile([p[0] for p in pts], 0.995), 2)
    assert value.value["records"] == 11

def test_gbif_range_needs_ten_points_after_null_island(monkeypatch):
    # 9 real points + 3 (0, 0) -> no geo_bounding_box
```

- [ ] **Step 2: Run them, expect failures**

- [ ] **Step 3: Implement**

`params` gets the wild filter from the Global Constraints, using a list for `basisOfRecord`. `_get_json` uses `urllib.parse.urlencode(params)`, which would send the list as one string. Change it to `urlencode(params, doseq=True)`; add a test that the URL contains `basisOfRecord=HUMAN_OBSERVATION&basisOfRecord=MACHINE_OBSERVATION`. Keep the null-island filter. `records` = number of points used; `countries` = None.

- [ ] **Step 4: Run the backend suite, expect PASS; commit** `fix: on-demand ranges use wild records and percentile edges`

---

### Task 6: Run the import, live check, docs

**Files:**
- Modify: `Docs/Manual.md` (Rankings row; Optional enrichment section: "GBIF ranges")
- Modify: `Docs/DB_SCHEMA.md` (`geo_bounding_box` keys, `records`, `countries`, latitude-only)
- Modify: `CLAUDE.md` (data-pipeline command line for the import)
- Modify: `Docs/PLAN.md` (Increment 24: Built, results, Data Source Reference row for the GBIF SQL download with the DOI)

- [ ] **Step 1: Dry run on the real DB**

Run from the project root: `.venv\Scripts\python data\import_gbif_ranges.py --dry-run`
Expected: accepted ≈ 167,900 (10+ records), extinct ≈ 700, no errors. Record the table in PLAN.md.

- [ ] **Step 2: Real run**

Run: `.venv\Scripts\python data\import_gbif_ranges.py`
Expected: rows changed ≈ accepted + usable synonyms; backup file written. Rerun → `0` rows changed.

- [ ] **Step 3: Spot checks** (read-only SQL)

- *Spheniscus mendiculus* lat_max 0.1;
- *Spheniscus humboldti* lat_max −5.2;
- *Ursus maritimus* has no `lon_min`;
- *Phascolarctos cinereus* has `records` 350798.

- [ ] **Step 4: Ranking speed** (Task 4 Step 4 command): record the time.

- [ ] **Step 5: Live chat check**

Run: `.venv\Scripts\python data\chat_eval.py "which penguins live furthest north, give the top 3" "what is the northernmost bear" "where does the koala live"`

Expected:
- penguins: `rank_species_by_trait` with a north trait; Galápagos, Humboldt, then Magellanic or African, labelled Database;
- bear: polar bear first;
- koala: range from lookup.

Record the results in PLAN.md, and failures with the reason.

- [ ] **Step 6: Full checks**

- Backend: pytest.
- Frontend: `npm run test`.
- E2E: from the project root, `set AK_PORT=8031 && npx playwright test`. Never port 8010.

Expected: all pass. Record the counts.

- [ ] **Step 7: Docs and commit** `docs: record Increment 24 GBIF ranges`
