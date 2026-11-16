# Chat Model qwen3.8 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the chat model a setting, prepare the label checker and the agent loop for qwen3.8:27b, and switch the default to it only if the 20-answer model eval shows it is better than llama3.1:8b.

**Architecture:** `llm_agent.get_llm()` reads the model name from `AK_CHAT_MODEL` (default constant `OLLAMA_MODEL`), always with thinking off and a fixed context size. `LabelChecker` learns the sentence shapes qwen writes about the tool results. `stream_response` holds the answer text until a tool has run; an answer written without any tool call is discarded and asked once more with a nudge. `data/chat_eval.py` gets the model comparison suite from the 2026-11-10 tests, with scoring, and that run decides the default.

**Tech Stack:** Python 3.12, LangGraph `create_react_agent`, langchain-ollama 1.1.0 (`ChatOllama(reasoning=False, num_ctx=…)`), Ollama 0.40.16 on ROCm (RX 7900 XTX, 24 GB).

**Spec:** `Docs/PLAN.md`, Increment 22 (the goal, the model comparison table, and the gate). There is no separate design doc: the comparison results there are the requirements.

## Global Constraints

- Default model stays `llama3.1:8b` until Task 5's gate passes; switching is one constant.
- `AK_CHAT_MODEL` set and non-empty overrides the default; nothing else reads the model name.
- Every `ChatOllama` the app builds uses `reasoning=False`, `temperature=0`, `num_ctx=16384` (`OLLAMA_NUM_CTX`).
- Keep `HF_HUB_OFFLINE` / `TRANSFORMERS_OFFLINE` first: `data/chat_eval.py` must import `app` before `langchain_ollama` (an earlier harness imported langchain first and semantic search tried to reach huggingface.co).
- E2E only on a private port (`AK_PORT=8031`), never against the user's backend on 8010. Unload other models (`ollama stop`) before timing a model: a model left loaded made the next one spill into RAM.
- Label rules stay evidence-based: a new rule may only accept a sentence when the tool output of this turn backs it.

## Review Focus

1. `AK_CHAT_MODEL` names a model that isn't pulled: the chat must show an error naming the model, not hang or show an empty bubble. Test in Task 1.
2. A greeting ("hi") or any answer the model writes without a tool: one retry with the nudge, then the second answer is shown, never both answers. Test in Task 4.
3. The model calls a tool and writes nothing afterwards: no retry (a tool was called), and the empty answer is reported by the eval, not hidden. Test in Task 4.
4. A long conversation (6 history messages of up to 1,500 characters plus tool results) must fit `num_ctx`: Ollama silently drops the start of the prompt (the system prompt) when it doesn't. The suite's third conversation covers it; Task 5 checks the prompt token count stays under 16,384.
5. The first answer after the model has been unloaded takes about 20 s longer (17 GB load). The E2E chat timeout (90 s) must cover it, and the manual must say so. Covered in Task 5.

---

### Task 1: Chat model setting

**Files:**
- Modify: `backend/app/llm_agent.py` (constants near `OLLAMA_MODEL`, `get_llm`)
- Test: `backend/tests/test_llm_agent.py`

**Interfaces:**
- Produces: `chat_model() -> str` (env `AK_CHAT_MODEL` if non-empty, else `OLLAMA_MODEL`); `OLLAMA_NUM_CTX = 16384`; `get_llm()` returns `ChatOllama(model=chat_model(), base_url=OLLAMA_BASE_URL, temperature=0, reasoning=False, num_ctx=OLLAMA_NUM_CTX)`.

- [ ] **Step 1: Write the failing tests**

```python
def test_chat_model_defaults_and_env_override(monkeypatch):
    from app import llm_agent
    monkeypatch.delenv("AK_CHAT_MODEL", raising=False)
    assert llm_agent.chat_model() == llm_agent.OLLAMA_MODEL == "llama3.1:8b"
    monkeypatch.setenv("AK_CHAT_MODEL", "qwen3.8:27b")
    assert llm_agent.chat_model() == "qwen3.8:27b"
    monkeypatch.setenv("AK_CHAT_MODEL", "  ")
    assert llm_agent.chat_model() == "llama3.1:8b"

def test_get_llm_thinking_off_and_fixed_context(monkeypatch):
    from app import llm_agent
    monkeypatch.setenv("AK_CHAT_MODEL", "qwen3.8:27b")
    llm = llm_agent.get_llm()
    assert (llm.model, llm.reasoning, llm.temperature, llm.num_ctx) == ("qwen3.8:27b", False, 0, 16384)

@pytest.mark.asyncio
async def test_missing_model_error_names_the_model(monkeypatch):
    # Ollama answers 404 "model 'x' not found"; the user must see that text
    from app.llm_agent import stream_response
    agent = MagicMock()
    agent.astream_events = MagicMock(side_effect=Exception("model 'qwen9:99b' not found (status code: 404)"))
    with patch("app.llm_agent.build_agent", return_value=agent):
        chunks = [c async for c in stream_response("hi")]
    errors = [json.loads(c[6:]) for c in chunks if '"type": "error"' in c]
    assert errors and "qwen9:99b" in errors[0]["detail"]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `..\.venv\Scripts\python -m pytest tests/test_llm_agent.py -k "chat_model or thinking_off or missing_model" -v` (from `backend/`)
Expected: the first two FAIL (`chat_model` not defined, `reasoning` is None / `num_ctx` None). The third may already pass; if so, keep it as a guard and note it in the ledger.

- [ ] **Step 3: Implement `chat_model()`, `OLLAMA_NUM_CTX` and the new `get_llm()`** in `backend/app/llm_agent.py` per the Interfaces block. Comment why `reasoning=False` (qwen3.8 thinks by default: seconds per answer, and thinking-capable models can leak it into the text) and why 16,384 (Ollama drops the start of an over-long prompt, the system prompt).

- [ ] **Step 4: Run the tests; then the whole backend suite**

Run: `..\.venv\Scripts\python -m pytest tests/ -q`
Expected: all pass (570 + 3).

- [ ] **Step 5: Commit** — `feat: chat model is a setting (AK_CHAT_MODEL), thinking off, 16k context`

---

### Task 2: Model comparison suite in chat_eval

**Files:**
- Modify: `data/chat_eval.py`
- Create: `backend/tests/test_chat_eval.py`

**Interfaces:**
- Consumes: `llm_agent.chat_model()` (Task 1) via the env var.
- Produces: `chat_eval.SUITE_SINGLE: list[tuple[str, set[str]]]` (question, acceptable first evidence tools); `chat_eval.SUITE_CHATS: list[list[str]]`; `chat_eval.Scorer` with `record(question, answer, calls, corrections, seconds, expected)` and `summary() -> str`; CLI `--model NAME` (sets `os.environ["AK_CHAT_MODEL"]`; `chat_model()` reads it per call) and `--suite`.

The suite (copy exactly):
- Singles with acceptable tools: the 10 `QUESTIONS` plus "what does the blue whale eat" {lookup_species, taxonomy_of}, "where does the snow leopard live" {lookup_species, taxonomy_of}, "which animals can get 100 years or more? display only the top 5" {rank_species_by_trait}. For the 10: oldest/turtles/heaviest bird → {rank_species_by_trait}; kangaroos → {lookup_species, find_species}; owls endangered, mammals extinct → {group_stats}; whale related, mammal orders → {taxonomy_of}; eagle owl name → {find_species, lookup_species}; thorny devil → {lookup_species, find_species}.
- Conversations: ["what is the largest animal", "what does it eat", "how long does it live"]; ["which animal can get oldest", "which animals can get 100 years or more? display only the top 5", "what kind of animal is #1", "and #2"]; ["tell me about the snow leopard", "how heavy is it", "is it endangered", "where does it live"] (the last turn carries 6 history messages: Review Focus 4).

- [ ] **Step 1: Write the failing tests** (`backend/tests/test_chat_eval.py`; add `data/` to `sys.path` as `test_build_col_db.py` does)

```python
def test_scorer_summary_counts_tool_choice_empties_and_corrections():
    from chat_eval import Scorer
    s = Scorer()
    s.record("q1", "Database: x.", ["rank_species_by_trait({...})"], 0, 4.0, {"rank_species_by_trait"})
    s.record("q2", "", [], 0, 1.0, {"group_stats"})
    s.record("q3", "Database: y.", ["lookup_species({...})"], 2, 9.0, None)   # conversation turn: no expectation
    assert s.summary() == ("3 answers, median 4.0 s, max 9.0 s, tool choice 1/2, "
                           "empty answers 1, label corrections 2")

def test_suite_questions_have_expectations():
    from chat_eval import SUITE_SINGLE, SUITE_CHATS
    assert len(SUITE_SINGLE) == 13 and all(tools for _, tools in SUITE_SINGLE)
    assert sum(len(c) for c in SUITE_CHATS) == 11
```

A turn's tool choice counts as right when the first called tool's name is in its set.

- [ ] **Step 2: Run them to verify they fail** — `..\.venv\Scripts\python -m pytest tests/test_chat_eval.py -v`; Expected: ImportError on `Scorer`.

- [ ] **Step 3: Implement** the suite, `Scorer`, label-correction counting (wrap `LabelChecker._process`: count a labelled input sentence whose output differs) and the `--model` / `--suite` flags; keep the existing plain and `--chat` modes working. `--suite` prints each answer with its tools and corrections, then `summary()` and the `ollama ps` line (processor and context) after the first answer.

- [ ] **Step 4: Run the tests** — Expected: PASS. Then a smoke run: `.venv\Scripts\python data\chat_eval.py --model llama3.1:8b "which animal can get oldest"` prints an answer from llama.

- [ ] **Step 5: Commit** — `feat: chat_eval model comparison suite with scoring`

---

### Task 3: Label checker reads qwen's phrasing

**Files:**
- Modify: `backend/app/llm_agent.py` (`LabelChecker.add_tool_output`, `_supported`)
- Test: `backend/tests/test_llm_agent.py`

**Interfaces:**
- Consumes: the tool output formats as they are on master (ranking header "… among N species in X with a recorded L.", END line "Values are the maximum recorded or estimated …", find_species "**Name** (rank rank)" lines, "- Not recorded: a, b, c").
- Produces: no new public names.

All four come from qwen3.8's relabelled sentences on 2026-11-10; each sentence is backed by the tool output.

- [ ] **Step 1: Write the failing tests**

```python
_BIRDS = "\n".join([
    "DATABASE RESULT: FOUND — top 1 by body mass among 1469 species in Aves (Birds, class) with a recorded body mass.",
    "- #1 Struthio camelus (Common Ostrich): 111 kg",
    "END OF DATABASE RESULT. Values are the maximum recorded or estimated in the source, not typical values. "
    'Label these facts "Database:".'])

def test_label_checker_accepts_the_ranking_coverage_count():
    text = "Database: This ranking is based on 1,469 bird species in the database."
    assert _check(text, _BIRDS) == text

def test_label_checker_accepts_the_ranking_caveat():
    text = "Database: These values are maximum recorded or estimated masses, not typical ones."
    assert _check(text, _BIRDS) == text

def test_label_checker_accepts_a_not_recorded_statement_for_a_listed_field():
    result = _LION_RESULT + "\n- Not recorded: diet / trophic level, activity period"
    for text in ("Database: Diet / trophic level is not recorded in the database.",
                 "Database: The database does not record the diet of Panthera leo."):
        assert _check(text, result) == text, text
    # a field the result does hold is not "not recorded"
    assert _check("Database: Its IUCN status is not recorded.", result).startswith("From general knowledge:")

def test_label_checker_accepts_other_find_species_match_names(monkeypatch):
    from app import taxon_queries
    from app.llm_agent import find_species
    milesi = {"scientific_name": "Bubo milesi", "taxon_rank": "species", "common_names": '["Arabian eagle-owl"]',
              "taxon_path": "Animalia|Chordata|Aves|Strigiformes|Strigidae|Bubo|Bubo milesi"}
    monkeypatch.setattr(taxon_queries, "find_matches", lambda name, limit=5: [_EAGLE_OWL, milesi])
    out = find_species.invoke({"name": "eagle owl"})
    text = "Database: Other related eagle-owl species include *Bubo milesi*."
    assert _check(text, out) == text
```

(`_LION_RESULT` holds IUCN status VU; "not recorded" for it must stay general knowledge.)

- [ ] **Step 2: Run them to verify they fail** — `-k "coverage_count or ranking_caveat or not_recorded_statement or other_find_species"`; Expected: 4 FAIL with the "From general knowledge:" label.

- [ ] **Step 3: Implement**
  - Ranking header: the N in "among N species" goes into `_count_numbers` (count words already include "species").
  - Ranking END line: add the phrase "maximum recorded or estimated" to `_phrases`.
  - "- Not recorded:" line: keep its fields (split on ", ", lowercased) in a new `_not_recorded: set[str]` (still not evidence for positive claims). In `_supported`: a sentence matching `\bnot recorded\b|\bdoes not record\b|\bdoesn't record\b|\bno (?:data|record)\b|\bnot in the database\b` is "db" when any not-recorded field, or its first word of 4+ letters ("diet" from "diet / trophic level"), appears in it.
  - find_species: a "**Name** (… rank)" line adds Name as a phrase (scientific name only).

- [ ] **Step 4: Run the tests; then the whole backend suite** — Expected: all pass.

- [ ] **Step 5: Commit** — `fix: label checker accepts coverage counts, caveats, not-recorded statements and match names`

---

### Task 4: An answer without a tool call is asked again

**Files:**
- Modify: `backend/app/llm_agent.py` (`stream_response`)
- Test: `backend/tests/test_llm_agent.py`

**Interfaces:**
- Consumes: `build_agent(follow_up=…)`, `_name_list_refs`, `LabelChecker` (existing).
- Produces: `_TOOL_NUDGE = "\n(Call one of the tools before answering.)"`; `stream_response` behaviour below.

Behaviour: per attempt, token output (after the JSON filter and a fresh `LabelChecker`) is held back until the first `on_tool_start` event; from then on it streams as now. If the agent finishes without any tool call, the held text is dropped and the agent runs once more with `_TOOL_NUDGE` appended to the question; that second attempt streams whatever it produces (held text released at the end if it again calls no tool). Image events are not held. qwen3.8 answered 3 of 7 follow-ups from memory, which the label checker then marks "From general knowledge"; the nudge fixed 2 of 5 for mistral on 2026-11-10.

- [ ] **Step 1: Write the failing tests** (reuse `_async_iter`; build a mock agent per attempt with `side_effect` on `build_agent`)

```python
def _agent(events):
    a = MagicMock(); a.astream_events = MagicMock(return_value=_async_iter(events)); return a

def _tokens(text):
    return {"event": "on_chat_model_stream", "data": {"chunk": AIMessageChunk(content=text)}}

_TOOL = [{"event": "on_tool_start", "name": "lookup_species", "data": {"input": {}}},
         {"event": "on_tool_end", "name": "lookup_species", "data": {"output": _LION_RESULT}}]

@pytest.mark.asyncio
async def test_answer_without_a_tool_is_asked_again_with_a_nudge():
    first, second = _agent([_tokens("From memory: lions are big.")]), _agent(_TOOL + [_tokens("Database: Panthera leo has a body mass of 175 kg.")])
    with patch("app.llm_agent.build_agent", side_effect=[first, second]):
        text = await _collect(stream_response("how heavy is a lion"))
    assert text == "Database: Panthera leo has a body mass of 175 kg."
    assert second.astream_events.call_args.args[0]["messages"][-1].content.endswith(_TOOL_NUDGE)

@pytest.mark.asyncio
async def test_answer_with_a_tool_streams_once():
    only = _agent(_TOOL + [_tokens("Database: Panthera leo has a body mass of 175 kg.")])
    with patch("app.llm_agent.build_agent", side_effect=[only]) as build:
        text = await _collect(stream_response("how heavy is a lion"))
    assert build.call_count == 1 and text == "Database: Panthera leo has a body mass of 175 kg."

@pytest.mark.asyncio
async def test_second_answer_without_a_tool_is_shown_once():
    with patch("app.llm_agent.build_agent", side_effect=[_agent([_tokens("Hello!")]), _agent([_tokens("Hi there.")])]):
        assert await _collect(stream_response("hi")) == "Hi there."

@pytest.mark.asyncio
async def test_tool_called_but_no_text_is_not_retried():
    with patch("app.llm_agent.build_agent", side_effect=[_agent(_TOOL)]) as build:
        assert await _collect(stream_response("how heavy is a lion")) == ""
    assert build.call_count == 1
```

`_collect` joins the `token` events' content (add it beside `_async_iter` if absent).

- [ ] **Step 2: Run them to verify they fail** — Expected: the nudge test and the "shown once" test FAIL (one attempt only; both texts or the first text shown).

- [ ] **Step 3: Implement** the hold-and-retry in `stream_response` (a loop of at most 2 attempts; the image handling and error handling stay as they are; `_name_list_refs` applies to the question before the nudge is appended).

- [ ] **Step 4: Run the tests; then the whole backend suite and the chat E2E specs** — `AK_PORT=8031 npx playwright test e2e/chat.spec.ts e2e/full_journey.spec.ts`; Expected: all pass.

- [ ] **Step 5: Commit** — `feat: an answer written without a tool call is asked again once`

---

### Task 5: Gate, switch and docs

**Files:**
- Modify: `backend/app/llm_agent.py` (`OLLAMA_MODEL`, only if the gate passes), `CLAUDE.md`, `Docs/Manual.md`, `Docs/PLAN.md`
- Test: `backend/tests/test_llm_agent.py` (`test_chat_model_defaults_and_env_override` default value)

**Interfaces:**
- Consumes: `chat_eval.py --suite --model` (Task 2).

- [ ] **Step 1: Run the suite for both models, each alone on the GPU** (`ollama stop` every loaded model first):
  `.venv\Scripts\python data\chat_eval.py --suite --model llama3.1:8b > <scratch>\suite_llama.txt`, then the same for `qwen3.8:27b`.
  Record both summary lines and the `ollama ps` line (100% GPU expected) in `Docs/PLAN.md`. Check the longest conversation's prompt token count stays under 16,384 (Ollama's `prompt_eval_count`, printed by `--suite` for the last turn of each conversation).

- [ ] **Step 2: Apply the gate.** qwen3.8 becomes the default only if all hold: tool choice ≥ 12/13; empty answers 0; label corrections ≤ llama's; median ≤ 10 s and max ≤ 20 s; the six screenshot turns (blue whale and oldest-animal conversations) answered from the database. Read every qwen answer for wrong facts under a "Database:" label: one is a fail.
  - Pass: write the failing test first (`OLLAMA_MODEL == "qwen3.8:27b"` in `test_chat_model_defaults_and_env_override`), run it (FAIL), change the constant, run it (PASS).
  - Fail: keep llama; record which criterion failed and stop after Step 4's docs.

- [ ] **Step 3: Full checks with the chosen default** — backend suite; `npx vitest run` (from `frontend/`); `AK_PORT=8031 npx playwright test` (all specs; rerun only timeouts once, they are the known stall); `data\chat_eval.py` (the 10 questions).

- [ ] **Step 4: Docs** — `CLAUDE.md`: tech stack / project overview model name, the `AK_CHAT_MODEL` setting, the `--suite --model` command. `Docs/Manual.md`: which model the chat uses, how to switch (`set AK_CHAT_MODEL=llama3.1:8b` before `start.bat`), that the first answer after a few idle minutes takes about 20 s longer (model load), and that Ollama 0.40.16 or newer is needed for qwen3.8's speed on AMD. `Docs/PLAN.md`: tasks checked, results table, Status "awaiting user approval".

- [ ] **Step 5: Commit** — `feat: qwen3.8:27b is the chat model` (or `docs: record the qwen3.8 evaluation` if the gate failed)
