"""
Build frontend/data/world.json, the country outlines of the species panel's range map.

Source: Natural Earth 1:50m admin-0 map units (public domain), the same file
build_places.py reads. Each map unit becomes one feature with its ISO 3166 alpha-2
code (as GBIF records it), simplified so the file stays small:
  - Douglas-Peucker with a tolerance in degrees (default 0.08)
  - coordinates rounded to 2 decimals
  - rings that collapse below a triangle are dropped, except a unit's largest ring
  - rings rewound for d3-geo: outer rings clockwise, holes counter-clockwise

Usage (from project root; downloads kept in <data dir>/natural_earth):
    .venv\\Scripts\\python data\\build_world_map.py [--source DIR] [--out FILE] [--tolerance DEG]
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_places import _DEFAULT_SOURCE, _iso  # noqa: E402

_DEFAULT_OUT = Path(__file__).resolve().parent.parent / "frontend" / "data" / "world.json"
TOLERANCE = 0.08


def _point_line_dist(p, a, b) -> float:
    (x, y), (x1, y1), (x2, y2) = p, a, b
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)))
    return ((x - x1 - t * dx) ** 2 + (y - y1 - t * dy) ** 2) ** 0.5


def simplify(points: list, tol: float) -> list:
    """Douglas-Peucker on an open line; keeps both ends. Iterative (rings can be long)."""
    if len(points) < 3:
        return list(points)
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        i, j = stack.pop()
        best, idx = 0.0, None
        for k in range(i + 1, j):
            d = _point_line_dist(points[k], points[i], points[j])
            if d > best:
                best, idx = d, k
        if idx is not None and best > tol:
            keep[idx] = True
            stack += [(i, idx), (idx, j)]
    return [p for p, k in zip(points, keep) if k]


def signed_area(ring: list) -> float:
    """Shoelace area in lon/lat; negative = clockwise."""
    return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:])) / 2


def rewind(ring: list, clockwise: bool) -> list:
    return ring[::-1] if (signed_area(ring) < 0) != clockwise else ring


def simplify_ring(ring: list, tol: float) -> list | None:
    """A closed ring, simplified and rounded; None if it collapses below a triangle."""
    # Split at the point farthest from the start so a closed ring keeps its shape
    far = max(range(len(ring)), key=lambda k: (ring[k][0] - ring[0][0]) ** 2 + (ring[k][1] - ring[0][1]) ** 2)
    half = simplify(ring[:far + 1], tol)[:-1] + simplify(ring[far:], tol)
    out = []
    for x, y in half:
        pt = [round(x, 2), round(y, 2)]
        if not out or out[-1] != pt:
            out.append(pt)
    if out[0] != out[-1]:
        out.append(out[0])
    return out if len(out) >= 4 else None


def _polygons(geometry) -> list:
    if geometry is None:
        return []
    if geometry["type"] == "Polygon":
        return [geometry["coordinates"]]
    if geometry["type"] == "MultiPolygon":
        return geometry["coordinates"]
    return []


def unit_feature(feature: dict, tol: float) -> dict | None:
    polys = _polygons(feature.get("geometry"))
    if not polys:
        return None
    out = []
    for poly in polys:
        outer = simplify_ring(poly[0], tol)
        if outer is None:
            continue
        holes = [h for h in (simplify_ring(r, tol) for r in poly[1:]) if h]
        out.append([rewind(outer, True), *(rewind(h, False) for h in holes)])
    if not out:
        # Keep a small island state visible: its largest outer ring, unsimplified
        biggest = max((p[0] for p in polys), key=lambda r: abs(signed_area(r)))
        out = [[rewind([[round(x, 2), round(y, 2)] for x, y in biggest], True)]]
    p = feature["properties"]
    return {"type": "Feature",
            "properties": {"code": _iso(p), "name": p.get("NAME_LONG") or p.get("NAME")},
            "geometry": {"type": "MultiPolygon", "coordinates": out}}


def build(features: list, tol: float = TOLERANCE) -> dict:
    return {"type": "FeatureCollection",
            "features": [f for f in (unit_feature(x, tol) for x in features) if f]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--source", type=Path, default=_DEFAULT_SOURCE)
    ap.add_argument("--out", type=Path, default=_DEFAULT_OUT)
    ap.add_argument("--tolerance", type=float, default=TOLERANCE)
    args = ap.parse_args()
    src = json.loads((args.source / "ne_50m_admin_0_map_units.geojson").read_text(encoding="utf-8"))
    world = build(src["features"], args.tolerance)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(world, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    coded = sum(1 for f in world["features"] if f["properties"]["code"])
    print(f"{len(world['features'])} map units ({coded} with a code) -> {args.out} "
          f"({args.out.stat().st_size / 1e3:.0f} KB)")


if __name__ == "__main__":
    sys.exit(main())
