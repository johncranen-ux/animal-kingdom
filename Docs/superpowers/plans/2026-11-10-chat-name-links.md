# Chat Name Links Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The animals and groups a chat question is about (the ones the chat looked up in the database) become links in the answer. Clicking one opens it in the tree and the panel, as a search result does.

**Architecture:**
- **New module `backend/app/taxon_links.py`:** reads the subjects' scientific names from each tool's text output, loads their rows by primary key, and finds where the answer mentions them.
- **`llm_agent._run_agent`:** collects the subjects and the sent text of the attempt that is shown.
- **`stream_response`:** sends one `links` SSE event before `done`.
- **Browser:**
  - `frontend/js/chat.js` wraps the matched texts in `<a class="taxon-link">`;
  - `app.js` routes link clicks and search-result clicks through one `openTaxon(item)`.

**Tech Stack:** Python 3.12 / FastAPI / LangGraph, SQLite; ES modules, Vitest (jsdom), Playwright.

**Spec:** `Docs/superpowers/specs/2026-11-10-chat-name-links-design.md`

## Global Constraints

- **Subjects** (spec table):

  | Tool | Subjects |
  |---|---|
  | lookup_species | the looked-up species |
  | find_species | the first match only |
  | rank_species_by_trait | every ranked entry (not the group) |
  | group_stats | the group (not the threatened examples) |
  | taxonomy_of | the subject, plus its "- Members" and "- Relatives in genus" items (not the lineage) |
  | semantic_search_species | every returned species |
  | get_species_image | none |

  Only results that start with "DATABASE RESULT: FOUND" count, except semantic search, which has no header.
- **Only the shown attempt counts.** A dropped no-tool attempt contributes nothing.
- **Matching:**
  - scientific names exactly, common names case-insensitively;
  - word boundaries on both sides;
  - plurals of common names (+s, +es);
  - longest match first, no matches inside a longer match;
  - every mention is linked;
  - an unmentioned subject gets no link.
- **Homonym keys:** a key "Name [Parent]" is matched in the text as "Name" but the link carries the full key.
- **The `links` event** is `{"type": "links", "links": [{"text", "scientific_name", "taxon_path", "taxon_rank"}]}`:
  - one entry per distinct matched text (the exact substring of the answer);
  - sent after the last token and before `done`;
  - not sent when empty or after an error.
- **Clicks behave like a search-result click:**
  - domain: `openDomain(taxon_path)`;
  - path set: `highlightNodes([path])`, `expandToNode(path)`, `_fetchAndShowSpecies(name)`;
  - no path: `highlightNodes([])`, `_fetchAndShowSpecies(name)`.
- **Look:** dotted underline in the chat's colours, solid on hover, pointer cursor; tooltip "scientific name (rank)".
- **Process:**
  - E2E only on port 8031 (`AK_PORT=8031`), never against the user's backend on 8010.
  - Use the Edit tool for code containing backslashes: Bash heredocs on this machine collapse `\\`.
  - Primary-key lookups only (`scientific_name IN (...)`): `database.get_species`'s NOCASE fallback scans the table.

## Review Focus

1. **Possessives and Markdown around a name:** "the koala's diet" and "**Blue whale** (*Balaenoptera musculus*)" must link "koala", "Blue whale" and "Balaenoptera musculus". Tests: Task 2 (possessive) and Task 4 (emphasis spans one text node).
2. **A subject's common name inside a longer word elsewhere in the answer:** "Lion" in "Lionfish" must not be wrapped. The browser wraps every occurrence, so it needs its own boundary check. Test: Task 4.
3. **Names with regex characters:** apostrophes, curly quotes, parentheses, "[Parent]" keys must match literally and never raise. Test: Task 2.
4. **An error after some tokens:** no `links` event, and the partial text keeps no stale links. Test: Task 3.
5. **A subject with no `taxon_path`** (GBIF_ONLY row): the link still opens the panel and doesn't touch the tree. Test: Task 4 (Vitest on the item `openTaxon` gets, `taxon_path: null`).

---

### Task 1: Subject names from tool output

**Files:**
- Create: `backend/app/taxon_links.py`
- Test: `backend/tests/test_taxon_links.py`

**Interfaces:**
- Produces: `subject_names(tool_name: str, output: str) -> list[str]`. Scientific names (row keys) in output order, without duplicates, `[]` for tools without subjects or unsuccessful results.

- [ ] **Step 1: Write the failing tests.** Build the inputs by calling the real tools with monkeypatched `taxon_queries` / `database`, as `test_llm_agent.py` does (`_rank`, `_stats`, `_taxonomy`, `_EAGLE_OWL`, `_LION_RESULT`); import those helpers from `tests.test_llm_agent` or copy the small fixtures.

```python
def test_lookup_subject_is_the_species():
    assert subject_names("lookup_species", _LION_RESULT) == ["Panthera leo"]

def test_find_species_subject_is_the_first_match_only(monkeypatch):   # eagle owl + Bubo milesi
    assert subject_names("find_species", out) == ["Bubo bubo"]

def test_ranking_subjects_are_the_entries_not_the_group(monkeypatch):
    assert subject_names("rank_species_by_trait", out) == ["Bubo bubo", "Tyto alba"]

def test_group_stats_subject_is_the_group_not_the_examples(monkeypatch):
    assert subject_names("group_stats", out) == ["Strigiformes"]

def test_taxonomy_subjects_are_subject_members_and_relatives(monkeypatch):
    # group: subject + "- Members" items; species: subject + "- Relatives in genus" items; never lineage
    assert subject_names("taxonomy_of", group_out) == ["Mammalia", "Carnivora", "Cetacea"]
    assert subject_names("taxonomy_of", species_out)[0] == "Bubo bubo"
    assert "Chordata" not in subject_names("taxonomy_of", species_out)

def test_semantic_search_subjects():
    out = "- **Moloch horridus** (Thorny devil) [species]\n  A lizard.\n- **Bubo bubo** (no common name) [species]\n  x"
    assert subject_names("semantic_search_species", out) == ["Moloch horridus", "Bubo bubo"]

def test_no_subjects_for_failures_and_images():
    assert subject_names("lookup_species", "DATABASE RESULT: No species found with scientific name 'X'.") == []
    assert subject_names("get_species_image", '{"url": "u"}') == []

def test_homonym_key_is_kept_whole():
    out = "DATABASE RESULT: FOUND — top 1 by max lifespan among 3 species in X with a recorded max lifespan.\n- #1 Bubo [Strigidae] (Eagle-owls): 5 years"
    assert subject_names("rank_species_by_trait", out) == ["Bubo [Strigidae]"]
```

- [ ] **Step 2: Run them to verify they fail.** Run: `..\.venv\Scripts\python -m pytest tests/test_taxon_links.py -q` (from `backend/`). Expected: ImportError, `taxon_links` doesn't exist.

- [ ] **Step 3: Implement `subject_names`.** Line rules on the formats in `llm_agent.py`. The scientific name is the text before the first " (" of an item:
  - lookup: the header between "FOUND — " and " is in the database";
  - find: the first `**Name** (… rank)` line;
  - ranking: `- #N Name …:` lines;
  - group_stats / taxonomy_of: the header after "statistics for " / "classification of ";
  - taxonomy items: "- Members (…): a; b" or "- Relatives in genus G: a; b", split on "; ", skipping "none recorded";
  - semantic: `- **Name** (…) [rank]` lines.

- [ ] **Step 4: Run them to verify they pass.** Expected: all PASS.

- [ ] **Step 5: Commit.** Message: `feat: subject names of the chat's database results`. Include the plan, the spec and the PLAN.md entry in this first commit.

---

### Task 2: Subject rows and matching in the answer

**Files:**
- Modify: `backend/app/taxon_links.py`
- Test: `backend/tests/test_taxon_links.py` (temp DB as `test_taxon_queries.py`'s `isolated_db` / `_add`)

**Interfaces:**
- Produces:
  - `subject_rows(names: list[str]) -> list[dict]`: rows by primary key (`scientific_name IN (...)`), in `names` order; unknown names are dropped.
  - `match_links(text: str, rows: list[dict]) -> list[dict]`: `[{"text", "scientific_name", "taxon_path", "taxon_rank"}]`, in first-appearance order, one per distinct matched substring.

- [ ] **Step 1: Write the failing tests.**

```python
_KOALA = {"scientific_name": "Phascolarctos cinereus", "taxon_path": "Animalia|…|Phascolarctos cinereus",
          "taxon_rank": "species", "common_names": '["Koala", "Koala bear"]'}

def test_common_name_plural_possessive_and_case():
    links = match_links("Database: Koalas eat eucalyptus. The koala's diet is narrow.", [_KOALA])
    assert [l["text"] for l in links] == ["Koalas", "koala"]
    assert {l["scientific_name"] for l in links} == {"Phascolarctos cinereus"}

def test_scientific_name_exact_case_only():
    assert match_links("phascolarctos cinereus", [_KOALA]) == []
    assert match_links("(*Phascolarctos cinereus*)", [_KOALA])[0]["text"] == "Phascolarctos cinereus"

def test_longest_match_wins_and_word_boundaries():
    # "Koala bear" not "Koala"; "Koalabear" is no match
    assert [l["text"] for l in match_links("The Koala bear. Koalabear.", [_KOALA])] == ["Koala bear"]

def test_unmentioned_subject_and_other_animals_get_no_link():
    whale = {"scientific_name": "Balaenoptera musculus", "taxon_path": "p", "taxon_rank": "species",
             "common_names": '["Blue whale"]'}
    links = match_links("Database: The blue whale eats krill.", [whale, _KOALA])
    assert [l["text"] for l in links] == ["blue whale"]

def test_homonym_key_matches_its_plain_name():
    row = {"scientific_name": "Bubo [Strigidae]", "taxon_path": "p", "taxon_rank": "genus", "common_names": "[]"}
    assert match_links("The genus Bubo.", [row]) == [
        {"text": "Bubo", "scientific_name": "Bubo [Strigidae]", "taxon_path": "p", "taxon_rank": "genus"}]

def test_names_with_regex_characters_match_literally():
    row = {"scientific_name": "Lachenalia x", "taxon_path": "p", "taxon_rank": "species",
           "common_names": '["Lutzeyer’s lachenalia", "a+b (c)"]'}
    assert [l["text"] for l in match_links("Lutzeyer’s lachenalia and a+b (c).", [row])] == \
        ["Lutzeyer’s lachenalia", "a+b (c)"]

def test_subject_rows_by_primary_key_in_order(seed):   # rows added with _add
    assert [r["scientific_name"] for r in subject_rows(["Tyto alba", "Nope", "Bubo bubo"])] == ["Tyto alba", "Bubo bubo"]
```

- [ ] **Step 2: Run them to verify they fail.** Expected: ImportError on `match_links` / `subject_rows`.

- [ ] **Step 3: Implement.**
  - Forms per row:
    - the plain scientific name (key without " [ … ]"), case-sensitive;
    - each common name of 3+ characters (`database.parse_common_names`), plus +s and +es, case-insensitive.
  - One compiled alternation, longest form first, each form `re.escape`d. Case-insensitive forms go in `(?i:…)` groups. Wrap the whole alternation as `(?<!\w)(?:…)(?!\w)`, then `finditer`.
  - Map each match back to its row: exact scientific name, or a lowercased common name with the plural removed.
  - Write this in the Edit tool, not a heredoc.

- [ ] **Step 4: Run them to verify they pass**, then the whole backend suite (`..\.venv\Scripts\python -m pytest tests/ -q`). Expected: all PASS.

- [ ] **Step 5: Commit.** Message: `feat: match the chat's subjects in the answer text`.

---

### Task 3: `links` event in the chat stream

**Files:**
- Modify: `backend/app/llm_agent.py` (`stream_response`, `_run_agent`)
- Test: `backend/tests/test_llm_agent.py` (reuse `_agent`, `_tokens`, `_TOOL`, `_collect`, `_LION_RESULT`)

**Interfaces:**
- Consumes: `subject_names`, `subject_rows`, `match_links` (Tasks 1–2).
- Produces:
  - `_run_agent(agent, prompt, history, run: dict)`: fills `run["text"]` (str, the token text it yielded) and `run["subjects"]` (list[str], from `subject_names` per `on_tool_end`; every tool except `get_species_image` is offered).
  - `stream_response` yields `_sse("links", {"links": [...]})` before `done` when `match_links(run["text"], subject_rows(run["subjects"]))` of the shown attempt is non-empty.

- [ ] **Step 1: Write the failing tests.**

```python
@pytest.mark.asyncio
async def test_links_event_names_the_looked_up_species(monkeypatch):
    from app import taxon_links
    monkeypatch.setattr(taxon_links, "subject_rows", lambda names: [
        {"scientific_name": "Panthera leo", "taxon_path": "Animalia|…|Panthera leo", "taxon_rank": "species",
         "common_names": '["Lion"]'}] if names == ["Panthera leo"] else [])
    events = _TOOL + [_tokens("Database: The Lion (Panthera leo) has a body mass of 175 kg.")]
    with patch("app.llm_agent.build_agent", side_effect=[_agent(events)]):
        chunks = [c async for c in stream_response("how heavy is a lion")]
    kinds = [json.loads(c[6:])["type"] for c in chunks]
    assert kinds[-2:] == ["links", "done"]
    assert [l["text"] for l in json.loads(chunks[-2][6:])["links"]] == ["Lion", "Panthera leo"]

@pytest.mark.asyncio
async def test_no_links_event_without_a_lookup_or_after_an_error():
    # no tool on either attempt: no links
    # an error after tokens: no links and no done (as before)
```

Write the error case with an `astream_events` side effect that yields `_TOOL`, then a token, then raises. Assert that no chunk has type `links`.

- [ ] **Step 2: Run them to verify they fail.** Expected: the first FAILS (no `links` event); the second may already pass and stays as a guard.

- [ ] **Step 3: Implement.**
  - Call the helpers through the module (`taxon_links.subject_rows(...)`) so tests can patch them.
  - A fresh `run` dict per attempt.
  - The `links` event is computed only after the attempt loop ends normally, from the attempt that was shown.
  - The DB lookup runs once per answer, so wrap it in `asyncio.to_thread` to keep the event loop free.

- [ ] **Step 4: Run the tests and the whole backend suite.** Expected: all PASS. `data/chat_eval.py` ignores unknown event types; check that `ask()` still works with an event type it doesn't print.

- [ ] **Step 5: Commit.** Message: `feat: chat sends the subjects it mentions as links`.

---

### Task 4: Links in the chat bubble

**Files:**
- Modify: `frontend/js/chat.js`, `frontend/js/app.js` (`_showResults`, `_streamChat`, `_initChat`), `frontend/css/style.css`
- Test: `frontend/tests/chat.test.js`, `e2e/chat.spec.ts`

**Interfaces:**
- Consumes: the `links` SSE event (Task 3).
- Produces:
  - `linkNames(root: Element, links: Array<{text, scientific_name, taxon_path, taxon_rank}>) -> number` in `chat.js` (number of links made);
  - `taxonItem(anchor: Element) -> {scientific_name, taxon_path, taxon_rank}` in `chat.js` (`taxon_path: null` when empty);
  - `openTaxon(item)` in `app.js`, used by search results and chat links.

- [ ] **Step 1: Write the failing Vitest tests** (jsdom).

```js
it('wraps each mention in a taxon link with its data and tooltip', () => {
  const el = document.createElement('div');
  el.innerHTML = '<p>Database: Koalas eat leaves. The <strong>Koalas</strong> sleep.</p>';
  expect(linkNames(el, [{ text: 'Koalas', scientific_name: 'Phascolarctos cinereus',
                          taxon_path: 'A|P', taxon_rank: 'species' }])).toBe(2);
  const a = el.querySelector('a.taxon-link');
  expect(a.dataset.scientificName).toBe('Phascolarctos cinereus');
  expect(a.title).toBe('Phascolarctos cinereus (species)');
});

it('does not wrap inside a longer word, a link or code', () => {
  el.innerHTML = '<p>Lionfish. <a href="#">Lion</a> <code>Lion</code> Lion.</p>';
  expect(linkNames(el, [{ text: 'Lion', scientific_name: 'Panthera leo', taxon_path: 'p', taxon_rank: 'species' }])).toBe(1);
});

it('wraps a name inside emphasis', () => {   // marked renders *Panthera leo* as <em>
  el.innerHTML = '<p>(<em>Panthera leo</em>)</p>';
  expect(linkNames(el, [{ text: 'Panthera leo', /* … */ }])).toBe(1);
});

it('reads the item back from a link, without a path for rows outside the tree', () => {
  // anchor made by linkNames with taxon_path null -> taxonItem(a).taxon_path === null
});
```

- [ ] **Step 2: Run them to verify they fail.** Run: `npx vitest run tests/chat.test.js` (from `frontend/`). Expected: FAIL, `linkNames` is not exported.

- [ ] **Step 3: Implement.**
  - **`linkNames`:** a TreeWalker over text nodes, skipping nodes inside `A`, `CODE` or `PRE`. Longest `text` first. A match counts only when the characters before and after aren't letters or digits (`/[\p{L}\p{N}]/u`). Split the text node and insert `<a class="taxon-link" href="#">`. Set `data-scientific-name`, `data-taxon-path` and `data-taxon-rank` on it, and title it "name (rank)".
  - **`app.js`:**
    - move the search-result click body into `openTaxon(item)` and call it from `_showResults`;
    - in `_streamChat`, a `links` event calls `linkNames(textEl, event.links)`;
    - one delegated click listener on `#chat-messages` for `a.taxon-link`: `preventDefault()`, then `openTaxon(taxonItem(a))`.
  - **`style.css`:** `.taxon-link` with a dotted underline in the chat's text colour, solid on hover, `cursor: pointer`.

- [ ] **Step 4: Run Vitest** (Expected: all PASS), **then add the E2E test** in `e2e/chat.spec.ts`. Fake the SSE with `page.route` as the follow-up test does:
  - a token "Database: The Lion (*Panthera leo*) is big.";
  - a `links` event for "Lion" with the real `Panthera leo` path from the DB (`Animalia|Chordata|Mammalia|Carnivora|Felidae|Panthera|Panthera leo`; check it with a query first);
  - `done`.

  Assert that `#chat-messages a.taxon-link` has count 1, click it, then expect the species panel visible with "Panthera leo" and the tree node highlighted, using the same locators as `full_journey.spec.ts`.

  Run: `AK_PORT=8031 npx playwright test e2e/chat.spec.ts` (from the project root). Expected: all PASS.

- [ ] **Step 5: Commit.** Message: `feat: chat answers link the animals they are about`.

---

### Task 5: Live check, full checks, docs

**Files:**
- Modify: `CLAUDE.md` (chat flow), `Docs/Manual.md` (chat section), `Docs/PLAN.md` (Increment 23 results; boxes stay unchecked until the user approves)

- [ ] **Step 1: Live check with llama3.1:8b.** Run `.venv\Scripts\python data\chat_eval.py "what do koalas eat" "which animals live the longest, give the top 3" "what does the blue whale eat"`. Extend `chat_eval._print` to print a `links: …` line from the `links` event (`ask()` returns it as a 4th value only if that doesn't break the `--suite` callers; else a module-level list as `prompt_tokens`).

  Expected:
  - the koala answer links "koala(s)";
  - the top-3 answer links three animals;
  - the blue-whale answer links the whale, not krill.

  Record the three link lines in PLAN.md.
- [ ] **Step 2: Full checks:**
  - the backend suite;
  - `npx vitest run`;
  - `AK_PORT=8031 npx playwright test` (rerun only a timeout once: the known startup stall).
- [ ] **Step 3: Docs:**
  - `CLAUDE.md` chat flow: the `links` event and `taxon_links.py`;
  - Manual: "Names in an answer are links when the chat looked them up: click one to open it in the tree and the species panel";
  - PLAN.md: results and Status "implemented, awaiting user approval".
- [ ] **Step 4: Commit.** Message: `docs: record Increment 23 chat name links`.
