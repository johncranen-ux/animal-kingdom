"""Places for the chat's species_in_place tool: countries, continents, islands,
regions and seas from Natural Earth, built by data/build_places.py into
app/data/places.json as rows of a 0.5° grid.

A species counts for a place when its range box (geo_bounding_box) shares a grid
cell with the place. Range boxes are rough, so this is "the recorded range
overlaps", not "lives there"."""

import bisect
import functools
import json
import math
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

PLACES_PATH = Path(__file__).resolve().parent / "data" / "places.json"
RES = 0.5
# On a shared name the country wins: "Ireland" the country, not the island
_KIND_ORDER = ("country", "continent", "island", "island group", "sea", "country part", "region")
_LEADING = ("in ", "on ", "at ", "around ", "the ")


@dataclass
class Place:
    name: str
    kind: str
    bbox: list[float]                         # lat_min, lat_max, lon_min, lon_max
    rows: dict[int, list[list[int]]] = field(repr=False)
    countries: tuple[str, ...] = ()           # GBIF country codes; empty = use range boxes
    partial: tuple[str, ...] = ()             # codes of countries only partly in the place
    _starts: dict[int, list[int]] = field(default_factory=dict, repr=False)

    def overlaps(self, lat_min: float, lat_max: float, lon_min: float, lon_max: float) -> bool:
        """True if the box shares a grid cell with the place."""
        return self._touches(_row(lat_min), _row(lat_max), _col(lon_min), _col(lon_max))

    def _touches(self, r0: int, r1: int, c0: int, c1: int) -> bool:
        """True if a cell in rows r0..r1, columns c0..c1 belongs to the place."""
        for r in range(r0, r1 + 1):
            runs = self.rows.get(r)
            if not runs:
                continue
            starts = self._starts.get(r)
            if starts is None:
                starts = self._starts[r] = [s for s, _ in runs]
            # The last run starting at or before c1 is the only one that can reach c0
            i = bisect.bisect_right(starts, c1) - 1
            if i >= 0 and runs[i][1] >= c0:
                return True
        return False

    @property
    def label(self) -> str:
        return f"{self.name} ({self.kind})"


def _row(lat: float) -> int:
    return min(int(180 / RES) - 1, max(0, math.floor((lat + 90) / RES)))


def _col(lon: float) -> int:
    return min(int(360 / RES) - 1, max(0, math.floor((lon + 180) / RES)))


def norm(name: str) -> str:
    """Same as data/build_places.py: lowercase, no accents, no leading 'in' / 'the'."""
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    text = " ".join(text.replace(".", " ").replace("?", " ").split())
    changed = True
    while changed:
        changed = False
        for word in _LEADING:
            if text.startswith(word):
                text, changed = text[len(word):], True
    return text


@functools.lru_cache(maxsize=1)
def _load() -> dict[str, list[Place]]:
    data = json.loads(Path(PLACES_PATH).read_text(encoding="utf-8"))
    index: dict[str, list[Place]] = {}
    for p in data:
        place = Place(p["name"], p["kind"], p["bbox"], {int(r): v for r, v in p["rows"].items()},
                      tuple(p.get("countries", ())), tuple(p.get("partial", ())))
        for key in {norm(p["name"]), *(norm(a) for a in p["aliases"])}:
            index.setdefault(key, []).append(place)
    rank = {k: i for i, k in enumerate(_KIND_ORDER)}
    for places in index.values():
        places.sort(key=lambda pl: rank.get(pl.kind, len(rank)))
    return index


def find_place(name: str) -> Place | None:
    """The place a name refers to ('Holland', 'in the Mediterranean'), else None."""
    hits = _load().get(norm(name or ""))
    return hits[0] if hits else None


@functools.lru_cache(maxsize=1)
def _by_code() -> dict[str, Place]:
    """GBIF country code -> its place; a country wins over a country part. Continents
    list codes too (Increment 29) but are no code's place."""
    out: dict[str, Place] = {}
    for places_ in _load().values():
        for place in places_:
            if place.kind not in ("country", "country part"):
                continue
            for code in place.countries:
                if code not in out or (out[code].kind != "country" and place.kind == "country"):
                    out[code] = place
    return out


def country_by_code(code: str) -> Place | None:
    return _by_code().get(code)


# A species' countries: the well-recorded ones (START_SHARE of its records and
# START_RECORDS or more, and always the most recorded one) and, through neighbours
# with records, the ones around them. Zoo animals and misplaced records sit in
# countries away from those (tigers in Brazil, koalas in Japan).
START_SHARE = 0.02
START_RECORDS = 20
NEIGHBOUR_CELLS = 2      # 1°: across a narrow strait
# St. Lawrence Island (Alaska) lies ~60 km off Chukotka: without this a few Russian
# records would carry tigers to the USA. Species living on both sides (wolves, brown
# bears) are well recorded on both, so each side is a starting point of its own.
NOT_NEIGHBOURS = {frozenset({"RU", "US"})}


def _near(a: Place, b: Place, k: int = NEIGHBOUR_CELLS) -> bool:
    """True if a cell of `a` lies within k cells of a cell of `b`."""
    pad = k * RES
    if (a.bbox[0] > b.bbox[1] + pad or a.bbox[1] < b.bbox[0] - pad
            or a.bbox[2] > b.bbox[3] + pad or a.bbox[3] < b.bbox[2] - pad):
        return False
    for r, runs in a.rows.items():
        for c0, c1 in runs:
            if b._touches(r - k, r + k, c0 - k, c1 + k):
                return True
    return False


def native_countries(records: list[tuple[str, int]]) -> tuple[list[tuple[str, int]], int]:
    """(country name, records) of the countries the species lives in, in the given
    order, and how many other countries have records of it."""
    inside, outside = split_countries(records)
    return [(name, n) for _, name, n in inside], len(outside)


def split_countries(records: list[tuple[str, int]]
                    ) -> tuple[list[tuple[str, str, int]], list[tuple[str, str, int]]]:
    """(code, name, records) of the countries the species lives in and of the other
    countries with records (zoos, misplaced records), both in the given order. A code
    with no place keeps the code as its name and counts as elsewhere."""
    kept = _native_codes(records)
    inside, outside = [], []
    for code, n in records:
        place = country_by_code(code)
        (inside if code in kept else outside).append((code, place.name if place else code, n))
    return inside, outside


def _native_codes(records: list[tuple[str, int]]) -> set[str]:
    known = [(code, n, place) for code, n in records if (place := country_by_code(code))]
    if not known:
        return set()
    total = sum(n for _, n, _ in known)
    top = max(n for _, n, _ in known)
    kept = {code for code, n, _ in known
            if n == top or (n >= START_RECORDS and n >= START_SHARE * total)}
    todo = [(code, p) for code, _, p in known if code in kept]
    while todo:
        here, place = todo.pop()
        for code, _, other in known:
            if (code not in kept and frozenset({code, here}) not in NOT_NEIGHBOURS
                    and _near(other, place)):
                kept.add(code)
                todo.append((code, other))
    return kept
