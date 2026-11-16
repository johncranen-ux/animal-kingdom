"""
Build backend/app/data/places.json for the chat's species_in_place tool.

Places come from Natural Earth (public domain), 1:50m:
  - ne_50m_admin_0_map_units      countries; overseas parts are their own places
                                  (France is mainland France, French Guiana is separate)
  - ne_50m_geography_regions_polys continents, islands, island groups, deserts, ranges, ...
  - ne_50m_geography_marine_polys  seas, gulfs, bays, oceans

Each place is stored as rows of a 0.5° grid (row = latitude band, runs of longitude
columns), so the chat tests a species' range box against it with a lookup and no
geometry. A cell belongs to a place if its centre lies inside a polygon or an edge of
the polygon passes through it. Holes (lakes) are ignored.

Usage (from project root; downloads kept in E:\\AnimalKingdomSystem\\natural_earth):
    .venv\\Scripts\\python data\\build_places.py [--source DIR] [--out FILE]
"""

import argparse
import json
import math
import sys
import unicodedata
from pathlib import Path

import numpy as np

RES = 0.5                       # degrees per cell
N_ROWS, N_COLS = int(180 / RES), int(360 / RES)
_DEFAULT_SOURCE = Path(r"E:\AnimalKingdomSystem\natural_earth")
_DEFAULT_OUT = Path(__file__).resolve().parent.parent / "backend" / "app" / "data" / "places.json"

# Extra names people use; keys are place names as built here
ALIASES = {
    "Netherlands": ["holland", "the netherlands", "nederland"],
    "United Kingdom": ["uk", "britain", "great britain and northern ireland"],
    "United States of America": ["usa", "us", "united states", "the united states", "the us", "the usa"],
    "Czechia": ["czech republic"],
    "Myanmar": ["burma"],
    "Eswatini": ["swaziland"],
    "Côte d'Ivoire": ["ivory coast"],
    "Democratic Republic of the Congo": ["dr congo", "drc", "congo-kinshasa"],
    "Republic of the Congo": ["congo-brazzaville"],
    "North America": ["the americas north"],
    "Australia": ["oz"],
    "Mediterranean Sea": ["mediterranean", "the mediterranean"],
    "Amazon basin": ["amazon", "amazonia", "amazon rainforest", "the amazon"],
    "Congo basin": ["congo rainforest"],
}

_REGION_KINDS = {"continent": "continent", "island": "island", "island group": "island group"}


def norm(name: str) -> str:
    """Lowercase, accents and a leading 'the' dropped: 'Côte d'Ivoire' -> 'cote d'ivoire'."""
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    text = " ".join(text.replace(".", " ").split())
    return text[4:] if text.startswith("the ") else text


# ── Rasterising ───────────────────────────────────────────────────────────────

def _row(lat: float) -> int:
    return min(N_ROWS - 1, max(0, math.floor((lat + 90) / RES)))


def _col(lon: float) -> int:
    return min(N_COLS - 1, max(0, math.floor((lon + 180) / RES)))


def _ring_cells(ring) -> set[tuple[int, int]]:
    pts = np.asarray(ring, dtype=float)
    lons, lats = pts[:, 0], pts[:, 1]
    r0, r1, c0, c1 = _row(lats.min()), _row(lats.max()), _col(lons.min()), _col(lons.max())
    cells: set[tuple[int, int]] = set()
    # Inside: even-odd test of the cell centres within the ring's box
    rows = np.arange(r0, r1 + 1)
    cols = np.arange(c0, c1 + 1)
    cy = (rows + 0.5) * RES - 90
    cx = (cols + 0.5) * RES - 180
    gx, gy = np.meshgrid(cx, cy)
    inside = np.zeros(gx.shape, dtype=bool)
    x1, y1 = lons[:-1], lats[:-1]
    x2, y2 = lons[1:], lats[1:]
    for ax, ay, bx, by in zip(x1, y1, x2, y2):
        if ay == by:
            continue
        crosses = (ay > gy) != (by > gy)
        xint = ax + (gy - ay) * (bx - ax) / (by - ay)
        inside ^= crosses & (gx < xint)
    for i, j in zip(*np.nonzero(inside)):
        cells.add((int(rows[i]), int(cols[j])))
    # Edge: points along each segment, closer than a cell
    for ax, ay, bx, by in zip(x1, y1, x2, y2):
        steps = max(1, int(max(abs(bx - ax), abs(by - ay)) / (RES / 4)))
        for k in range(steps + 1):
            t = k / steps
            cells.add((_row(ay + (by - ay) * t), _col(ax + (bx - ax) * t)))
    return cells


def runs(cols) -> list[list[int]]:
    """Sorted column indices -> inclusive runs: [3,4,5,9] -> [[3,5],[9,9]]."""
    out: list[list[int]] = []
    for c in sorted(set(cols)):
        if out and c == out[-1][1] + 1:
            out[-1][1] = c
        else:
            out.append([c, c])
    return out


def rasterise(rings) -> dict[int, list[list[int]]]:
    """Outer rings -> {row: [[col_start, col_end], ...]}."""
    cells: set[tuple[int, int]] = set()
    for ring in rings:
        cells |= _ring_cells(ring)
    by_row: dict[int, list[int]] = {}
    for r, c in cells:
        by_row.setdefault(r, []).append(c)
    return {r: runs(cs) for r, cs in sorted(by_row.items())}


def _outer_rings(geometry) -> list:
    if geometry is None:
        return []
    if geometry["type"] == "Polygon":
        return [geometry["coordinates"][0]]
    if geometry["type"] == "MultiPolygon":
        return [poly[0] for poly in geometry["coordinates"]]
    return []


def _bbox(rings) -> list[float]:
    lats = [p[1] for ring in rings for p in ring]
    lons = [p[0] for ring in rings for p in ring]
    return [round(min(lats), 2), round(max(lats), 2), round(min(lons), 2), round(max(lons), 2)]


def _place(name: str, kind: str, names, rings, countries=()) -> dict:
    aliases = {norm(n) for n in [*names, *ALIASES.get(name, [])] if n}
    aliases.discard(norm(name))
    out = {"name": name, "kind": kind, "aliases": sorted(aliases), "bbox": _bbox(rings),
           "rows": {str(r): v for r, v in rasterise(rings).items()}}
    if countries:
        out["countries"] = sorted(countries)
    return out


def _iso(p: dict) -> str | None:
    """The unit's ISO 3166 alpha-2 code as GBIF's countryCode uses it. ISO_A2_EH fills
    the -99 of France, Norway and the UK's parts; Somaliland and N. Cyprus have none."""
    code = p.get("ISO_A2_EH") or p.get("ISO_A2")
    return code if code and len(code) == 2 and code.isalpha() else None


# ── Places from the three layers ──────────────────────────────────────────────

def country_places(features) -> list[dict]:
    """One place per map unit, plus one per country (ADMIN) made of its home units:
    the unit named like the country, else all its units (England, Scotland, ... -> UK)."""
    out, by_admin = [], {}
    for f in features:
        p = f["properties"]
        rings = _outer_rings(f["geometry"])
        if not rings:
            continue
        by_admin.setdefault(p["ADMIN"], []).append((p, rings))
    for admin, units in by_admin.items():
        own = [u for u in units if u[0].get("GEOUNIT") == admin]
        home = own or units
        names = [admin]
        # A country joined from parts (England, Scotland, ...) keeps only its own
        # names: the parts' names belong to the parts
        name_keys = (("NAME", "NAME_LONG", "FORMAL_EN", "NAME_ALT", "GEOUNIT", "BRK_NAME") if own
                     else ("FORMAL_EN",))
        for p, _ in home:
            names += [p.get(k) for k in name_keys]
        codes = {c for c in (_iso(p) for p, _ in home) if c}
        country = _place(admin, "country", names, [r for _, rings in home for r in rings], codes)
        continents = [p.get("CONTINENT") for p, _ in home if p.get("CONTINENT") not in (None, _OPEN_OCEAN)]
        if continents:
            country["_continent"] = max(set(continents), key=continents.count)
        out.append(country)
        for p, rings in units:
            if p.get("GEOUNIT") == admin or p.get("NAME") == admin or len(units) == 1:
                continue
            unit_names = [p.get(k) for k in ("NAME", "NAME_LONG", "GEOUNIT", "SUBUNIT", "NAME_ALT")]
            # A part with its own code (French Guiana GF, Svalbard SJ) gets GBIF's
            # country list; one sharing the country's code (England GB) keeps the box test
            code = _iso(p)
            own_code = {code} if code and code not in codes else set()
            part = _place(p.get("NAME_LONG") or p["NAME"], "country part", unit_names, rings, own_code)
            if own_code and p.get("CONTINENT") not in (None, _OPEN_OCEAN):
                part["_continent"] = p["CONTINENT"]
            out.append(part)
    return out


# ── Continents as lists of countries (Increment 29) ──────────────────────────

_OPEN_OCEAN = "Seven seas (open ocean)"
# Natural Earth's CONTINENT value -> the continent place's name
_CONTINENT_PLACE = {"Oceania": "Australia"}
# A country with this share of its cells on another continent's outline is on both
# (Russia, Turkey, Kazakhstan, Georgia, Azerbaijan; Egypt's Sinai is 2%)
TRANSCONTINENTAL_SHARE = 0.05


def _cells(place: dict) -> set[tuple[int, int]]:
    return {(int(r), c) for r, runs in place["rows"].items() for a, b in runs for c in range(a, b + 1)}


def assign_continents(built: list[dict]) -> None:
    """Give each continent place the GBIF codes of its countries (Natural Earth's
    CONTINENT field: the outlines are mainlands only, without the UK or Madagascar).
    A country on two continents goes to both as `partial`: there a species counts only
    if its range box touches the continent. Drops the builder's `_continent` keys."""
    continents = {p["name"]: p for p in built if p["kind"] == "continent"}
    outline = {name: _cells(p) for name, p in continents.items()}
    for p in continents.values():
        p["countries"], p["partial"] = set(), set()
    # "Oceania" names the continent place Australia, not the country
    for value, name in _CONTINENT_PLACE.items():
        if name in continents and norm(value) not in continents[name]["aliases"]:
            continents[name]["aliases"] = sorted({*continents[name]["aliases"], norm(value)})
    for country in built:
        own = country.pop("_continent", None)
        codes = set(country.get("countries", ()))
        if own is None or not codes:
            continue
        own = _CONTINENT_PLACE.get(own, own)
        cells = _cells(country)
        others = [name for name, cs in outline.items()
                  if name != own and cells and len(cells & cs) / len(cells) >= TRANSCONTINENTAL_SHARE]
        for name in [own, *others]:
            if name in continents:
                continents[name]["countries"] |= codes
                if others:
                    continents[name]["partial"] |= codes
    for p in continents.values():
        p["countries"], p["partial"] = sorted(p["countries"]), sorted(p["partial"])
        if not p["partial"]:
            del p["partial"]
        if not p["countries"]:
            del p["countries"]


def _title(name: str) -> str:
    return name.title() if name.isupper() else name


def region_places(features) -> list[dict]:
    out = []
    for f in features:
        p = f["properties"]
        rings = _outer_rings(f["geometry"])
        if not rings or not p.get("NAME"):
            continue
        name = p.get("NAME_EN") or _title(p["NAME"])
        kind = _REGION_KINDS.get((p.get("FEATURECLA") or "").lower(), "region")
        out.append(_place(name, kind, [p.get("NAME"), p.get("NAMEALT"), p.get("NAME_EN")], rings))
    return out


def sea_places(features) -> list[dict]:
    out = []
    for f in features:
        p = f["properties"]
        rings = _outer_rings(f["geometry"])
        # River mouths ("Amazon") would win the name over the river's basin
        if not rings or not p.get("name") or (p.get("featurecla") or "").lower() == "river":
            continue
        name = p.get("name_en") or p["name"]
        out.append(_place(name, "sea", [p.get("name"), p.get("namealt"), p.get("name_en")], rings))
    return out


# Places missing from the 1:50m layers, as boxes: (name, kind, aliases, lat_min, lat_max, lon_min, lon_max)
EXTRA_BOXES = [
    ("Galápagos Islands", "island group", ["galapagos", "galapagos islands", "galápagos"],
     -1.5, 0.7, -92.1, -89.2),
]


def extra_places() -> list[dict]:
    out = []
    for name, kind, aliases, la0, la1, lo0, lo1 in EXTRA_BOXES:
        ring = [[lo0, la0], [lo1, la0], [lo1, la1], [lo0, la1], [lo0, la0]]
        out.append(_place(name, kind, [name, *aliases], [ring]))
    return out


def _load(path: Path) -> list:
    return json.loads(path.read_text(encoding="utf-8"))["features"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--source", type=Path, default=_DEFAULT_SOURCE)
    ap.add_argument("--out", type=Path, default=_DEFAULT_OUT)
    args = ap.parse_args()
    built = (country_places(_load(args.source / "ne_50m_admin_0_map_units.geojson"))
             + region_places(_load(args.source / "ne_50m_geography_regions_polys.geojson"))
             + sea_places(_load(args.source / "ne_50m_geography_marine_polys.geojson"))
             + extra_places())
    assign_continents(built)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(built, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    kinds: dict[str, int] = {}
    for p in built:
        kinds[p["kind"]] = kinds.get(p["kind"], 0) + 1
    print(f"{len(built)} places -> {args.out} ({args.out.stat().st_size / 1e6:.1f} MB): "
          + ", ".join(f"{k} {n}" for k, n in sorted(kinds.items())))


if __name__ == "__main__":
    sys.exit(main())
