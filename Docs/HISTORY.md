# How Animal Kingdom got here

This project was built by an AI coding agent ([Claude Code](https://claude.com/claude-code)) working with one human. The human chose what to build next, made the design calls, tested every step in the browser (often by sending screenshots of something that looked wrong), and approved each increment before it was merged. The agent planned, wrote the tests and the code, ran the data pipelines, reviewed its own work and kept the build log.

The detailed log, with every task, decision and measurement, is [`PLAN.md`](PLAN.md). This page is the short version of the road. The working rules the agent followed are in [`../CLAUDE.md`](../CLAUDE.md), and the larger design plans are in [`superpowers/plans/`](superpowers/plans/).

## How each step was done

1. **Plan:** write the increment into `PLAN.md` with its tasks and open questions; the human decides the questions.
2. **Test first:** a failing test for the behaviour, then the code that makes it pass.
3. **Review:** a code review pass before handing over; deferred minor points are recorded, not lost.
4. **Human test:** the human tries it in the real app. Problems come back as screenshots, and each is traced to a root cause before anything is changed.
5. **Record and commit:** decisions go into `PLAN.md`, the branch is merged to master.

## Phase 1 — The skeleton (June 6–11, 2026)

The first week built the whole app end to end on the **GBIF Backbone Taxonomy**, about 1.78 million animal species.

| Increment | What it added |
|---|---|
| 0 | Project scaffold: FastAPI backend, static frontend, test set-up on all three layers |
| 1 | SQLite schema (20 fields per species) and data helpers |
| 2 / 2b | Import of the GBIF backbone, then enrichment: IUCN Red List, Wikipedia, AnAge lifespans and body mass, GBIF ranges, pictures |
| 3 | Taxonomy API: root, children, single node, search |
| 4 | The D3.js collapsible tree and search |
| 5 | ChromaDB embeddings of the Wikipedia summaries |
| 6–8 | The chat: a LangChain agent on a local Ollama model, streamed over Server-Sent Events, with its own panel |
| 9 | Playwright end-to-end tests |
| 10 / 10b | Performance and hardening (a `taxon_depth` index), tree tooltips |
| 10d | A–Z letter nodes for groups too large to show at once |
| 10e | Pictures looked up on demand from four sources |

## Phase 2 — Making it right (November 3–5)

Work resumed with the bugs found by actually using the app.

- **10c, the honey bee:** *Apis* was a SYNONYM genus in GBIF, so the honey bee's genus vanished from the tree. Fixed by keeping synonym genera that still hold accepted species.
- **11:** history and documentation clean-up; every command in the docs was re-run and checked.
- **12, traits on demand:** opening a species fetches the missing traits from IUCN, GBIF, Wikidata and Wikipedia at once, and then lets the local model estimate the rest from the Wikipedia text. Every value records its source, and estimates are marked. Found along the way: IUCN population-trend codes were read off by one, so "Unknown" was stored as "Increasing".
- **13, extinct taxa:** fossils get a † and a "Hide extinct" switch (in the genus *Tapirus*, 21 of 28 species are fossils).
- **14 / 15:** hover texts for classes and orders, fact-checked against sources; the tree now starts at the three domains of life. Wrong common names were corrected on the way.

## Phase 3 — A new backbone (November 6–10)

- **16, the switch to the Catalogue of Life.** After a trial comparison, the human decided to replace the 2023 GBIF backbone with **COL26.10 XR**. Of 1,810,226 accepted animal species, COL accepts 1,595,764, keeps 69,173 as synonyms and lacks 144,888. A new build script carried every collected picture, trait and abstract across by name. Gaps where COL leaves an order or family blank were filled only where independent sources agreed (checked through Global Names). Names COL lacks stay searchable but outside the tree. Result: 1,800,133 accepted animal species in the tree.
- **17:** search ranking, frontend caching, picture clean-up.
- **18:** a hover text for every node in the tree.

## Phase 4 — A chat you can trust (November 10–12)

The chat had answered "which animal can get oldest" from memory while labelling it "Database:". The next increments made it answer from the data and made code check its labels.

- **19, query tools:** name lookup, rankings by trait, group statistics and lineage, all as tested SQL. Code now checks every `Database:` sentence against the tool output and relabels the unsupported ones.
- **20 / 21:** polish, and memory, so follow-up questions work ("what is the largest animal" → "what does it eat").
- **22, a model bake-off:** a scored suite compared `llama3.1:8b` with a 27B model. The larger model was slower, picked the wrong tool more often and needed three times as many label corrections. The gate failed, so the small model stayed.
- **23:** animals named in an answer become links into the tree.
- **24, ranges from real observations:** a GBIF occurrence download gave 172,104 species a range, so "which penguins live furthest north" comes from data.
- **25–29, places:** better tool choice for one-animal questions; "animals of a place" from Natural Earth shapes and GBIF country records; the countries of one species; fixed lists for lizards, sharks and marsupials (COL lumps lizards with snakes); continents through their countries.

## Phase 5 — Finishing touches (November 12–14)

- **30:** search ranks the real species above its synonyms and finds old names.
- **31–33, pictures:** a retry button for a missing picture, a gallery to choose another one (rejected pictures are remembered), and the leftover rough edges.
- **Wikipedia run:** summaries for 88,506 species, embedded for semantic search.
- **Tree legend:** a colour key for ranks, and sister species stay lit when one is selected.

## What the numbers say

- 33 increments plus fixes, 200+ commits on the private working repository
- 25 backend test modules, 5 frontend test modules, 11 Playwright specs
- 6.1 million rows in the database; 1.8 million accepted animal species in the tree; 172,000 with a range; 88,500 with a Wikipedia summary

The public repository starts from a single snapshot of this work. The commit-by-commit history stays in the private working copy, and this page and [`PLAN.md`](PLAN.md) keep the record of how it was built.
