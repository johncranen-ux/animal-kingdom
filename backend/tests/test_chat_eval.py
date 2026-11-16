"""data/chat_eval.py: model comparison suite and its scoring (no Ollama needed)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "data"))
import chat_eval  # noqa: E402


def test_scorer_summary_counts_tool_choice_empties_and_corrections():
    s = chat_eval.Scorer()
    s.record("q1", "Database: x.", ["rank_species_by_trait({...})"], 0, 4.0, {"rank_species_by_trait"})
    s.record("q2", "", [], 0, 1.0, {"group_stats"})
    s.record("q3", "Database: y.", ["lookup_species({...})"], 2, 9.0, None)   # conversation turn: no expectation
    assert s.summary() == ("3 answers, median 4.0 s, max 9.0 s, tool choice 1/2, "
                           "empty answers 1, label corrections 2")


def test_tool_choice_uses_the_first_tool_called():
    s = chat_eval.Scorer()
    s.record("q", "a", ["find_species({})", "rank_species_by_trait({})"], 0, 1.0, {"rank_species_by_trait"})
    assert "tool choice 0/1" in s.summary()


def test_suite_questions_have_expectations():
    assert len(chat_eval.SUITE_SINGLE) == 20 and all(tools for _, tools in chat_eval.SUITE_SINGLE)
    assert [q for q, _ in chat_eval.SUITE_SINGLE[:10]] == chat_eval.QUESTIONS
    assert sum(len(c) for c in chat_eval.SUITE_CHATS) == 11


def test_ask_collects_links_and_print_shows_them(monkeypatch, capsys):
    import asyncio
    import json

    async def fake_stream(question, history=None):
        yield 'data: {"type": "token", "content": "Database: The Lion."}\n\n'
        yield "data: " + json.dumps({"type": "links", "links": [
            {"text": "Lion", "scientific_name": "Panthera leo", "taxon_path": "p", "taxon_rank": "species"}]}) + "\n\n"
        yield 'data: {"type": "done"}\n\n'
    monkeypatch.setattr(chat_eval.llm_agent, "stream_response", fake_stream)
    answer, calls, errors = asyncio.run(chat_eval.ask("lion"))
    assert answer == "Database: The Lion." and errors == []
    assert chat_eval.links == ["Lion -> Panthera leo"]
    chat_eval._print("lion", 1.0, answer, calls, errors)
    assert "links: Lion -> Panthera leo" in capsys.readouterr().out
