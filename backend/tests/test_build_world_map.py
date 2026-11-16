"""data/build_world_map.py: Natural Earth map units -> the range map's country outlines."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "data"))
import build_world_map as bw  # noqa: E402


def _ccw_square(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]


def _unit(props, *polys):
    return {"type": "Feature", "properties": props,
            "geometry": {"type": "MultiPolygon", "coordinates": list(polys)}}


def test_simplify_drops_points_on_a_straight_line():
    line = [[0, 0], [1, 0.001], [2, 0], [3, 0.002], [4, 0]]
    assert bw.simplify(line, 0.01) == [[0, 0], [4, 0]]


def test_simplify_keeps_a_corner():
    assert bw.simplify([[0, 0], [1, 0], [2, 0], [2, 1], [2, 2]], 0.01) == [[0, 0], [2, 0], [2, 2]]


def test_ring_is_closed_rounded_and_keeps_its_corners():
    ring = bw.simplify_ring([[0.001, 0], [5, 0.0001], [10, 0], [10, 10], [0, 10], [0.001, 0]], 0.05)
    assert ring[0] == ring[-1]
    assert {tuple(p) for p in ring} == {(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)}


def test_tiny_ring_collapses():
    assert bw.simplify_ring([[0, 0], [0.01, 0], [0.01, 0.01], [0, 0]], 0.1) is None


def test_rewind_outer_clockwise_hole_counter_clockwise():
    sq = _ccw_square(0, 0, 10, 10)
    assert bw.signed_area(sq) > 0
    assert bw.signed_area(bw.rewind(sq, True)) < 0
    assert bw.rewind(sq, False) == sq


def test_unit_feature_has_code_name_and_d3_winding():
    f = bw.unit_feature(_unit({"ISO_A2": "-99", "ISO_A2_EH": "FR", "NAME": "France", "NAME_LONG": "France"},
                              [_ccw_square(0, 0, 10, 10), bw.rewind(_ccw_square(2, 2, 4, 4), True)]), 0.05)
    assert f["properties"] == {"code": "FR", "name": "France"}
    outer, hole = f["geometry"]["coordinates"][0]
    assert bw.signed_area(outer) < 0 and bw.signed_area(hole) > 0


def test_small_island_state_is_kept():
    f = bw.unit_feature(_unit({"ISO_A2": "TV", "NAME": "Tuvalu"},
                              [_ccw_square(179.0, -8.0, 179.02, -7.98)]), 0.08)
    assert f is not None and len(f["geometry"]["coordinates"]) == 1


def test_unit_without_code_and_empty_geometry():
    f = bw.unit_feature(_unit({"ISO_A2": "-99", "ISO_A2_EH": "-99", "NAME": "Somaliland"},
                              [_ccw_square(0, 0, 5, 5)]), 0.05)
    assert f["properties"]["code"] is None
    assert bw.unit_feature({"type": "Feature", "properties": {}, "geometry": None}, 0.05) is None
    assert bw.build([])["features"] == []
