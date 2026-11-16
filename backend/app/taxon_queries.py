"""Database queries behind the chat's group tools: name resolution, rankings,
group statistics and lineage. Plain dicts out; the tools in llm_agent.py turn
them into text.

Counts and rankings cover accepted species in the tree only (taxon_rank
'species', status ACCEPTED, taxon_path set). Descendants are selected with a
range on taxon_path ('|' < '}' in ASCII); LIKE is ~40x slower on the live table.
"""

import difflib
import re

from app import database

_SPECIES_FILTER = ("taxon_rank = 'species' AND taxonomic_status = 'ACCEPTED' "
                   "AND taxon_path IS NOT NULL")


def _group_filter(conn, path: str) -> str:
    """_SPECIES_FILTER for the species under `path`: unary + keeps a small group on
    idx_taxon_path (through idx_taxonomic_status an order takes 0.7 s, and a listed
    group of 79 lizard families minutes); a large group stays on the status index."""
    if _is_large(conn, path):
        return _SPECIES_FILTER
    return "+taxon_rank = 'species' AND +taxonomic_status = 'ACCEPTED' AND taxon_path IS NOT NULL"


def _under(path: str) -> tuple[str, str]:
    """Range bounds selecting every row below `path`."""
    return path + "|", path + "}"


def _in_tree(row) -> bool:
    return bool(row["taxon_path"]) and row["taxonomic_status"] != "SYNONYM"


_SPECIES_RANKS = ("species", "subspecies", "variety", "form", "infraspecies")


def resolve_taxon(name: str, groups_only: bool = False) -> dict | None:
    """The tree row a scientific or common name refers to, else None.

    Exact scientific name first; then an exact common-name element (also its
    singular / plural). A row listing the name as its first common name wins
    ("Snakes": the suborder Serpentes, not Squamata = "Lizards", "Snakes"),
    then the broadest group ("Owls" is the first name of an order and a
    family: the order wins). `groups_only` skips species-level rows, so a
    group question never lands on one species.

    A name typed in lowercase that is a non-animal's scientific name gives way
    to an animal with that common name: "panda" is the giant panda, not the
    plant genus Panda ("Panda" still is the genus). So does one of a group with
    no living species: "koala" is not COL's empty wombat genus Koala."""
    name = name.strip()
    if not name:
        return None
    deferred = None
    conn = database.get_connection()
    try:
        for candidate in dict.fromkeys([name[:1].upper() + name[1:].lower(), name]):
            row = conn.execute("SELECT * FROM species WHERE scientific_name = ?",
                               (candidate,)).fetchone()
            if row and _in_tree(row) and not (groups_only and row["taxon_rank"] in _SPECIES_RANKS):
                if name.islower() and (not _is_animal(row["taxon_path"]) or (
                        row["taxon_rank"] not in _SPECIES_RANKS
                        and not _has_living_species(conn, row["taxon_path"]))):
                    deferred = dict(row)
                    break
                return dict(row)
        forms = list(dict.fromkeys([name, name[:-1] if name.lower().endswith("s") else name + "s"]))
        anywhere = " OR ".join("common_names LIKE ? ESCAPE '\\'" for _ in forms)
        rank_cond = (f" AND taxon_rank NOT IN ({','.join('?' * len(_SPECIES_RANKS))})"
                     if groups_only else "")
        candidates = [dict(r) for r in conn.execute(
            f"SELECT * FROM species WHERE ({anywhere}) AND taxon_path IS NOT NULL "
            f"AND taxonomic_status IS NOT 'SYNONYM'{rank_cond} "
            # +taxon_depth: walking idx_taxon_depth_path for a LIKE scan takes ~30 s, a plain scan ~1 s
            # Ties go to the better-known row, as in search ("snow leopard" is also a moth)
            "ORDER BY +taxon_depth, (wikipedia_abstract IS NOT NULL) + (iucn_status IS NOT NULL) "
            "+ (primary_image_url IS NOT NULL) DESC, scientific_name LIMIT 50",
            [*(f'%"{_like_literal(f)}"%' for f in forms), *(_SPECIES_RANKS if groups_only else ())])]
        # A group row with no species below is a stand-in (COL keeps snake families
        # directly under Squamata; its "Serpentes" rows are empty)
        valid = [r for r in candidates if r["taxon_rank"] in _SPECIES_RANKS
                 or _has_species(conn, r["taxon_path"])]
        if deferred:
            valid = [r for r in valid if _is_animal(r["taxon_path"])]
            if not valid:
                return deferred
        if not valid:
            # A misspelt scientific name ("Cinachyrya antarctica" for Cinachyra)
            close = closest_name(name)
            row = close and conn.execute("SELECT * FROM species WHERE scientific_name = ?",
                                         (close,)).fetchone()
            if row and not (groups_only and row["taxon_rank"] in _SPECIES_RANKS):
                return dict(row)
            return None
        # A row whose first common name matches wins, shallowest first (the form as
        # typed first within a level), but only near the top: the genus Chelonia
        # ("turtle") must not beat the order Testudines
        # One level down only below a top match: the panda catfish (first name
        # "panda") must not beat the giant panda's genus
        # A well-known species named exactly so beats a group that doesn't contain it:
        # "tiger" is Panthera tigris, not the butterfly genus Parantica ("Tigers"); a
        # turtle species inside the order Testudines ("Turtles") does not beat it.
        # Well-known: a summary and a range from RANK_MIN_RECORDS+ wild records, so the
        # aquarium catfish Corydoras panda ("panda") doesn't beat the giant panda's genus
        if not groups_only:
            names = {f.lower() for f in forms}
            for row in valid:
                first = database.parse_common_names(row["common_names"])[:1]
                observed = database.parse_geo_bbox(row.get("geo_bounding_box")).get("records") or 0
                if (row["taxon_rank"] in _SPECIES_RANKS and row.get("wikipedia_abstract")
                        and observed >= RANK_MIN_RECORDS
                        and first and first[0].lower() in names
                        and not any(row["taxon_path"].startswith(g["taxon_path"] + "|") for g in valid
                                    if g["taxon_rank"] not in _SPECIES_RANKS)):
                    return row
        top = valid[0]["taxon_depth"]
        top_paths = tuple(r["taxon_path"] + "|" for r in valid if r["taxon_depth"] == top)
        for depth in (top, top + 1):
            level = [r for r in valid if r["taxon_depth"] == depth
                     and (depth == top or r["taxon_path"].startswith(top_paths))]
            for form in forms:
                for row in level:
                    first = database.parse_common_names(row["common_names"])[:1]
                    if first and first[0].lower() == form.lower():
                        return row
        return valid[0]
    finally:
        conn.close()


def _is_animal(path: str | None) -> bool:
    return bool(path) and (path == "Animalia" or path.startswith("Animalia|"))


def _has_living_species(conn, path: str) -> bool:
    return conn.execute(f"SELECT 1 FROM species WHERE {_SPECIES_FILTER} AND taxon_path >= ? "
                        "AND taxon_path < ? AND (extinct IS NULL OR extinct != 1) LIMIT 1",
                        _under(path)).fetchone() is not None


def sole_living_species(group_path: str) -> dict | None:
    """The only accepted species under a group not flagged extinct, else None
    (none or several). The koala family has fossil species beside the koala."""
    conn = database.get_connection()
    try:
        rows = conn.execute(f"SELECT * FROM species WHERE {_SPECIES_FILTER} AND taxon_path >= ? "
                            "AND taxon_path < ? AND (extinct IS NULL OR extinct != 1) LIMIT 2",
                            _under(group_path)).fetchall()
    finally:
        conn.close()
    return dict(rows[0]) if len(rows) == 1 else None


# Words that never start or end a name in a question ("what do koalas eat")
_NOT_NAME_WORDS = frozenset("""
a an the of in on at to for from and or with by about is are was were be been do does did can could
would will should what which who whom whose where when how why tell me my you your it its they them
their there this that these those some any all much many more most very
eat eats eating ate eaten diet food foods feed feeds feeding prey hunt hunts hunting
live lives living lived habitat habitats home range ranges found find where located location
big bigger biggest large larger largest small smaller smallest size sizes long longer length tall
height heavy heavier weight weigh weighs old older age ages lifespan life fast speed
animal animals species kind kinds type types sort facts fact information info about
endangered extinct threatened status population
""".split())
_MAX_NAME_WORDS = 3
_MAX_CONTENT_WORDS = 4


def named_species(text: str) -> dict | None:
    """The animal species a short query names by common name ("koalas diet",
    "what does the barn owl eat"), else None.

    Longest phrase first, resolved like the group tools (groups first): a species
    row counts, and so does a group with exactly one living species ("koalas" is
    the family Phascolarctidae). A group of many ("owls") names no species.
    Descriptions longer than a few words are left to semantic search."""
    words = re.findall(r"[a-z][a-z'-]*", text.lower())
    if sum(w not in _NOT_NAME_WORDS for w in words) > _MAX_CONTENT_WORDS:
        return None
    phrases = []
    for size in range(_MAX_NAME_WORDS, 0, -1):
        for i in range(len(words) - size + 1):
            gram = words[i:i + size]
            if gram[0] not in _NOT_NAME_WORDS and gram[-1] not in _NOT_NAME_WORDS:
                phrases.append(" ".join(gram))
    for phrase in dict.fromkeys(phrases):
        row = resolve_taxon(phrase)
        if row is None or not _is_animal(row["taxon_path"]):
            continue
        if row["taxon_rank"] in _SPECIES_RANKS:
            return row
        return sole_living_species(row["taxon_path"])
    return None


def closest_name(name: str) -> str | None:
    """The accepted, in-tree scientific name closest to a misspelt one, else None.

    llama3.1:8b copies some names with a typo ("Cinachyrya antarctica" from a
    ranking that says Cinachyra). Candidates share the first three letters (a
    primary-key range, ~1 ms) and the number of words; 0.9 similarity or more."""
    words = name.split()
    if not words or len(words[0]) < 3:
        return None
    norm = " ".join([words[0][:1].upper() + words[0][1:].lower(), *(w.lower() for w in words[1:])])
    prefix = norm[:3]
    conn = database.get_connection()
    try:
        names = [r[0] for r in conn.execute(
            "SELECT scientific_name FROM species WHERE scientific_name >= ? AND scientific_name < ? "
            "AND taxon_path IS NOT NULL AND taxonomic_status IS NOT 'SYNONYM'",
            (prefix, prefix[:-1] + chr(ord(prefix[-1]) + 1)))]
    finally:
        conn.close()
    same = [n for n in names if n.count(" ") == norm.count(" ")]
    match = difflib.get_close_matches(norm, same, n=1, cutoff=0.9)
    return match[0] if match else None


def _like_literal(text: str) -> str:
    """Escape LIKE wildcards: "Ow_s" or "%" must not match any name."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _has_species(conn, path: str) -> bool:
    # Unary + keeps the planner on idx_taxon_path: through idx_taxonomic_status
    # an empty group scans every accepted row (minutes on the live table)
    return conn.execute(
        "SELECT 1 FROM species WHERE +taxon_rank = 'species' AND +taxonomic_status = 'ACCEPTED' "
        "AND taxon_path >= ? AND taxon_path < ? LIMIT 1", _under(path)).fetchone() is not None


def find_matches(name: str, limit: int = 5) -> list[dict]:
    """Search hits that are in the tree (no synonyms, no GBIF-only rows), in
    search order."""
    rows = database.search_species(name, limit * 4)
    return [r for r in rows if _in_tree(r)][:limit]


# Trait aliases the chat may pass -> (column, unit)
TRAITS: dict[str, tuple[str, str]] = {
    **dict.fromkeys(("max_lifespan", "lifespan", "age", "oldest", "longevity"), ("max_lifespan", "years")),
    **dict.fromkeys(("body_mass", "mass", "weight", "heaviest"), ("body_mass", "kg")),
    **dict.fromkeys(("body_length", "length", "longest", "size"), ("body_length", "m")),
    **dict.fromkeys(("north", "northern", "northernmost", "furthest_north", "lat_max"), ("lat_max", "°")),
    **dict.fromkeys(("south", "southern", "southernmost", "furthest_south", "lat_south"), ("lat_south", "°")),
}
_TRAIT_COLUMNS = frozenset(column for column, _ in TRAITS.values())
# Range edges from geo_bounding_box (GBIF wild records). lat_south is the negated
# southern edge, so "highest" means furthest south.
RANGE_COLUMNS = frozenset({"lat_max", "lat_south"})
_RANK_EXPR = {
    **{c: c for c in _TRAIT_COLUMNS - RANGE_COLUMNS},
    "lat_max": "json_extract(geo_bounding_box, '$.lat_max')",
    "lat_south": "-json_extract(geo_bounding_box, '$.lat_min')",
}
# A range edge is the 0.5% percentile of the wild records. Below ~200 records that
# is the single extreme record, so one stray point (a swapped coordinate, a zoo)
# sets it: a Madagascar mongoose at 85°N, an African butterfly at 82.7°S. Rankings
# use ranges from at least 1,000 records (5+ records beyond each edge); smaller
# and pre-Increment-24 ranges (no record count) still show in the panel.
RANK_MIN_RECORDS = 1000
_HAS_LATITUDES = ("json_extract(geo_bounding_box, '$.lat_min') IS NOT NULL "
                  "AND json_extract(geo_bounding_box, '$.lat_max') IS NOT NULL "
                  f"AND json_extract(geo_bounding_box, '$.records') >= {RANK_MIN_RECORDS}")


def _paths(group_path) -> list[str]:
    """One taxon path or several (a listed group: the shark orders)."""
    return [group_path] if isinstance(group_path, str) else list(group_path)


def _group_where(conn, group_path) -> tuple[str, tuple]:
    """(SQL, params) selecting the accepted species under one path, or under several
    children of one parent (a listed group): one range over the parent, filtered on
    the child's path segment. Per child, 79 lizard families took 12 s."""
    paths = _paths(group_path)
    if len(paths) == 1:
        return f"{_group_filter(conn, paths[0])} AND taxon_path >= ? AND taxon_path < ?", _under(paths[0])
    parent = paths[0].rsplit("|", 1)[0]
    if not paths or any(path.rsplit("|", 1)[0] != parent for path in paths):
        raise ValueError("a listed group's paths must share one parent")
    start = len(parent) + 2                       # 1-based start of the child's segment
    rest = f"substr(taxon_path, {start})"
    segment = f"CASE instr({rest}, '|') WHEN 0 THEN {rest} ELSE substr({rest}, 1, instr({rest}, '|') - 1) END"
    names = [path.rsplit("|", 1)[1] for path in paths]
    return (f"{_group_filter(conn, parent)} AND taxon_path >= ? AND taxon_path < ? "
            f"AND {segment} IN ({','.join('?' * len(names))})", (*_under(parent), *names))


def rank_by_trait(column: str, group_path, highest: bool, limit: int) -> tuple[int, list[dict]]:
    """(species in the group with a value, the top `limit` of them). Each row
    carries its ranked value as `rank_value`. `group_path` may be a list of paths
    sharing one parent."""
    if column not in _TRAIT_COLUMNS:
        raise ValueError(f"not a rankable trait: {column!r}")
    expr = _RANK_EXPR[column]   # fixed SQL per column, never from input
    # On the extracted values, so a broken range ('{}', '{"lat_min": 0}') doesn't
    # count: a range needs both latitudes, as in the panel and the chat lookup
    has_value = (_HAS_LATITUDES if column in RANGE_COLUMNS else f"{expr} IS NOT NULL")
    conn = database.get_connection()
    try:
        group, params = _group_where(conn, group_path)
        where = f"{group} AND {has_value}"
        n = conn.execute(f"SELECT COUNT(*) FROM species WHERE {where}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT *, {expr} AS rank_value FROM species WHERE {where} "
            f"ORDER BY rank_value {'DESC' if highest else 'ASC'}, scientific_name LIMIT ?",
            (*params, limit),
        ).fetchall()
        return n, [dict(r) for r in rows]
    finally:
        conn.close()


def species_count(group_path, living_only: bool = False) -> int:
    """Accepted species in the tree under a group (~0.7 s for Animalia); with
    `living_only`, without those flagged extinct (fossils have no range).
    `group_path` may be a list of paths sharing one parent."""
    living = " AND (extinct IS NULL OR extinct != 1)" if living_only else ""
    conn = database.get_connection()
    try:
        group, params = _group_where(conn, group_path)
        return conn.execute(f"SELECT COUNT(*) FROM species WHERE {group}{living}", params).fetchone()[0]
    finally:
        conn.close()


IUCN_ORDER = ("CR", "EN", "VU", "NT", "LC", "DD", "EW", "EX")


def group_summary(group_path, examples: int = 5) -> dict:
    """Species, extinct, IUCN and trend counts for the accepted species under a group,
    plus up to `examples` threatened species (CR, then EN, then VU). `group_path` may
    be a list of paths sharing one parent."""
    conn = database.get_connection()
    try:
        where, bounds = _group_where(conn, group_path)
        species, extinct = conn.execute(
            f"SELECT COUNT(*), COALESCE(SUM(extinct = 1), 0) FROM species WHERE {where}", bounds
        ).fetchone()
        iucn = dict(conn.execute(
            f"SELECT iucn_status, COUNT(*) FROM species WHERE {where} "
            "AND iucn_status IS NOT NULL GROUP BY iucn_status", bounds).fetchall())
        trends = dict(conn.execute(
            f"SELECT population_trend, COUNT(*) FROM species WHERE {where} "
            "AND population_trend IS NOT NULL GROUP BY population_trend "
            "ORDER BY COUNT(*) DESC, population_trend", bounds).fetchall())
        threatened = conn.execute(
            f"SELECT * FROM species WHERE {where} AND iucn_status IN ('CR', 'EN', 'VU') "
            "ORDER BY CASE iucn_status WHEN 'CR' THEN 0 WHEN 'EN' THEN 1 ELSE 2 END, "
            "scientific_name LIMIT ?", (*bounds, examples)).fetchall()
    finally:
        conn.close()
    return {
        "species": species,
        "extinct": extinct,
        "iucn": {code: iucn[code] for code in IUCN_ORDER if iucn.get(code)},
        "trends": trends,
        "threatened": [dict(r) for r in threatened],
    }


def first_common(row) -> str:
    """First Latin-script common name (the chat answers in English), else the first.
    ';' and ':' become ',' and ' -': the chat tools use them as list separators."""
    names = database.parse_common_names(row["common_names"])
    latin = [n for n in names if all(ord(ch) < 0x250 for ch in n)]
    return (latin or names or [""])[0].replace(";", ",").replace(":", " -")


def lineage(taxon_path: str) -> list[dict]:
    """One {name, rank, common} per level of the path, kingdom first. A level
    without its own row keeps its name with empty rank and common name."""
    segs = taxon_path.split("|")
    paths = ["|".join(segs[:i]) for i in range(1, len(segs) + 1)]
    conn = database.get_connection()
    try:
        rows = {r["taxon_path"]: r for r in conn.execute(
            f"SELECT taxon_path, taxon_rank, common_names FROM species "
            f"WHERE taxon_path IN ({','.join('?' * len(paths))}) "
            "AND taxonomic_status IS NOT 'SYNONYM'", paths)}
    finally:
        conn.close()
    return [{"name": seg,
             "rank": (rows[p]["taxon_rank"] or "") if p in rows else "",
             "common": first_common(rows[p]) if p in rows else ""}
            for seg, p in zip(segs, paths)]


_CHILDREN = ("taxonomic_status IS NOT 'SYNONYM' AND taxon_depth = ? "
             "AND taxon_path >= ? AND taxon_path < ?")


def child_rank_counts(taxon_path: str) -> dict[str, int]:
    """{rank: number of accepted direct children}, most common rank first. A
    class can hold orders and also families or genera placed directly under it."""
    conn = database.get_connection()
    try:
        return dict(conn.execute(
            f"SELECT COALESCE(taxon_rank, ''), COUNT(*) FROM species WHERE {_CHILDREN} "
            "GROUP BY taxon_rank ORDER BY COUNT(*) DESC, taxon_rank",
            (taxon_path.count("|") + 1, *_under(taxon_path))).fetchall())
    finally:
        conn.close()


def members(taxon_path: str, limit: int = 15, rank: str | None = None) -> tuple[int, list[dict]]:
    """(number of accepted direct children, the first `limit`: common-named first,
    then A-Z), optionally only children of one rank."""
    where = _CHILDREN + (" AND taxon_rank = ?" if rank else "")
    params = (taxon_path.count("|") + 1, *_under(taxon_path), *((rank,) if rank else ()))
    conn = database.get_connection()
    try:
        n = conn.execute(f"SELECT COUNT(*) FROM species WHERE {where}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM species WHERE {where} "
            "ORDER BY (common_names IS NULL OR common_names = '[]'), scientific_name LIMIT ?",
            (*params, limit)).fetchall()
        return n, [dict(r) for r in rows]
    finally:
        conn.close()


# ── Species in a place (Increment 26) ─────────────────────────────────────────

# COL keeps most snake families directly under Squamata (its Serpentes rows are
# nearly empty), so "snakes" would mean all lizards too. The chat's group tools
# use this list instead; the tree still shows COL's classification.
SNAKE_FAMILIES = frozenset("""
Acrochordidae Aniliidae Anomalepidae Anomalepididae Anomalophiidae Anomochilidae Atractaspididae
Boidae Bolyeriidae Calabariidae Candoiidae Charinidae Colubridae Colubrinae Crotalidae Cyclocoridae
Cylindrophiidae Dinilysiidae Dipsadidae Elapidae Erycidae Gerrhopilidae Homalopsidae Lamprophiidae
Lapparentophiidae Lapparantophiidae Lapparentopheidae Laticaudidae Leptotyphlopidae Loxocemidae
Madtsoiidae Micrelapidae Natricidae Nigerophiidae Pachyophiidae Palaeophiidae Pareidae Prosymnidae
Psammodynastidae Psammophiidae Pseudaspididae Pseudoxyrhophiidae Pythonidae Russelophiidae
Sanziniidae Serpentes Simoliophiidae Tropidophiidae Typhlopidae Uropeltidae Viperidae Xenodermidae
Xenopeltidae Xenophidiidae Xenotyphlopidae
""".split())
_SNAKE_NAMES = frozenset({"snake", "snakes", "serpent", "serpents", "serpentes"})
_SQUAMATA = "Animalia|Chordata|Reptilia|Squamata"
# Worm lizards: squamates, but neither snakes nor lizards
AMPHISBAENIAN_FAMILIES = frozenset("Amphisbaenidae Bipedidae Blanidae Cadeidae Rhineuridae Trogonophidae".split())
# Shark orders of COL's Elasmobranchii (the class mixes them with the rays;
# its Selachimorpha row is a synonym)
SHARK_ORDERS = frozenset("""
Carcharhiniformes Echinorhiniformes Heterodontiformes Hexanchiformes Lamniformes Orectolobiformes
Pristiophoriformes Squaliformes Squatiniformes
""".split())
# Marsupial orders, filed directly under Mammalia (COL's Marsupialia row is a synonym)
MARSUPIAL_ORDERS = frozenset("""
Dasyuromorphia Didelphimorphia Diprotodontia Microbiotheria Notoryctemorphia Paucituberculata
Peramelemorphia
""".split())
_ELASMOBRANCHII = "Animalia|Chordata|Elasmobranchii"
_MAMMALIA = "Animalia|Chordata|Mammalia"
# name forms -> (label, parent path, rank, members; None = every child of that rank
# under the parent except `excluded`)
_LISTED_GROUPS = (
    (_SNAKE_NAMES, "snakes (snake families)", _SQUAMATA, "family", SNAKE_FAMILIES, frozenset()),
    (frozenset({"lizard", "lizards", "lacertilia"}), "lizards (lizard families)", _SQUAMATA, "family",
     None, SNAKE_FAMILIES | AMPHISBAENIAN_FAMILIES),
    (frozenset({"shark", "sharks", "selachii", "selachimorpha"}), "sharks (shark orders)",
     _ELASMOBRANCHII, "order", SHARK_ORDERS, frozenset()),
    (frozenset({"marsupial", "marsupials", "marsupialia"}), "marsupials (marsupial orders)",
     _MAMMALIA, "order", MARSUPIAL_ORDERS, frozenset()),
)
# Same bar as the range rankings: below it one stray record can set a range edge
PLACE_MIN_RECORDS = RANK_MIN_RECORDS
PLACE_FIT_RATIO = 20
# Above this many rows under a group, the status index beats the path index
_LARGE_GROUP_ROWS = 100_000


def _is_large(conn, path: str) -> bool:
    """A group with many rows below (Animalia, insects): an index-only count, capped."""
    return conn.execute("SELECT COUNT(*) FROM (SELECT 1 FROM species WHERE taxon_path >= ? AND taxon_path < ? "
                        "LIMIT ?)", (*_under(path), _LARGE_GROUP_ROWS)).fetchone()[0] >= _LARGE_GROUP_ROWS


def _listed_paths(parent: str, rank: str, members, excluded) -> list[str]:
    """Paths of the parent's direct children of `rank` named in `members` (or all
    but `excluded`)."""
    conn = database.get_connection()
    try:
        rows = conn.execute(
            "SELECT scientific_name, taxon_path FROM species WHERE taxon_rank = ? "
            "AND taxonomic_status IS NOT 'SYNONYM' AND taxon_depth = ? AND taxon_path >= ? "
            "AND taxon_path < ? ORDER BY scientific_name",
            (rank, parent.count("|") + 1, *_under(parent))).fetchall()
    finally:
        conn.close()
    return [r["taxon_path"] for r in rows
            if (r["scientific_name"] in members if members is not None else r["scientific_name"] not in excluded)]


def group_paths(name: str) -> tuple[str, str, list[str]] | None:
    """(short name, label, taxon paths) of the group a question asks about, else
    None. Snakes, lizards, sharks and marsupials are lists of COL families or orders
    (Increments 26 and 28); other names resolve to one group."""
    key = " ".join(name.strip().lower().split())
    for forms, label, parent, rank, members, excluded in _LISTED_GROUPS:
        if key in forms:
            return label.split(" (")[0], label, _listed_paths(parent, rank, members, excluded)
    row = resolve_taxon(name, groups_only=True)
    if row is None:
        return None
    extra = ", ".join(x for x in (first_common(row), row.get("taxon_rank")) if x)
    label = f"{row['scientific_name']} ({extra})" if extra else row["scientific_name"]
    return row["scientific_name"], label, [row["taxon_path"]]


def place_group(name: str) -> tuple[str, list[str]] | None:
    """(label, taxon paths) of the group a place question asks about, else None."""
    found = group_paths(name)
    return found and (found[1], found[2])


def _fit(row: dict, bbox: list[float]) -> float:
    """Share of the species' range box inside the place's box: 1.0 for a box within
    the place, near 0 for a worldwide species (introduced populations widen a box)."""
    lat0, lat1, lon0, lon1 = bbox
    h = min(row["r_lat_max"], lat1) - max(row["r_lat_min"], lat0)
    w = min(row["r_lon_max"], lon1) - max(row["r_lon_min"], lon0)
    area = max(row["r_lat_max"] - row["r_lat_min"], 0.01) * max(row["r_lon_max"] - row["r_lon_min"], 0.01)
    return round(min(1.0, max(h, 0.0) * max(w, 0.0) / area), 4) if h > 0 and w > 0 else 0.0


def species_in_place(group_paths: list[str], place, limit: int) -> tuple[int, int, int, list[dict]]:
    """(species whose range overlaps the place and fits it closely, all species whose
    range overlaps it, species in the groups with a range, the `limit` close ones with
    the best fit first, then most records). Rows carry `records`, `fit` and the range
    as r_lat_min ... r_lon_max."""
    lat0, lat1, lon0, lon1 = place.bbox
    lat_min, lat_max = "json_extract(geo_bounding_box, '$.lat_min')", "json_extract(geo_bounding_box, '$.lat_max')"
    lon_min, lon_max = "json_extract(geo_bounding_box, '$.lon_min')", "json_extract(geo_bounding_box, '$.lon_max')"
    records = "json_extract(geo_bounding_box, '$.records')"
    # One query for the whole group (_group_where: a listed group is one range over
    # its parent; an OR of ~50 path ranges scans the table).
    # Hybrids ("Anser anser x Branta canadensis") are not species.
    rest = ("AND scientific_name NOT LIKE '% x %' "
            f"AND geo_bounding_box IS NOT NULL AND {records} >= {PLACE_MIN_RECORDS} "
            f"AND {lon_min} IS NOT NULL AND {lon_max} IS NOT NULL")
    conn = database.get_connection()
    try:
        where, params = _group_where(conn, group_paths)
        base = f"FROM species WHERE {where} {rest}"
        ranged = conn.execute(f"SELECT COUNT(*) {base}", params).fetchone()[0]
        candidates = conn.execute(
            f"SELECT *, {lat_min} AS r_lat_min, {lat_max} AS r_lat_max, {lon_min} AS r_lon_min, "
            f"{lon_max} AS r_lon_max, {records} AS records {base} "
            f"AND {lat_min} <= ? AND {lat_max} >= ? AND {lon_min} <= ? AND {lon_max} >= ?",
            (*params, lat1, lat0, lon1, lon0)).fetchall()
    finally:
        conn.close()
    hits = []
    for r in candidates:
        if place.overlaps(r["r_lat_min"], r["r_lat_max"], r["r_lon_min"], r["r_lon_max"]):
            row = dict(r)
            row["fit"] = _fit(row, place.bbox)
            hits.append(row)
    hits.sort(key=lambda r: (-r["fit"], -r["records"], r["scientific_name"]))
    # Not listed: boxes fitting far worse than the best one, mostly stretched by escaped
    # or introduced animals (corn snakes in the Netherlands); the count keeps them
    # (Galápagos: ~400 birds overlap, most of them seabirds ranging over half the Pacific)
    floor = hits[0]["fit"] / PLACE_FIT_RATIO if hits else 0
    close = [r for r in hits if r["fit"] >= floor]
    return len(close), len(hits), ranged, close[:limit]


# Listed for a country: COUNTRY_MIN_RECORDS+ wild GBIF records there and at least
# 1/COUNTRY_LIST_RATIO of the best recorded species' count. The rest is counted, not
# listed: mostly strays, escaped pets and misidentifications (Netherlands snakes: the
# Amur ratsnake with 85 records and the corn snake with 25, against 42,296 for the
# barred grass snake; Ireland has no snake records at all)
COUNTRY_MIN_RECORDS = 5
COUNTRY_LIST_RATIO = 100


def _box_touches(row, place) -> bool:
    """True if the row's range box shares a grid cell with the place; False without a
    box with latitudes. Without longitudes (across the 180° line) latitude decides."""
    box = database.parse_geo_bbox(row["geo_bounding_box"])
    if place is None or box.get("lat_min") is None or box.get("lat_max") is None:
        return False
    lon0 = box["lon_min"] if box.get("lon_min") is not None else -180.0
    lon1 = box["lon_max"] if box.get("lon_max") is not None else 180.0
    return place.overlaps(box["lat_min"], box["lat_max"], lon0, lon1)


def has_country_records(codes) -> bool:
    """True if species_countries holds any rows for these country codes."""
    codes = list(codes)
    if not codes:
        return False
    conn = database.get_connection()
    try:
        return conn.execute(f"SELECT 1 FROM species_countries WHERE country IN ({','.join('?' * len(codes))}) "
                            "LIMIT 1", codes).fetchone() is not None
    finally:
        conn.close()


def species_in_country(group_paths: list[str], codes, limit: int, partial=(), place=None
                       ) -> tuple[int, int, list[dict]]:
    """(species of the groups listed for the countries, species with fewer records
    there, the `limit` listed ones with the most records first). Rows carry `records`,
    summed over the codes. Records from a `partial` country (Russia for Europe) count
    only if the species' range box touches `place` (Increment 29)."""
    codes = list(codes)
    partial = set(partial)
    marks = ",".join("?" * len(codes))
    totals: dict[str, dict] = {}
    conn = database.get_connection()
    try:
        where, params = _group_where(conn, group_paths)
        # Driven from the country's rows (primary key), then each species by its key;
        # the group's columns (taxon_path, taxon_rank, taxonomic_status) are the species'
        for r in conn.execute(
                f"SELECT s.*, c.country AS country, c.records AS c_records "
                f"FROM species_countries c CROSS JOIN species s "
                f"ON s.scientific_name = c.scientific_name WHERE c.country IN ({marks}) "
                f"AND {where} AND s.scientific_name NOT LIKE '% x %'",
                (*codes, *params)):
            if r["country"] in partial and not _box_touches(r, place):
                continue
            row = totals.setdefault(r["scientific_name"], {**dict(r), "records": 0})
            row["records"] += r["c_records"]
    finally:
        conn.close()
    rows = sorted(totals.values(), key=lambda r: (-r["records"], r["scientific_name"]))
    floor = max(COUNTRY_MIN_RECORDS, rows[0]["records"] / COUNTRY_LIST_RATIO) if rows else 0
    listed = [r for r in rows if r["records"] >= floor]
    return len(listed), len(rows) - len(listed), listed[:limit]


def countries_of(scientific_name: str) -> list[tuple[str, int]]:
    """(country code, wild GBIF records) of one species, most records first."""
    conn = database.get_connection()
    try:
        return [(r[0], r[1]) for r in conn.execute(
            "SELECT country, records FROM species_countries WHERE scientific_name = ? "
            "ORDER BY records DESC, country", (scientific_name,))]
    finally:
        conn.close()


def living_species_count(group_paths: list[str]) -> int:
    """Accepted species not flagged extinct under any of the groups (index choice as
    in species_in_place)."""
    return species_count(group_paths, living_only=True)
