"""Chat name links: the subjects of a turn's database results, and where the answer mentions them.

Subjects are read from the tools' text output (formats in llm_agent.py), so they stay correct
when LangGraph runs tools concurrently: each on_tool_end carries its own output.
"""

import re

from app import database

_MIN_COMMON = 3          # shorter common names ("Ox") match too much ordinary text
_PLURALS = ("", "s", "es")
_FOUND = "DATABASE RESULT: FOUND"
# A one-word common name right after another word may be part of another animal's name
# ("sea lions", "mountain lions"); after these words it is the animal itself ("the lion")
_PRECEDING_OK = frozenset("""
    a an the this that these those its their his her our your my some any all many most more
    few several both each every no not other such and or nor but of in on at to for from with by
    as like than about among between including include includes are is was were be being been
    do does did eat eats ate how what which why where when whose while if so also only even
    one two three four five six seven eight nine ten
""".split())
_PREV_WORD_RE = re.compile(r"([^\W\d_]+)[ \-]$")
_BOLD_RE = re.compile(r"^\*\*(?P<name>.+?)\*\* \(")
_SEMANTIC_RE = re.compile(r"^- \*\*(?P<name>.+?)\*\* \(.*\) \[[^\]]*\]$")
_RANKED_RE = re.compile(r"^- #\d+ (?P<item>.+):")
_ITEMS_RE = re.compile(r"^- (?:Members(?: \([^)]*\))?|Relatives in genus [^:]+|Only living species): "
                       r"(?P<items>.+)$")


def _key_candidates(item: str) -> list[str]:
    """Row keys an item may name, longest first: 'Aedes (Stegomyia) (Tiger mosquitoes, subgenus)'
    -> itself, 'Aedes (Stegomyia)', 'Aedes'. Subgenus keys contain ' (', so the text can't just be cut
    at the first one; subject_rows keeps the longest candidate that is a key."""
    item = item.strip()
    out = [item]
    while " (" in item:
        item = item.rsplit(" (", 1)[0].strip()
        out.append(item)
    return out


def _after(header: str, marker: str) -> str:
    return header.partition(marker)[2].removesuffix(".")


def subject_names(tool_name: str, output: str) -> list[str]:
    """The subjects of one tool result as item texts ('Bubo bubo (Eurasian eagle-owl)'), in output
    order, no duplicates; subject_rows resolves each to its row key."""
    lines = (output or "").splitlines()
    names: list[str] = []
    if tool_name == "semantic_search_species":
        # A species the query names leads, in the lookup_species format
        if lines and lines[0].startswith(_FOUND):
            names = [_after(lines[0], "FOUND — ").partition(" is in the database")[0]]
        names += [m["name"] for line in lines if (m := _SEMANTIC_RE.match(line))]
    elif lines and lines[0].startswith(_FOUND):
        header = lines[0]
        if tool_name == "lookup_species":
            names = [_after(header, "FOUND — ").partition(" is in the database")[0]]
        elif tool_name == "find_species":
            names = [m["name"] for line in lines[1:] if (m := _BOLD_RE.match(line))][:1]
        elif tool_name == "rank_species_by_trait":
            names = [m["item"] for line in lines[1:] if (m := _RANKED_RE.match(line))]
        elif tool_name == "species_in_place":
            names = [item for line in lines[1:] if line.startswith("- Species: ")
                     for item in line[len("- Species: "):].split("; ")]
        elif tool_name == "group_stats":
            names = [_after(header, "statistics for ")]
        elif tool_name == "taxonomy_of":
            names = [_after(header, "classification of ")]
            for line in lines[1:]:
                if (m := _ITEMS_RE.match(line)) and m["items"] != "none recorded":
                    names += m["items"].split("; ")
    return list(dict.fromkeys(n.strip() for n in names if n.strip()))


def subject_rows(names: list[str]) -> list[dict]:
    """Rows of the subjects by exact primary key, in `names` order, without duplicates.

    Each name is an item text from subject_names; its longest key candidate that exists wins.
    Unknown names are dropped. No NOCASE fallback: database.get_species's fallback scans the table.
    """
    candidates = {n: _key_candidates(n) for n in names}
    keys = list(dict.fromkeys(k for ks in candidates.values() for k in ks))
    if not keys:
        return []
    conn = database.get_connection()
    try:
        rows = conn.execute(
            "SELECT scientific_name, taxon_path, taxon_rank, common_names FROM species "
            f"WHERE scientific_name IN ({', '.join('?' * len(keys))})", keys).fetchall()
    finally:
        conn.close()
    by_key = {r["scientific_name"]: dict(r) for r in rows}
    found = (next((by_key[k] for k in candidates[n] if k in by_key), None) for n in names)
    return list({r["scientific_name"]: r for r in found if r}.values())


def _plain(key: str) -> str:
    """A homonym key 'Bubo [Strigidae]' is written 'Bubo' in text."""
    return re.sub(r"\s*\[[^\]]*\]$", "", key)


def match_links(text: str, rows: list[dict]) -> list[dict]:
    """Where the answer mentions the subjects: one entry per distinct matched text, first appearance first.

    Scientific names match exactly, common names in any case with +s / +es plurals, on word boundaries;
    the longest form wins and nothing inside a longer match is matched again.
    """
    exact: dict[str, dict] = {}
    folded: dict[str, dict] = {}
    for row in rows:
        exact.setdefault(_plain(row["scientific_name"]), row)
        for name in database.parse_common_names(row.get("common_names")):
            if isinstance(name, str) and len(name.strip()) >= _MIN_COMMON:
                for suffix in _PLURALS:
                    folded.setdefault((name.strip() + suffix).casefold(), row)
    if not text or not (exact or folded):
        return []
    forms = [(f, False) for f in exact] + [(f, True) for f in folded]
    forms.sort(key=lambda form: len(form[0]), reverse=True)
    alternation = "|".join(f"(?i:{re.escape(f)})" if fold else re.escape(f) for f, fold in forms)
    pattern = re.compile(rf"(?<!\w)(?:{alternation})(?!\w)")
    links: dict[str, dict] = {}
    doubtful: set[str] = set()   # the browser links every mention of a text, so one doubt drops it
    for m in pattern.finditer(text):
        found = m.group(0)
        row = exact.get(found)
        if row is None:
            row = folded.get(found.casefold())
            if row and " " not in found and "-" not in found:
                prev = _PREV_WORD_RE.search(text, 0, m.start())
                if prev and prev.group(1).lower() not in _PRECEDING_OK:
                    doubtful.add(found)
        if row and found not in links:
            links[found] = {"text": found, "scientific_name": row["scientific_name"],
                            "taxon_path": row.get("taxon_path"), "taxon_rank": row.get("taxon_rank")}
    return [link for text_, link in links.items() if text_ not in doubtful]


# "Genus species" or "Genus species subspecies": capital first word, lower-case epithets
_BINOMIAL_RE = re.compile(r"(?<![\w-])([A-Z][a-z]+(?:-[a-z]+)?) ([a-z]+(?:-[a-z]+)?)(?: ([a-z]+(?:-[a-z]+)?))?(?![\w-])")


def named_rows(text: str) -> list[dict]:
    """Species in the tree whose exact scientific name the answer writes, even from general knowledge.

    Scientific names can't open a look-alike, unlike common names ("small fish"), so they link
    without a lookup. The rows carry no common names: those link only for looked-up subjects.
    """
    candidates: list[str] = []
    for m in _BINOMIAL_RE.finditer(text or ""):
        genus, species, sub = m.groups()
        if sub:
            candidates.append(f"{genus} {species} {sub}")
        candidates.append(f"{genus} {species}")
    keys = list(dict.fromkeys(candidates))
    if not keys:
        return []
    conn = database.get_connection()
    try:
        rows = conn.execute(
            "SELECT scientific_name, taxon_path, taxon_rank FROM species "
            f"WHERE scientific_name IN ({', '.join('?' * len(keys))}) "
            "AND taxon_path IS NOT NULL AND taxonomic_status IS NOT 'SYNONYM'", keys).fetchall()
    finally:
        conn.close()
    by_key = {r["scientific_name"]: dict(r, common_names="[]") for r in rows}
    return [by_key[k] for k in keys if k in by_key]
