"""FastAPI entry point — route registration and app configuration."""

import asyncio
import datetime
from pathlib import Path
from typing import Any, Literal
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import database, image_utils, trait_utils
from app.llm_agent import stream_response

app = FastAPI(title="Animal Kingdom API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:5173",  # Vite dev server
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# --- Response models ---

class TaxonNode(BaseModel):
    node_id: str
    name: str
    rank: str
    scientific_name: str | None = None   # the row's key; differs from name for homonyms
    common_names: list[str] = []
    taxonomic_status: str | None = None
    extinct: bool | None = None          # 1/0/NULL column; None = unknown
    children: list["TaxonNode"] = []

TaxonNode.model_rebuild()


class SpeciesRecord(BaseModel):
    scientific_name: str
    taxon_path: str | None = None
    taxon_rank: str | None = None
    common_names: list[str] = []
    taxonomic_status: str | None = None
    body_mass: float | None = None
    body_length: float | None = None
    max_lifespan: float | None = None
    metabolic_rate: float | None = None
    reproduction_strategy: str | None = None
    geo_bounding_box: dict | None = None
    habitat_type: str | None = None
    elevation_limits: str | None = None
    trophic_level: str | None = None
    activity_period: str | None = None
    iucn_status: str | None = None
    population_trend: str | None = None
    primary_image_url: str | None = None
    image_attribution: str | None = None
    wikipedia_abstract: str | None = None
    extinct: bool | None = None
    provenance: dict[str, dict] = {}
    traits_sourced: bool = False
    traits_estimated: bool = False
    trait_eligible: bool = False
    current_name: dict | None = None      # old name → accepted taxon (Increment 30)


class TraitsResponse(BaseModel):
    scientific_name: str
    values: dict[str, Any]
    provenance: dict[str, dict]
    traits_sourced: bool
    traits_estimated: bool
    trait_eligible: bool
    current_name: dict | None = None


class SearchResult(BaseModel):
    scientific_name: str
    common_names: list[str] = []
    taxon_rank: str | None = None
    taxon_path: str | None = None
    taxonomic_status: str | None = None
    iucn_status: str | None = None
    extinct: bool | None = None
    accepted_name: str | None = None      # set on old names (Increment 30)


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    # Earlier turns of this conversation, oldest first; the browser keeps them
    history: list[ChatTurn] = []


class ImageResponse(BaseModel):
    url: str
    attribution: str


class ImageCandidate(BaseModel):
    url: str
    attribution: str
    source: str


class ImageCandidatesResponse(BaseModel):
    candidates: list[ImageCandidate]
    unavailable: bool   # a source didn't answer, so the list may be short


class ImageChoice(BaseModel):
    url: str
    attribution: str = ""


# --- Internal helpers ---

def _node_name(taxon_path: str) -> str:
    return taxon_path.rsplit("|", 1)[-1] if "|" in taxon_path else taxon_path


def _build_tree(flat: list[dict], parent_path: str) -> list[TaxonNode]:
    """Recursively nest a flat get_children result into TaxonNode trees.

    Multiple DB rows can share the same taxon_path (e.g. unranked taxa or
    species classified only to family level).  Deduplicate by path, preferring
    the row whose scientific_name matches the last path segment (the canonical
    taxon record), then any ACCEPTED row, then the first row seen.
    """
    seen: dict[str, dict] = {}
    for node in flat:
        path = node.get("taxon_path") or ""
        if parent_path:
            if not path.startswith(parent_path + "|"):
                continue
            rest = path[len(parent_path) + 1:]
        else:
            rest = path
        if "|" in rest:
            continue  # grandchild or deeper — belongs to a nested level
        if path not in seen:
            seen[path] = node
        else:
            last_seg = path.rsplit("|", 1)[-1] if "|" in path else path
            cur = seen[path]
            # Prefer canonical row (scientific_name == last path segment)
            if node.get("scientific_name", "") == last_seg:
                seen[path] = node
            # Otherwise prefer ACCEPTED over non-ACCEPTED
            elif (cur.get("taxonomic_status") != "ACCEPTED"
                  and node.get("taxonomic_status") == "ACCEPTED"):
                seen[path] = node

    return [
        TaxonNode(
            node_id=path,
            name=_node_name(path),
            rank=node.get("taxon_rank") or "",
            scientific_name=node.get("scientific_name"),
            common_names=database.parse_common_names(node.get("common_names")),
            taxonomic_status=node.get("taxonomic_status"),
            extinct=node.get("extinct"),
            children=_build_tree(flat, path),
        )
        for path, node in seen.items()
    ]


# For each parent rank, the set of ranks that are valid direct children.
# Anything outside this set is considered an orphan and grouped under [Unclassified].
_EXPECTED_CHILD_RANKS: dict[str, frozenset[str]] = {
    "domain":      frozenset({"phylum", "superphylum"}),
    "kingdom":     frozenset({"phylum", "subkingdom", "superphylum", "division", "subdivision"}),
    "subkingdom":  frozenset({"phylum", "superphylum"}),
    "phylum":      frozenset({"class", "subphylum", "infraphylum", "superclass", "subclass"}),
    "subphylum":   frozenset({"class", "superclass", "subclass"}),
    "infraphylum": frozenset({"class", "superclass"}),
    "superclass":  frozenset({"class", "subclass"}),
    "class":       frozenset({"order", "subclass", "infraclass", "superorder", "cohort"}),
    "subclass":    frozenset({"order", "superorder", "infraclass", "cohort"}),
    "infraclass":  frozenset({"order", "superorder", "cohort"}),
    "cohort":      frozenset({"order", "superorder"}),
    "superorder":  frozenset({"order", "suborder"}),
    "order":       frozenset({"family", "suborder", "infraorder", "parvorder", "superfamily"}),
    "suborder":    frozenset({"family", "infraorder", "superfamily", "parvorder"}),
    "infraorder":  frozenset({"family", "superfamily", "parvorder"}),
    "parvorder":   frozenset({"family", "superfamily"}),
    "superfamily": frozenset({"family", "subfamily"}),
    "family":      frozenset({"genus", "subfamily", "tribe", "subtribe"}),
    "subfamily":   frozenset({"genus", "tribe", "subtribe"}),
    "tribe":       frozenset({"genus", "subtribe"}),
    "subtribe":    frozenset({"genus"}),
    "genus":       frozenset({"species", "subgenus"}),
    "subgenus":    frozenset({"species"}),
}

# Where Catalogue of Life has no order, family or the like, the lowest level it does have
# stands in for it (data/build_col_db.py), so these are real nodes, not orphans.
_STAND_IN_RANKS = frozenset({
    "realm", "subkingdom", "infrakingdom", "superphylum", "subphylum", "infraphylum", "parvphylum",
    "gigaclass", "megaclass", "superclass", "subclass", "infraclass", "subterclass", "cohort",
    "superorder", "suborder", "infraorder", "parvorder", "nanorder", "superfamily", "epifamily",
    "subfamily", "supertribe", "tribe", "subtribe", "infratribe", "supergenus",
    "section zoology", "subsection zoology", "series zoology", "section botany", "unranked",
})
_CHILDREN_OF_STAND_IN = frozenset({"kingdom", "phylum", "class", "order", "family", "genus", "species"})
_EXPECTED_CHILD_RANKS = {
    **{rank: _CHILDREN_OF_STAND_IN for rank in _STAND_IN_RANKS},
    **{rank: _EXPECTED_CHILD_RANKS[rank] | _STAND_IN_RANKS
       for rank in ("kingdom", "phylum", "class", "order", "family")},
    "domain": _EXPECTED_CHILD_RANKS["domain"] | {"kingdom"} | _STAND_IN_RANKS,
    "genus": _EXPECTED_CHILD_RANKS["genus"],
    "subgenus": _EXPECTED_CHILD_RANKS["subgenus"],
}


def _expected_ranks_to_depth(parent_rank: str, depth: int) -> frozenset[str] | None:
    """Return the union of expected child ranks for all levels 1..depth.

    e.g. depth=2 from 'kingdom' → phyla ∪ classes, so a single DB query
    can fetch both levels and _build_tree will nest them correctly.
    """
    all_ranks: set[str] = set()
    frontier = {parent_rank}
    for _ in range(depth):
        next_frontier: set[str] = set()
        for r in frontier:
            for child_r in _EXPECTED_CHILD_RANKS.get(r, frozenset()):
                all_ranks.add(child_r)
                next_frontier.add(child_r)
        frontier = next_frontier
    return frozenset(all_ranks) if all_ranks else None


def _row_to_species(row: dict) -> SpeciesRecord:
    bbox = database.parse_geo_bbox(row.get("geo_bounding_box"))
    return SpeciesRecord(
        scientific_name=row["scientific_name"],
        taxon_path=row.get("taxon_path"),
        taxon_rank=row.get("taxon_rank"),
        common_names=database.parse_common_names(row.get("common_names")),
        taxonomic_status=row.get("taxonomic_status"),
        body_mass=row.get("body_mass"),
        body_length=row.get("body_length"),
        max_lifespan=row.get("max_lifespan"),
        metabolic_rate=row.get("metabolic_rate"),
        reproduction_strategy=row.get("reproduction_strategy"),
        geo_bounding_box=bbox or None,
        habitat_type=row.get("habitat_type"),
        elevation_limits=row.get("elevation_limits"),
        trophic_level=row.get("trophic_level"),
        activity_period=row.get("activity_period"),
        iucn_status=row.get("iucn_status"),
        population_trend=row.get("population_trend"),
        primary_image_url=row.get("primary_image_url"),
        image_attribution=row.get("image_attribution"),
        wikipedia_abstract=row.get("wikipedia_abstract"),
        extinct=row.get("extinct"),
        **_trait_state(row),
    )


def _trait_state(row: dict) -> dict:
    """Provenance and stage markers shared by SpeciesRecord and TraitsResponse."""
    markers = database.parse_trait_sources(row.get("trait_sources"))
    return {
        "provenance": database.trait_provenance(row),
        "traits_sourced": "_sourced" in markers,
        "traits_estimated": "_estimated" in markers,
        "trait_eligible": trait_utils.is_eligible(row),
        "current_name": database.current_name(row),
    }


def _row_to_traits(row: dict) -> TraitsResponse:
    values = {f: row[f] for f in database.TRAIT_FIELDS if row.get(f) not in (None, "")}
    if "geo_bounding_box" in values:
        values["geo_bounding_box"] = database.parse_geo_bbox(values["geo_bounding_box"]) or None
    return TraitsResponse(scientific_name=row["scientific_name"], values=values, **_trait_state(row))


# --- Routes ---

@app.get("/health")
def health():
    return {"status": "ok"}


_root_cache: dict[str, list] = {}

# Domains exist only in the tree: taxon_path still starts at the kingdom, or at
# Bacteria / Archaea, so trait matching and the data scripts are unaffected.
# Bacteria and Archaea have no row of their own: those names belong to animal
# genera, and scientific_name is the primary key.
_PATH_DOMAINS = ("Bacteria", "Archaea")
_EUKARYA = "Eukarya"
_EUKARYOTE_KINGDOMS = frozenset({"Animalia", "Plantae", "Fungi", "Chromista", "Protozoa"})


@app.get("/api/taxonomy/root", response_model=list[TaxonNode])
def taxonomy_root():
    """Return the domains, then anything outside them such as Viruses (cached per
    DB path; rarely changes). Eukarya arrives with its kingdoms, so it opens on load."""
    db_key = database.DB_PATH
    if db_key not in _root_cache:
        rows = database.get_children("", depth=1)
        accepted = [r for r in rows if r.get("taxonomic_status") == "ACCEPTED"]
        top = _build_tree(accepted, "")
        kingdoms = [n for n in top if n.node_id in _EUKARYOTE_KINGDOMS]
        roots = [
            TaxonNode(node_id=name, name=name, rank="domain")
            for name in _PATH_DOMAINS
            if database.count_children(name, depth=1)
        ]
        if kingdoms:
            roots.append(TaxonNode(node_id=_EUKARYA, name=_EUKARYA, rank="domain", children=kingdoms))
        roots += [n for n in top if n not in kingdoms and n.node_id not in _PATH_DOMAINS]
        _root_cache[db_key] = roots
    return _root_cache[db_key]


def _parent_rank(node_id: str) -> str:
    """Rank of the node being expanded. A bare "Bacteria" path also matches old
    synonym families stored there, which must not decide what its children are."""
    if node_id in _PATH_DOMAINS:
        return "domain"
    row = database.get_taxon_by_path(node_id)
    return (row.get("taxon_rank") or "") if row else ""


_CHILD_LIMIT = 200


def _alpha_sentinels(parent_path: str, letter_counts: dict[str, int]) -> list[TaxonNode]:
    """Build alpha-group sentinel nodes from a {letter: count} map."""
    return [
        TaxonNode(
            node_id=f"__alpha__{parent_path}|{letter}",
            name=f"[{letter}] ({count:,})",
            rank="alpha",
        )
        for letter, count in sorted(letter_counts.items())
    ]


@app.get("/api/taxonomy/zoom", response_model=list[TaxonNode])
def taxonomy_zoom(
    node_id: str = Query(..., description="taxon_path of the node to expand"),
    depth: int = Query(1, ge=1, le=2, description="Levels to expand (1 or 2)"),
):
    """Return child nodes for a given taxon_path, nested up to `depth` levels.

    When the parent rank is known, only expected-rank children are returned and
    all others are grouped under a synthetic [Unclassified] sentinel node that
    is lazily loaded via /api/taxonomy/unclassified.
    """
    parent_rank  = _parent_rank(node_id)
    # For depth>1 we need phyla+classes etc. in one query; for orphan counting
    # we only care about immediate (depth=1) children.
    expected_all = _expected_ranks_to_depth(parent_rank, depth)
    expected_d1  = _EXPECTED_CHILD_RANKS.get(parent_rank)

    if expected_all:
        # Fetch proper children for all requested levels (no row limit — small sets)
        rows = database.get_children_by_rank(node_id, expected_all, depth)
        # Keep non-synonyms; also keep synonym genus/subgenus nodes that are
        # structural parents for ACCEPTED descendants (e.g. the Apis honey bee genus).
        non_synonym = [r for r in rows if r.get("taxonomic_status") != "SYNONYM"]
        synonym_genera = [
            r for r in rows
            if r.get("taxonomic_status") == "SYNONYM"
            and r.get("taxon_rank") in ("genus", "subgenus")
        ]
        if synonym_genera:
            active = database.paths_with_accepted_descendants(
                [r["taxon_path"] for r in synonym_genera if r.get("taxon_path")]
            )
            non_synonym += [r for r in synonym_genera if r.get("taxon_path") in active]
        rows  = non_synonym
        nodes = _build_tree(rows, node_id)

        # Alpha-group when depth=1 result exceeds the child limit
        if depth == 1 and len(nodes) > _CHILD_LIMIT:
            alpha = _alpha_sentinels(node_id, database.get_children_letter_counts(node_id))
            if expected_d1:
                orphan_count = database.count_orphan_children(node_id, expected_d1, depth=1)
                if orphan_count > 0:
                    alpha.append(TaxonNode(
                        node_id=f"__unclassified__{node_id}",
                        name=f"[Unclassified] ({orphan_count:,})",
                        rank="unclassified",
                    ))
            return alpha

        if expected_d1:
            orphan_count = database.count_orphan_children(node_id, expected_d1, depth=1)
            if orphan_count > 0:
                nodes.append(TaxonNode(
                    node_id=f"__unclassified__{node_id}",
                    name=f"[Unclassified] ({orphan_count:,})",
                    rank="unclassified",
                ))
    else:
        total = database.count_children(node_id, depth=1)
        if total > _CHILD_LIMIT:
            return _alpha_sentinels(node_id, database.get_children_letter_counts(node_id))
        rows  = database.get_children(node_id, depth=depth, limit=_CHILD_LIMIT)
        rows  = [r for r in rows if r.get("taxonomic_status") != "SYNONYM"]
        nodes = _build_tree(rows, node_id)
    return nodes


@app.get("/api/taxonomy/unclassified", response_model=list[TaxonNode])
def taxonomy_unclassified(
    node_id: str = Query(..., description="taxon_path of the parent node"),
    offset: int  = Query(0, ge=0),
    letter: str | None = Query(None, min_length=1, max_length=1),
):
    """Return orphaned (non-expected-rank) children of a node.

    When `letter` is provided, return only children starting with that letter.
    When total orphan count exceeds _CHILD_LIMIT, return alpha-group sentinels
    instead of raw children (unless `letter` is provided).
    """
    expected = _EXPECTED_CHILD_RANKS.get(_parent_rank(node_id))
    if not expected:
        return []

    if letter:
        rows = database.get_orphan_children_by_letter(node_id, expected, letter, depth=1)
        return _build_tree(rows, node_id)

    total = database.count_orphan_children(node_id, expected, depth=1)
    if total > _CHILD_LIMIT:
        return _alpha_sentinels(
            f"__unclassified__{node_id}",
            database.get_orphan_letter_counts(node_id, expected),
        )

    rows  = database.get_orphan_children(node_id, expected, depth=1,
                                         limit=_CHILD_LIMIT, offset=offset)
    return _build_tree(rows, node_id)


@app.get("/api/taxonomy/alpha", response_model=list[TaxonNode])
def taxonomy_alpha(
    node_id: str = Query(..., description="taxon_path of the parent node"),
    letter: str  = Query(..., min_length=1, max_length=1),
):
    """Return children of node_id whose name starts with `letter`.

    Applies the same structural-SYNONYM filter as taxonomy_zoom.
    """
    rows = database.get_children_by_letter(node_id, letter)
    non_synonym = [r for r in rows if r.get("taxonomic_status") != "SYNONYM"]
    synonym_genera = [
        r for r in rows
        if r.get("taxonomic_status") == "SYNONYM"
        and r.get("taxon_rank") in ("genus", "subgenus")
    ]
    if synonym_genera:
        active = database.paths_with_accepted_descendants(
            [r["taxon_path"] for r in synonym_genera if r.get("taxon_path")]
        )
        non_synonym += [r for r in synonym_genera if r.get("taxon_path") in active]
    return _build_tree(non_synonym, node_id)


@app.get("/api/taxonomy/node", response_model=TaxonNode)
def taxonomy_node(
    node_id: str = Query(..., description="taxon_path of the node to fetch"),
):
    """Return a single taxonomy node by its taxon_path without loading siblings.

    Used by the frontend to inject a node that was truncated by the child limit.
    """
    row = database.get_taxon_by_path(node_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Node not found")
    return TaxonNode(
        node_id=row.get("taxon_path") or node_id,
        name=_node_name(node_id),
        rank=row.get("taxon_rank") or "",
        scientific_name=row.get("scientific_name"),
        common_names=database.parse_common_names(row.get("common_names")),
        taxonomic_status=row.get("taxonomic_status"),
        extinct=row.get("extinct"),
    )


@app.get("/api/species/{scientific_name}/image", response_model=ImageResponse)
def species_image(scientific_name: str, force: bool = Query(False), retry: bool = Query(False),
                  failed: str | None = Query(None)):
    """Fetch an image for a species on demand, caching the result to the DB.

    Returns 404 immediately if primary_image_url == '__none__' (all sources
    previously failed) unless force=true is passed (e.g. after an onerror event).
    On all-fail with force=False, writes '__none__' sentinel to prevent re-fetch loops.
    retry=true (the panel's "Search again") implies force and runs the wide search
    (an old name's current name, GBIF photos); a miss stores '__none__' with
    "searched again <date>" unless the row has a real URL. A source that didn't
    answer gives 503 and stores nothing. failed=<url> (a stored picture the browser
    couldn't load) is skipped by this lookup only: being offline makes every picture
    fail, so it doesn't join rejected_images.
    """
    row = database.get_species(scientific_name)
    if row is None:
        raise HTTPException(status_code=404, detail="Species not found")

    current_url = row.get("primary_image_url") or ""
    if not (force or retry) and current_url == "__none__":
        raise HTTPException(status_code=404, detail="No image available")

    common_names = database.parse_common_names(row.get("common_names"))
    current = database.current_name(row) if retry else None
    exclude = set(database.parse_rejected_images(row.get("rejected_images")))
    if failed:
        exclude.add(failed)
    try:
        result = image_utils.fetch_image(
            scientific_name, common_names or None, row.get("taxon_path"),
            rank=row.get("taxon_rank"), wide=retry, exclude=exclude,
            current_name=current["scientific_name"] if current else None,
            current_path=current.get("taxon_path") if current else None,
            current_rank=current.get("taxon_rank") if current else None)
    except image_utils.ImagesUnavailable:
        raise HTTPException(status_code=503, detail="A picture source didn't answer; try again later")

    read = row.get("primary_image_url")   # a choice made while the lookup ran wins
    if result:
        url, attribution = result
        if not database.replace_species_image(scientific_name, url, attribution, read):
            return _stored_picture(scientific_name)
        return ImageResponse(url=url, attribution=attribution)

    no_real_url = current_url in ("", "__none__")
    if retry and no_real_url:
        today = datetime.date.today().isoformat()
        if not database.replace_species_image(scientific_name, "__none__", f"searched again {today}", read):
            return _stored_picture(scientific_name)
        raise HTTPException(status_code=404,
                            detail={"message": "No image found", "searched_again": today})
    if not force and not retry and no_real_url:
        if not database.replace_species_image(scientific_name, "__none__", "", read):
            return _stored_picture(scientific_name)

    raise HTTPException(status_code=404, detail="No image found")


def _stored_picture(scientific_name: str) -> ImageResponse:
    """The picture stored now (one the user chose while a lookup ran); 404 if none."""
    row = database.get_species(scientific_name) or {}
    url = row.get("primary_image_url") or ""
    if url and url != "__none__":
        return ImageResponse(url=url, attribution=row.get("image_attribution") or "")
    raise HTTPException(status_code=404, detail="No image found")


@app.get("/api/species/{scientific_name}/traits", response_model=TraitsResponse)
def species_traits(scientific_name: str,
                   stage: Literal["sourced", "estimated"] = Query("sourced"),
                   force: bool = Query(False)):
    """Fill missing traits on demand and cache them (write-through, like /image).

    stage=sourced queries IUCN / GBIF / Wikidata / Wikipedia; stage=estimated
    also has the local LLM read the abstract. A stage whose marker is stored is
    skipped unless force=true; a stage that could not finish leaves no marker.
    """
    row = database.get_species(scientific_name)
    if row is None:
        raise HTTPException(status_code=404, detail="Species not found")
    if not trait_utils.is_eligible(row):
        return _row_to_traits(row)

    name = row["scientific_name"]
    markers = database.parse_trait_sources(row.get("trait_sources"))
    if force or "_sourced" not in markers:
        row = trait_utils.apply_stage(row, "sourced", *trait_utils.run_sourced_stage(row))
    elif "_names" not in markers:
        # Sourced before Increment 30: the Wikidata old-name check once on its own
        row = trait_utils.apply_stage(row, "names", *trait_utils.run_name_stage(row))
    # The estimate reads the abstract the sourced stage fetches; with that stage
    # incomplete, "no abstract" means "not fetched yet", so don't mark it done
    sourced_done = "_sourced" in database.parse_trait_sources(row.get("trait_sources"))
    if stage == "estimated" and sourced_done and (force or "_estimated" not in markers):
        row = trait_utils.apply_stage(row, "estimated", *trait_utils.run_estimate_stage(row))
    return _row_to_traits(row)



@app.get("/api/species/{scientific_name}/image/candidates", response_model=ImageCandidatesResponse)
def species_image_candidates(scientific_name: str):
    """Pictures to choose from for the panel's "Other pictures": every source at once,
    without the current picture and the ones replaced before."""
    row = database.get_species(scientific_name)
    if row is None:
        raise HTTPException(status_code=404, detail="Species not found")
    exclude = set(database.parse_rejected_images(row.get("rejected_images")))
    if row.get("primary_image_url") and row["primary_image_url"] != "__none__":
        exclude.add(row["primary_image_url"])
    current = database.current_name(row)
    candidates, down = image_utils.image_candidates(
        scientific_name, database.parse_common_names(row.get("common_names")) or None,
        row.get("taxon_path"), rank=row.get("taxon_rank"),
        current_name=current["scientific_name"] if current else None,
        current_path=current.get("taxon_path") if current else None,
        current_rank=current.get("taxon_rank") if current else None,
        exclude=exclude)
    return ImageCandidatesResponse(candidates=[ImageCandidate(**c) for c in candidates], unavailable=down)


@app.put("/api/species/{scientific_name}/image", response_model=ImageResponse)
def choose_species_image(scientific_name: str, choice: ImageChoice):
    """Keep the picture the user picked; the one it replaces is never offered again."""
    if not choice.url.startswith(("https://", "http://")):
        raise HTTPException(status_code=400, detail="Picture URL must start with http(s)://")
    if database.get_species(scientific_name) is None:
        raise HTTPException(status_code=404, detail="Species not found")
    database.choose_species_image(scientific_name, choice.url, choice.attribution)
    return ImageResponse(url=choice.url, attribution=choice.attribution)


@app.get("/api/species/{scientific_name}", response_model=SpeciesRecord)
def species_detail(scientific_name: str):
    """Return the full record for a single species."""
    row = database.get_species(scientific_name)
    if row is None:
        raise HTTPException(status_code=404, detail="Species not found")
    return _row_to_species(row)


@app.post("/api/chat")
async def chat(req: ChatRequest):
    """Stream an agent response as server-sent events (text/event-stream).

    Each SSE frame is one of:
      data: {"type": "token",  "content": "..."}
      data: {"type": "image",  "url": "...", "attribution": "..."}
      data: {"type": "done"}
    """
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="message must not be empty")

    async def _event_stream():
        try:
            async for chunk in stream_response(req.message, [t.model_dump() for t in req.history]):
                yield chunk
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            import json
            yield f"data: {json.dumps({'type': 'error', 'detail': str(exc)})}\n\n"

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/search", response_model=list[SearchResult])
def search(
    q: str = Query(..., min_length=1, description="Search term"),
    limit: int = Query(20, ge=1, le=100),
):
    """Full-text search across scientific_name and common_names, plus domain names."""
    rows = database.search_species(q, limit=limit)
    return (_domain_hits(q) + [
        SearchResult(
            scientific_name=r["scientific_name"],
            common_names=database.parse_common_names(r.get("common_names")),
            taxon_rank=r.get("taxon_rank"),
            taxon_path=r.get("taxon_path"),
            taxonomic_status=r.get("taxonomic_status"),
            iucn_status=r.get("iucn_status"),
            extinct=r.get("extinct"),
            accepted_name=r.get("accepted_name"),
        )
        for r in rows
    ])[:limit]


def _domain_hits(q: str) -> list[SearchResult]:
    """Domains have no database row, so search adds them by name (3+ letters, prefix)."""
    prefix = q.strip().casefold()
    if len(prefix) < 3:
        return []
    return [
        SearchResult(scientific_name=n.name, taxon_rank=n.rank, taxon_path=n.node_id)
        for n in taxonomy_root()
        if n.rank == "domain" and n.name.casefold().startswith(prefix)
    ]


# ── Serve frontend static files (must be last — catches everything else) ──────

class _RevalidatedStaticFiles(StaticFiles):
    """Browsers keep the files but must ask first, so stale JS never runs (304 if unchanged)."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


_FRONTEND = Path(__file__).parent.parent.parent / "frontend"
if _FRONTEND.exists():
    app.mount("/", _RevalidatedStaticFiles(directory=str(_FRONTEND), html=True), name="frontend")
