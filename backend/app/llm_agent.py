"""LangChain tool definitions and Ollama agent configuration."""

import asyncio
import json
import logging
import math
import os
import re
import warnings
from typing import AsyncGenerator

# langgraph 1.x raises LangGraphDeprecatedSinceV10 about create_react_agent
# moving to langchain.agents, but langchain base isn't in our deps and the
# langgraph version works identically — suppress until we upgrade.
warnings.filterwarnings(
    "ignore",
    message="create_react_agent has been moved",
)

from langchain_ollama import ChatOllama
from langchain_core.tools import tool
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langgraph.prebuilt import create_react_agent

from app import database, image_utils, places, taxon_links, taxon_queries, trait_utils, vector_db

log = logging.getLogger(__name__)

OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL    = "llama3.1:8b"
# Ollama drops the start of an over-long prompt, i.e. the system prompt;
# 16k holds the prompt, 6 history messages and the tool results
OLLAMA_NUM_CTX  = 16384


def chat_model() -> str:
    """The chat's Ollama model: AK_CHAT_MODEL if set, else OLLAMA_MODEL."""
    return os.environ.get("AK_CHAT_MODEL", "").strip() or OLLAMA_MODEL


_SYSTEM_PROMPT = """You are a factual naturalist assistant backed by a local database of \
1.78 million species.

MANDATORY WORKFLOW — follow exactly, in order:
1. Call ONE tool immediately — no text before the first tool call.
2. If the result is empty, call a DIFFERENT tool using the scientific name you already know.
3. Write a concise 3–5 sentence answer. Label each fact with its source:
   - Facts from the tool result → prefix that sentence with "Database:"
   - Facts from your own training knowledge → prefix with "From general knowledge:"
   - Facts from a tool-result line ending in "(estimated)" → prefix with "Database (estimated):"
     e.g. line "- Activity period: nocturnal (estimated)" → Database (estimated): It is nocturnal.
   This way the user always knows which information is DB-backed and which is not.
   A sentence may start with "Database:" ONLY if its fact appears in a line of the tool
   result. If the question asks about something the result does not contain (see its
   "Not recorded" line), answer that part with "From general knowledge:".
   Still report what the database DOES hold: for a general question ("tell me about X")
   start with "Database:" sentences covering the recorded facts (body mass, lifespan,
   IUCN status, population trend, …), then add general knowledge.
   Example — tool result has body mass and lifespan; user asks "which breeds exist for cats":
     From general knowledge: There are over 70 recognised cat breeds, such as the Siamese and Persian.
     Database: Felis catus has a body mass of 3.9 kg and a maximum lifespan of 30 years.

SCIENTIFIC NAME DETECTION (highest priority rule):
  If the query contains 2–3 words that look like a scientific name (e.g. "felis maxima",
  "Panthera leo", "canis lupus familiaris"), call lookup_species DIRECTLY — capitalise the
  first word, lowercase the rest (e.g. "felis maxima" → lookup_species("Felis maxima")).
  Never call semantic_search_species for scientific-name-shaped queries.

COMMON-NAME → SCIENTIFIC NAME (use lookup_species directly, skip semantic search):
  ladybug / ladybird → Coccinella septempunctata
  black panther      → Panthera pardus
  mountain lion      → Puma concolor
  cougar / puma      → Puma concolor
  wolf               → Canis lupus
  lion               → Panthera leo
  tiger              → Panthera tigris
  polar bear         → Ursus maritimus
  killer whale       → Orcinus orca
  great white shark  → Carcharodon carcharias
  house cat          → Felis catus
  domestic dog       → Canis lupus familiaris
  For unlisted common names (single words or multi-word phrases that are NOT \
scientific names): call find_species first, then lookup_species on the best match.
  Use semantic_search_species only for descriptions without a name ("a striped horse-like animal").

QUESTIONS ABOUT GROUPS (not one species):
  Oldest, heaviest, largest, longest-lived (or lightest, shortest-lived) animals →
  rank_species_by_trait. Pass group as a scientific or common name ("birds", "Strigiformes").
  How many species / how many are endangered, extinct or declining in a group → group_stats.
  What a species or group belongs to, what it is related to, or what groups it contains →
  taxonomy_of.
  Which animals of a group live in a country, continent, island, region or sea ("which snakes
  live in Holland", "owls of Borneo") → species_in_place with the place and the group.
  Which countries one species lives in ("where can I find tigers") → lookup_species: its
  result lists the countries.

HARD RULES — violations break the app:
  ✗ NEVER write {"name": ...} or any JSON in your reply.
  ✗ NEVER narrate your reasoning ("I will try...", "Let me call...").
  ✓ Always label every fact — "Database:" or "From general knowledge:" — never mix unlabelled.
  ✗ NEVER say a species is "not found" or "not in the database" if the tool returned
    "DATABASE RESULT: FOUND". Trust the tool — it queries 1.78 million records. If the
    tool says FOUND, the species exists; report the data it returned.
"""

# Added only when the request carries earlier turns: in the single-question
# prompt it made llama3.1:8b pick the wrong tool for "aren't there turtles over 100 years"
_FOLLOW_UP_PROMPT = """
FOLLOW-UP QUESTIONS:
  Earlier messages are the conversation so far. If the question says "it", "they" or
  "that one", it means the species or group named in the previous answer: call the tool
  again with that scientific name (e.g. after the blue whale, "what does it eat" →
  lookup_species("Balaenoptera musculus")). Never ask which species is meant when the
  previous answer named one. Facts from earlier answers are not evidence: call a tool.
"""

# ── Tools ─────────────────────────────────────────────────────────────────────

@tool
def lookup_species(scientific_name: str) -> str:
    """Look up detailed facts for a species by its scientific name.

    Returns a markdown-formatted summary of taxonomy, physical traits,
    ecology, conservation status, and a Wikipedia abstract if available.
    """
    row, note = database.get_species(scientific_name), ""
    if row is None and (close := taxon_queries.closest_name(scientific_name)):
        # The 8B model copies some names with a typo ("Cinachyrya" for Cinachyra)
        row, note = database.get_species(close), f" (closest match to '{scientific_name}')"
    if row is None:
        return f"DATABASE RESULT: No species found with scientific name '{scientific_name}'."
    row = _with_sourced_traits(row)
    prov = database.trait_provenance(row)

    def est(field: str) -> str:
        return " (estimated)" if prov.get(field, {}).get("estimated") else ""

    common = database.parse_common_names(row.get("common_names"))
    common_str = ", ".join(common) if common else "none recorded"
    bbox = database.parse_geo_bbox(row.get("geo_bounding_box"))

    lines = [
        f"DATABASE RESULT: FOUND — {row['scientific_name']} is in the database{note}.",
        f"**{row['scientific_name']}** ({row.get('taxon_rank', 'unknown')} rank)",
        f"- Common names: {common_str}",
        f"- Lineage: {(row.get('taxon_path') or 'not in the classification').replace('|', ' → ')}",
        f"- Taxonomic status: {row.get('taxonomic_status', 'unknown')}",
    ]
    if row.get("body_mass"):
        lines.append(f"- Body mass: {_fmt_quantity(row['body_mass'])} kg{est('body_mass')}")
    if row.get("body_length"):
        lines.append(f"- Body length: {_fmt_quantity(row['body_length'])} m{est('body_length')}")
    if row.get("max_lifespan"):
        lines.append(f"- Max lifespan: {_fmt_quantity(row['max_lifespan'])} years{est('max_lifespan')}")
    if row.get("habitat_type"):
        lines.append(f"- Habitat: {row['habitat_type']}{est('habitat_type')}")
    if row.get("trophic_level"):
        lines.append(f"- Trophic level: {row['trophic_level']}{est('trophic_level')}")
    if row.get("elevation_limits"):
        lines.append(f"- Elevation: {row['elevation_limits']}{est('elevation_limits')}")
    if row.get("activity_period"):
        lines.append(f"- Activity period: {row['activity_period']}{est('activity_period')}")
    if row.get("reproduction_strategy"):
        lines.append(f"- Reproduction: {row['reproduction_strategy']}{est('reproduction_strategy')}")
    if row.get("iucn_status"):
        lines.append(f"- IUCN status: {row['iucn_status']}")
    if row.get("population_trend"):
        lines.append(f"- Population trend: {row['population_trend']}")
    range_text = _range_text(bbox)
    if range_text:
        lines.append(f"- Geographic range: {range_text}")
    country_lines = _country_lines(row["scientific_name"])
    lines += country_lines
    if row.get("wikipedia_abstract"):
        lines.append(f"\n**Summary:** {row['wikipedia_abstract'][:500]}")

    # Spell out the result's boundary — without it the LLM labels general
    # knowledge (cat breeds, lion diet) as "Database:".
    missing = [label for field, label in _OPTIONAL_FIELDS if not row.get(field)]
    if not country_lines:
        missing.append("countries")
    if missing:
        lines.append(f"- Not recorded: {', '.join(missing)}")
    lines.append(
        'END OF DATABASE RESULT. Report the facts above that answer the question with "Database:". '
        "Anything not listed above (e.g. breeds, diet, behaviour, appearance) is not in the "
        'database — label it "From general knowledge:". Facts from a line ending in "(estimated)" '
        'are labelled "Database (estimated):".'
    )

    return "\n".join(lines)


_COUNTRIES_LINE = "- Countries with wild records (most first):"
_MAX_COUNTRIES = 20


def _country_lines(scientific_name: str) -> list[str]:
    """The countries the species lives in, from its wild GBIF records per country
    (Increment 27, places.native_countries); records elsewhere are counted: tigers in
    Brazil, koalas in Japan."""
    inside, outside = places.native_countries(taxon_queries.countries_of(scientific_name))
    lines = []
    if inside:
        names = [name for name, _ in inside[:_MAX_COUNTRIES]]
        more = len(inside) - len(names)
        lines.append(f"{_COUNTRIES_LINE} {', '.join(names)}" + (f", and {more} more" if more else ""))
    if outside:
        lines.append(f"- Records far from its range: {outside} other countr{'y' if outside == 1 else 'ies'} "
                     "(zoo animals, escapes or misplaced records), not listed")
    return lines


def _fmt_quantity(value: float) -> str:
    """Three significant figures: converted values (6.2 oz → 0.17576… kg) must
    read the way the LLM will repeat them, or LabelChecker can't match them."""
    if not value:
        return "0"
    decimals = max(0, 2 - math.floor(math.log10(abs(value))))
    text = f"{value:.{decimals}f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _with_sourced_traits(row: dict) -> dict:
    """Fill missing traits from online sources once per species (cached by the
    _sourced marker). Never the LLM estimate stage: chat must not wait on a
    second model call. Any failure falls back to the stored record."""
    if not trait_utils.is_eligible(row):
        return row
    if "_sourced" in database.parse_trait_sources(row.get("trait_sources")):
        return row
    try:
        return trait_utils.apply_stage(row, "sourced", *trait_utils.run_sourced_stage(row))
    except Exception:
        log.warning("Sourced trait stage failed for %s", row.get("scientific_name"), exc_info=True)
        return row


# (row field, label used in the "Not recorded" line)
_OPTIONAL_FIELDS = [
    ("body_mass", "body mass"),
    ("body_length", "body length"),
    ("max_lifespan", "lifespan"),
    ("habitat_type", "habitat"),
    ("trophic_level", "diet / trophic level"),
    ("elevation_limits", "elevation"),
    ("activity_period", "activity period"),
    ("reproduction_strategy", "reproduction"),
    ("iucn_status", "IUCN status"),
    ("population_trend", "population trend"),
    ("geo_bounding_box", "geographic range"),
    ("wikipedia_abstract", "description / summary"),
]


@tool
def find_species(name: str) -> str:
    """Find the scientific name for a common name (e.g. 'eagle owl', 'kangaroo').

    Use before lookup_species when the user gives a common name.
    """
    matches = taxon_queries.find_matches(name)
    if not matches:
        return (f"DATABASE RESULT: No species or group matches '{name}'.\n"
                'END OF DATABASE RESULT. Answer from your own knowledge and label it '
                '"From general knowledge:", or call lookup_species with a scientific name you know.')
    lines = [f"DATABASE RESULT: FOUND — {len(matches)} match{'es' if len(matches) > 1 else ''} for '{name}'."]
    for i, row in enumerate(matches):
        common = database.parse_common_names(row.get("common_names"))
        lines.append(f"**{row['scientific_name']}** ({row.get('taxon_rank') or 'unknown'} rank)")
        if common:
            lines.append(f"- Common names: {', '.join(common[:5])}")
        # Only the first match's lineage is evidence: other matches are other animals
        key = "- Lineage:" if i == 0 else "- Lineage (other match):"
        lines.append(f"{key} {row['taxon_path'].replace('|', ' → ')}")
    lines.append("END OF DATABASE RESULT. Use the first match unless another fits the question better; "
                 "call lookup_species with its scientific name for facts.")
    return "\n".join(lines)


def _no_group(name: str) -> str:
    return (f"DATABASE RESULT: No group found for '{name}'.\n"
            'END OF DATABASE RESULT. Answer from your own knowledge and label it "From general knowledge:".')


_first_common = taxon_queries.first_common


def _named(row: dict) -> str:
    """'Bubo bubo (Eurasian eagle-owl)', or the bare name without a common name."""
    common = _first_common(row)
    return f"{row['scientific_name']} ({common})" if common else row["scientific_name"]


def _range_text(bbox: dict) -> str | None:
    """'lat 51.6–83.0, longitude not recorded (…) (4,892 wild records)'; None without latitudes.
    Same text as the panel (frontend/js/traits.js)."""
    if bbox.get("lat_min") is None or bbox.get("lat_max") is None:
        return None
    text = f"lat {bbox['lat_min']}–{bbox['lat_max']}"
    if bbox.get("lon_min") is not None and bbox.get("lon_max") is not None:
        text += f", lon {bbox['lon_min']}–{bbox['lon_max']}"
    else:
        text += ", longitude not recorded (range crosses the 180° line)"
    if bbox.get("records"):
        text += f" ({bbox['records']:,} wild records)"
    return text


@tool
def rank_species_by_trait(trait: str, order: str = "highest", group: str = "Animalia",
                          limit: int = 10) -> str:
    """Rank species in a group by lifespan, body mass, body length, or how far north
    or south their range reaches.

    trait: 'lifespan', 'mass', 'length', 'north' or 'south'. order: 'highest' or 'lowest'.
    group: a scientific or common group name ('Animalia', 'birds', 'Strigiformes').
    Use for the oldest, heaviest, largest, longest-lived (or lightest) animals, and for
    the most northern / furthest south species (trait 'north' or 'south', order 'highest').
    """
    key = re.sub(r"[\s-]+", "_", trait.strip().lower())   # "body mass", "Max Lifespan", "furthest north"
    if key not in taxon_queries.TRAITS:
        return (f"DATABASE RESULT: Cannot rank by '{trait}'. Supported traits: lifespan, mass, length, "
                "north, south.\n"
                'END OF DATABASE RESULT. Answer from your own knowledge and label it "From general knowledge:".')
    column, unit = taxon_queries.TRAITS[key]
    is_range = column in taxon_queries.RANGE_COLUMNS
    label = _RANGE_LABEL[column] if is_range else column.replace("_", " ")
    # Rankings use only well-recorded ranges (taxon_queries.RANK_MIN_RECORDS)
    recorded = (f"a range from {taxon_queries.RANK_MIN_RECORDS:,}+ wild records" if is_range
                else f"a recorded {label}")
    found = taxon_queries.group_paths(group)
    if found is None:
        return _no_group(group)
    where, _, paths = found
    group_path = paths[0] if len(paths) == 1 else paths
    highest = not order.strip().lower().startswith(_LOWEST_WORDS)
    n, ranked = taxon_queries.rank_by_trait(column, group_path, highest, max(1, min(int(limit), 20)))
    if not ranked:
        return (f"DATABASE RESULT: No species in {where} has {recorded}.\n"
                'END OF DATABASE RESULT. Answer from your own knowledge and label it "From general knowledge:".')
    lines = [f"DATABASE RESULT: FOUND — {'top' if highest else 'bottom'} {len(ranked)} by {label} "
             f"among {n} species in {where} with {recorded}."]
    if is_range:
        lat = (lambda v: v) if column == "lat_max" else (lambda v: -v)
        lines += [f"- #{i} {_named(r)}: {label} {_fmt_lat(lat(r['rank_value']))}" for i, r in enumerate(ranked, 1)]
    else:
        lines += [f"- #{i} {_named(r)}: {_fmt_quantity(r['rank_value'])} {unit}" for i, r in enumerate(ranked, 1)]
    if is_range or not highest:
        # The lightest recorded animal is not the lightest animal: most small
        # species (insects, mites) have no value; and most species have no range.
        # The chat adds this sentence itself if the answer leaves it out
        # (LabelChecker.closing_note)
        # A range comes from living animals' records: fossils don't count against it
        total = (taxon_queries.species_count(group_path, living_only=True) if is_range
                 else taxon_queries.species_count(group_path))
        if n < total / 2:
            lines.append(f"- Coverage note: Only {n:,} of {total:,} {'living ' if is_range else ''}"
                         f"species in {where} have {recorded}, so {_MAY_EXIST[column]} may exist.")
    if is_range:
        lines.append("END OF DATABASE RESULT. Range edges come from wild GBIF observations, leaving out the "
                     "outer 0.5% of records, so the true range can reach slightly further. "
                     'Label these facts "Database:". Species without a recorded range are not ranked — '
                     "say so if it matters.")
    else:
        lines.append("END OF DATABASE RESULT. Values are the maximum recorded or estimated in the source, "
                     'not typical values. Label these facts "Database:". Species without a recorded value '
                     "are not ranked — say so if it matters.")
    return "\n".join(lines)


def _fmt_lat(lat: float) -> str:
    """0.1 -> '0.1°N', -5.2 -> '5.2°S', 0 -> '0°'."""
    if lat == 0:
        return "0°"
    return f"{_fmt_quantity(abs(lat))}°{'N' if lat > 0 else 'S'}"


_RANGE_LABEL = {"lat_max": "northern range edge", "lat_south": "southern range edge"}
_LOWEST_WORDS = ("low", "small", "short", "least", "light", "asc", "min", "young", "few")
_MAY_EXIST = {"body_mass": "lighter species", "body_length": "smaller species",
              "max_lifespan": "shorter-lived species",
              "lat_max": "species further north", "lat_south": "species further south"}
# Main ranks, top down: a group lists its children of the next main rank present
_RANK_LADDER = ("kingdom", "phylum", "class", "order", "family", "genus", "species")


def _member_rank(parent_rank: str | None, counts: dict[str, int]) -> str:
    below = _RANK_LADDER[_RANK_LADDER.index(parent_rank) + 1:] if parent_rank in _RANK_LADDER else _RANK_LADDER
    return next((r for r in below if r in counts), next(iter(counts)))


def _group_heading(row: dict) -> str:
    """'Strigiformes (Owls, order)'."""
    extra = ", ".join(x for x in (_first_common(row), row.get("taxon_rank")) if x)
    return f"{row['scientific_name']} ({extra})" if extra else row["scientific_name"]


@tool
def group_stats(group: str) -> str:
    """Count the species in a group and how many are extinct, threatened or declining.

    group: a scientific or common group name ('owls', 'Mammalia', 'Felidae').
    Use for "how many species…", "how many are endangered / extinct / declining".
    """
    found = taxon_queries.group_paths(group)
    if found is None:
        return _no_group(group)
    _, heading, paths = found
    s = taxon_queries.group_summary(paths[0] if len(paths) == 1 else paths)
    lines = [f"DATABASE RESULT: FOUND — statistics for {heading}.",
             f"- Accepted species: {s['species']}",
             f"- Extinct, including fossil species: {s['extinct']}",
             f"- IUCN-assessed species: {sum(s['iucn'].values())}"]
    lines += [f"- IUCN {code} ({_IUCN_NAMES.get(code, code)}): {n}" for code, n in s["iucn"].items()]
    lines += [f"- Population trend {trend}: {n}" for trend, n in s["trends"].items()]
    if s["threatened"]:
        examples = "; ".join(f"{r['scientific_name']} ("
                             + ", ".join(x for x in (_first_common(r), r["iucn_status"]) if x) + ")"
                             for r in s["threatened"])
        lines.append(f"- Threatened examples: {examples}")
    lines.append('END OF DATABASE RESULT. Label these counts "Database:". "Extinct" includes fossil '
                 "species known only from the fossil record; IUCN EX counts species lost in recent "
                 "centuries. Only species assessed by the IUCN have a status; 'not assessed' is not "
                 "the same as safe.")
    return "\n".join(lines)


@tool
def taxonomy_of(name: str) -> str:
    """Show what a species or group belongs to, its relatives, or the groups it contains.

    name: a scientific or common name ('whale', 'Felidae', 'Bubo bubo').
    Use for "what is X related to", "what does X belong to", "which orders do mammals have".
    """
    row = taxon_queries.resolve_taxon(name)
    if row is None:
        return (f"DATABASE RESULT: No species or group found for '{name}'.\n"
                'END OF DATABASE RESULT. Answer from your own knowledge and label it "From general knowledge:".')
    path = row["taxon_path"]
    chain = " → ".join(f"{n['name']} ({n['common']})" if n["common"] else n["name"]
                       for n in taxon_queries.lineage(path))
    lines = [f"DATABASE RESULT: FOUND — classification of {_group_heading(row)}.",
             f"- Lineage: {chain}"]
    sole = None
    if row.get("taxon_rank") == "species" and "|" in path:
        genus_path = path.rsplit("|", 1)[0]
        _, rows = taxon_queries.members(genus_path, 11)
        others = [r for r in rows if r["scientific_name"] != row["scientific_name"]][:10]
        genus = genus_path.rsplit("|", 1)[-1]
        lines.append(f"- Relatives in genus {genus}: "
                     + ("; ".join(_named(r) for r in others) if others else "none recorded"))
        lines += _species_facts(row["scientific_name"])
    else:
        counts = taxon_queries.child_rank_counts(path)
        # "where do koalas live" lands on the koala family: its one living species
        # carries the facts the question is about
        if row.get("taxon_rank") not in taxon_queries._SPECIES_RANKS:
            sole = taxon_queries.sole_living_species(path)
        if sole:
            lines.append(f"- Only living species: {_named(sole)}")
            lines += _species_facts(sole["scientific_name"])
        if counts:
            rank = _member_rank(row.get("taxon_rank"), counts)
            n, rows = taxon_queries.members(path, 15, rank=rank)
            lines.append(f"- Members ({rank or 'unranked'}, {n} in total): "
                         + "; ".join(_named(r) for r in rows))
            others = [f"{r or 'unranked'} {c}" for r, c in counts.items() if r != rank]
            if others:
                lines.append(f"- Other direct children: {', '.join(others)}")
        else:
            lines.append("- Members: none recorded")
    end = ('END OF DATABASE RESULT. Label the classification and the names above "Database:". '
           "Lists are capped; say \"for example\" rather than implying they are complete.")
    if row.get("taxon_rank") == "species" or sole:
        end += (' Anything not listed above (e.g. diet, behaviour) is not in the database — label it '
                '"From general knowledge:".')
    lines.append(end)
    return "\n".join(lines)


_FACT_SKIP = ("- Common names:", "- Lineage:", "- Taxonomic status:")


def _species_facts(scientific_name: str) -> list[str]:
    """The lookup_species fact lines (traits, status, summary, "Not recorded").
    llama3.1:8b calls taxonomy_of for "what does the blue whale eat" whatever the
    prompt says, and prompt fixes for that broke other questions."""
    out = lookup_species.func(scientific_name).splitlines()
    return [l.strip() for l in out[1:]
            if l.strip().startswith(("- ", "**Summary:**")) and not l.startswith(_FACT_SKIP)]


_FOUND = "DATABASE RESULT: FOUND"
# Separates a named species' facts (evidence) from the semantic hits (not evidence)
_SEMANTIC_HEADER = "Other species from semantic search:"


def _evidence_part(tool_name: str, output: str) -> str:
    """The part of a tool result that backs "Database:" sentences, '' for none."""
    if tool_name in _EVIDENCE_TOOLS:
        return output
    if tool_name == "semantic_search_species" and output.startswith(_FOUND):
        return output.partition(_SEMANTIC_HEADER)[0]
    return ""


@tool
def semantic_search_species(query: str) -> str:
    """Search for species semantically using a natural-language query.

    Returns the top-3 most relevant species with a short abstract snippet.
    Use this when you don't know the exact scientific name or want related species.
    """
    # llama3.1:8b sends "what do koalas eat" here as "koalas diet" whatever the prompt
    # says, and only ~7k species have an embedded abstract: a species the query names
    # leads with its lookup_species facts
    named = taxon_queries.named_species(query)
    facts = lookup_species.func(named["scientific_name"]) if named else ""
    if not facts.startswith(_FOUND):
        facts = ""
    results = vector_db.semantic_search(query, n_results=3)
    if not results:
        return facts or (
            "No results from semantic search. "
            "Call lookup_species with your best scientific-name guess to continue."
        )

    parts = [facts + "\n\n" + _SEMANTIC_HEADER] if facts else []
    for r in results:
        common = ", ".join(r["common_names"]) if r["common_names"] else "no common name"
        snippet = r["abstract_snippet"] or "(no abstract)"
        parts.append(
            f"- **{r['scientific_name']}** ({common}) [{r['taxon_rank']}]\n"
            f"  {snippet}"
        )
    return "\n".join(parts)


@tool
def species_in_place(place: str, group: str = "Animalia", limit: int = 10) -> str:
    """List species of a group whose recorded range overlaps a country, continent,
    island, region or sea.

    place: 'Netherlands', 'Holland', 'Europe', 'Borneo', 'Mediterranean Sea'.
    group: a scientific or common group name ('snakes', 'birds', 'Strigiformes').
    Use for "which snakes live in Holland", "what owls are found on Borneo".
    """
    where = places.find_place(place)
    if where is None:
        return (f"DATABASE RESULT: No place found for '{place}'.\n"
                'END OF DATABASE RESULT. Answer from your own knowledge and label it "From general knowledge:".')
    found = taxon_queries.place_group(group)
    if found is None:
        return _no_group(group)
    label, paths = found
    limit = max(1, min(int(limit), 20))
    codes = getattr(where, "countries", ())
    if codes and taxon_queries.has_country_records(codes):
        return _species_in_country(label, paths, where, codes, limit)
    close, n, ranged, rows = taxon_queries.species_in_place(paths, where, limit)
    lines = []
    if rows:
        lines.append(f"DATABASE RESULT: FOUND — {close} species in {label} have a recorded range that "
                     f"overlaps {where.label} and fits it closely; showing {len(rows)}, closest fit first.")
        lines.append("- Species: " + "; ".join(_named(r) for r in rows))
        if n > close:
            lines.append(f"- Wider ranges: {n - close} more species have a much wider range that also "
                         "overlaps it.")
    else:
        lines.append(f"DATABASE RESULT: No species in {label} has a recorded range overlapping {where.label}.")
    total = taxon_queries.living_species_count(paths)
    if ranged < total / 2:
        lines.append(f"- Coverage note: Only {ranged:,} of {total:,} living species in {label} have a range "
                     f"from {taxon_queries.PLACE_MIN_RECORDS:,}+ wild records, so other species may occur "
                     f"in {where.name} too.")
    lines.append("END OF DATABASE RESULT. A range is a box around a species' wild GBIF records, so an "
                 "overlapping range means the species may occur there, not that it does: say its recorded "
                 "range overlaps the place, and don't call the list complete. "
                 + ('Label these facts "Database:".' if rows else
                    'Answer the rest from your own knowledge and label it "From general knowledge:".'))
    return "\n".join(lines)


def _species_in_country(label: str, paths: list[str], where, codes, limit: int) -> str:
    """species_in_place for a country: wild GBIF records per country, not range boxes."""
    n, few, rows = taxon_queries.species_in_country(paths, codes, limit,
                                                    getattr(where, "partial", ()), where)
    least = taxon_queries.COUNTRY_MIN_RECORDS
    lines = []
    if rows:
        lines.append(f"DATABASE RESULT: FOUND — {n:,} species in {label} are commonly recorded in the wild "
                     f"in {where.label}; showing {len(rows)}, most recorded first.")
        lines.append("- Species: " + "; ".join(_named(r) for r in rows))
    elif not few:
        # No record at all is an answer in itself (Ireland has no snakes)
        lines.append(f"DATABASE RESULT: FOUND — no species in {label} has any wild GBIF record in "
                     f"{where.label}.")
        lines.append(f"END OF DATABASE RESULT. GBIF holds wild records from all over {where.name} (surveys, "
                     "citizen science), so this means they are absent or very rare there. Say that the "
                     'database has no wild records of them there, labelled "Database:"; don\'t name '
                     "species as found there.")
        return "\n".join(lines)
    else:
        lines.append(f"DATABASE RESULT: No species in {label} has {least} or more wild GBIF records in "
                     f"{where.label}.")
    if few:
        lines.append(f"- Rarely recorded: {few:,} more species have far fewer records there (under 1% of "
                     "the most recorded one): rarely seen species, strays or escaped pets.")
    lines.append("END OF DATABASE RESULT. These species have been observed in the wild in this country "
                 "(GBIF: surveys, citizen science); rarely observed species may be missing, so don't call "
                 "the list complete. "
                 + ('Label these facts "Database:".' if rows else
                    'Answer from your own knowledge and label it "From general knowledge:".'))
    return "\n".join(lines)


@tool
def get_species_image(scientific_name: str) -> str:
    """Retrieve an image URL and attribution for a species.

    Checks the local database first; if no image is stored, runs the 4-source
    chain (Wikipedia → iNaturalist → Wikimedia Commons → DuckDuckGo) and caches
    the result back to the database.
    Returns a JSON string with 'url', 'attribution', and 'source' fields.
    """
    row = database.get_species(scientific_name)
    if row is None:
        return json.dumps({"error": f"Species '{scientific_name}' not found."})

    url         = row.get("primary_image_url") or ""
    attribution = row.get("image_attribution") or ""

    if url == "__none__":
        return json.dumps({"error": "No image found in any source."})

    if url:
        return json.dumps({"url": url, "attribution": attribution, "source": "database"})

    common_names = database.parse_common_names(row.get("common_names"))
    try:
        result = image_utils.fetch_image(
            scientific_name, common_names or None, row.get("taxon_path"), rank=row.get("taxon_rank"),
            exclude=set(database.parse_rejected_images(row.get("rejected_images"))))
    except image_utils.ImagesUnavailable:
        return json.dumps({"error": "Picture sources are unavailable right now."})
    if result:
        url, attribution = result
        if not database.replace_species_image(scientific_name, url, attribution,
                                              row.get("primary_image_url")):
            stored = database.get_species(scientific_name) or {}
            url, attribution = stored.get("primary_image_url") or url, stored.get("image_attribution") or ""
        return json.dumps({"url": url, "attribution": attribution, "source": "fetched"})

    return json.dumps({"error": "No image found in database, Wikipedia, iNaturalist, Wikimedia Commons, or DuckDuckGo."})


# ── Source-label verification ─────────────────────────────────────────────────

_DB_LABEL = "Database:"
_DB_EST_LABEL = "Database (estimated):"
_GK_LABEL = "From general knowledge:"
_LABEL_TEXT = {"db": _DB_LABEL, "est": _DB_EST_LABEL, "gk": _GK_LABEL}
# Labels as the LLM writes them (case and spacing vary). The estimated form is
# tried first so it is never split into "Database:" + "(estimated):".
_LABEL_RE = re.compile(
    r"(?P<est>database\s*\(\s*estimated\s*\)\s*:)|(?P<db>database\s*:)|(?P<gk>from general knowledge\s*:)",
    re.IGNORECASE)
_EST_SUFFIX = " (estimated)"

_IUCN_NAMES = {
    "LC": "least concern", "NT": "near threatened", "VU": "vulnerable",
    "EN": "endangered", "CR": "critically endangered", "EW": "extinct in the wild",
    "EX": "extinct", "DD": "data deficient",
}
_NUMBER_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
# Count lines of group_stats / taxonomy_of: their numbers only back sentences about counts
_COUNT_LINE_RE = re.compile(
    r"- (?:Accepted species:|Extinct, including|IUCN-assessed|IUCN [A-Z]{2} \(|Population trend [^:]|"
    r"Other direct children:)")
_COUNT_WORDS_RE = re.compile(
    r"\b(?:species|extinct|endangered|vulnerable|threatened|assessed|concern|deficient|"
    r"declin\w*|decreas\w*|increas\w*|stable|population|genera|genus|famil\w+|orders?|"
    r"class(?:es)?|phyl\w+|members?|groups?)\b")


def _nums(text: str) -> set[float]:
    """Numbers in text; "9,642" is one number."""
    return {float(n.replace(",", "")) for n in _NUMBER_RE.findall(text)}
_WORD_RE = re.compile(r"[a-z]+")
_COVERAGE_RE = re.compile(r"\bamong ([\d,]+) species\b")
# species_in_place for a country without a single wild record of the group
_ABSENT_HEAD_RE = re.compile(r"— no species in .+ has any wild GBIF record in ")
_NEGATION_RE = re.compile(r"\b(?:no|none|not|absent|never)\b")
_PLACE_HEAD_RE = re.compile(r"— ([\d,]+) species in .+ (?:have a recorded range that overlaps |are commonly recorded in the wild in )")
_CAVEAT_LINE = "END OF DATABASE RESULT. Values are the maximum recorded or estimated"
_CAVEAT = "maximum recorded or estimated"
_MATCH_LINE_RE = re.compile(r"\*\*(.+?)\*\* \([^)]* rank\)$")
_FIND_HEAD_RE = re.compile(r"DATABASE RESULT: FOUND — \d+ match(?:es)? for ")
_COVERAGE_WORDS_RE = re.compile(r"\b(?:recorded|ranking|ranked|based on|among|data)\b")
# Fact-line labels whose "Not recorded" name differs
_LINE_FIELD = {"max lifespan": "lifespan", "trophic level": "diet / trophic level"}
_MISSING_RE = re.compile(
    r"\bnot recorded\b|\bdoes not record\b|\bdoesn't record\b|\bno (?:data|record)\b"
    r"|\bnot in the database\b")
# Split after . ! ? followed by whitespace, or before a newline
_SENTENCE_END_RE = re.compile(r"[.!?](?=\s)|(?=\n)")
_RANKED_RE = re.compile(r"- #\d+ (?P<names>[^:]+):(?P<value>.*)")
# A denial, then a threshold in the same clause: "no turtles … live over 100 years"
_DENIAL_RE = re.compile(r"\b(?:no|none|never|not|cannot|nothing)\b|n't\b")
_BELOW_WORDS = ("under", "less than", "fewer than", "lighter than", "smaller than",
                "shorter than", "below")
_THRESHOLD_RE = re.compile(
    r"\b(?P<dir>over|more than|longer than|older than|greater than|heavier than|larger than|"
    r"bigger than|above|exceeding|exceeds?|beyond|" + "|".join(_BELOW_WORDS) + r")\s+"
    r"(?P<n>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)")
_CLAUSE_BREAK_RE = re.compile(r"[,;]|\b(?:and|but|while|although|though|yet|whereas)\b")
_LIST_MARKER_RE = re.compile(r"(?:[-*+]|\d+\.)\s+")
_SUMMARY_MIN_WORDS = 3
_SUMMARY_MIN_OVERLAP = 0.5


class LabelChecker:
    """Verify "Database:" labels in streamed LLM text against actual tool output.

    The LLM decides which sentences it labels "Database:", and an 8B model
    gets that wrong when asked about things the record doesn't hold (cat
    breeds, lion diet). Each "Database:" sentence must contain a value from a
    lookup_species result — a number, IUCN status, trend, habitat, trophic
    level, higher taxon, or enough summary words — otherwise it is relabelled
    "From general knowledge:". Text is buffered and emitted per sentence.
    """

    def __init__(self) -> None:
        self._buf = ""
        self._segment: str | None = None   # label in force in the LLM's text
        self._emitted: str | None = None   # label in force in our output
        self._numbers: set[float] = set()
        self._phrases: set[str] = set()
        self._est_numbers: set[float] = set()   # evidence from "(estimated)" lines
        self._est_phrases: set[str] = set()
        self._common: set[str] = set()
        self._summary: set[str] = set()
        self._summary_numbers: set[float] = set()
        self._name_words: set[str] = set()
        self._count_numbers: set[float] = set()   # group counts: need a count word
        self._ranked: list[float] = []   # values of a rank_species_by_trait result
        self._ranked_unit = ""
        self._not_recorded: set[str] = set()   # fields a lookup lists as missing
        self._held_fields: set[str] = set()    # fields some result of the turn holds
        self._coverage_numbers: set[float] = set()
        self._caveat = False
        self._coverage_note = ""          # a ranking's "- Coverage note:" sentence
        self._note_said = False           # the answer stated the coverage itself
        self._said_anything = False
        self._absent = False              # a country without any record of the group

    def add_tool_output(self, output: str) -> None:
        matches = 0   # find_species "**Name** (rank rank)" lines seen
        for line in output.splitlines():
            line = line.strip()
            if line.startswith("DATABASE RESULT: FOUND"):
                name = line.split("—", 1)[-1].replace("is in the database.", "")
                self._name_words |= set(_WORD_RE.findall(name.lower()))
                # A ranking's coverage ("among 1469 species"): only for a sentence
                # about the ranking, not "there are 1469 bird species"
                if m := _COVERAGE_RE.search(line):
                    self._coverage_numbers |= _nums(m.group(1))
                # species_in_place: "116 species in … have a recorded range that overlaps …"
                if m := _PLACE_HEAD_RE.search(line):
                    self._count_numbers |= _nums(m.group(1))
                if _ABSENT_HEAD_RE.search(line):
                    self._absent = True
            elif line.startswith(_CAVEAT_LINE):
                self._caveat = True
            elif m := _MATCH_LINE_RE.match(line):
                # Other find_species matches are findings; the first is the subject
                if matches and _FIND_HEAD_RE.match(output.lstrip()):
                    self._phrases.add(m.group(1).lower())
                matches += 1
            elif line.startswith("- Lineage:"):
                taxa = [t.strip() for t in line.split(":", 1)[1].split("→") if t.strip()]
                names = [t.split(" (")[0].strip() for t in taxa]
                # The subject is not evidence: the last level, and for a species or
                # subspecies every level from its genus down ("Panthera",
                # "Panthera leo" both match "Panthera leo leo")
                cut = len(names) - 1
                if names and " " in names[-1]:
                    genus = names[-1].split()[0]
                    cut = names.index(genus) if genus in names else len(names) - 2
                # Scientific names only: common names of higher taxa are generic
                # ("Animal", "Cat") and would back unrelated sentences; the
                # kingdom is true of everything
                for name in names[1:cut]:
                    self._add_names(name, common=False)
            elif line.startswith(("- Members", "- Relatives in genus")):
                head, _, items = line.partition(":")
                self._count_numbers |= _nums(head)
                for item in items.split(";"):
                    self._add_names(item, common=False)
            elif _COUNT_LINE_RE.match(line):
                self._count_numbers |= _nums(line.split(":", 1)[-1])
            elif line.startswith("- Common names:"):
                self._common |= {c.strip().lower() for c in line.split(":", 1)[1].split(",")}
            elif line.startswith("- IUCN status:"):
                self._held_fields.add("iucn status")
                code = line.split(":", 1)[1].strip().upper()
                self._phrases.add(code.lower())
                if code in _IUCN_NAMES:
                    self._phrases.add(_IUCN_NAMES[code])
            elif line.startswith("**Summary:**"):
                self._summary |= set(_WORD_RE.findall(line.lower()))
                self._summary_numbers |= {*_nums(line)}
            elif line.startswith("- Not recorded:"):
                # Names of missing fields are the opposite of evidence, except
                # for a sentence saying they are missing
                self._not_recorded |= {f.strip().lower() for f in line.split(":", 1)[1].split(",")
                                       if f.strip()}
            elif line.startswith("- Lineage (other match):"):
                continue
            elif line.startswith("- Coverage note:"):
                self._coverage_note = line.split(":", 1)[1].strip()
                self._coverage_numbers |= _nums(self._coverage_note)
            elif m := _RANKED_RE.match(line):
                # "- #1 Bubo bubo (Eurasian eagle-owl): 68 years": the name is the finding
                self._add_names(m["names"])
                self._numbers |= _nums(m["value"])
                number, _, unit = m["value"].strip().partition(" ")
                if _NUMBER_RE.fullmatch(number):
                    self._ranked.append(float(number.replace(",", "")))
                    self._ranked_unit = unit.strip()
            elif line.startswith(_COUNTRIES_LINE):
                self._held_fields.add("countries")
                for name in line.split(":", 1)[1].split(","):
                    name = name.strip().lower()
                    if name and not name.startswith("and "):
                        self._phrases.add(name)
            elif line.startswith(("- Threatened examples:", "- Species:")):
                for item in line.split(":", 1)[1].split(";"):
                    self._add_names(item)
            elif line.startswith("- "):
                field = line[2:].split(":", 1)[0].strip().lower()
                self._held_fields.add(_LINE_FIELD.get(field, field))
                estimated = line.endswith(_EST_SUFFIX)
                if estimated:
                    line = line[:-len(_EST_SUFFIX)]
                numbers, phrases = ((self._est_numbers, self._est_phrases) if estimated
                                    else (self._numbers, self._phrases))
                value = line.split(":", 1)[-1]
                numbers |= _nums(value)
                if not _NUMBER_RE.search(value):
                    phrases.add(value.strip().lower())
                if line.startswith("- Habitat:"):
                    # Multi-value lines ("Grassland - Subtropical/Tropical Dry; Savanna - Dry")
                    # get paraphrased: each part, and each IUCN class head, is evidence too
                    for part in re.split(r"[;,]", value):
                        part = part.strip().lower()
                        if len(part) >= 4:
                            phrases.add(part)
                            head = part.split(" - ", 1)[0].strip()
                            if len(head) >= 4:
                                phrases.add(head)

    def _add_names(self, text: str, common: bool = True) -> None:
        """'Name (common, common)' -> each name as evidence. An IUCN code in the
        parentheses ('EN') is not a name: "en" would match unrelated words."""
        sci, _, rest = text.strip().partition(" (")
        if sci.strip():
            self._phrases.add(sci.strip().lower())
        if not common:
            return
        self._phrases |= {c.strip().lower() for c in rest.rstrip(")").split(",")
                          if c.strip() and c.strip() not in _IUCN_NAMES}

    def feed(self, text: str) -> str:
        self._buf += text
        out = []
        while True:
            body_start = len(self._buf) - len(self._buf.lstrip())
            m = _SENTENCE_END_RE.search(self._buf, body_start)
            if not m or m.end() == body_start:
                break
            out.append(self._process(self._buf[:m.end()]))
            self._buf = self._buf[m.end():]
        return "".join(out)

    def flush(self) -> str:
        rest, self._buf = self._buf, ""
        return self._process(rest) if rest.strip() else rest

    def closing_note(self) -> str:
        """The ranking's coverage sentence, for the end of an answer that left
        it out ("the smallest animal is …" from 3,612 of 1.8 million species)."""
        if self._coverage_note and self._said_anything and not self._note_said:
            return f"\n\n{_DB_LABEL} {self._coverage_note}"
        return ""

    def _process(self, sentence: str) -> str:
        body = sentence.lstrip()
        lead = sentence[:len(sentence) - len(body)]
        own = None
        m = _LABEL_RE.match(body)
        if m:
            own, body = m.lastgroup, body[m.end():].lstrip()
            self._segment = own
        if body.strip():
            self._said_anything = True
            if self._coverage_note and _nums(body) & _nums(self._coverage_note):
                self._note_said = True
        if (correction := self._contradiction(body)) is not None:
            self._emitted = "db"
            return f"{lead}{_DB_LABEL} {correction}"
        if self._segment is None:
            return sentence
        # A database-labelled sentence gets the label its evidence earns
        want = (self._supported(body) or "gk") if self._segment in ("db", "est") else "gk"
        if own is None and want == self._emitted:
            return sentence
        self._emitted = want
        # "Database: - #1 …" breaks the Markdown list: the label goes after the bullet
        if marker := _LIST_MARKER_RE.match(body):
            return f"{lead}{marker.group()}{_LABEL_TEXT[want]} {body[marker.end():]}"
        return f"{lead}{_LABEL_TEXT[want]} {body}"

    def _supported(self, body: str) -> str | None:
        """"est" if any estimate-only value backs the sentence, "db" if a sourced
        value does, else None."""
        low = body.lower()
        # Any estimate-only value in the sentence makes the whole sentence an
        # estimate, even when a sourced value is mentioned beside it
        if self._backed(low, self._est_numbers - self._numbers, self._est_phrases - self._phrases):
            return "est"
        if self._backed(low, self._numbers, self._phrases):
            return "db"
        if _COUNT_WORDS_RE.search(low) and _nums(low) & self._count_numbers:
            return "db"
        if (self._coverage_numbers and _COVERAGE_WORDS_RE.search(low)
                and _nums(low) & self._coverage_numbers):
            return "db"
        known = (self._numbers | self._est_numbers | self._summary_numbers
                 | self._count_numbers | self._coverage_numbers)
        if self._caveat and _CAVEAT in low and _nums(low) <= known:
            return "db"
        # One clause only: "not recorded, but lions hunt zebras" must not ride along
        if (_MISSING_RE.search(low) and not _CLAUSE_BREAK_RE.search(low)
                and any(re.search(rf"\b{re.escape(w)}\b", low) for w in self._missing_words())):
            return "db"
        # "There are no wild records of snakes in Ireland": one clause, no numbers
        if (self._absent and _NEGATION_RE.search(low) and not _CLAUSE_BREAK_RE.search(low)
                and not _nums(low)):
            return "db"
        if "name" in low and any(re.search(rf"\b{re.escape(c)}\b", low) for c in self._common if c):
            return "db"
        words = {w for w in _WORD_RE.findall(low) if len(w) >= 5} - self._name_words
        if (self._summary and len(words) >= _SUMMARY_MIN_WORDS
                and len(words & self._summary) / len(words) >= _SUMMARY_MIN_OVERLAP):
            # Overlapping words don't vouch for a number ("can live up to 20 years")
            known = self._numbers | self._est_numbers | self._summary_numbers
            if _nums(low) <= known:
                return "db"
        return None

    def _contradiction(self, body: str) -> str | None:
        """The ranked count, if the sentence denies that anything passes a threshold
        the ranking passes ("there are no turtles … over 100 years" next to a
        152-year tortoise). An 8B model answers "aren't there …?" with a denial
        whatever the tool returned; the prompt can't stop it."""
        if not self._ranked:
            return None
        low = body.lower()
        denial = _DENIAL_RE.search(low)
        if not denial:
            return None
        for t in _THRESHOLD_RE.finditer(low, denial.end()):
            if _CLAUSE_BREAK_RE.search(low, denial.end(), t.start()):
                break   # "no teeth, and some live over 100 years" denies something else
            limit = float(t["n"].replace(",", ""))
            below = t["dir"] in _BELOW_WORDS
            k = sum(v < limit if below else v > limit for v in self._ranked)
            if k:
                unit = f" {self._ranked_unit}" if self._ranked_unit else ""
                return (f"{k} of the {len(self._ranked)} ranked species "
                        f"{'are below' if below else 'exceed'} {t['n']}{unit}.")
        return None

    def _missing_words(self) -> set[str]:
        """Words naming a field missing from every result of the turn: the field
        and its long words, except words of held fields ("body" when body mass
        is recorded and body length is not)."""
        missing = self._not_recorded - self._held_fields
        held = {w for f in self._held_fields for w in _WORD_RE.findall(f)}
        words = set(missing)
        for field in missing:
            words |= {w for w in _WORD_RE.findall(field) if len(w) >= 4 and w not in held}
        return words

    @staticmethod
    def _backed(low: str, numbers: set[float], phrases: set[str]) -> bool:
        if _nums(low) & numbers:
            return True
        return any(re.search(rf"\b{re.escape(p)}\b", low) for p in phrases)


# ── Agent ──────────────────────────────────────────────────────────────────────

def ollama_llm(**extra) -> ChatOllama:
    """The app's Ollama model (chat and trait estimator share it). Thinking
    off: qwen3.8 thinks by default (seconds per answer), and thinking models
    can leak the reasoning into the answer text."""
    import langchain_ollama   # looked up per call so tests can swap the class
    return langchain_ollama.ChatOllama(model=chat_model(), base_url=OLLAMA_BASE_URL, temperature=0,
                                       reasoning=False, num_ctx=OLLAMA_NUM_CTX, **extra)


def get_llm() -> ChatOllama:
    return ollama_llm()


def build_agent(follow_up: bool = False):
    llm = get_llm()
    tools = [lookup_species, find_species, rank_species_by_trait, group_stats, taxonomy_of,
             species_in_place, semantic_search_species, get_species_image]
    prompt = _SYSTEM_PROMPT + _FOLLOW_UP_PROMPT if follow_up else _SYSTEM_PROMPT
    return create_react_agent(llm, tools, prompt=prompt)


# Tools whose output is evidence for "Database:" sentences
_EVIDENCE_TOOLS = frozenset({"lookup_species", "find_species", "rank_species_by_trait",
                             "group_stats", "taxonomy_of", "species_in_place"})

_TOOL_CALL_RE = re.compile(r'^\s*\{\s*"name"\s*:')


def _filter_json_blobs(text: str, state: dict) -> str:
    """Strip raw JSON tool-call blobs ({"name": ...}) from streamed text.

    `state` carries brace_depth and buf across token boundaries.
    Returns only the characters that should be forwarded to the client.
    """
    out_chars: list[str] = []
    for ch in text:
        if state["depth"] == 0:
            if ch == '{':
                state["depth"] = 1
                state["buf"] = ch
            else:
                out_chars.append(ch)
        else:
            state["buf"] += ch
            if ch == '{':
                state["depth"] += 1
            elif ch == '}':
                state["depth"] -= 1
                if state["depth"] == 0:
                    if not _TOOL_CALL_RE.match(state["buf"]):
                        out_chars.append(state["buf"])
                    state["buf"] = ""
    return "".join(out_chars)


# Conversation memory: the last turns the browser sends, each cut to a length
# llama3.1:8b handles without slowing down
HISTORY_MAX_MESSAGES = 6
HISTORY_MAX_CHARS = 1500


_LIST_ITEM_RE = re.compile(r"#(\d+)\s+([A-Z][a-z-]+(?: [a-z-]+){1,2})")
_LIST_REF_RE = re.compile(r"#(\d+)\b")


def _name_list_refs(question: str, history: list[dict] | None) -> str:
    """'and #2' -> 'and #2 (#2 = Cinachyra antarctica)' from the previous answer's
    numbered list: llama3.1:8b passed "#1" itself to taxonomy_of."""
    previous = next((t["content"] for t in reversed(history or []) if t["role"] == "assistant"), "")
    items = dict(_LIST_ITEM_RE.findall(previous))
    named = [f"#{n} = {items[n]}" for n in dict.fromkeys(_LIST_REF_RE.findall(question)) if n in items]
    return f"{question} ({'; '.join(named)})" if named else question


def _history_messages(history: list[dict] | None) -> list:
    msgs = []
    for turn in (history or [])[-HISTORY_MAX_MESSAGES:]:
        cls = HumanMessage if turn["role"] == "user" else AIMessage
        msgs.append(cls(content=turn["content"][:HISTORY_MAX_CHARS]))
    return msgs


async def stream_response(user_message: str, history: list[dict] | None = None) -> AsyncGenerator[str, None]:
    """Yield server-sent event strings for each token/image from the agent.
    `history`: earlier turns as {role: user|assistant, content}, oldest first."""
    question = _name_list_refs(user_message, history)
    # An answer written without any tool call is held back and, the first
    # time, dropped and asked again with a nudge: qwen3.8 answered 3 of 7
    # follow-ups from memory, which the label checker then marks general knowledge
    for attempt in range(2):
        try:
            agent = build_agent(follow_up=bool(history))
        except Exception as exc:
            yield _sse("error", {"detail": f"Failed to initialise agent: {exc}"})
            return
        prompt = question + (_TOOL_NUDGE if attempt else "")
        held: list[str] = []
        tool_called = False
        run: dict = {}   # this attempt's sent text and subjects, for the links event
        async for sse in _run_agent(agent, prompt, history, run):
            if sse is _TOOL_STARTED:
                tool_called = True
                for h in held:   # one event per chunk: readers parse them singly
                    yield h
                held.clear()
            elif sse.startswith(_ERROR_PREFIX):
                yield sse
                return
            elif tool_called or attempt == 1 or not sse.startswith(_TOKEN_PREFIX):
                yield sse   # images, and the last attempt's text, are never held
            else:
                held.append(sse)
        if tool_called or attempt == 1:
            for h in held:
                yield h
            break
    try:
        links = await asyncio.to_thread(_answer_links, run)
    except Exception:   # links are optional: a database error must not fail a complete answer
        log.exception("chat name links failed")
        links = []
    if links:
        yield _sse("links", {"links": links})
    yield _sse("done", {})


def _answer_links(run: dict) -> list[dict]:
    """Where the shown attempt's text mentions the subjects of its database results (scientific
    and common names), or writes the exact scientific name of any species in the tree."""
    text = run.get("text") or ""
    if not text:
        return []
    names = run.get("subjects") or []
    subjects = taxon_links.subject_rows(names) if names else []
    known = {r["scientific_name"] for r in subjects}
    named = [r for r in taxon_links.named_rows(text) if r["scientific_name"] not in known]
    return taxon_links.match_links(text, subjects + named)


_TOOL_NUDGE = "\n(Call one of the tools before answering.)"
_TOOL_STARTED = "tool started"   # sentinel from _run_agent, compared by identity
_TOKEN_PREFIX = 'data: {"type": "token"'
_ERROR_PREFIX = 'data: {"type": "error"'


async def _run_agent(agent, prompt: str, history: list[dict] | None,
                     run: dict | None = None) -> AsyncGenerator[str, None]:
    """One agent run: SSE token / image / error strings, and _TOOL_STARTED when
    the first tool starts. No "done": the caller decides when the answer ends.
    `run` is filled with "text" (the token text yielded) and "subjects" (row keys
    of the database results' subjects, taxon_links.subject_names)."""
    inputs = {"messages": [*_history_messages(history), HumanMessage(content=prompt)]}
    json_state = {"depth": 0, "buf": ""}
    labels = LabelChecker()
    started = False
    run = {} if run is None else run
    run["text"], run["subjects"] = "", []

    try:
        async for event in agent.astream_events(inputs, version="v2"):
            kind = event["event"]

            if kind == "on_chat_model_stream":
                chunk: AIMessageChunk = event["data"]["chunk"]
                text = chunk.content
                if text:
                    filtered = labels.feed(_filter_json_blobs(text, json_state))
                    if filtered:
                        run["text"] += filtered
                        yield _sse("token", {"content": filtered})

            elif kind == "on_tool_start" and not started:
                started = True
                yield _TOOL_STARTED

            elif kind == "on_tool_end":
                tool_name = event.get("name", "")
                output = event["data"].get("output", "")
                output = getattr(output, "content", output)  # ToolMessage or str
                if isinstance(output, str) and (evidence := _evidence_part(tool_name, output)):
                    labels.add_tool_output(evidence)
                if isinstance(output, str):
                    run["subjects"] += [n for n in taxon_links.subject_names(tool_name, output)
                                        if n not in run["subjects"]]
                if tool_name == "get_species_image" and isinstance(output, str):
                    try:
                        payload = json.loads(output)
                        if "url" in payload:
                            yield _sse("image", payload)
                    except (json.JSONDecodeError, TypeError):
                        pass

    except Exception as exc:
        msg = str(exc)
        if "Connection refused" in msg or "Failed to connect" in msg or "ConnectError" in msg:
            yield _sse("error", {"detail": "Ollama is not running. Start it with: ollama serve"})
        else:
            yield _sse("error", {"detail": msg})
        return

    # Flush any unterminated buffer as plain text (incomplete JSON → probably prose)
    rest = labels.feed(json_state["buf"]) + labels.flush()
    rest += labels.closing_note()
    if rest:
        run["text"] += rest
        yield _sse("token", {"content": rest})


def _sse(event_type: str, data: dict) -> str:
    return f"data: {json.dumps({'type': event_type, **data})}\n\n"
