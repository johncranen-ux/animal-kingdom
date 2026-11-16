"""SQLite connection and query helpers for the species database."""

import json
import logging
import os
import sqlite3
from datetime import date
from typing import Literal, NamedTuple

from app.paths import data_path

log = logging.getLogger(__name__)

DB_PATH = os.environ.get("SPECIES_DB_PATH") or str(data_path("species.db"))

_CREATE_SPECIES_TABLE = """
CREATE TABLE IF NOT EXISTS species (
    scientific_name       TEXT PRIMARY KEY,
    taxon_path            TEXT,
    taxon_rank            TEXT,
    common_names          TEXT,
    taxonomic_status      TEXT,
    body_mass             REAL,
    body_length           REAL,
    max_lifespan          REAL,
    metabolic_rate        REAL,
    reproduction_strategy TEXT,
    geo_bounding_box      TEXT,
    habitat_type          TEXT,
    elevation_limits      TEXT,
    trophic_level         TEXT,
    activity_period       TEXT,
    iucn_status           TEXT,
    population_trend      TEXT,
    primary_image_url     TEXT,
    image_attribution     TEXT,
    wikipedia_abstract    TEXT,
    taxon_depth           INTEGER,
    extinct               INTEGER
)
"""

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_taxon_rank ON species(taxon_rank)",
    "CREATE INDEX IF NOT EXISTS idx_taxonomic_status ON species(taxonomic_status)",
    "CREATE INDEX IF NOT EXISTS idx_iucn_status ON species(iucn_status)",
    "CREATE INDEX IF NOT EXISTS idx_taxon_path ON species(taxon_path)",
    "CREATE INDEX IF NOT EXISTS idx_taxon_depth_path ON species(taxon_depth, taxon_path)",
]


# Wild GBIF records per species per country (ISO alpha-2), filled by
# data/import_gbif_countries.py; the chat's species_in_place reads it for countries.
_CREATE_SPECIES_COUNTRIES = """
CREATE TABLE IF NOT EXISTS species_countries (
    country         TEXT NOT NULL,
    scientific_name TEXT NOT NULL,
    records         INTEGER NOT NULL,
    PRIMARY KEY (country, scientific_name)
) WITHOUT ROWID
"""


_CREATE_TRIGGERS = [
    # Auto-compute taxon_depth whenever a row is inserted or taxon_path changes.
    """CREATE TRIGGER IF NOT EXISTS trg_taxon_depth_insert
       AFTER INSERT ON species
       WHEN NEW.taxon_path IS NOT NULL
       BEGIN
           UPDATE species
           SET taxon_depth = length(NEW.taxon_path) - length(replace(NEW.taxon_path,'|',''))
           WHERE scientific_name = NEW.scientific_name;
       END""",
    """CREATE TRIGGER IF NOT EXISTS trg_taxon_depth_update
       AFTER UPDATE OF taxon_path ON species
       WHEN NEW.taxon_path IS NOT NULL
       BEGIN
           UPDATE species
           SET taxon_depth = length(NEW.taxon_path) - length(replace(NEW.taxon_path,'|',''))
           WHERE scientific_name = NEW.scientific_name;
       END""",
]


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.execute(_CREATE_SPECIES_TABLE)
    # taxon_depth was added in Increment 10; add it if missing (idempotent)
    existing = {r[1] for r in conn.execute("PRAGMA table_info(species)").fetchall()}
    # trait_sources (JSON provenance + stage markers) added in Increment 12
    if "trait_sources" not in existing:
        conn.execute("ALTER TABLE species ADD COLUMN trait_sources TEXT")
    # extinct (1/0, NULL = unknown; from GBIF species profiles) added after Increment 12
    if "extinct" not in existing:
        conn.execute("ALTER TABLE species ADD COLUMN extinct INTEGER")
    # Catalogue of Life build columns (data/build_col_db.py); in the app schema since
    # Increment 30, which reads accepted_name
    for column in ("gbif_taxon_path", "col_id", "accepted_name"):
        if column not in existing:
            conn.execute(f"ALTER TABLE species ADD COLUMN {column} TEXT")
    # rejected_images (JSON list of picture URLs the user replaced) added in Increment 32
    if "rejected_images" not in existing:
        conn.execute("ALTER TABLE species ADD COLUMN rejected_images TEXT")
    if "taxon_depth" not in existing:
        conn.execute("ALTER TABLE species ADD COLUMN taxon_depth INTEGER")
        conn.execute("""
            UPDATE species
            SET taxon_depth = length(taxon_path) - length(replace(taxon_path, '|', ''))
            WHERE taxon_path IS NOT NULL
        """)
    for stmt in _CREATE_INDEXES:
        conn.execute(stmt)
    for stmt in _CREATE_TRIGGERS:
        conn.execute(stmt)
    conn.execute(_CREATE_SPECIES_COUNTRIES)
    conn.commit()


def get_connection(timeout: float = 300.0) -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=timeout)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _init_schema(conn)
    return conn


# --- JSON helpers ---

def parse_common_names(json_str: str | None) -> list[str]:
    if not json_str:
        return []
    try:
        return json.loads(json_str)
    except (json.JSONDecodeError, TypeError):
        return []


def serialize_common_names(names: list[str]) -> str:
    return json.dumps(names, ensure_ascii=False)


def parse_geo_bbox(json_str: str | None) -> dict:
    if not json_str:
        return {}
    try:
        return json.loads(json_str)
    except (json.JSONDecodeError, TypeError):
        return {}


def serialize_geo_bbox(bbox: dict) -> str:
    return json.dumps(bbox, ensure_ascii=False)


# --- Query helpers ---

def get_children(taxon_path: str, depth: int = 1, limit: int | None = None) -> list[dict]:
    """Return nodes whose taxon_path is within `depth` levels below `taxon_path`."""
    conn = get_connection()
    try:
        parent_depth = taxon_path.count("|") if taxon_path else -1
        max_depth = parent_depth + depth

        if taxon_path:
            sql = """
                SELECT * FROM species
                WHERE taxon_depth <= ?
                  AND taxon_path LIKE ?
                """
            params: list = [max_depth, taxon_path + "|%"]
        else:
            sql = "SELECT * FROM species WHERE taxon_depth <= ?"
            params = [max_depth]

        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def count_children(taxon_path: str, depth: int = 1) -> int:
    """Count nodes within `depth` levels below `taxon_path`."""
    conn = get_connection()
    try:
        parent_depth = taxon_path.count("|") if taxon_path else -1
        max_depth = parent_depth + depth

        if taxon_path:
            row = conn.execute(
                "SELECT COUNT(*) FROM species WHERE taxon_depth <= ? AND taxon_path LIKE ?",
                (max_depth, taxon_path + "|%"),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) FROM species WHERE taxon_depth <= ?",
                (max_depth,),
            ).fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


def get_children_letter_counts(parent_path: str) -> dict[str, int]:
    """Return a {letter: count} map for non-SYNONYM direct children.

    Uses the (taxon_depth, taxon_path) index for a fast range-scan.
    Names that do not start with A–Z are grouped under '#'.
    """
    conn = get_connection()
    try:
        child_depth = parent_path.count("|") + 1
        offset      = len(parent_path) + 2   # 1-indexed; skip "parent_path|"
        lo          = parent_path + "|"
        hi          = parent_path + chr(ord("|") + 1)
        rows = conn.execute(
            """
            SELECT upper(substr(taxon_path, ?, 1)) AS letter, count(*) AS cnt
            FROM   species
            WHERE  taxon_depth = ?
              AND  taxon_path  >= ?
              AND  taxon_path  <  ?
              AND  taxonomic_status != 'SYNONYM'
            GROUP  BY letter
            ORDER  BY letter
            """,
            (offset, child_depth, lo, hi),
        ).fetchall()
        result: dict[str, int] = {}
        for letter, cnt in rows:
            key = letter if (letter and 'A' <= letter <= 'Z') else "#"
            result[key] = result.get(key, 0) + cnt
        return dict(sorted(result.items()))
    finally:
        conn.close()


def get_children_by_letter(parent_path: str, letter: str) -> list[dict]:
    """Return ALL direct children whose name starts with `letter`.

    Pass letter='#' to get children whose first character is not A–Z.
    SYNONYM filtering is intentionally left to the Python layer in taxonomy_alpha
    so that structural-SYNONYM genera (e.g. Apis) with ACCEPTED descendants are
    retained.  This mirrors the pattern used by get_children_by_rank / taxonomy_zoom.
    """
    conn = get_connection()
    try:
        child_depth = parent_path.count("|") + 1
        offset      = len(parent_path) + 2   # 1-indexed; skip "parent_path|"
        lo          = parent_path + "|"
        hi          = parent_path + chr(ord("|") + 1)
        letter_up   = letter.upper()
        if letter_up == "#":
            sql = """
                SELECT * FROM species
                WHERE  taxon_depth = ?
                  AND  taxon_path  >= ?
                  AND  taxon_path  <  ?
                  AND  (upper(substr(taxon_path, ?, 1)) < 'A'
                        OR upper(substr(taxon_path, ?, 1)) > 'Z')
            """
            params: list = [child_depth, lo, hi, offset, offset]
        else:
            sql = """
                SELECT * FROM species
                WHERE  taxon_depth = ?
                  AND  taxon_path  >= ?
                  AND  taxon_path  <  ?
                  AND  upper(substr(taxon_path, ?, 1)) = ?
            """
            params = [child_depth, lo, hi, offset, letter_up]
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def get_orphan_letter_counts(
    parent_path: str,
    expected_ranks: frozenset[str],
) -> dict[str, int]:
    """Return a {letter: count} map for orphan (non-expected-rank) direct children."""
    conn = get_connection()
    try:
        child_depth = parent_path.count("|") + 1
        offset      = len(parent_path) + 2
        lo          = parent_path + "|"
        hi          = parent_path + chr(ord("|") + 1)
        ranks_list  = sorted(expected_ranks)
        ph          = ",".join("?" * len(ranks_list))
        rows = conn.execute(
            f"""
            SELECT upper(substr(taxon_path, ?, 1)) AS letter, count(*) AS cnt
            FROM   species
            WHERE  taxon_depth = ?
              AND  taxon_path  >= ?
              AND  taxon_path  <  ?
              AND  (taxon_rank NOT IN ({ph}) OR taxon_rank IS NULL)
              AND  taxonomic_status != 'SYNONYM'
            GROUP  BY letter
            ORDER  BY letter
            """,
            [offset, child_depth, lo, hi] + ranks_list,
        ).fetchall()
        result: dict[str, int] = {}
        for letter, cnt in rows:
            key = letter if (letter and 'A' <= letter <= 'Z') else "#"
            result[key] = result.get(key, 0) + cnt
        return dict(sorted(result.items()))
    finally:
        conn.close()


def get_orphan_children_by_letter(
    parent_path: str,
    expected_ranks: frozenset[str],
    letter: str,
    depth: int = 1,
) -> list[dict]:
    """Return orphan direct children whose name starts with `letter`."""
    conn = get_connection()
    try:
        child_depth = parent_path.count("|") + 1
        offset      = len(parent_path) + 2
        lo          = parent_path + "|"
        hi          = parent_path + chr(ord("|") + 1)
        ranks_list  = sorted(expected_ranks)
        ph          = ",".join("?" * len(ranks_list))
        letter_up   = letter.upper()
        if letter_up == "#":
            letter_filter = "AND (upper(substr(taxon_path, ?, 1)) < 'A' OR upper(substr(taxon_path, ?, 1)) > 'Z')"
            letter_params: list = [offset, offset]
        else:
            letter_filter = "AND upper(substr(taxon_path, ?, 1)) = ?"
            letter_params = [offset, letter_up]
        sql = f"""
            SELECT * FROM species
            WHERE  taxon_depth = ?
              AND  taxon_path  >= ?
              AND  taxon_path  <  ?
              AND  (taxon_rank NOT IN ({ph}) OR taxon_rank IS NULL)
              AND  taxonomic_status != 'SYNONYM'
              {letter_filter}
        """
        params: list = [child_depth, lo, hi] + ranks_list + letter_params
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def get_species(scientific_name: str) -> dict | None:
    conn = get_connection()
    try:
        # Exact name via the primary-key index; NOCASE fallback scans the table
        row = conn.execute(
            "SELECT * FROM species WHERE scientific_name = ?", (scientific_name,)
        ).fetchone() or conn.execute(
            "SELECT * FROM species WHERE scientific_name = ? COLLATE NOCASE", (scientific_name,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


class TraitValue(NamedTuple):
    value: float | str | dict
    source: str
    estimated: bool = False


TRAIT_FIELDS: tuple[str, ...] = (
    "habitat_type", "elevation_limits", "body_mass", "body_length", "max_lifespan",
    "trophic_level", "activity_period", "reproduction_strategy", "iucn_status",
    "population_trend", "geo_bounding_box", "wikipedia_abstract", "extinct",
)

# Provenance for values imported by the bulk data/ scripts (no trait_sources entry)
_IMPORTED_SOURCES = {
    "body_mass": "AnAge", "max_lifespan": "AnAge", "metabolic_rate": "AnAge",
    "iucn_status": "IUCN Red List", "population_trend": "IUCN Red List",
    "geo_bounding_box": "GBIF occurrences", "wikipedia_abstract": "Wikipedia",
}


def parse_trait_sources(json_str: str | None) -> dict:
    if not json_str:
        return {}
    try:
        parsed = json.loads(json_str)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def serialize_trait_sources(d: dict) -> str:
    return json.dumps(d, ensure_ascii=False)


# Trait writes come from user-facing requests: wait briefly for the lock, never
# minutes, when a bulk data/ script holds a long write transaction.
TRAIT_WRITE_TIMEOUT_S = 10.0


# Written like a trait but not shown as one: an old name the Catalogue of Life keeps
# as accepted (Tapirus malayanus) gets its link from Wikidata (Increment 30). Only
# filled when NULL, so the Catalogue's own synonym links are never replaced.
NAME_FIELDS: tuple[str, ...] = ("accepted_name",)
_LINK_HOPS = 4


def current_name(row: dict) -> dict | None:
    """The accepted taxon an old name points to, following synonyms of synonyms
    (Tapirus malayanus → Tapirus indicus indicus → Acrocodia indica). None for an
    accepted name, a target missing from the DB, or a loop. `source` is the link's
    provenance: Wikidata, else the Catalogue of Life."""
    target = row.get("accepted_name")
    if not target:
        return None
    entry = parse_trait_sources(row.get("trait_sources")).get("accepted_name")
    source = entry.get("source") if isinstance(entry, dict) else None
    seen = {row.get("scientific_name")}
    conn = get_connection()
    try:
        for _ in range(_LINK_HOPS):
            if target in seen:
                return None
            seen.add(target)
            hit = conn.execute(
                "SELECT scientific_name, common_names, taxon_path, taxon_rank, taxonomic_status, "
                "accepted_name FROM species WHERE scientific_name = ?", (target,)).fetchone()
            if hit is None:
                return None
            if hit["taxonomic_status"] == "SYNONYM" and hit["accepted_name"]:
                target = hit["accepted_name"]
                continue
            names = parse_common_names(hit["common_names"])
            return {"scientific_name": hit["scientific_name"], "common_name": names[0] if names else None,
                    "taxon_path": hit["taxon_path"], "taxon_rank": hit["taxon_rank"],
                    "source": source or "Catalogue of Life"}
        return None
    finally:
        conn.close()


def merge_trait_values(row: dict, values: dict[str, TraitValue],
                       stage: Literal["sourced", "estimated", "names"], completed: bool) -> dict:
    """Column updates (incl. trait_sources) applying `values` to `row` under the
    write rules: fill NULL fields, or replace an estimate with a sourced value."""
    sources = parse_trait_sources(row.get("trait_sources"))
    updates: dict[str, object] = {}
    for field, tv in values.items():
        if field not in TRAIT_FIELDS and field not in NAME_FIELDS:
            continue
        current_is_estimate = sources.get(field, {}).get("estimated", False)
        if row.get(field) is not None and not (current_is_estimate and not tv.estimated):
            continue
        updates[field] = serialize_geo_bbox(tv.value) if field == "geo_bounding_box" else tv.value
        sources[field] = {"source": tv.source, "estimated": tv.estimated}
    if completed:
        sources[f"_{stage}"] = date.today().isoformat()
        # The sourced stage's Wikidata lookup includes the name check (Increment 30);
        # rows sourced before that get it once through the "names" stage
        if stage == "sourced":
            sources["_names"] = sources[f"_{stage}"]
    updates["trait_sources"] = serialize_trait_sources(sources)
    return updates


_SPECIES_LEVEL_RANKS = ("species", "subspecies", "variety", "form", "infraspecies")


def extinct_rollup_source(n: int) -> str:
    return f"Derived: all {n:,} accepted species extinct"


def rollup_extinct_ancestors(conn: sqlite3.Connection, taxon_path: str) -> list[str]:
    """After a species is flagged extinct: flag each ancestor group (genus, family, ...)
    whose accepted species are now all extinct. Climbs until the first group that
    still has a living or unknown species; never flags the kingdom. Runs in the
    caller's transaction. Returns the newly flagged paths. (Same rule as pass 2 of
    data/backfill_extinct.py.)"""
    flagged: list[str] = []
    segs = (taxon_path or "").split("|")
    ph = ",".join("?" * len(_SPECIES_LEVEL_RANKS))
    for i in range(len(segs) - 1, 1, -1):
        anc = "|".join(segs[:i])
        lo, hi = anc + "|", anc + chr(ord("|") + 1)
        # unary + keeps SQLite on the taxon_path range: left alone it picks the
        # taxonomic_status index and walks ~2.5 M accepted rows (seconds per write)
        species = ("FROM species WHERE taxon_path >= ? AND taxon_path < ? "
                   "AND +taxon_rank = 'species' AND +taxonomic_status = 'ACCEPTED'")
        if conn.execute(f"SELECT 1 {species} AND (extinct IS NULL OR extinct != 1) LIMIT 1",
                        (lo, hi)).fetchone():
            break
        n = conn.execute(f"SELECT COUNT(*) {species}", (lo, hi)).fetchone()[0]
        if not n:
            break
        for name, extinct, iucn, ts in conn.execute(
            f"SELECT scientific_name, extinct, iucn_status, trait_sources FROM species "
            f"WHERE taxon_path = ? AND taxon_rank NOT IN ({ph})", (anc, *_SPECIES_LEVEL_RANKS),
        ).fetchall():
            if extinct is not None or iucn not in (None, "", "EX"):
                continue
            sources = parse_trait_sources(ts)
            sources["extinct"] = {"source": extinct_rollup_source(n), "estimated": False}
            conn.execute("UPDATE species SET extinct = 1, trait_sources = ? WHERE scientific_name = ?",
                         (serialize_trait_sources(sources), name))
            flagged.append(anc)
    return flagged


def update_species_traits(scientific_name: str, values: dict[str, TraitValue],
                          stage: Literal["sourced", "estimated", "names"], completed: bool) -> bool:
    """Write-through trait cache (see merge_trait_values); marks the stage done if
    `completed`. Returns False if the row is missing or the DB stayed locked."""
    conn = get_connection(timeout=TRAIT_WRITE_TIMEOUT_S)
    try:
        # BEGIN IMMEDIATE takes the write lock before reading, so concurrent
        # writers (panel + chat) can't lose each other's provenance entries.
        conn.execute("BEGIN IMMEDIATE")
        # Exact name first (primary-key index); NOCASE can't use the index and scans
        # all ~5.8 M rows (~0.7 s) while holding the write lock.
        row = conn.execute(
            "SELECT * FROM species WHERE scientific_name = ?", (scientific_name,)
        ).fetchone() or conn.execute(
            "SELECT * FROM species WHERE scientific_name = ? COLLATE NOCASE", (scientific_name,)
        ).fetchone()
        if row is None:
            conn.rollback()
            return False
        updates = merge_trait_values(dict(row), values, stage, completed)
        assignments = ", ".join(f"{col} = ?" for col in updates)
        conn.execute(
            f"UPDATE species SET {assignments} WHERE scientific_name = ?",
            (*updates.values(), row["scientific_name"]),
        )
        if updates.get("extinct") == 1 and row["taxon_rank"] == "species":
            rollup_extinct_ancestors(conn, row["taxon_path"])
        conn.commit()
        return True
    except sqlite3.OperationalError as e:
        if "locked" not in str(e):
            raise
        log.warning("Trait write for %s skipped: database locked", scientific_name)
        return False
    finally:
        conn.close()


def trait_provenance(row: dict) -> dict[str, dict]:
    """{field: {"source", "estimated"}} for every non-NULL trait or imported field."""
    sources = parse_trait_sources(row.get("trait_sources"))
    prov = {}
    for field in (*TRAIT_FIELDS, "metabolic_rate"):
        if row.get(field) in (None, ""):
            continue
        entry = sources.get(field)
        if isinstance(entry, dict) and "source" in entry:
            prov[field] = {"source": entry["source"], "estimated": bool(entry.get("estimated"))}
        elif field in _IMPORTED_SOURCES:
            prov[field] = {"source": _IMPORTED_SOURCES[field], "estimated": False}
    return prov


def update_species_image(scientific_name: str, url: str, attribution: str) -> None:
    """Write primary_image_url and image_attribution. Used for write-through image cache."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE species SET primary_image_url = ?, image_attribution = ? "
            "WHERE scientific_name = ?",
            (url, attribution, scientific_name),
        )
        conn.commit()
    finally:
        conn.close()


def replace_species_image(scientific_name: str, url: str, attribution: str,
                          expected: str | None) -> bool:
    """Write the picture only if primary_image_url still holds `expected` (what the
    lookup read when it started): a choice made meanwhile wins. True if written."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "UPDATE species SET primary_image_url = ?, image_attribution = ? "
            "WHERE scientific_name = ? AND primary_image_url IS ?",
            (url, attribution, scientific_name, expected),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def parse_rejected_images(raw: str | None) -> list[str]:
    """The rejected_images column: picture URLs the user replaced ("Other pictures")."""
    try:
        value = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        return []
    return [u for u in value if isinstance(u, str)] if isinstance(value, list) else []


def choose_species_image(scientific_name: str, url: str, attribution: str) -> None:
    """Store the picture the user chose; the picture it replaces (a real URL, not
    the same one) joins rejected_images so no lookup offers it again."""
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")   # read and write as one step: two quick choices can't lose a rejection
        row = conn.execute("SELECT primary_image_url, rejected_images FROM species "
                           "WHERE scientific_name = ?", (scientific_name,)).fetchone()
        if row is None:
            conn.rollback()
            return
        rejected = parse_rejected_images(row["rejected_images"])
        old = row["primary_image_url"] or ""
        if old and old != "__none__" and old != url and old not in rejected:
            rejected.append(old)
        conn.execute(
            "UPDATE species SET primary_image_url = ?, image_attribution = ?, rejected_images = ? "
            "WHERE scientific_name = ?",
            (url, attribution, json.dumps(rejected) if rejected else None, scientific_name),
        )
        conn.commit()
    finally:
        conn.close()


def get_taxon_by_path(taxon_path: str) -> dict | None:
    """Return the row for any taxon level looked up by its exact taxon_path."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM species WHERE taxon_path = ?",
            (taxon_path,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_children_by_rank(
    taxon_path: str,
    ranks: frozenset[str],
    depth: int = 1,
) -> list[dict]:
    """Return depth-1 children whose taxon_rank is in `ranks` (no row limit)."""
    conn = get_connection()
    try:
        parent_depth = taxon_path.count("|") if taxon_path else -1
        max_depth    = parent_depth + depth
        ranks_list   = sorted(ranks)
        ph           = ",".join("?" * len(ranks_list))
        if taxon_path:
            sql    = f"SELECT * FROM species WHERE taxon_depth<=? AND taxon_path LIKE ? AND taxon_rank IN ({ph})"
            params: list = [max_depth, taxon_path + "|%"] + ranks_list
        else:
            sql    = f"SELECT * FROM species WHERE taxon_depth<=? AND taxon_rank IN ({ph})"
            params = [max_depth] + ranks_list
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def paths_with_accepted_descendants(paths: list[str]) -> set[str]:
    """Return the subset of `paths` that have at least one ACCEPTED descendant.

    Uses the compound (taxon_depth, taxon_path) index for a fast range scan:
    querying at exactly depth = target_depth + 1 (direct children) is ~40× faster
    than a LIKE-only query on a 1.78 M-row table.  All paths are assumed to share
    the same parent and depth (always true when called from taxonomy_zoom).
    """
    if not paths:
        return set()
    conn = get_connection()
    try:
        paths_set    = set(paths)
        sample       = next(iter(paths_set))
        parent_path  = sample.rsplit("|", 1)[0]
        target_depth = sample.count("|")   # e.g. 5 for Apidae|Genus
        child_depth  = target_depth + 1    # species one level below genus

        # Use idx_taxon_depth_path: filter by exact depth first, then path range.
        lo = parent_path + "|"
        hi = parent_path + chr(ord("|") + 1)   # '|' + 1 = '}'
        cur = conn.execute(
            "SELECT taxon_path FROM species "
            "WHERE taxon_depth = ? AND taxon_path >= ? AND taxon_path < ? "
            "  AND taxonomic_status = 'ACCEPTED'",
            (child_depth, lo, hi),
        )
        result: set[str] = set()
        for (tp,) in cur:
            # Extract the ancestor path at target_depth (the genus segment)
            pos = 0
            for _ in range(target_depth):
                pos = tp.index("|", pos) + 1
            end = tp.find("|", pos)
            genus_path = tp[:end] if end != -1 else tp
            if genus_path in paths_set:
                result.add(genus_path)
            if len(result) == len(paths_set):
                break  # all candidate paths found — stop early
        return result
    finally:
        conn.close()


def get_orphan_children(
    taxon_path: str,
    expected_ranks: frozenset[str],
    depth: int = 1,
    limit: int | None = None,
    offset: int = 0,
) -> list[dict]:
    """Return depth-1 children whose rank is NOT in `expected_ranks`, paginated."""
    conn = get_connection()
    try:
        parent_depth = taxon_path.count("|") if taxon_path else -1
        max_depth    = parent_depth + depth
        ranks_list   = sorted(expected_ranks)
        ph           = ",".join("?" * len(ranks_list))
        base = (
            f"taxon_depth<=? AND taxon_path LIKE ? "
            f"AND (taxon_rank NOT IN ({ph}) OR taxon_rank IS NULL) "
            f"AND taxonomic_status != 'SYNONYM'"
        ) if taxon_path else (
            f"taxon_depth<=? "
            f"AND (taxon_rank NOT IN ({ph}) OR taxon_rank IS NULL) "
            f"AND taxonomic_status != 'SYNONYM'"
        )
        params: list = [max_depth, taxon_path + "|%"] + ranks_list if taxon_path else [max_depth] + ranks_list
        sql = f"SELECT * FROM species WHERE {base}"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params += [limit, offset]
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def count_orphan_children(
    taxon_path: str,
    expected_ranks: frozenset[str],
    depth: int = 1,
) -> int:
    """Count depth-1 children whose rank is NOT in `expected_ranks`."""
    conn = get_connection()
    try:
        parent_depth = taxon_path.count("|") if taxon_path else -1
        max_depth    = parent_depth + depth
        ranks_list   = sorted(expected_ranks)
        ph           = ",".join("?" * len(ranks_list))
        if taxon_path:
            row = conn.execute(
                f"SELECT COUNT(*) FROM species WHERE taxon_depth<=? AND taxon_path LIKE ? "
                f"AND (taxon_rank NOT IN ({ph}) OR taxon_rank IS NULL) "
                f"AND taxonomic_status != 'SYNONYM'",
                [max_depth, taxon_path + "|%"] + ranks_list,
            ).fetchone()
        else:
            row = conn.execute(
                f"SELECT COUNT(*) FROM species WHERE taxon_depth<=? "
                f"AND (taxon_rank NOT IN ({ph}) OR taxon_rank IS NULL) "
                f"AND taxonomic_status != 'SYNONYM'",
                [max_depth] + ranks_list,
            ).fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


def search_species(query: str, limit: int = 20) -> list[dict]:
    conn = get_connection()
    try:
        pattern = f"%{query}%"
        # Rank: exact accepted scientific name > exact common name (JSON element)
        # > exact synonym name > a whole word of a common name ("Common wombat",
        # "Hairy-nosed Wombats"; Increment 30) > scientific-name prefix ("Wombatus")
        # > any substring; then ACCEPTED, well-known (abstract, IUCN status, photo),
        # shorter, A–Z. ("Zebra" is also an outdated snail genus.)
        # LIKE '%…%' already forces a full scan, so ordering adds little cost.
        rows = conn.execute(
            """
            SELECT * FROM species
            WHERE scientific_name LIKE ?
               OR common_names LIKE ?
            ORDER BY
                CASE
                    WHEN scientific_name = ? COLLATE NOCASE
                         AND taxonomic_status IS NOT 'SYNONYM' THEN 0
                    WHEN common_names LIKE ? THEN 1
                    WHEN scientific_name = ? COLLATE NOCASE THEN 2
                    WHEN common_names LIKE ? OR common_names LIKE ? OR common_names LIKE ?
                         OR common_names LIKE ? THEN 3
                    WHEN scientific_name LIKE ? THEN 4
                    ELSE 5
                END,
                taxonomic_status = 'SYNONYM',
                (wikipedia_abstract IS NOT NULL)
                    + (iucn_status IS NOT NULL)
                    + (primary_image_url IS NOT NULL) DESC,
                length(scientific_name),
                scientific_name
            LIMIT ?
            """,
            (pattern, pattern, query, f'%"{query}"%', query,
             f'%"{query} %', f'% {query}"%', f"% {query} %", f'% {query}s"%',
             f"{query}%", limit),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
