"""
Ask the chat a fixed set of questions and print each answer with the tools it called.

Live check for the chat tools (Increment 19) and the chat model comparison
(Increment 22). The answers are judged by a person, not asserted. Runs the
agent in-process through llm_agent.stream_response (same label checking as
/api/chat) so the tool calls can be shown; needs Ollama, not a running backend.

Usage:
    .venv\\Scripts\\python data\\chat_eval.py
    .venv\\Scripts\\python data\\chat_eval.py "how old can kangaroos get"   # own questions
    .venv\\Scripts\\python data\\chat_eval.py --chat "q1" "q2"              # one conversation
    .venv\\Scripts\\python data\\chat_eval.py --suite --model qwen3.8:27b  # scored comparison
Unload other models first (`ollama stop NAME`): a model left loaded makes the
next one spill into RAM and the times mean nothing.
"""

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
# app before langchain_ollama: app/__init__ sets the HF offline flags
from app import llm_agent  # noqa: E402

QUESTIONS = [
    "which animal can get oldest",
    "arent there turtles who reach over 100 years",
    "how old can kangaroos get",
    "what is the heaviest bird",
    "how many owl species are endangered",
    "how many mammals have gone extinct",
    "what is a whale related to",
    "which orders do mammals have",
    "what is the scientific name of the eagle owl",
    "tell me about the thorny devil",
]

_RANK = {"rank_species_by_trait"}
_SPECIES = {"lookup_species", "find_species"}
_SPECIES_FACTS = {"lookup_species", "taxonomy_of"}

# (question, tools acceptable as the first call)
SUITE_SINGLE: list[tuple[str, set[str]]] = [
    (QUESTIONS[0], _RANK),
    (QUESTIONS[1], _RANK),
    (QUESTIONS[2], _SPECIES),
    (QUESTIONS[3], _RANK),
    (QUESTIONS[4], {"group_stats"}),
    (QUESTIONS[5], {"group_stats"}),
    (QUESTIONS[6], {"taxonomy_of"}),
    (QUESTIONS[7], {"taxonomy_of"}),
    (QUESTIONS[8], _SPECIES),
    (QUESTIONS[9], _SPECIES),
    ("what does the blue whale eat", _SPECIES_FACTS),
    ("where does the snow leopard live", _SPECIES_FACTS),
    ("which animals can get 100 years or more? display only the top 5", _RANK),
    ("which snakes can be found in holland", {"species_in_place"}),
    ("what owls live on borneo", {"species_in_place"}),
    ("are there snakes in ireland", {"species_in_place"}),
    ("in what countries can i find tigers", _SPECIES_FACTS),
    ("how many species of sharks are there", {"group_stats"}),
    ("which lizards live in the uk", {"species_in_place"}),
    ("which snakes live in europe", {"species_in_place"}),
]

SUITE_CHATS: list[list[str]] = [
    ["what is the largest animal", "what does it eat", "how long does it live"],
    ["which animal can get oldest", "which animals can get 100 years or more? display only the top 5",
     "what kind of animal is #1", "and #2"],
    # the last turn carries 6 history messages: the longest prompt
    ["tell me about the snow leopard", "how heavy is it", "is it endangered", "where does it live"],
]


class Scorer:
    """Collects answers of a suite run; summary() is the comparison line."""

    def __init__(self):
        self.times: list[float] = []
        self.right = self.judged = self.empty = self.corrections = 0

    def record(self, question: str, answer: str, calls: list[str], corrections: int,
               seconds: float, expected: set[str] | None) -> None:
        self.times.append(seconds)
        self.corrections += corrections
        self.empty += not answer.strip()
        if expected is not None:
            self.judged += 1
            self.right += bool(calls) and calls[0].split("(", 1)[0] in expected

    def summary(self) -> str:
        t = sorted(self.times)
        return (f"{len(t)} answers, median {t[len(t) // 2]:.1f} s, max {t[-1]:.1f} s, "
                f"tool choice {self.right}/{self.judged}, empty answers {self.empty}, "
                f"label corrections {self.corrections}")


# Sentences the label checker changed during the current ask()
corrections: list[str] = []
# Largest prompt (tokens) Ollama reported during the current ask()
prompt_tokens = {"max": 0}
# Chat name links of the current ask(): "text -> scientific name"
links: list[str] = []


def _count_corrections() -> None:
    original = llm_agent.LabelChecker._process

    def counting(self, sentence):
        out = original(self, sentence)
        if out.strip() != sentence.strip() and llm_agent._LABEL_RE.match(sentence.strip()):
            corrections.append(f"{sentence.strip()[:80]!r} -> {out.strip()[:25]!r}")
        return out

    llm_agent.LabelChecker._process = counting


class _TracingAgent:
    """Passes the real agent's events through and records each tool call."""

    def __init__(self, agent, calls: list[str]):
        self._agent, self._calls = agent, calls

    async def astream_events(self, *args, **kwargs):
        async for event in self._agent.astream_events(*args, **kwargs):
            if event["event"] == "on_tool_start":
                args_ = event["data"].get("input", {})
                self._calls.append(f"{event['name']}({json.dumps(args_, ensure_ascii=False)})")
            elif event["event"] == "on_chat_model_end":
                usage = getattr(event["data"].get("output"), "usage_metadata", None) or {}
                prompt_tokens["max"] = max(prompt_tokens["max"], usage.get("input_tokens", 0))
            yield event


async def ask(question: str, history: list[dict] | None = None) -> tuple[str, list[str], list[str]]:
    """(answer, tool calls, errors) for one question, after `history` if given."""
    calls: list[str] = []
    corrections.clear()
    links.clear()
    prompt_tokens["max"] = 0
    real_build = llm_agent.build_agent
    llm_agent.build_agent = lambda **kw: _TracingAgent(real_build(**kw), calls)
    text, errors = [], []
    try:
        async for chunk in llm_agent.stream_response(question, history):
            event = json.loads(chunk[len("data: "):])
            if event["type"] == "token":
                text.append(event["content"])
            elif event["type"] == "error":
                errors.append(event.get("detail", ""))
            elif event["type"] == "links":
                links.extend(f"{l['text']} -> {l['scientific_name']}" for l in event["links"])
    finally:
        llm_agent.build_agent = real_build
    return "".join(text), calls, errors


def _print(label: str, seconds: float, answer: str, calls: list[str], errors: list[str]) -> None:
    print(f"=== {label}  ({seconds:.1f} s)" + ("  [EMPTY]" if not answer.strip() else ""))
    print("tools: " + ("; ".join(calls) or "none"))
    for e in errors:
        print(f"ERROR: {e}")
    for c in corrections:
        print(f"label correction: {c}")
    if links:
        print("links: " + "; ".join(links))
    print(answer.strip(), end="\n\n", flush=True)


async def _timed(question: str, history: list[dict] | None):
    t0 = time.monotonic()
    answer, calls, errors = await ask(question, history)
    return answer, calls, errors, time.monotonic() - t0


async def suite() -> None:
    """The model comparison: SUITE_SINGLE, then SUITE_CHATS, then the summary."""
    _count_corrections()
    model = llm_agent.chat_model()
    print(f"##### {model}\n")
    await ask("hi")   # loads the model; not timed
    print(subprocess.run(["ollama", "ps"], capture_output=True, text=True).stdout)
    scorer = Scorer()
    for question, expected in SUITE_SINGLE:
        answer, calls, errors, dt = await _timed(question, None)
        _print(question, dt, answer, calls, errors)
        scorer.record(question, answer, calls, len(corrections), dt, expected)
    for chat in SUITE_CHATS:
        print("----- conversation")
        history: list[dict] = []
        for question in chat:
            answer, calls, errors, dt = await _timed(question, history)
            _print(question, dt, answer, calls, errors)
            scorer.record(question, answer, calls, len(corrections), dt, None)
            if answer.strip() and not errors:
                history += [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]
        print(f"prompt tokens (last turn): {prompt_tokens['max']} of {llm_agent.OLLAMA_NUM_CTX}\n")
    print(f"##### {model}: {scorer.summary()}")


async def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    if "--model" in args:
        i = args.index("--model")
        os.environ["AK_CHAT_MODEL"] = args[i + 1]   # chat_model() reads it per call
        del args[i:i + 2]
    if args[:1] == ["--suite"]:
        await suite()
        return
    chat = args[:1] == ["--chat"]   # the questions form one conversation, as in the browser
    history: list[dict] | None = [] if chat else None
    for i, question in enumerate(args[chat:] or QUESTIONS, 1):
        answer, calls, errors, dt = await _timed(question, history)
        if chat and answer.strip() and not errors:
            history += [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]
        _print(f"{i}. {question}", dt, answer, calls, errors)


if __name__ == "__main__":
    asyncio.run(main())
