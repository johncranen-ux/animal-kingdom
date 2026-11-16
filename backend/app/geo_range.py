"""Geographic ranges from GBIF wild records: shared by data/import_gbif_ranges.py
(the SQL download) and the on-demand fallback in trait_utils.

A range edge is the 0.5% percentile of the records' coordinates, not the extreme.
That trims stray points (zoos, swapped coordinates) only for well-recorded species:
below ~200 records the percentile is the single extreme record. Rankings therefore
use ranges from at least taxon_queries.RANK_MIN_RECORDS (1,000) records.
"""

from collections.abc import Sequence

MIN_RECORDS = 10        # fewer wild records say little about a range
WRAP_SPAN = 340.0       # a wider longitude span crosses the 180° line: keep latitude only
Q_LOW = 0.005
Q_HIGH = 0.995


def percentile(values: Sequence[float], q: float) -> float:
    """Linear interpolation between the closest ranks, like SQL PERCENTILE_CONT."""
    ordered = sorted(values)
    pos = q * (len(ordered) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def make_range(lat_min: float, lat_max: float, lon_min: float, lon_max: float,
               records: int, countries: int | None = None) -> dict:
    """The stored geo_bounding_box dict (values rounded to 2 decimals)."""
    out: dict = {"lat_min": round(lat_min, 2), "lat_max": round(lat_max, 2)}
    if lon_max - lon_min <= WRAP_SPAN:
        out["lon_min"] = round(lon_min, 2)
        out["lon_max"] = round(lon_max, 2)
    out["records"] = records
    if countries is not None:
        out["countries"] = countries
    return out
