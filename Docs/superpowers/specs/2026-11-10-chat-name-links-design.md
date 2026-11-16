# Chat Name Links — Design

Date: 2026-11-10. Status: approved by the user in chat; this document records it.

## Intent

The chat names animals in its answers. Seeing one in the tree means typing its name into search. The user wants the animals a question is about to be links in the answer. Clicking one should **navigate to the node in the tree and display the information if available**, as clicking a search result does now.

The user's examples define the scope:
- "What do koalas eat" → a link to koala.
- "What are the animals with the largest life span, give the top 3" → 3 links.
- "What does the blue whale eat" → just a link to the blue whale, "not to the krill it eats".

## Goals

- The animals and groups the chat looked up in the database to answer the question become links where the answer mentions them.
- Clicking a link does exactly what clicking a search result does (`frontend/js/app.js` `_showResults` click handler):
  - domain rank: `openDomain(taxon_path)`;
  - otherwise: `highlightNodes([taxon_path])`, `expandToNode(taxon_path)`, then `_fetchAndShowSpecies(scientific_name)`.
- Links appear once the answer has finished streaming.

## What gets linked: the question's subjects

The subjects come from this turn's successful database tool results ("DATABASE RESULT: FOUND"), from the attempt whose text is shown.

| Tool | Subjects | Not subjects |
|---|---|---|
| `lookup_species` | the looked-up species | lineage ancestors |
| `find_species` | the first match (my call) | other matches |
| `rank_species_by_trait` | every ranked entry | the group ranked within |
| `group_stats` | the group | the example threatened species (my call) |
| `taxonomy_of` | the subject, plus its listed members and relatives: these are the list the question asked for, like the top 3 (my call) | lineage ancestors (my call) |
| `semantic_search_species` | the species it returns (my call) | — |
| `get_species_image` | nothing | — |

A subject is linked where the answer text mentions it (my calls):
- by its scientific name, or by any of its common names, single words included ("koala");
- case-insensitively for common names and exactly for scientific names, on word boundaries;
- a plural of a common name counts ("koalas": +s / +es);
- every mention is linked, and text inside a longer match isn't matched again ("Panthera" inside "Panthera uncia");
- a subject the answer never mentions gets no link.

Everything else stays plain text, including animals named from general knowledge (the krill), names the database doesn't have, the source labels and the user's own messages.

## Non-goals

- Linking every name the database knows. (The user first chose this, then narrowed it after the reviewer showed that names like "small fish", "sea star" and "fruit fly" are species common names in the data.)
- Links in the species panel or search list.
- Re-linking after a page reload.
- Changing how the chat answers or labels.

## Anti-goals

- A link opening a different animal from the one the chat looked up. The tool result names the exact row, homonyms keyed `Name [Parent]` included; the link carries that row's `scientific_name` and `taxon_path`.
- Links on animals the question isn't about: the krill.
- Slower streaming, or the answer arriving later.

## Constraints

- Tool results are plain text (formats in `llm_agent.py`). `stream_response` / `_run_agent` already see every tool's output in `on_tool_end` and feed the evidence tools to `LabelChecker`.
- Per subject, the link needs `scientific_name`, `taxon_path`, `taxon_rank` and the common names.
  - Some outputs carry them in the text: `lookup_species` (name, rank, common names, lineage).
  - Others give only "Name (Common name)": ranking entries, members, relatives.
  - Exact primary-key lookups of `scientific_name` take milliseconds and fill the gaps (a ranking has at most 20 entries).
- FastAPI routes stay thin: the logic belongs in `llm_agent.py` or a small module beside `taxon_queries.py`. The frontend API base is the page origin.
- Tests:
  - pytest for subject extraction and matching;
  - Vitest for the link wrapping;
  - Playwright for the click, on port 8031, never the user's 8010. The E2E can fake the SSE stream as `e2e/chat.spec.ts` already does.

## How (decided)

1. **Server.** While a turn runs:
   - collect the subjects from the shown attempt's tool results (table above);
   - after the answer is complete, match them against the text that was sent;
   - before the final `done` event, send `{"type": "links", "links": [{"text", "scientific_name", "taxon_path", "taxon_rank"}]}`, one entry per distinct matched text;
   - send no `links` event when nothing matched, or after an error.
2. **Browser.** When the `links` event arrives (the Markdown is already rendered):
   - walk the bubble's text nodes and wrap each occurrence of each `text` in `<a class="taxon-link">`;
   - skip text already inside a link or a code element;
   - the tooltip shows the scientific name and rank.
3. **Clicking.** One shared function, used by both the search list and chat links so the behaviour can't drift. It takes `{scientific_name, taxon_path, taxon_rank}`, the shape search results already have.
4. **Look.** A subtle underline in the chat's existing colours (dotted, solid on hover), readable in the dark chat panel, with a pointer cursor.

## Left to the builder

- Module and function names.
- Whether subjects come from parsing the tool text or from a side channel the tools fill. It must stay correct when LangGraph runs tools concurrently, and only the shown attempt counts.
- The exact plural rule within "+s / +es".
- Styling details.

## Success

- "What do koalas eat": "koala" / "koalas" in the answer is a link; clicking it expands the tree to *Phascolarctos cinereus*, highlights it, and opens its panel.
- "Top 3 longest-living animals": the three ranked animals are links.
- "What does the blue whale eat": the blue whale is a link (common and scientific name); krill is not.
- A greeting, or an answer without a database lookup, has no links.
