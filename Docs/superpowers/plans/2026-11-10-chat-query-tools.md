# Chat Query Tools (Increment 19) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the chat answer name, ranking, counting and relationship questions from the database ("which animal gets oldest", "how many owls are endangered", "what is a whale related to"), and stop a "Database:" label passing on a number the database doesn't hold.

**Architecture:** SQL for the new questions lives in a new `backend/app/taxon_queries.py`, which returns plain dicts. Four thin LangChain tools in `llm_agent.py` turn those dicts into "DATABASE RESULT" text the model reads and `LabelChecker` can parse. `stream_response` feeds every database tool's output to `LabelChecker`, not only `lookup_species`.

**Tech Stack:** Python 3.12, SQLite, LangChain `@tool`, LangGraph `create_react_agent`, Ollama `llama3.1:8b`, pytest.

**Spec:** Agreed in chat on 2026-11-10 and summarised in `Docs/PLAN.md`, Increment 19. The source facts are below.
- **Field coverage.** Out of 2,504,739 accepted species: `max_lifespan` 4,074, `body_mass` 3,612, `body_length` 13, `iucn_status` 170,732, `population_trend` 164,621, `extinct` 1,108,424, `common_names` 192,338. Habitat, diet and activity are almost empty, so no tool filters on them.
- **Query speed** on the live DB: a range scan on `taxon_path` (`>= path||'|'` and `< path||'}'`) counts all of Animalia in 0.8 s, and a ranking query takes 1.1–1.5 s.
- **Thorny devil diagnosis.** The *Moloch horridus* row has `max_lifespan` NULL, and its abstract mentions no age. The sentence "Database: Moloch horridus is a species of lizard that can live up to 20 years in the wild." kept its label through `LabelChecker._supported`'s summary-overlap rule ("species" and "lizard" are summary words), which ignores the unsupported number 20.

## Global Constraints

- Group arguments default to `"Animalia"`, so plants (bristlecone pine, baobab) don't answer animal questions.
- Count and rank only rows with `taxon_rank = 'species'`, `taxonomic_status = 'ACCEPTED'` and a non-NULL `taxon_path`.
- Select descendants with the range form `taxon_path >= ? AND taxon_path < ?` and the values `(path + "|", path + "}")`. Don't use `LIKE`, which is about 40× slower here.
- Every tool result starts with `DATABASE RESULT:` and ends with an `END OF DATABASE RESULT.` line that tells the model how to label what it read, in the same style as `lookup_species`.
- Every list in a tool result is capped (10 by default, never more than 20), so the 8B model's context stays small.
- FastAPI routes don't change. All LLM work stays in `llm_agent.py`, as `CLAUDE.md` requires.
- Run live checks on a private port (`AK_PORT=8031`), never on 8010, which is the user's backend.
- Commit per task, on branch `increment-19-chat-tools`.

## Review Focus

1. **A common name matching several taxa.** For example, "Owls" is the common name of both the family Strigidae and the order Strigiformes. The broadest group (smallest `taxon_depth`) should win. Tested in Task 2.
2. **A group that isn't in the database or is misspelled** ("owlz"). The tool should say "No group found" and tell the model to answer from general knowledge with that label, without raising. Tested in Tasks 3–5.
3. **A trait with few or no values in the group** (`body_length` has 13 in all). The result should state how many species have a value, and say plainly when none do. Tested in Task 3.
4. **Synonym rows and rows outside the tree** (`GBIF_ONLY`, `taxon_path` NULL). They must never appear in counts, rankings or member lists. Tested in Tasks 3–4.
5. **Implausible-looking extremes** (glass sponges at 15,000 years). The result should carry a caveat that values are the maximum recorded or estimated by the source, so the model doesn't present them as certain. Tested in Task 3.

---

### Task 1: LabelChecker rejects unsupported numbers in summary-backed sentences

**Files:**
- Modify: `backend/app/llm_agent.py`: `LabelChecker.__init__`, `add_tool_output` (the `**Summary:**` branch), `_supported`
- Test: `backend/tests/test_llm_agent.py` (next to `test_summary_overlap_counts_as_db_fact`)

**Interfaces:**
- Produces: `LabelChecker._summary_numbers: set[float]`, filled from the numbers in the `**Summary:**` line.

- [ ] **Step 1: Write the failing tests**

```python
_DEVIL = "\n".join([
    "DATABASE RESULT: FOUND — Moloch horridus is in the database.",
    "**Moloch horridus** (species rank)",
    "- Lineage: Animalia → Chordata → Reptilia → Squamata → Agamidae → Moloch → Moloch horridus",
    "\n**Summary:** The thorny devil is a species of lizard in the family Agamidae. "
    "It grows up to 21 cm (8.3 in) in total length.",
])

def test_summary_overlap_with_unsupported_number_is_general_knowledge():
    text = "Database: Moloch horridus is a species of lizard that can live up to 20 years in the wild."
    assert _check(text, _DEVIL) == (
        "From general knowledge: Moloch horridus is a species of lizard "
        "that can live up to 20 years in the wild.")

def test_summary_overlap_with_a_summary_number_keeps_its_label():
    text = "Database: This species of lizard grows up to 21 cm in total length."
    assert _check(text, _DEVIL) == text
```

- [ ] **Step 2: Run them and confirm the first fails**

Run: `cd backend && ..\.venv\Scripts\python -m pytest tests/test_llm_agent.py -k summary -v`
Expected: `test_summary_overlap_with_unsupported_number_is_general_knowledge` FAILS (the label is kept as "Database:"). The other summary tests pass.

- [ ] **Step 3: Implement the change**

In `add_tool_output`, the `**Summary:**` branch also adds `float(n) for n in _NUMBER_RE.findall(line)` to `self._summary_numbers`.

In `_supported`, the summary-overlap branch, and only that branch, returns `"db"` only if every number in the sentence is in `self._numbers | self._est_numbers | self._summary_numbers`. The number-backed and common-name branches stay as they are, so a converted value like "175 kg (386 lb)" keeps its label.

- [ ] **Step 4: Run the whole agent test file**

Run: `cd backend && ..\.venv\Scripts\python -m pytest tests/test_llm_agent.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/llm_agent.py backend/tests/test_llm_agent.py
git commit -m "fix: a summary match can't carry an unsupported number under Database:"
```

---

### Task 2: `find_species`: common name to scientific name, and group resolution

**Files:**
- Create: `backend/app/taxon_queries.py`
- Modify: `backend/app/llm_agent.py`: new tool, `build_agent` tool list, `_SYSTEM_PROMPT`, `stream_response`
- Test: create `backend/tests/test_taxon_queries.py`; modify `backend/tests/test_llm_agent.py`

**Interfaces:**
- Consumes: `database.get_connection()`, `database.get_species(name)`, `database.search_species(query, limit)`, `database.parse_common_names(s)`.
- Produces:
  - `taxon_queries.resolve_taxon(name: str) -> dict | None`. Returns a full row with a non-NULL `taxon_path`. It tries an exact scientific name first (the first word capitalised, the rest lowercase, then the input as given). Next it tries an exact common-name element (`common_names LIKE '%"<name>"%' COLLATE NOCASE`, also trying the singular and plural, i.e. without or with a trailing "s"), preferring the smallest `taxon_depth`. Otherwise it returns None.
  - `taxon_queries.find_matches(name: str, limit: int = 5) -> list[dict]`. Uses `database.search_species(name, limit * 4)`, keeps rows with a `taxon_path` that aren't `SYNONYM`, and returns the first `limit` in search order.
  - Tool `find_species(name: str) -> str`.
  - Module constant `llm_agent._EVIDENCE_TOOLS: frozenset[str]`. Every tool whose output goes to `LabelChecker.add_tool_output`; starts as `{"lookup_species", "find_species"}`.

**Test fixture** (`test_taxon_queries.py`, reused by Tasks 3–5): an autouse `isolated_db` like the one in `test_database.py`, plus a helper `_add(name, path, rank="species", status="ACCEPTED", common="[]", **fields)` that inserts one row. Seed:
- Animalia; Chordata; Aves; the order Strigiformes (`["Owls","Owl"]`); the family Strigidae (`["Owls","True Owls"]`); *Bubo bubo* (`["Eurasian eagle-owl"]`, max_lifespan 68, iucn LC); *Tyto alba* (max_lifespan 34, iucn LC, population_trend "Stable").
- *Strix occidentalis* (iucn NT, population_trend "Decreasing"), plus an EN owl and an extinct owl (extinct=1).
- *Strix ghost*: `taxonomic_status` SYNONYM, max_lifespan 999.
- A GBIF_ONLY row with `taxon_path` NULL and max_lifespan 500.
- Plantae / Pinus longaeva, max_lifespan 5062.

- [ ] **Step 1: Write the failing tests**

```python
def test_resolve_taxon_prefers_broadest_group_for_shared_common_name(seed):
    assert taxon_queries.resolve_taxon("owls")["scientific_name"] == "Strigiformes"

def test_resolve_taxon_scientific_name_any_case(seed):
    assert taxon_queries.resolve_taxon("bubo bubo")["scientific_name"] == "Bubo bubo"

def test_resolve_taxon_singular_common_name(seed):
    assert taxon_queries.resolve_taxon("Owl")["scientific_name"] == "Strigiformes"

def test_resolve_taxon_unknown_is_none(seed):
    assert taxon_queries.resolve_taxon("owlz") is None

def test_find_matches_skips_synonyms_and_rows_outside_tree(seed):
    names = [r["scientific_name"] for r in taxon_queries.find_matches("Strix")]
    assert "Strix ghost" not in names and names
```

In `test_llm_agent.py`, with `taxon_queries.find_matches` monkeypatched:

```python
def test_find_species_lists_matches_with_lineage(monkeypatch): ...
    # assert "DATABASE RESULT: FOUND" in out, "Bubo bubo" in out, "Eurasian eagle-owl" in out,
    # "Lineage:" in out, out.rstrip().endswith(...END OF DATABASE RESULT line...)

def test_find_species_no_match_says_so(monkeypatch): ...
    # find_matches -> []  →  out.startswith("DATABASE RESULT: No species")

async def test_stream_response_feeds_find_species_output_to_label_checker(): ...
    # on_tool_end name="find_species" with a result containing "- Common names: Eurasian eagle-owl"
    # then token "Database: Its name is Eurasian eagle-owl." → label kept
```

Also extend `test_tools_have_correct_names` and `test_tools_have_descriptions` with `find_species`.

- [ ] **Step 2: Run them and confirm they fail**

Run: `cd backend && ..\.venv\Scripts\python -m pytest tests/test_taxon_queries.py tests/test_llm_agent.py -v`
Expected: FAIL with `ModuleNotFoundError: app.taxon_queries` or `ImportError: find_species`.

- [ ] **Step 3: Implement**

Write `resolve_taxon` and `find_matches` as specified in Interfaces.

Output format of `find_species`. A block per match, using the line prefixes `LabelChecker` already parses:

```
DATABASE RESULT: FOUND — 2 matches for 'eagle owl'.
**Bubo bubo** (species rank)
- Common names: Eurasian eagle-owl
- Lineage: Animalia → Chordata → Aves → Strigiformes → Strigidae → Bubo → Bubo bubo
END OF DATABASE RESULT. Use the first match unless another fits the question better; call lookup_species with its scientific name for facts.
```

The docstring says: "Find the scientific name for a common name (e.g. 'eagle owl', 'kangaroo'). Use before lookup_species when the user gives a common name."

Prompt change: replace the sentence "For unlisted common names … call semantic_search_species first, then lookup_species on the best match." with: "For unlisted common names call find_species first, then lookup_species on the best match. Use semantic_search_species only for descriptions without a name ('a striped horse-like animal')."

In `stream_response`, `if tool_name in _EVIDENCE_TOOLS` replaces `if tool_name == "lookup_species"`.

- [ ] **Step 4: Run the backend tests**

Run: `cd backend && ..\.venv\Scripts\python -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/taxon_queries.py backend/app/llm_agent.py backend/tests/test_taxon_queries.py backend/tests/test_llm_agent.py
git commit -m "feat: find_species chat tool resolves common names from the database"
```

---

### Task 3: `rank_species_by_trait`

**Files:**
- Modify: `backend/app/taxon_queries.py`, `backend/app/llm_agent.py`
- Test: `backend/tests/test_taxon_queries.py`, `backend/tests/test_llm_agent.py`

**Interfaces:**
- Consumes: `resolve_taxon` (Task 2), `_EVIDENCE_TOOLS` (Task 2).
- Produces:
  - `taxon_queries.TRAITS: dict[str, tuple[str, str]]`, mapping each alias to `(column, unit)`:
    - `max_lifespan`, `lifespan`, `age`, `oldest`, `longevity` → `("max_lifespan", "years")`
    - `body_mass`, `mass`, `weight`, `heaviest` → `("body_mass", "kg")`
    - `body_length`, `length`, `longest`, `size` → `("body_length", "m")`
  - `taxon_queries.rank_by_trait(column: str, group_path: str, highest: bool, limit: int) -> tuple[int, list[dict]]`. Returns `(number of species in the group with a value, top rows)`, following the Global Constraints filters. `column` must be one of the three TRAITS columns, otherwise `ValueError`.
  - Tool `rank_species_by_trait(trait: str, order: str = "highest", group: str = "Animalia", limit: int = 10) -> str`. `order` is `"highest"` or `"lowest"`; `limit` is clamped to 1–20.

- [ ] **Step 1: Write the failing tests**

```python
def test_rank_by_trait_highest_within_group(seed):
    n, rows = taxon_queries.rank_by_trait("max_lifespan", "Animalia|Chordata|Aves|Strigiformes", True, 10)
    assert [r["scientific_name"] for r in rows][:2] == ["Bubo bubo", "Tyto alba"] and n == 2

def test_rank_by_trait_excludes_synonyms_outside_tree_and_plants(seed):
    _, rows = taxon_queries.rank_by_trait("max_lifespan", "Animalia", True, 10)
    names = {r["scientific_name"] for r in rows}
    assert not names & {"Strix ghost", "Pinus longaeva"} and all(r["taxon_path"] for r in rows)

def test_rank_by_trait_lowest(seed): ...       # highest=False → Tyto alba first
def test_rank_by_trait_rejects_unknown_column(seed): ...  # pytest.raises(ValueError)
```

In `test_llm_agent.py`, with `resolve_taxon` and `rank_by_trait` monkeypatched:

```python
def test_rank_tool_states_coverage_and_caveat(): ...
    # "among 2 species in Strigiformes with a recorded max lifespan" in out
    # "- #1 Bubo bubo (Eurasian eagle-owl): 68 years" in out
    # "maximum recorded or estimated" in out
def test_rank_tool_unknown_trait_lists_supported_ones(): ...   # trait="diet" → names lifespan, mass, length
def test_rank_tool_unknown_group(): ...                         # resolve_taxon → None → "No group found"
def test_rank_tool_no_values_in_group(): ...                    # (0, []) → "No species in … has a recorded"
def test_label_checker_accepts_ranked_name_and_value(): ...
    # LabelChecker fed the rank output; "Database: The Eurasian eagle-owl can live 68 years." kept
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `cd backend && ..\.venv\Scripts\python -m pytest tests/test_taxon_queries.py tests/test_llm_agent.py -k rank -v`
Expected: FAIL with `AttributeError: rank_by_trait`.

- [ ] **Step 3: Implement**

Write `rank_by_trait` as specified: one `COUNT(*)` and one `ORDER BY <column> DESC|ASC, scientific_name LIMIT ?`, both with the Global Constraints filters. Build the column name only from the TRAITS whitelist.

The tool's output lines:

```
DATABASE RESULT: FOUND — top 2 by max lifespan among 2 species in Strigiformes with a recorded max lifespan.
- #1 Bubo bubo (Eurasian eagle-owl): 68 years
- #2 Tyto alba: 34 years
END OF DATABASE RESULT. Values are the maximum recorded or estimated in the source, not typical ages. Label these facts "Database:". Species without a recorded value are not ranked — say so if it matters.
```

In `LabelChecker.add_tool_output`, a line starting `- #` adds the scientific name and each common name in its parentheses to `self._phrases`, and the number to `self._numbers`. The generic `- ` branch already adds the number, so only the names are new.

Add `"rank_species_by_trait"` to `_EVIDENCE_TOOLS` and to `build_agent`. Add to the prompt: "Questions about the oldest, heaviest, largest, longest-lived (or lightest, shortest-lived) animals → rank_species_by_trait. Pass group as a scientific or common name ('birds', 'Strigiformes')."

- [ ] **Step 4: Run the backend tests**

Run: `cd backend && ..\.venv\Scripts\python -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/taxon_queries.py backend/app/llm_agent.py backend/tests/test_taxon_queries.py backend/tests/test_llm_agent.py
git commit -m "feat: rank_species_by_trait chat tool for oldest, heaviest and longest questions"
```

---

### Task 4: `group_stats`

**Files:**
- Modify: `backend/app/taxon_queries.py`, `backend/app/llm_agent.py`
- Test: `backend/tests/test_taxon_queries.py`, `backend/tests/test_llm_agent.py`

**Interfaces:**
- Consumes: `resolve_taxon` (Task 2), `_EVIDENCE_TOOLS`.
- Produces:
  - `taxon_queries.group_summary(group_path: str, examples: int = 5) -> dict`, with these keys:
    - `species`: int
    - `extinct`: int
    - `iucn`: `dict[str, int]`, with codes in the order CR, EN, VU, NT, LC, DD, EW, EX; only codes with a count > 0
    - `trends`: `dict[str, int]`, keyed by `population_trend` text
    - `threatened`: `list[dict]`, up to `examples` rows with status CR, then EN, then VU, ordered by status and then name
  - Tool `group_stats(group: str) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
def test_group_summary_counts_only_accepted_species(seed):
    s = taxon_queries.group_summary("Animalia|Chordata|Aves|Strigiformes")
    assert s["species"] == 5 and s["extinct"] == 1      # Strix ghost (synonym) not counted
    assert s["iucn"]["EN"] == 1 and s["trends"]["Decreasing"] == 1

def test_group_summary_threatened_examples_most_threatened_first(seed): ...
def test_group_summary_empty_group(seed): ...   # path with no species → species 0, empty dicts
```

Tool tests, with mocks:

```python
def test_group_stats_tool_lines(): ...
    # "- Accepted species: 5", "- Extinct: 1", "- IUCN EN (endangered): 1",
    # "- Population trend Decreasing: 1", "- Threatened examples:" line with names
def test_group_stats_tool_unknown_group(): ...   # "No group found"
def test_group_stats_tool_notes_iucn_coverage(): ...
    # END line says only assessed species have an IUCN status
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `cd backend && ..\.venv\Scripts\python -m pytest tests/test_taxon_queries.py tests/test_llm_agent.py -k "group" -v`
Expected: FAIL with `AttributeError: group_summary`.

- [ ] **Step 3: Implement**

Use one aggregate query (`COUNT(*)`, `SUM(extinct = 1)`) and two `GROUP BY` queries (`iucn_status`, `population_trend`), plus one examples query, all with the Global Constraints filters.

The tool spells each IUCN code out with `_IUCN_NAMES`. A line starting `- Threatened examples:` lists `Name (common name, CODE)`. `LabelChecker` treats it like the `- #` lines: names and common names become phrases.

The END line says: "Only species assessed by the IUCN have a status; 'not assessed' is not the same as safe."

Add `"group_stats"` to `_EVIDENCE_TOOLS` and `build_agent`. Add to the prompt: "How many species / how many are endangered, extinct or declining in a group → group_stats."

- [ ] **Step 4: Run the backend tests**

Run: `cd backend && ..\.venv\Scripts\python -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/taxon_queries.py backend/app/llm_agent.py backend/tests/test_taxon_queries.py backend/tests/test_llm_agent.py
git commit -m "feat: group_stats chat tool for species counts and conservation status"
```

---

### Task 5: `taxonomy_of`

**Files:**
- Modify: `backend/app/taxon_queries.py`, `backend/app/llm_agent.py`
- Test: `backend/tests/test_taxon_queries.py`, `backend/tests/test_llm_agent.py`

**Interfaces:**
- Consumes: `resolve_taxon` (Task 2), `_EVIDENCE_TOOLS`.
- Produces:
  - `taxon_queries.lineage(taxon_path: str) -> list[dict]`. One dict per ancestor, from kingdom down, each `{"name", "rank", "common"}`. `common` is the first common name or `""`. The rows are fetched with one `WHERE taxon_path IN (...)` query.
  - `taxon_queries.members(taxon_path: str, limit: int = 15) -> tuple[int, list[dict]]`. Returns the accepted direct children (depth + 1, not SYNONYM), sorted with common-named children first and then alphabetically, plus their total count.
  - Tool `taxonomy_of(name: str) -> str`. For a species, it lists up to 10 relatives: the accepted siblings in its genus, excluding itself, under `- Relatives in genus X:`. For a group, it lists up to 15 members under `- Members (<child rank>, N in total):`.

- [ ] **Step 1: Write the failing tests**

```python
def test_lineage_from_kingdom_down_with_common_names(seed):
    names = [(a["name"], a["common"]) for a in taxon_queries.lineage(
        "Animalia|Chordata|Aves|Strigiformes|Strigidae|Bubo|Bubo bubo")]
    assert names[0][0] == "Animalia" and ("Strigiformes", "Owls") in names

def test_members_count_and_exclude_synonyms(seed): ...   # Strix ghost absent; count matches
```

Tool tests:

```python
def test_taxonomy_of_group_lists_members(): ...      # "- Members (family, 1 in total): Strigidae (Owls)"
def test_taxonomy_of_species_lists_relatives(): ...  # "- Relatives in genus Strix:" and not the species itself
def test_taxonomy_of_unknown(): ...                  # "No species or group found"
def test_label_checker_accepts_member_name(): ...    # "Database: Owls include the family Strigidae." kept
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `cd backend && ..\.venv\Scripts\python -m pytest tests/test_taxon_queries.py tests/test_llm_agent.py -k "lineage or members or taxonomy" -v`
Expected: FAIL with `AttributeError: lineage`.

- [ ] **Step 3: Implement**

Write `lineage` and `members` as specified. `members` uses `taxon_depth = parent_depth + 1` together with the range condition, which hits the `idx_taxon_depth_path` index.

The tool's lineage line is `- Lineage: Animalia → … → Strigiformes (Owls) → …`. `LabelChecker` must strip the parenthesised common names before splitting on "→"; add a test that "Database: It belongs to the owls." is kept. Member and relative lines are parsed like `- #` lines: names and common names become phrases.

Add `"taxonomy_of"` to `_EVIDENCE_TOOLS` and `build_agent`. Add to the prompt: "What a species or group belongs to, what it is related to, or what groups it contains → taxonomy_of."

- [ ] **Step 4: Run the backend tests**

Run: `cd backend && ..\.venv\Scripts\python -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/taxon_queries.py backend/app/llm_agent.py backend/tests/test_taxon_queries.py backend/tests/test_llm_agent.py
git commit -m "feat: taxonomy_of chat tool for lineage, members and relatives"
```

---

### Task 6: Live check with Ollama, docs

**Files:**
- Create: `data/chat_eval.py`. A one-off script that posts each question to `/api/chat` on `AK_PORT`, collects the SSE text, and prints the question, the answer and the elapsed time.
- Modify: `CLAUDE.md` (Key Data Flows → Chat: tool list), `Docs/Manual.md` (chat section: example questions), `Docs/PLAN.md` (Increment 19: results and decisions)

- [ ] **Step 1: Start a private backend**

Run: `cd backend && ..\.venv\Scripts\python -m uvicorn app.main:app --port 8031` (in the background). Ollama must be running.

- [ ] **Step 2: Run the eval questions**

Run: `set AK_PORT=8031 && .venv\Scripts\python data\chat_eval.py`

Questions, and what counts as a pass:

| Question | Pass when |
|---|---|
| which animal can get oldest | names a sponge, *Arctica islandica* or *Somniosus microcephalus*, as "Database:" |
| arent there turtles who reach over 100 years | doesn't deny it; gives *Aldabrachelys gigantea* 152 or general knowledge labelled as such |
| how old can kangaroos get | *Macropus giganteus* 25 years "Database:" (regression) |
| what is the heaviest bird | ranks within Aves |
| how many owl species are endangered | number from group_stats |
| how many mammals have gone extinct | number from group_stats |
| what is a whale related to | lineage via taxonomy_of |
| which orders do mammals have | members list |
| what is the scientific name of the eagle owl | *Bubo bubo* via find_species |
| tell me about the thorny devil | no "Database:" sentence with a lifespan |

- [ ] **Step 3: Judge the results**

Pass when at least 8 of the 10 questions pass and the thorny-devil one passes. If tool choice fails on 3 or more, stop and report to the user before going further. The agreed fallback is to merge `group_stats` and `taxonomy_of` into one `explore_group` tool, which needs the user's decision.

- [ ] **Step 4: Run the full test suites and the chat E2E**

Run:
- `cd backend && ..\.venv\Scripts\python -m pytest tests/ -q`
- `cd frontend && npm run test`
- `set AK_PORT=8031 && npx playwright test e2e/chat.spec.ts e2e/full_journey.spec.ts`

Expected: all pass. `full_journey` has a known 5 s search flake; re-run it once before treating a failure as real.

- [ ] **Step 5: Update the docs and stop the private backend**

In `CLAUDE.md`, Chat flow: list the seven tools. In `Docs/Manual.md`, add example questions. In `Docs/PLAN.md`, record the eval table with results, decisions and open items under Increment 19.

- [ ] **Step 6: Commit**

```bash
git add data/chat_eval.py CLAUDE.md Docs/Manual.md Docs/PLAN.md
git commit -m "docs: record Increment 19 chat tools and the live eval"
```

Merge to master only after the user approves.
